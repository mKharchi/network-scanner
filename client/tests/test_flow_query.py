"""Tests for the v2 on-demand local flow query."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

CLIENT_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLIENT_DIRECTORY / "app"))

from flow_query import get_requested_flows, query_flows  # noqa: E402
from telemetry_storage import get_flows_path  # noqa: E402


class FlowQueryTests(unittest.TestCase):
    def _write(self, root, day, filename, records):
        path = get_flows_path(day, root=root)
        if filename != "flows.json":
            path = path.with_name(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(records), encoding="utf-8")

    def test_reads_active_and_rotated_files_across_window_days(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write(root, "2026-09-01", "flows.1.json", [{
                "flow_id": "old",
                "first_seen": "2026-09-01T23:59:00Z",
                "last_seen": "2026-09-02T00:01:00Z",
                "src_mac": "AA-BB-CC-DD-EE-01",
                "dst_mac": "11:22:33:44:55:66",
            }])
            self._write(root, "2026-09-02", "flows.json", [{
                "flow_id": "new",
                "first_seen": "2026-09-02T00:02:00Z",
                "last_seen": "2026-09-02T00:03:00Z",
                "src_mac": "aa:bb:cc:dd:ee:01",
                "dst_mac": "11:22:33:44:55:66",
            }, {
                "flow_id": "outside",
                "first_seen": "2026-09-02T00:20:00Z",
                "last_seen": "2026-09-02T00:21:00Z",
                "src_mac": "aa:bb:cc:dd:ee:01",
                "dst_mac": "11:22:33:44:55:66",
            }])

            result = query_flows(
                "aa:bb:cc:dd:ee:01",
                "2026-09-01T23:55:00Z_2026-09-02T00:05:00Z",
                root=root,
            )

        self.assertEqual([flow["flow_id"] for flow in result], ["old", "new"])

    def test_rejects_invalid_window_mac_and_result_limit(self):
        with self.assertRaises(ValueError):
            query_flows("not-a-mac", "2026-09-02T00:00:00Z_2026-09-02T00:15:00Z")
        with self.assertRaises(ValueError):
            query_flows("AA:BB:CC:DD:EE:01", "2026-09-02T00:15:00Z_2026-09-02T00:00:00Z")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write(root, "2026-09-02", "flows.json", [{
                "flow_id": "one",
                "first_seen": "2026-09-02T00:01:00Z",
                "last_seen": "2026-09-02T00:02:00Z",
                "src_mac": "aa:bb:cc:dd:ee:01",
                "dst_mac": "11:22:33:44:55:66",
            }])
            with self.assertRaises(ValueError):
                query_flows(
                    "AA:BB:CC:DD:EE:01",
                    "2026-09-02T00:00:00Z_2026-09-02T00:15:00Z",
                    root=root,
                    max_results=0,
                )

    def test_command_response_contains_only_flow_detail_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write(root, "2026-09-02", "flows.json", [{
                "flow_id": "one",
                "first_seen": "2026-09-02T00:01:00Z",
                "last_seen": "2026-09-02T00:02:00Z",
                "src_mac": "aa:bb:cc:dd:ee:01",
                "dst_mac": "11:22:33:44:55:66",
            }])
            result = get_requested_flows({
                "args": {
                    "device_mac": "AA:BB:CC:DD:EE:01",
                    "window": "2026-09-02T00:00:00Z_2026-09-02T00:15:00Z",
                }
            }, root=root)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["flow_count"], 1)
        self.assertNotIn("packets", result)


if __name__ == "__main__":
    unittest.main()
