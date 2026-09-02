"""Unit tests for activity_window_aggregator module (v2 Phase 5)."""

import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

from activity_window_aggregator import (
    ActivityWindowAggregator,
    build_activity_window_records,
    compute_window_bounds,
)
from telemetry_storage import (
    RotatingJSONAppendStore,
    atomic_write_json,
    get_activity_window_path,
    get_devices_path,
    get_flows_path,
)


def _flow(**overrides):
    base = {
        "flow_id": "client_07-1725282922495",
        "observer_client_id": "client_07",
        "first_seen": "2026-09-02T11:05:00.000Z",
        "last_seen": "2026-09-02T11:07:00.000Z",
        "src_mac": "e4:fd:45:ba:8b:96",
        "src_ip": "172.16.2.246",
        "dst_mac": "ac:71:2e:fa:88:3f",
        "dst_ip": "43.163.42.171",
        "src_port": 61488,
        "dst_port": 443,
        "protocol": "TCP",
        "packet_count": 100,
        "bytes": 50000,
    }
    base.update(overrides)
    return base


class TestComputeWindowBounds(unittest.TestCase):
    def test_bounds_15_minutes_apart(self):
        window_end = datetime(2026, 9, 2, 11, 15, 0, tzinfo=timezone.utc)
        start, end = compute_window_bounds(window_end, 900)
        self.assertEqual(end, window_end)
        self.assertEqual((end - start).total_seconds(), 900)
        self.assertEqual(start, datetime(2026, 9, 2, 11, 0, 0, tzinfo=timezone.utc))


class TestBuildActivityWindowRecords(unittest.TestCase):
    def setUp(self):
        self.window_start = datetime(2026, 9, 2, 11, 0, 0, tzinfo=timezone.utc)
        self.window_end = datetime(2026, 9, 2, 11, 15, 0, tzinfo=timezone.utc)

    def test_device_with_flow_marked_active(self):
        flows = [_flow()]
        known_macs = ["e4:fd:45:ba:8b:96"]
        records = build_activity_window_records(flows, known_macs, self.window_start, self.window_end)
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertTrue(record["active"])
        self.assertEqual(record["flow_count"], 1)
        self.assertEqual(record["packet_count"], 100)
        self.assertEqual(record["bytes"], 50000)
        self.assertEqual(record["device_mac"], "e4:fd:45:ba:8b:96")
        self.assertEqual(record["window_id"], "2026-09-02T11:00:00Z_2026-09-02T11:15:00Z")

    def test_device_with_no_flows_marked_inactive_with_zero_counters(self):
        flows = []
        known_macs = ["e4:fd:45:ba:8b:96"]
        records = build_activity_window_records(flows, known_macs, self.window_start, self.window_end)
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertFalse(record["active"])
        self.assertEqual(record["flow_count"], 0)
        self.assertEqual(record["packet_count"], 0)
        self.assertEqual(record["bytes"], 0)
        self.assertEqual(record["protocols"], {})
        self.assertEqual(record["ports"], {})
        self.assertEqual(record["connections"], {"internal": 0, "external": 0})
        self.assertEqual(record["unique_destinations"], 0)

    def test_multiple_known_devices_all_get_records(self):
        flows = [_flow()]
        known_macs = ["e4:fd:45:ba:8b:96", "11:22:33:44:55:66"]
        records = build_activity_window_records(flows, known_macs, self.window_start, self.window_end)
        self.assertEqual(len(records), 2)
        active_macs = {r["device_mac"] for r in records if r["active"]}
        inactive_macs = {r["device_mac"] for r in records if not r["active"]}
        self.assertEqual(active_macs, {"e4:fd:45:ba:8b:96"})
        self.assertEqual(inactive_macs, {"11:22:33:44:55:66"})

    def test_protocols_and_ports_tally(self):
        flows = [_flow(dst_port=443, protocol="TCP", packet_count=10),
                 _flow(dst_port=53, protocol="UDP", packet_count=5)]
        known_macs = ["e4:fd:45:ba:8b:96"]
        records = build_activity_window_records(flows, known_macs, self.window_start, self.window_end)
        record = records[0]
        self.assertEqual(record["protocols"], {"TCP": 10, "UDP": 5})
        self.assertEqual(record["ports"], {"443": 1, "53": 1})
        self.assertEqual(record["unique_destinations"], 1)  # both flows share dst_ip

    def test_internal_vs_external_connection_classification(self):
        internal_flow = _flow(src_ip="172.16.2.246", dst_ip="172.16.2.99")
        external_flow = _flow(src_ip="172.16.2.246", dst_ip="8.8.8.8")
        known_macs = ["e4:fd:45:ba:8b:96"]
        records = build_activity_window_records(
            [internal_flow, external_flow], known_macs, self.window_start, self.window_end
        )
        record = records[0]
        self.assertEqual(record["connections"]["internal"], 1)
        self.assertEqual(record["connections"]["external"], 1)


class TestActivityWindowAggregator(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_activity_window_")
        self.root = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _seed_devices(self, date_str, macs):
        devices_path = get_devices_path(date_str, root=self.root)
        atomic_write_json(devices_path, [{"mac": mac} for mac in macs])

    def _seed_flows(self, date_str, flows):
        flows_path = get_flows_path(date_str, root=self.root)
        store = RotatingJSONAppendStore(flows_path)
        store.append_many(flows)

    def test_run_once_writes_window_file(self):
        date_str = "2026-09-02"
        self._seed_devices(date_str, ["e4:fd:45:ba:8b:96"])
        self._seed_flows(date_str, [_flow()])

        window_end = datetime(2026, 9, 2, 11, 15, 0, tzinfo=timezone.utc)
        aggregator = ActivityWindowAggregator(
            date_provider=lambda: date_str,
            now_provider=lambda: window_end,
            root=self.root,
        )
        records = aggregator.run_once()
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0]["active"])

        window_path = get_activity_window_path(date_str, "11-00", "11-15", root=self.root)
        self.assertTrue(window_path.exists())
        data = json.loads(window_path.read_text(encoding="utf-8"))
        self.assertEqual(data, records)

    def test_run_once_excludes_flows_outside_window(self):
        date_str = "2026-09-02"
        self._seed_devices(date_str, ["e4:fd:45:ba:8b:96"])
        # This flow's last_seen is before the window start (10:00-10:15 range doesn't
        # matter here since we request window ending 11:15, i.e. window 11:00-11:15).
        self._seed_flows(date_str, [_flow(last_seen="2026-09-02T10:59:00.000Z")])

        window_end = datetime(2026, 9, 2, 11, 15, 0, tzinfo=timezone.utc)
        aggregator = ActivityWindowAggregator(
            date_provider=lambda: date_str,
            now_provider=lambda: window_end,
            root=self.root,
        )
        records = aggregator.run_once()
        self.assertEqual(len(records), 1)
        self.assertFalse(records[0]["active"])

    def test_on_window_closed_callback_invoked(self):
        date_str = "2026-09-02"
        self._seed_devices(date_str, ["e4:fd:45:ba:8b:96"])
        self._seed_flows(date_str, [_flow()])

        captured = {}

        def callback(window_id, records):
            captured["window_id"] = window_id
            captured["records"] = records

        window_end = datetime(2026, 9, 2, 11, 15, 0, tzinfo=timezone.utc)
        aggregator = ActivityWindowAggregator(
            date_provider=lambda: date_str,
            now_provider=lambda: window_end,
            root=self.root,
            on_window_closed=callback,
        )
        aggregator.run_once()
        self.assertEqual(captured["window_id"], "2026-09-02T11:00:00Z_2026-09-02T11:15:00Z")
        self.assertEqual(len(captured["records"]), 1)

    def test_no_known_devices_produces_no_records(self):
        date_str = "2026-09-02"
        self._seed_devices(date_str, [])
        self._seed_flows(date_str, [_flow()])
        window_end = datetime(2026, 9, 2, 11, 15, 0, tzinfo=timezone.utc)
        aggregator = ActivityWindowAggregator(
            date_provider=lambda: date_str,
            now_provider=lambda: window_end,
            root=self.root,
        )
        records = aggregator.run_once()
        self.assertEqual(records, [])


if __name__ == "__main__":
    unittest.main()
