"""Unit tests for device_enrichment module (v2 Phase 4)."""

import json
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

from device_enrichment import (
    DeviceEnrichmentJob,
    build_device_record,
    merge_device_records,
)
from telemetry_storage import get_devices_path


def _correlator_device(**overrides):
    base = {
        "mac_address": "E4:FD:45:BA:8B:96",
        "ip_addresses": ["172.16.2.110"],
        "hostname": "DESKTOP-XYZ",
        "vendor": "Dell",
        "os_hint": None,
        "first_seen": "2026-09-02T08:12:03Z",
        "last_seen": "2026-09-02T13:37:27Z",
        "protocols_seen": ["dhcp", "mdns"],
        "services": ["_nsdswc._tcp.local"],
        "evidence": {"hostname": ["dhcp"]},
    }
    base.update(overrides)
    return base


class TestBuildDeviceRecord(unittest.TestCase):
    def test_maps_fields_per_v2_schema(self):
        record = build_device_record(_correlator_device())
        self.assertEqual(record["mac"], "e4:fd:45:ba:8b:96")
        self.assertEqual(record["ip"], "172.16.2.110")
        self.assertEqual(record["hostname"], "DESKTOP-XYZ")
        self.assertEqual(record["vendor"], "Dell")
        self.assertIsNone(record["os_guess"])
        self.assertEqual(record["first_seen"], "2026-09-02T08:12:03Z")
        self.assertEqual(record["last_seen"], "2026-09-02T13:37:27Z")

    def test_discovery_block_marks_seen_protocols(self):
        record = build_device_record(_correlator_device())
        discovery = record["discovery"]
        self.assertTrue(discovery["dhcp"]["seen"])
        self.assertTrue(discovery["mdns"]["seen"])
        self.assertFalse(discovery["llmnr"]["seen"])
        self.assertFalse(discovery["nbns"]["seen"])
        self.assertFalse(discovery["ssdp"]["seen"])

    def test_unseen_protocol_last_seen_is_none(self):
        record = build_device_record(_correlator_device())
        self.assertIsNone(record["discovery"]["ssdp"]["last_seen"])
        self.assertIsNotNone(record["discovery"]["dhcp"]["last_seen"])

    def test_mdns_includes_services(self):
        record = build_device_record(_correlator_device())
        self.assertEqual(record["discovery"]["mdns"]["services"], ["_nsdswc._tcp.local"])

    def test_no_mac_returns_none(self):
        self.assertIsNone(build_device_record({"ip_addresses": ["1.2.3.4"]}))

    def test_no_activity_fields_present(self):
        record = build_device_record(_correlator_device())
        # This job must never emit flow/activity numbers.
        forbidden_keys = {"packet_count", "bytes", "flow_count", "active", "connections"}
        self.assertFalse(forbidden_keys & set(record.keys()))
        for entry in record["discovery"].values():
            self.assertFalse(forbidden_keys & set(entry.keys()))


class TestMergeDeviceRecords(unittest.TestCase):
    def test_merge_adds_new_device(self):
        existing = [{"mac": "aa:bb:cc:dd:ee:ff", "hostname": "old"}]
        fresh = [{"mac": "11:22:33:44:55:66", "hostname": "new"}]
        merged = merge_device_records(existing, fresh)
        macs = {d["mac"] for d in merged}
        self.assertEqual(macs, {"aa:bb:cc:dd:ee:ff", "11:22:33:44:55:66"})

    def test_merge_updates_existing_device(self):
        existing = [{"mac": "aa:bb:cc:dd:ee:ff", "hostname": "old"}]
        fresh = [{"mac": "aa:bb:cc:dd:ee:ff", "hostname": "new"}]
        merged = merge_device_records(existing, fresh)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["hostname"], "new")

    def test_merge_preserves_devices_not_seen_this_cycle(self):
        existing = [
            {"mac": "aa:bb:cc:dd:ee:ff", "hostname": "device-a"},
            {"mac": "11:22:33:44:55:66", "hostname": "device-b"},
        ]
        fresh = [{"mac": "aa:bb:cc:dd:ee:ff", "hostname": "device-a-updated"}]
        merged = merge_device_records(existing, fresh)
        self.assertEqual(len(merged), 2)
        by_mac = {d["mac"]: d for d in merged}
        self.assertEqual(by_mac["aa:bb:cc:dd:ee:ff"]["hostname"], "device-a-updated")
        self.assertEqual(by_mac["11:22:33:44:55:66"]["hostname"], "device-b")


class TestDeviceEnrichmentJob(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_device_enrichment_")
        self.root = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_run_once_writes_devices_json(self):
        job = DeviceEnrichmentJob(
            device_snapshot_provider=lambda: [_correlator_device()],
            date_provider=lambda: "2026-09-02",
            root=self.root,
        )
        merged = job.run_once()
        self.assertEqual(len(merged), 1)

        devices_path = get_devices_path("2026-09-02", root=self.root)
        self.assertTrue(devices_path.exists())
        data = json.loads(devices_path.read_text(encoding="utf-8"))
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["mac"], "e4:fd:45:ba:8b:96")

    def test_run_once_preserves_devices_across_cycles(self):
        call_count = {"n": 0}

        def provider():
            call_count["n"] += 1
            if call_count["n"] == 1:
                return [_correlator_device(mac_address="AA:AA:AA:AA:AA:AA")]
            return [_correlator_device(mac_address="BB:BB:BB:BB:BB:BB")]

        job = DeviceEnrichmentJob(
            device_snapshot_provider=provider,
            date_provider=lambda: "2026-09-02",
            root=self.root,
        )
        job.run_once()
        merged = job.run_once()
        macs = {d["mac"] for d in merged}
        self.assertEqual(macs, {"aa:aa:aa:aa:aa:aa", "bb:bb:bb:bb:bb:bb"})

    def test_provider_exception_does_not_raise(self):
        def bad_provider():
            raise RuntimeError("boom")

        job = DeviceEnrichmentJob(
            device_snapshot_provider=bad_provider,
            date_provider=lambda: "2026-09-02",
            root=self.root,
        )
        merged = job.run_once()
        self.assertEqual(merged, [])

    def test_start_stop_runs_initial_cycle(self):
        job = DeviceEnrichmentJob(
            device_snapshot_provider=lambda: [_correlator_device()],
            interval_seconds=10.0,
            date_provider=lambda: "2026-09-02",
            root=self.root,
        )
        job.start()
        time.sleep(0.2)
        job.stop()
        devices_path = get_devices_path("2026-09-02", root=self.root)
        self.assertTrue(devices_path.exists())


if __name__ == "__main__":
    unittest.main()
