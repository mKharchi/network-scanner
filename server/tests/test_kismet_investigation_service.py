"""Unit tests for Phase 4 Kismet Wireless Investigation Service and REST API."""

import json
import os
import sqlite3
import sys
import tempfile
import threading
import types
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SERVER_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIRECTORY))

try:
    import mysql.connector  # noqa: F401
except ModuleNotFoundError:
    mysql_module = types.ModuleType("mysql")
    mysql_module.connector = types.ModuleType("mysql.connector")
    sys.modules["mysql"] = mysql_module
    sys.modules["mysql.connector"] = mysql_module.connector

from api_server import run_api_server
from server_components.kismet_service import (
    KismetInvestigationService,
    frequency_to_channel,
    normalize_mac,
    parse_lookback_to_minutes,
)


class KismetInvestigationServiceTests(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="test_kismet_service_"))
        self.kismet_db_path = self.test_dir / "Kismet-20260905-test.kismet"
        self._init_mock_kismet_db()

        self.service = KismetInvestigationService(
            capture_dirs=[self.test_dir],
            fallback_scan_dir=self.test_dir,
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _init_mock_kismet_db(self):
        con = sqlite3.connect(self.kismet_db_path)
        cur = con.cursor()

        cur.execute("""
        CREATE TABLE datasources (
            uuid TEXT, typestring TEXT, definition TEXT, name TEXT, interface TEXT, json BLOB
        )
        """)
        cur.execute("""
        CREATE TABLE devices (
            first_time INT, last_time INT, devkey TEXT, phyname TEXT, devmac TEXT, strongest_signal INT, bytes_data INT, type TEXT, device BLOB
        )
        """)
        cur.execute("""
        CREATE TABLE packets (
            ts_sec INT, ts_usec INT, phyname TEXT, sourcemac TEXT, destmac TEXT, transmac TEXT, frequency REAL, signal INT, packet_len INT, datasource TEXT, dlt INT, packet BLOB, hash INT
        )
        """)

        ds_json = json.dumps({"kismet.datasource.uuid": "test-sensor-1", "kismet.datasource.hardware": "iwlwifi"}).encode("utf-8")
        cur.execute("INSERT INTO datasources VALUES (?, ?, ?, ?, ?, ?)", (
            "test-sensor-1", "linuxwifi", "wlp0s20f3mon", "wlp0s20f3mon", "wlp0s20f3mon", ds_json
        ))

        # Insert test packets for target device AA:BB:CC:DD:EE:01
        # 1. QoS Data packet (Type 2, Subtype 8 -> 0x88)
        qos_pkt = bytes([0x00, 0x00, 0x04, 0x00, 0x88, 0x01, 0x00, 0x00])  # Radiotap len 4 + frame control 0x88 (QoS Data)
        # 2. Beacon packet (Type 0, Subtype 8 -> 0x80)
        beacon_pkt = bytes([0x00, 0x00, 0x04, 0x00, 0x80, 0x00, 0x00, 0x00])
        # 3. Control ACK packet (Type 1, Subtype 13 -> 0xD4)
        ack_pkt = bytes([0x00, 0x00, 0x04, 0x00, 0xD4, 0x00, 0x00, 0x00])

        base_ts = 1788612000  # Epoch for 2026-09-05 12:40:00 UTC

        cur.execute("INSERT INTO packets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
            base_ts, 1000, "IEEE802.11", "AA:BB:CC:DD:EE:01", "11:22:33:44:55:66", "AA:BB:CC:DD:EE:01", 5220000.0, -65, 512, "wlp0s20f3mon", 127, qos_pkt, 101
        ))
        cur.execute("INSERT INTO packets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
            base_ts + 10, 2000, "IEEE802.11", "11:22:33:44:55:66", "AA:BB:CC:DD:EE:01", "11:22:33:44:55:66", 5220000.0, -70, 128, "wlp0s20f3mon", 127, beacon_pkt, 102
        ))
        cur.execute("INSERT INTO packets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
            base_ts + 20, 3000, "IEEE802.11", "AA:BB:CC:DD:EE:01", "11:22:33:44:55:66", "AA:BB:CC:DD:EE:01", 5220000.0, -60, 14, "wlp0s20f3mon", 127, ack_pkt, 103
        ))

        cur.execute("INSERT INTO devices VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (
            base_ts, base_ts + 20, "dev-1", "IEEE802.11", "AA:BB:CC:DD:EE:01", -60, 654, "Wi-Fi Client", None
        ))

        con.commit()
        con.close()

    def test_helpers_normalization_and_channel(self):
        self.assertEqual(normalize_mac("aabbccddeeff"), "AA:BB:CC:DD:EE:FF")
        self.assertEqual(normalize_mac("AA-BB-CC-DD-EE-FF"), "AA:BB:CC:DD:EE:FF")
        self.assertIsNone(normalize_mac("invalid"))
        self.assertEqual(frequency_to_channel(2412000), 1)
        self.assertEqual(frequency_to_channel(5220000), 44)
        self.assertEqual(parse_lookback_to_minutes("15m"), 15)
        self.assertEqual(parse_lookback_to_minutes("2h"), 120)

    def test_query_wireless_observations(self):
        result = self.service.query_wireless_observations(
            "AA:BB:CC:DD:EE:01",
            start_time=1788610000,
            end_time=1788615000,
            include_noise=True,
        )
        self.assertEqual(result["device"]["mac"], "AA:BB:CC:DD:EE:01")
        self.assertEqual(result["summary"]["observation_count"], 3)
        self.assertEqual(result["summary"]["avg_signal_dbm"], -65.0)
        self.assertIn(44, result["summary"]["channels"])

    def test_noise_filtering(self):
        # With include_noise=False, control ACK packet is filtered out
        result = self.service.query_wireless_observations(
            "AA:BB:CC:DD:EE:01",
            start_time=1788610000,
            end_time=1788615000,
            include_noise=False,
        )
        self.assertEqual(result["summary"]["observation_count"], 2)
        subtypes = [obs["frame_subtype"] for obs in result["observations"]]
        self.assertNotIn("ACK", subtypes)
        self.assertIn("QoS Data", subtypes)

    def test_time_filter_excludes_out_of_window_records(self):
        # Plan §5.3/§5.4: Test time filter bounds strictly exclude out-of-window records
        # Database packets are at epoch 1788612000, 1788612010, 1788612020.
        # 1. Querying a 15m window outside database timeframe returns 0 records
        out_of_window = self.service.query_wireless_observations(
            "AA:BB:CC:DD:EE:01",
            start_time=1788620000,
            end_time=1788620900,
        )
        self.assertEqual(out_of_window["summary"]["observation_count"], 0)
        self.assertEqual(len(out_of_window["observations"]), 0)

        # 2. Querying a window matching only the first packet returns exactly 1 record
        first_only = self.service.query_wireless_observations(
            "AA:BB:CC:DD:EE:01",
            start_time=1788611990,
            end_time=1788612005,
        )
        self.assertEqual(first_only["summary"]["observation_count"], 1)
        self.assertEqual(first_only["observations"][0]["epoch_sec"], 1788612000)

    def test_case_insensitive_mac_matching(self):
        # Real-world Kismet stores MAC addresses in lowercase (e.g. 11:22:33:44:55:66)
        con = sqlite3.connect(self.kismet_db_path)
        cur = con.cursor()
        qos_pkt = bytes([0x00, 0x00, 0x04, 0x00, 0x88, 0x01, 0x00, 0x00])
        cur.execute("INSERT INTO packets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
            1788612050, 4000, "IEEE802.11", "bb:cc:dd:ee:ff:02", "11:22:33:44:55:66", "bb:cc:dd:ee:ff:02", 5220000.0, -55, 256, "wlp0s20f3mon", 127, qos_pkt, 104
        ))
        con.commit()
        con.close()

        # Query with uppercase MAC
        res = self.service.query_wireless_observations(
            "BB:CC:DD:EE:FF:02",
            start_time=1788612000,
            end_time=1788612100,
        )
        self.assertEqual(res["summary"]["observation_count"], 1)
        self.assertEqual(res["observations"][0]["source_mac"], "BB:CC:DD:EE:FF:02")

    def test_list_wifi_sensors(self):
        sensors = self.service.list_sensors()
        self.assertGreaterEqual(len(sensors), 1)
        self.assertEqual(sensors[0]["driver"], "iwlwifi")

    def test_exact_10_minute_and_microsecond_bounds(self):
        """Test that packets outside the exact [start, end] window are strictly excluded."""
        con = sqlite3.connect(self.kismet_db_path)
        cur = con.cursor()
        qos_pkt = bytes([0x00, 0x00, 0x04, 0x00, 0x88, 0x01, 0x00, 0x00])

        target = "AA:11:22:33:44:55"
        # Reference 10m window: [1788700000.500000, 1788700600.500000] (600 seconds)
        window_start = 1788700000.5
        window_end = 1788700600.5

        # 1. Just before start (1788700000 sec, 499999 usec -> 1788700000.499999) -> OUT
        cur.execute("INSERT INTO packets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
            1788700000, 499999, "IEEE802.11", target, "11:22:33:44:55:66", target, 5220000.0, -65, 256, "wlp0s20f3mon", 127, qos_pkt, 201
        ))
        # 2. Exactly at start (1788700000 sec, 500000 usec -> 1788700000.5) -> IN
        cur.execute("INSERT INTO packets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
            1788700000, 500000, "IEEE802.11", target, "11:22:33:44:55:66", target, 5220000.0, -64, 256, "wlp0s20f3mon", 127, qos_pkt, 202
        ))
        # 3. Inside window (1788700300 sec, 0 usec -> 1788700300.0) -> IN
        cur.execute("INSERT INTO packets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
            1788700300, 0, "IEEE802.11", target, "11:22:33:44:55:66", target, 5220000.0, -60, 256, "wlp0s20f3mon", 127, qos_pkt, 203
        ))
        # 4. Exactly at end (1788700600 sec, 500000 usec -> 1788700600.5) -> IN
        cur.execute("INSERT INTO packets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
            1788700600, 500000, "IEEE802.11", target, "11:22:33:44:55:66", target, 5220000.0, -63, 256, "wlp0s20f3mon", 127, qos_pkt, 204
        ))
        # 5. Just after end (1788700600 sec, 500001 usec -> 1788700600.500001) -> OUT
        cur.execute("INSERT INTO packets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
            1788700600, 500001, "IEEE802.11", target, "11:22:33:44:55:66", target, 5220000.0, -68, 256, "wlp0s20f3mon", 127, qos_pkt, 205
        ))
        con.commit()
        con.close()

        res = self.service.query_wireless_observations(
            target,
            start_time=window_start,
            end_time=window_end,
            include_noise=True,
        )
        self.assertEqual(res["summary"]["observation_count"], 3)
        observed_hashes = [obs["packet_hash"] for obs in res["observations"]]
        self.assertIn(202, observed_hashes)
        self.assertIn(203, observed_hashes)
        self.assertIn(204, observed_hashes)
        self.assertNotIn(201, observed_hashes)
        self.assertNotIn(205, observed_hashes)

    def test_kismet_server_provenance_and_metadata(self):
        res = self.service.query_wireless_observations(
            "AA:BB:CC:DD:EE:01",
            start_time=1788610000,
            end_time=1788615000,
            include_noise=True,
        )
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["source"], "KISMET_SERVER")
        self.assertGreaterEqual(res["capture_files_scanned"], 1)
        for obs in res["observations"]:
            self.assertEqual(obs["source"], "KISMET_SERVER")
            self.assertTrue(obs["sensor"])

    def test_empty_result_success(self):
        # Unmatched device produces clean empty success (not an error)
        res = self.service.query_wireless_observations(
            "00:00:00:00:00:00",
            start_time=1788610000,
            end_time=1788615000,
        )
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["source"], "KISMET_SERVER")
        self.assertEqual(res["summary"]["observation_count"], 0)
        self.assertEqual(len(res["observations"]), 0)

    def test_invalid_time_and_limit_inputs_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Invalid start_time"):
            self.service.query_wireless_observations(
                "AA:BB:CC:DD:EE:01",
                start_time="not-a-timestamp",
            )
        with self.assertRaisesRegex(ValueError, "Invalid end_time"):
            self.service.query_wireless_observations(
                "AA:BB:CC:DD:EE:01",
                end_time="not-a-timestamp",
            )
        with self.assertRaisesRegex(ValueError, "limit must be an integer"):
            self.service.query_wireless_observations(
                "AA:BB:CC:DD:EE:01",
                limit="many",
            )

    def test_sensor_health_reports_source_readability_separately(self):
        health = self.service.get_sensor_health()

        self.assertIn(health["status"], {"DEGRADED", "OFFLINE"})
        self.assertTrue(health["source_health"]["readable"])
        self.assertFalse(health["source_health"]["capture_fresh"])
        self.assertIn("storage_health", health)


class KismetApiEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = run_api_server(host="127.0.0.1", port=0)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def test_rest_wifi_sensors_endpoint(self):
        url = f"http://127.0.0.1:{self.port}/api/v1/sensors/wifi"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            payload = json.loads(resp.read().decode("utf-8"))
            self.assertIn("data", payload)
            self.assertIn("items", payload["data"])

    def test_rest_device_wireless_observations_endpoint(self):
        url = f"http://127.0.0.1:{self.port}/api/v1/devices/B0:3C:DC:95:39:36/wireless-observations?lookback=60m"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            payload = json.loads(resp.read().decode("utf-8"))
            self.assertIn("data", payload)
            self.assertEqual(payload["data"]["device"]["mac"], "B0:3C:DC:95:39:36")
            self.assertIn("observations", payload["data"])
            self.assertIn("summary", payload["data"])

    def test_rest_device_not_found(self):
        url = f"http://127.0.0.1:{self.port}/api/v1/devices/nonexistent-invalid-device/wireless-observations"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(req)
        self.assertEqual(err.exception.code, 404)

    def test_alert_wireless_investigation_helpers(self):
        from server_components import api_service
        # Test mock alert with MAC in title
        mock_alert_rec = {
            "title": "Unrecognized wireless activity on AA:BB:CC:DD:EE:01",
            "description": "Suspicious probe request detected.",
        }
        mac = api_service._extract_suspect_mac(mock_alert_rec, None)
        self.assertEqual(mac, "AA:BB:CC:DD:EE:01")

        # Test alert with client data
        mock_client = {"mac_address": "11:22:33:44:55:66"}
        mac2 = api_service._extract_suspect_mac({"title": "Test"}, mock_client)
        self.assertEqual(mac2, "11:22:33:44:55:66")

    def test_rest_alert_wireless_investigation_endpoint_not_found(self):
        url = f"http://127.0.0.1:{self.port}/api/v1/alerts/999999/wireless-investigation"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(req)
        self.assertEqual(err.exception.code, 404)

    def test_rest_invalid_time_range_returns_400(self):
        url = f"http://127.0.0.1:{self.port}/api/v1/devices/B0:3C:DC:95:39:36/wireless-observations?start=2026-09-06T12:00:00Z&end=2026-09-06T10:00:00Z"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(req)
        self.assertEqual(err.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
