import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from sync_manager import SyncManager, build_delta_payload
from telemetry_storage import atomic_write_json, get_devices_path


class SyncManagerTests(unittest.TestCase):
    def test_payload_is_delta_and_excludes_raw_flow_fields(self):
        payload = build_delta_payload(
            client_id="client_07",
            window_id="2026-09-02T11:00:00Z_2026-09-02T11:15:00Z",
            activity_records=[
                {
                    "device_mac": "AA:BB:CC:DD:EE:01",
                    "window_id": "2026-09-02T11:00:00Z_2026-09-02T11:15:00Z",
                    "active": True,
                    "flow_count": 2,
                    "packet_count": 10,
                    "bytes": 1000,
                    "protocols": {"TCP": 10},
                    "ports": {"443": 2},
                    "connections": {"internal": 1, "external": 1},
                    "unique_destinations": 2,
                    "flow_id": "must-not-leave-client",
                    "src_ip": "10.0.0.1",
                }
            ],
            devices=[{"mac": "aa:bb:cc:dd:ee:01", "hostname": "host", "vendor": "Vendor"}],
            sync_timestamp="2026-09-02T11:15:03Z",
        )
        self.assertEqual(payload["client_id"], "client_07")
        self.assertEqual(len(payload["updated_devices"]), 1)
        device = payload["updated_devices"][0]
        self.assertEqual(device["hostname"], "host")
        self.assertNotIn("flow_id", device["activity"])
        self.assertNotIn("src_ip", device["activity"])

    def test_inactive_device_is_retained(self):
        payload = build_delta_payload(
            client_id="client_07",
            window_id="window-1",
            activity_records=[{"device_mac": "aa:bb", "window_id": "window-1", "active": False}],
            devices=[{"mac": "aa:bb", "ip": "10.0.0.2"}],
        )
        self.assertEqual(payload["updated_devices"][0]["activity"]["active"], False)

    def test_ack_marks_window_complete(self):
        sent = []
        acked = threading.Event()
        with tempfile.TemporaryDirectory() as directory:
            manager = SyncManager(
                client_id="client_07",
                send_message=lambda message: (sent.append(message), acked.wait(1)),
                root=Path(directory),
                ack_timeout_seconds=0.2,
                retry_base_seconds=0,
                max_retries=1,
            )
            manager.handle_window_closed("window-1", [{"device_mac": "aa:bb", "active": False}])
            deadline = time.time() + 1
            while not sent and time.time() < deadline:
                time.sleep(0.01)
            self.assertTrue(sent)
            self.assertEqual(sent[0]["type"], "TELEMETRY_SYNC")
            self.assertTrue(manager.handle_ack({"window_id": "window-1", "status": "ack"}))
            acked.set()
            self.assertTrue(manager.wait_for_window("window-1", timeout=1))
            pending_payloads = [p for p in (Path(directory) / "sync_pending").glob("*.json") if p.name != "completed.json"]
            self.assertFalse(pending_payloads)

    def test_nack_retries_then_remains_pending(self):
        sent = []
        with tempfile.TemporaryDirectory() as directory:
            manager = SyncManager(
                client_id="client_07",
                send_message=lambda message: sent.append(message),
                root=Path(directory),
                ack_timeout_seconds=0.05,
                retry_base_seconds=0,
                max_retries=1,
            )
            manager.handle_window_closed("window-2", [{"device_mac": "aa:bb", "active": False}])
            deadline = time.time() + 1
            while len(sent) < 1 and time.time() < deadline:
                time.sleep(0.01)
            manager.handle_ack({"window_id": "window-2", "status": "nack", "reason": "temporary"})
            time.sleep(0.15)
            self.assertGreaterEqual(len(sent), 2)
            self.assertTrue(list((Path(directory) / "sync_pending").glob("*.json")))

    def test_pending_window_retries_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sent = []
            manager = SyncManager(
                client_id="client_07", send_message=lambda message: sent.append(message),
                root=root, ack_timeout_seconds=0.1, max_retries=0,
            )
            manager.handle_window_closed("window-3", [{"device_mac": "aa:bb", "active": False}])
            time.sleep(0.15)
            restarted = SyncManager(
                client_id="client_07", send_message=lambda message: sent.append(message),
                root=root, ack_timeout_seconds=0.1, max_retries=0,
            )
            self.assertEqual(restarted.retry_pending(), 1)
            deadline = time.time() + 1
            while len(sent) < 2 and time.time() < deadline:
                time.sleep(0.01)
            self.assertGreaterEqual(len(sent), 2)


if __name__ == "__main__":
    unittest.main()
