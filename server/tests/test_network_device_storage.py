"""Unit tests for client neighbour-report validation and storage.

Run from repository root:
    python3 server/tests/test_network_device_storage.py
"""

import sys
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


SERVER_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIRECTORY))

try:
    import mysql.connector  # noqa: F401
except ModuleNotFoundError:
    mysql_module = types.ModuleType("mysql")
    mysql_module.connector = types.ModuleType("mysql.connector")
    sys.modules["mysql"] = mysql_module
    sys.modules["mysql.connector"] = mysql_module.connector

from server_components import network_device_storage, server_lib  # noqa: E402


class FakeCursor:
    def __init__(self):
        self.executed = []
        self._last_query = ""
        self.rows = []

    def execute(self, query, params=None):
        self.executed.append((query, params))
        self._last_query = query

    def fetchone(self):
        if "FROM clients" in self._last_query:
            return (7,)
        if "FROM sensors" in self._last_query:
            return (21,)
        if "FROM network_devices" in self._last_query:
            return (13,)
        return None

    def fetchall(self):
        return self.rows

    def close(self):
        pass


class FakeConnection:
    def __init__(self):
        self.cursor_instance = FakeCursor()
        self.committed = False
        self.rolled_back = False

    def cursor(self, **kwargs):
        return self.cursor_instance

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def is_connected(self):
        return False


class NetworkDeviceStorageTests(unittest.TestCase):
    def test_validation_normalizes_entries_and_ignores_invalid_rows(self):
        neighbours = network_device_storage.validate_neighbour_report(
            {
                "observed_at": "2026-08-17T10:00:00Z",
                "neighbours": [
                    {
                        "ip_address": "172.16.0.102",
                        "mac_address": "aa-bb-cc-dd-ee-ff",
                        "entry_type": "dynamic",
                        "interface": " eth0 ",
                    },
                    {
                        "ip_address": "224.0.0.1",
                        "mac_address": "01:00:5e:00:00:01",
                        "entry_type": "dynamic",
                    },
                    {"ip_address": "not-an-ip", "mac_address": "11:22:33:44:55:66"},
                ],
            }
        )
        self.assertEqual(
            neighbours,
            [
                {
                    "ip_address": "172.16.0.102",
                    "mac_address": "AA:BB:CC:DD:EE:FF",
                    "entry_type": "dynamic",
                    "interface": "eth0",
                }
            ],
        )

    def test_validation_rejects_invalid_envelope(self):
        with self.assertRaisesRegex(ValueError, "observed_at"):
            network_device_storage.validate_neighbour_report({"neighbours": []})
        with self.assertRaisesRegex(ValueError, "neighbours"):
            network_device_storage.validate_neighbour_report(
                {"observed_at": "2026-08-17T10:00:00Z", "neighbours": {}}
            )

    def test_validation_preserves_normalized_client_observation_sources(self):
        neighbours = network_device_storage.validate_neighbour_report(
            {
                "observed_at": "2026-08-20T10:00:00Z",
                "neighbours": [
                    {
                        "ip_address": "172.16.0.102",
                        "mac_address": "E4:FD:45:BA:8B:96",
                        "entry_type": "dynamic",
                        "source": "dhcp",
                        "sources": ["arp", "dhcp", "invalid"],
                    }
                ],
            }
        )

        self.assertEqual(neighbours[0]["sources"], ["arp", "dhcp"])

    def test_store_creates_device_and_source_attributed_observation(self):
        connection = FakeConnection()
        original_get_connection = network_device_storage.get_connection
        network_device_storage.get_connection = lambda: connection
        try:
            stored = network_device_storage.store_client_neighbour_observations(
                "AA:BB:CC:DD:EE:FF",
                [
                    {
                        "ip_address": "172.16.0.102",
                        "mac_address": "11:22:33:44:55:66",
                        "entry_type": "dynamic",
                        "interface": "eth0",
                    }
                ],
                observed_at=datetime(2026, 8, 17, 10, 0, 0),
            )
        finally:
            network_device_storage.get_connection = original_get_connection

        self.assertEqual(stored, 1)
        self.assertTrue(connection.committed)
        observation = next(
            params
            for query, params in connection.cursor_instance.executed
            if "INSERT INTO network_device_observations" in query
        )
        self.assertEqual(observation[:5], (13, "CLIENT_ARP", 7, 21, "172.16.0.102"))
        self.assertEqual(observation[6:8], ("dynamic", datetime(2026, 8, 17, 10, 0, 0)))

    def test_store_prefers_neighbour_observed_at_over_batch_timestamp(self):
        connection = FakeConnection()
        original_get_connection = network_device_storage.get_connection
        network_device_storage.get_connection = lambda: connection
        try:
            stored = network_device_storage.store_client_neighbour_observations(
                "AA:BB:CC:DD:EE:FF",
                [
                    {
                        "ip_address": "172.16.0.102",
                        "mac_address": "11:22:33:44:55:66",
                        "entry_type": "dynamic",
                        "observed_at": "2026-08-17T08:30:00+00:00",
                    }
                ],
                observed_at=datetime(2026, 8, 17, 10, 0, 0),
            )
        finally:
            network_device_storage.get_connection = original_get_connection

        self.assertEqual(stored, 1)
        observation = next(
            params
            for query, params in connection.cursor_instance.executed
            if "INSERT INTO network_device_observations" in query
        )
        self.assertEqual(observation[7], datetime(2026, 8, 17, 8, 30, 0))

    def test_handler_uses_registered_connection_mac_not_payload_identity(self):
        received = {}

        accepted = server_lib.handle_network_neighbour_report(
            "AA:BB:CC:DD:EE:FF",
            {"client_id": "untrusted-client-value"},
            report_validator=lambda payload: [{"mac_address": "12:22:33:44:55:66"}],
            observation_storer=lambda reporter_mac, neighbours: (
                received.update({"reporter_mac": reporter_mac, "neighbours": neighbours})
                or len(neighbours)
            ),
        )

        self.assertTrue(accepted)
        self.assertEqual(received["reporter_mac"], "AA:BB:CC:DD:EE:FF")
        self.assertEqual(received["neighbours"], [{"mac_address": "12:22:33:44:55:66"}])

    def test_handler_adds_only_dhcp_reports_to_daily_log(self):
        logged = {}
        payload = {
            "observation_source": "DHCP",
            "dhcp": {"message_type": 3},
        }
        neighbours = [{"mac_address": "12:22:33:44:55:66"}]

        accepted = server_lib.handle_network_neighbour_report(
            "AA:BB:CC:DD:EE:FF",
            payload,
            report_validator=lambda _: neighbours,
            observation_storer=lambda *_: 1,
            dhcp_observation_storer=lambda reporter_mac, rows, dhcp: (
                logged.update(
                    {
                        "reporter_mac": reporter_mac,
                        "neighbours": rows,
                        "dhcp": dhcp,
                    }
                )
                or "/tmp/network_scan_2026-08-17.json"
            ),
        )

        self.assertTrue(accepted)
        self.assertEqual(logged["reporter_mac"], "AA:BB:CC:DD:EE:FF")
        self.assertEqual(logged["neighbours"], neighbours)
        self.assertEqual(logged["dhcp"], {"message_type": 3})

    def test_handler_stores_one_daily_snapshot_and_skips_duplicates(self):
        stored = []
        logged = []
        payload = {"observation_source": "DAILY_NEIGHBOUR_SNAPSHOT"}
        neighbours = [{"mac_address": "12:22:33:44:55:66"}]

        accepted = server_lib.handle_network_neighbour_report(
            "AA:BB:CC:DD:EE:FF",
            payload,
            report_validator=lambda _: neighbours,
            observation_storer=lambda reporter_mac, rows: (
                stored.append((reporter_mac, rows)) or 1
            ),
            daily_snapshot_exists=lambda _: False,
            daily_snapshot_storer=lambda reporter_mac, rows: (
                logged.append((reporter_mac, rows))
                or ("/tmp/network_scan_2026-08-17.json", True)
            ),
            daily_scan_reference_storer=lambda file_path: logged.append(file_path),
        )

        self.assertTrue(accepted)
        self.assertEqual(stored, [("AA:BB:CC:DD:EE:FF", neighbours)])
        self.assertEqual(
            logged,
            [
                ("AA:BB:CC:DD:EE:FF", neighbours),
                "/tmp/network_scan_2026-08-17.json",
            ],
        )

        accepted = server_lib.handle_network_neighbour_report(
            "AA:BB:CC:DD:EE:FF",
            payload,
            report_validator=lambda _: neighbours,
            observation_storer=lambda *_: self.fail("duplicate was stored"),
            daily_snapshot_exists=lambda _: True,
            daily_snapshot_storer=lambda *_: self.fail("duplicate was logged"),
            daily_scan_reference_storer=lambda *_: self.fail("duplicate was referenced"),
        )
        self.assertTrue(accepted)

    def test_handler_stores_requested_neighbourhood_without_daily_deduplication(self):
        stored = []
        neighbours = [{"mac_address": "12:22:33:44:55:66"}]

        accepted = server_lib.handle_network_neighbour_report(
            "AA:BB:CC:DD:EE:FF",
            {"observation_source": "REQUESTED_NEIGHBOURHOOD"},
            report_validator=lambda _: neighbours,
            observation_storer=lambda reporter_mac, rows: (
                stored.append((reporter_mac, rows)) or len(rows)
            ),
        )

        self.assertTrue(accepted)
        self.assertEqual(stored, [("AA:BB:CC:DD:EE:FF", neighbours)])

    def test_handler_merges_active_scan_report(self):
        from server_components import event_broadcaster, network_discovery

        neighbours = [{"mac_address": "12:22:33:44:55:66"}]
        stored = []
        with patch.object(
            network_discovery,
            "run_manual_scan",
            return_value=({}, neighbours, "/tmp/network_scan_active.json"),
        ) as merge, patch.object(
            event_broadcaster, "broadcast_network_update"
        ) as broadcast:
            accepted = server_lib.handle_network_neighbour_report(
                "AA:BB:CC:DD:EE:FF",
                {"observation_source": "ACTIVE_NEIGHBOUR_SCAN"},
                report_validator=lambda _: neighbours,
                observation_storer=lambda reporter_mac, rows: (
                    stored.append((reporter_mac, rows)) or len(rows)
                ),
            )

        self.assertTrue(accepted)
        self.assertEqual(stored, [("AA:BB:CC:DD:EE:FF", neighbours)])
        merge.assert_called_once_with(
            context_overrides={"scan_type": "CLIENT_ACTIVE"}
        )
        broadcast.assert_called_once_with("network_scan_active", 1)

    def test_daily_scan_reference_is_upserted(self):
        connection = FakeConnection()
        original_get_connection = network_device_storage.get_connection
        network_device_storage.get_connection = lambda: connection
        try:
            network_device_storage.store_daily_network_scan_reference(
                "/tmp/network_scan_2026-08-17.json",
                observed_at=datetime(2026, 8, 17, 10, 0, 0),
            )
        finally:
            network_device_storage.get_connection = original_get_connection

        self.assertTrue(connection.committed)
        query, params = connection.cursor_instance.executed[0]
        self.assertIn("daily_network_scan_files", query)
        self.assertEqual(params, (datetime(2026, 8, 17).date(), "/tmp/network_scan_2026-08-17.json"))

    def test_server_scan_observations_are_persisted_with_their_source(self):
        connection = FakeConnection()
        original_get_connection = network_device_storage.get_connection
        network_device_storage.get_connection = lambda: connection
        try:
            stored = network_device_storage.store_server_scan_observations(
                [{"ip_address": "172.16.0.102", "mac_address": "12:22:33:44:55:66"}],
                observed_at=datetime(2026, 8, 17, 10, 0, 0),
            )
        finally:
            network_device_storage.get_connection = original_get_connection

        self.assertEqual(stored, 1)
        observation = next(
            params
            for query, params in connection.cursor_instance.executed
            if "INSERT INTO network_device_observations" in query
        )
        self.assertEqual(observation[:4], (13, "SERVER_SCAN", None, None))
        self.assertEqual(observation[4], "172.16.0.102")
        self.assertEqual(observation[6], "discovered")

    def test_recent_client_observations_keep_latest_record_per_reporting_client(self):
        connection = FakeConnection()
        connection.cursor_instance.rows = [
            {
                "mac_address": "AA:BB:CC:DD:EE:FF",
                "ip_address": "172.16.0.102",
                "interface_name": "eth0",
                "entry_type": "dynamic",
                "observed_at": datetime(2026, 8, 17, 10, 0, 0),
                "source_client_database_id": 7,
                "source_client_id": "client-reporter-a",
                "source_client_hostname": "reporter-a",
            },
            {
                "mac_address": "AA:BB:CC:DD:EE:FF",
                "ip_address": "172.16.0.99",
                "interface_name": "eth0",
                "entry_type": "static",
                "observed_at": datetime(2026, 8, 17, 9, 59, 0),
                "source_client_database_id": 7,
                "source_client_id": "client-reporter-a",
                "source_client_hostname": "reporter-a",
            },
        ]
        original_get_connection = network_device_storage.get_connection
        network_device_storage.get_connection = lambda: connection
        try:
            observations = network_device_storage.get_recent_client_neighbour_observations(
                now=datetime(2026, 8, 17, 10, 0, 30), max_age_seconds=60
            )
        finally:
            network_device_storage.get_connection = original_get_connection

        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0]["ip_address"], "172.16.0.102")
        self.assertEqual(observations[0]["source_client_id"], "client-reporter-a")

    def test_store_client_dhcp_observations_persists_client_dhcp_source(self):
        connection = FakeConnection()
        original_get_connection = network_device_storage.get_connection
        network_device_storage.get_connection = lambda: connection
        try:
            stored = network_device_storage.store_client_dhcp_observations(
                "AA:BB:CC:DD:EE:FF",
                [
                    {
                        "ip_address": "172.16.0.102",
                        "mac_address": "E4:FD:45:BA:8B:96",
                        "entry_type": "dynamic",
                        "hostname": "DESKTOP-DJP05CM",
                        "vendor": "Dell Inc.",
                    }
                ],
                observed_at=datetime(2026, 8, 17, 10, 0, 0),
            )
        finally:
            network_device_storage.get_connection = original_get_connection

        self.assertEqual(stored, 1)
        self.assertTrue(connection.committed)
        observation = next(
            params
            for query, params in connection.cursor_instance.executed
            if "INSERT INTO network_device_observations" in query
        )
        self.assertEqual(observation[:4], (13, "CLIENT_DHCP", 7, 21))
        self.assertEqual(observation[4], "172.16.0.102")
        self.assertEqual(observation[6:8], ("dynamic", datetime(2026, 8, 17, 10, 0, 0)))

    def test_store_local_neighbourhood_preserves_arp_and_dhcp_sources(self):
        connection = FakeConnection()
        original_get_connection = network_device_storage.get_connection
        network_device_storage.get_connection = lambda: connection
        try:
            stored = network_device_storage.store_client_neighbourhood_observations(
                "AA:BB:CC:DD:EE:FF",
                [
                    {
                        "ip_address": "172.16.0.102",
                        "mac_address": "E4:FD:45:BA:8B:96",
                        "entry_type": "dynamic",
                        "sources": ["arp", "dhcp"],
                    }
                ],
                observed_at=datetime(2026, 8, 17, 10, 0, 0),
            )
        finally:
            network_device_storage.get_connection = original_get_connection

        self.assertEqual(stored, 1)
        observation_params = [
            params
            for query, params in connection.cursor_instance.executed
            if "INSERT INTO network_device_observations" in query
        ]
        self.assertEqual([params[1] for params in observation_params], ["CLIENT_ARP", "CLIENT_DHCP"])
        self.assertEqual([params[3] for params in observation_params], [21, 21])

    def test_request_client_neighbourhood_returns_completed_or_timeout(self):
        with patch.object(
            server_lib,
            "execute_client_command",
            return_value={
                "status": "ok",
                "data": {"status": "ok", "observations_sent": 2},
            },
        ) as execute:
            completed = server_lib.request_client_network_neighbourhood(
                "client-a", timeout=4.0
            )

        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["observations_sent"], 2)
        execute.assert_called_once_with(
            "client-a",
            "GET_NETWORK_NEIGHBOURHOOD",
            timeout=4.0,
            process_network_scan=False,
        )

        with patch.object(
            server_lib,
            "execute_client_command",
            return_value={"status": "error", "message": "Command timed out after 4.0s."},
        ):
            timed_out = server_lib.request_client_network_neighbourhood(
                "client-a", timeout=4.0
            )

        self.assertEqual(timed_out["status"], "client_timeout")
        self.assertEqual(timed_out["timeout_seconds"], 4.0)


if __name__ == "__main__":
    unittest.main()
