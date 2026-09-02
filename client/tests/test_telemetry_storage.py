"""Unit tests for telemetry_storage module (v2 Phase 1)."""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

from telemetry_storage import (
    RotatingJSONAppendStore,
    atomic_write_json,
    get_activity_dir,
    get_activity_window_path,
    get_day_dir,
    get_devices_path,
    get_flows_path,
    get_packets_dir,
    get_protocol_packet_path,
    read_json,
)


class TestDayDirHelpers(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_telemetry_storage_")
        self.root = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_get_day_dir_creates_directory(self):
        day_dir = get_day_dir("2026-09-02", root=self.root)
        self.assertTrue(day_dir.is_dir())
        self.assertEqual(day_dir.name, "2026-09-02")

    def test_get_packets_dir_and_protocol_path(self):
        protocol_path = get_protocol_packet_path("2026-09-02", "TCP", root=self.root)
        self.assertTrue(protocol_path.parent.is_dir())
        self.assertEqual(protocol_path.name, "tcp.json")

    def test_get_flows_and_devices_paths(self):
        flows_path = get_flows_path("2026-09-02", root=self.root)
        devices_path = get_devices_path("2026-09-02", root=self.root)
        self.assertEqual(flows_path.name, "flows.json")
        self.assertEqual(devices_path.name, "devices.json")
        self.assertEqual(flows_path.parent, devices_path.parent)

    def test_get_activity_window_path(self):
        path = get_activity_window_path("2026-09-02", "11-00", "11-15", root=self.root)
        self.assertEqual(path.name, "11-00_11-15.json")
        self.assertTrue(get_activity_dir("2026-09-02", root=self.root).is_dir())

    def test_atomic_write_and_read_json(self):
        target = self.root / "sub" / "test.json"
        atomic_write_json(target, {"hello": "world"})
        self.assertTrue(target.exists())
        data = read_json(target)
        self.assertEqual(data, {"hello": "world"})

    def test_read_json_missing_file_returns_default(self):
        missing = self.root / "does_not_exist.json"
        self.assertEqual(read_json(missing, default={"x": 1}), {"x": 1})


class TestRotatingJSONAppendStore(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_rotating_store_")
        self.root = Path(self.temp_dir)
        self.base_path = self.root / "flows.json"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_append_single_record(self):
        store = RotatingJSONAppendStore(self.base_path, max_bytes=50 * 1024 * 1024)
        store.append({"flow_id": "a-1"})
        self.assertTrue(self.base_path.exists())
        records = store.read_all()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["flow_id"], "a-1")

    def test_append_many_accumulates(self):
        store = RotatingJSONAppendStore(self.base_path, max_bytes=50 * 1024 * 1024)
        store.append_many([{"flow_id": "a-1"}, {"flow_id": "a-2"}])
        store.append({"flow_id": "a-3"})
        records = store.read_all()
        self.assertEqual(len(records), 3)
        self.assertEqual([r["flow_id"] for r in records], ["a-1", "a-2", "a-3"])

    def test_rotation_on_size_limit(self):
        # Use a tiny max_bytes so the first append already triggers rotation
        # on the second write.
        store = RotatingJSONAppendStore(self.base_path, max_bytes=10)
        store.append({"flow_id": "a-1", "padding": "x" * 50})
        # File now exceeds 10 bytes; next append should roll it to flows.1.json
        store.append({"flow_id": "a-2"})

        rotated_path = self.root / "flows.1.json"
        self.assertTrue(rotated_path.exists())
        self.assertTrue(self.base_path.exists())

        rotated_data = json.loads(rotated_path.read_text(encoding="utf-8"))
        active_data = json.loads(self.base_path.read_text(encoding="utf-8"))
        self.assertEqual(len(rotated_data), 1)
        self.assertEqual(rotated_data[0]["flow_id"], "a-1")
        self.assertEqual(len(active_data), 1)
        self.assertEqual(active_data[0]["flow_id"], "a-2")

    def test_read_all_including_rotated(self):
        store = RotatingJSONAppendStore(self.base_path, max_bytes=10)
        store.append({"flow_id": "a-1", "padding": "x" * 50})
        store.append({"flow_id": "a-2"})
        all_records = store.read_all_including_rotated()
        self.assertEqual([r["flow_id"] for r in all_records], ["a-1", "a-2"])

    def test_empty_store_read_all_returns_empty_list(self):
        store = RotatingJSONAppendStore(self.base_path)
        self.assertEqual(store.read_all(), [])
        self.assertEqual(store.read_all_including_rotated(), [])


if __name__ == "__main__":
    unittest.main()
