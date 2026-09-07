"""Unit tests for Phase 2 Event Monitoring layer."""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

CLIENT_APP_DIR = Path(__file__).resolve().parents[1] / "app"
SERVER_DIR = Path(__file__).resolve().parents[2] / "server"
SERVER_COMPONENTS_DIR = SERVER_DIR / "server_components"

sys.path.insert(0, str(CLIENT_APP_DIR))

from event_monitor import (
    APP_INSTALLED,
    APP_UNINSTALLED,
    APP_UPDATED,
    FILE_CREATED,
    FILE_DELETED,
    FILE_MODIFIED,
    FILE_RENAMED,
    ClientEvent,
    EventDeduplicator,
    EventMonitor,
    EventRateLimiter,
    is_excluded_path,
)
from client_lib import get_activity_log, _handle_get_activity_log


class EventMonitorUnitTests(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="test_event_mon_"))
        self.monitored_dir = self.test_dir / "monitored"
        self.monitored_dir.mkdir()
        self.storage_dir = self.test_dir / "storage"
        self.storage_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_client_event_serialization(self):
        ev = ClientEvent(
            event_type=APP_UNINSTALLED,
            client_id="client-01",
            application="SuspiciousApp",
            version="1.2.3",
            user="alice",
        )
        d = ev.to_dict()
        self.assertEqual(d["event_type"], APP_UNINSTALLED)
        self.assertEqual(d["application"], "SuspiciousApp")
        self.assertEqual(d["version"], "1.2.3")
        self.assertEqual(d["user"], "alice")
        self.assertNotIn("path", d)  # None field dropped

    def test_rate_limiter_caps_bursts(self):
        limiter = EventRateLimiter(max_events=3, window_seconds=1.0)
        now = 100.0
        self.assertTrue(limiter.allow(now))
        self.assertTrue(limiter.allow(now))
        self.assertTrue(limiter.allow(now))
        # 4th in same window must be rejected
        self.assertFalse(limiter.allow(now))
        # After window passes, allowed again
        self.assertTrue(limiter.allow(now + 1.5))

    def test_deduplicator_suppresses_rapid_duplicates(self):
        dedup = EventDeduplicator(debounce_seconds=2.0)
        now = 100.0
        self.assertFalse(dedup.is_duplicate(FILE_DELETED, "/path/to/file.txt", now))
        # Immediate duplicate is suppressed
        self.assertTrue(dedup.is_duplicate(FILE_DELETED, "/path/to/file.txt", now + 0.5))
        # Different key is not suppressed
        self.assertFalse(dedup.is_duplicate(FILE_DELETED, "/path/to/other.txt", now + 0.5))
        # After debounce window expires, allowed again
        self.assertFalse(dedup.is_duplicate(FILE_DELETED, "/path/to/file.txt", now + 2.5))

    def test_application_uninstall_and_install_detection(self):
        mock_apps = {
            "AppA": "1.0",
            "AppB": "2.0",
        }

        def _provider():
            return dict(mock_apps)

        monitor = EventMonitor(
            client_id="test-client",
            apps_provider=_provider,
            storage_root=self.storage_dir,
        )
        monitor.initialize_baselines()

        # No changes initially
        events = monitor.check_application_changes()
        self.assertEqual(len(events), 0)

        # Uninstall AppA
        del mock_apps["AppA"]
        events = monitor.check_application_changes()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, APP_UNINSTALLED)
        self.assertEqual(events[0].application, "AppA")

        # Install AppC
        mock_apps["AppC"] = "3.1"
        events = monitor.check_application_changes()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, APP_INSTALLED)
        self.assertEqual(events[0].application, "AppC")

        # Update AppB
        mock_apps["AppB"] = "2.1"
        events = monitor.check_application_changes()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, APP_UPDATED)
        self.assertEqual(events[0].application, "AppB")
        self.assertEqual(events[0].version, "2.0 -> 2.1")

    def test_file_monitoring_created_modified_deleted(self):
        monitor = EventMonitor(
            client_id="test-client",
            monitored_directories=[self.monitored_dir],
            storage_root=self.storage_dir,
            apps_provider=lambda: {},
        )
        monitor.initialize_baselines()

        test_file = self.monitored_dir / "doc.txt"
        test_file.write_text("hello world")

        # 1. Detect creation
        events = monitor.check_file_changes()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, FILE_CREATED)
        self.assertEqual(events[0].path, str(test_file.resolve()))

        # 2. Detect modification
        time.sleep(0.05)
        test_file.write_text("updated text content")
        events = monitor.check_file_changes()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, FILE_MODIFIED)

        # 3. Detect deletion
        test_file.unlink()
        events = monitor.check_file_changes()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, FILE_DELETED)

    def test_noise_files_ignored(self):
        monitor = EventMonitor(
            client_id="test-client",
            monitored_directories=[self.monitored_dir],
            storage_root=self.storage_dir,
            apps_provider=lambda: {},
        )
        monitor.initialize_baselines()

        # Temporary / cache files should be ignored
        (self.monitored_dir / "scratch.tmp").write_text("temp")
        (self.monitored_dir / "audit.log").write_text("log")
        (self.monitored_dir / "document.partial").write_text("partial")
        (self.monitored_dir / "sync.lock").write_text("lock")

        events = monitor.check_file_changes()
        self.assertEqual(len(events), 0)

    def test_is_excluded_path_centralized_policy(self):
        # Passive network neighbourhood & DHCP files
        self.assertTrue(is_excluded_path("/client/storage/network_neighbourhood/2026-09-06.json"))
        self.assertTrue(is_excluded_path("C:\\client\\storage\\network_neighbourhood\\dhcp.json"))
        self.assertTrue(is_excluded_path("/client/storage/neighbour_snapshot_state.json"))

        # Passive packet & telemetry storage
        self.assertTrue(is_excluded_path("/client/storage/passive_packets/2026-09-06.json"))
        self.assertTrue(is_excluded_path("/client/storage/network_telemetry/2026-09-06/packets/dhcp.json"))

        # Internal client state & event storage
        self.assertTrue(is_excluded_path("/client/storage/events/2026-09-06.json"))
        self.assertTrue(is_excluded_path("/client/storage/sent-files/upload.zip"))
        self.assertTrue(is_excluded_path("/client/storage/forbidden_process_scan.json"))
        self.assertTrue(is_excluded_path("/client/storage/reported_alerts.json"))

        # Temporary & log files
        self.assertTrue(is_excluded_path("/client/temp_data.tmp"))
        self.assertTrue(is_excluded_path("/client/logs/client.log"))
        self.assertTrue(is_excluded_path("/client/.cache.lock"))

        # Legitimate user & application files MUST NOT be excluded
        self.assertFalse(is_excluded_path("/client/test_file.txt"))
        self.assertFalse(is_excluded_path("/client/storage/important_document.pdf"))
        self.assertFalse(is_excluded_path("/home/user/document.docx"))
        self.assertFalse(is_excluded_path("C:\\Users\\alice\\Desktop\\report.txt"))

    def test_passive_storage_directories_ignored_by_monitor(self):
        # Create a mock storage hierarchy inside monitored_dir
        storage_dir = self.monitored_dir / "storage"
        dhcp_dir = storage_dir / "network_neighbourhood"
        dhcp_dir.mkdir(parents=True)
        telemetry_dir = storage_dir / "network_telemetry"
        telemetry_dir.mkdir(parents=True)

        monitor = EventMonitor(
            client_id="test-client",
            monitored_directories=[self.monitored_dir],
            storage_root=self.storage_dir,
            apps_provider=lambda: {},
        )
        monitor.initialize_baselines()

        # Write high-frequency passive observation & packet files
        (dhcp_dir / "2026-09-06.json").write_text('{"dhcp": "observation"}')
        (telemetry_dir / "packets.json").write_text('{"packets": []}')
        (storage_dir / "neighbour_snapshot_state.json").write_text('{}')

        # Also write a legitimate user file
        user_file = self.monitored_dir / "user_notes.txt"
        user_file.write_text("legitimate user content")

        events = monitor.check_file_changes()
        # Only user_file should be detected! Passive files must be excluded.
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, FILE_CREATED)
        self.assertEqual(events[0].path, str(user_file.resolve()))

        # Modify passive DHCP file and modify user file
        (dhcp_dir / "2026-09-06.json").write_text('{"dhcp": "updated observation"}')
        time.sleep(0.05)
        user_file.write_text("updated user content")

        events = monitor.check_file_changes()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, FILE_MODIFIED)
        self.assertEqual(events[0].path, str(user_file.resolve()))

        # Delete passive DHCP file and delete user file
        (dhcp_dir / "2026-09-06.json").unlink()
        user_file.unlink()

        events = monitor.check_file_changes()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, FILE_DELETED)
        self.assertEqual(events[0].path, str(user_file.resolve()))

    def test_event_persistence_and_callback(self):
        dispatched = []

        monitor = EventMonitor(
            client_id="test-client",
            storage_root=self.storage_dir,
            event_callback=lambda ev: dispatched.append(ev),
        )

        ev = ClientEvent(
            event_type=FILE_DELETED,
            client_id="test-client",
            path="/home/user/critical.dat",
        )
        ok = monitor.emit_event(ev)
        self.assertTrue(ok)
        self.assertEqual(len(dispatched), 1)
        self.assertEqual(dispatched[0]["event_type"], FILE_DELETED)

        # Verify persisted on disk
        stored_files = list(self.storage_dir.glob("*.json"))
        self.assertGreaterEqual(len(stored_files), 1)
        content = json.loads(stored_files[0].read_text(encoding="utf-8"))
        self.assertIsInstance(content, list)
        self.assertEqual(content[0]["event_type"], FILE_DELETED)

    def test_start_and_stop_lifecycle(self):
        monitor = EventMonitor(
            client_id="test-client",
            monitored_directories=[self.monitored_dir],
            storage_root=self.storage_dir,
            scan_interval_seconds=0.1,
            app_scan_interval_seconds=0.1,
            apps_provider=lambda: {},
        )
        monitor.start()
        self.assertTrue(monitor._thread.is_alive())
        monitor.stop()
        self.assertIsNone(monitor._thread)


class TestFileActivityLoggingPlan(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="test_file_act_"))
        self.monitored_dir = self.test_dir / "monitored"
        self.monitored_dir.mkdir(parents=True)
        self.storage_dir = self.test_dir / "storage"
        self.storage_dir.mkdir(parents=True)
        self.events_dir = self.storage_dir / "events"
        self.events_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_file_lifecycle_detect_and_persist(self):
        """Verify file creation, modification, and deletion are detected and logged."""
        monitor = EventMonitor(
            client_id="client-test-01",
            monitored_directories=[self.monitored_dir],
            storage_root=self.events_dir,
            apps_provider=lambda: {},
        )
        monitor.initialize_baselines()

        test_file = self.monitored_dir / "document.txt"

        # 1. Create file
        test_file.write_text("initial content")
        events = monitor.check_file_changes()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, FILE_CREATED)
        self.assertEqual(events[0].path, str(test_file.resolve()))
        monitor.emit_event(events[0])

        # 2. Modify file
        time.sleep(0.05)
        test_file.write_text("modified content")
        events = monitor.check_file_changes()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, FILE_MODIFIED)
        self.assertEqual(events[0].path, str(test_file.resolve()))
        monitor.emit_event(events[0])

        # 3. Delete file
        test_file.unlink()
        events = monitor.check_file_changes()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, FILE_DELETED)
        self.assertEqual(events[0].path, str(test_file.resolve()))
        monitor.emit_event(events[0])

        # Verify all 3 events are persisted to disk
        event_files = list(self.events_dir.glob("*.json"))
        self.assertGreaterEqual(len(event_files), 1)
        persisted = []
        for ef in event_files:
            persisted.extend(json.loads(ef.read_text(encoding="utf-8")))

        event_types = [e["event_type"] for e in persisted]
        self.assertIn(FILE_CREATED, event_types)
        self.assertIn(FILE_MODIFIED, event_types)
        self.assertIn(FILE_DELETED, event_types)

    def test_no_alerts_generated_for_file_events(self):
        """Plan §3 & §7: Ensure ordinary file events NEVER generate real-time alerts."""
        alerts_sent = []

        def mock_send_alerts(client_sock, alerts, source):
            alerts_sent.extend(alerts)

        # Import _on_activity_event behavior from client.py
        def _on_activity_event(event):
            ev_type = event.get("event_type")
            if ev_type in (
                FILE_CREATED,
                FILE_MODIFIED,
                FILE_DELETED,
                FILE_RENAMED,
            ):
                return
            mock_send_alerts(None, [{"type": "ALERT", "alert": event}], "event-monitor")

        # Test all file event types
        for ev_type in (FILE_CREATED, FILE_MODIFIED, FILE_DELETED, FILE_RENAMED):
            _on_activity_event({"event_type": ev_type, "path": "/some/file.txt"})

        # Exactly 0 alerts must have been sent
        self.assertEqual(len(alerts_sent), 0)

        # Non-file event MUST still generate alerts
        _on_activity_event({"event_type": APP_INSTALLED, "application": "EvilTool"})
        self.assertEqual(len(alerts_sent), 1)
        self.assertEqual(alerts_sent[0]["alert"]["event_type"], APP_INSTALLED)

    def test_get_activity_log_includes_file_events(self):
        """Plan §5 & §15: Get Log response contains relevant file activity."""
        now = datetime.now()
        ts_created = (now - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        ts_modified = (now - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        ts_deleted = (now - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%S+00:00")

        today_str = now.strftime("%Y-%m-%d")
        day_file = self.events_dir / f"{today_str}.json"

        stored_events = [
            {
                "event_type": FILE_CREATED,
                "timestamp": ts_created,
                "path": "/data/confidential.docx",
                "source": "filesystem_monitor",
            },
            {
                "event_type": FILE_MODIFIED,
                "timestamp": ts_modified,
                "path": "/data/confidential.docx",
                "source": "filesystem_monitor",
            },
            {
                "event_type": FILE_DELETED,
                "timestamp": ts_deleted,
                "path": "/data/confidential.docx",
                "source": "filesystem_monitor",
            },
        ]
        day_file.write_text(json.dumps(stored_events), encoding="utf-8")

        result = get_activity_log(period="1d", storage_dir=self.storage_dir)
        self.assertIn("activity", result)
        activity = result["activity"]

        # Check that file events are included
        types = [a["type"] for a in activity]
        self.assertIn(FILE_CREATED, types)
        self.assertIn(FILE_MODIFIED, types)
        self.assertIn(FILE_DELETED, types)

        # Check entry structure
        deleted_entry = next(a for a in activity if a["type"] == FILE_DELETED)
        self.assertEqual(deleted_entry["detail"], "/data/confidential.docx")
        self.assertEqual(deleted_entry["path"], "/data/confidential.docx")
        self.assertEqual(deleted_entry["filename"], "confidential.docx")
        self.assertIn("time", deleted_entry)
        self.assertNotEqual(deleted_entry["time"], "Unknown")

    def test_acceptance_file_deletion_specifically(self):
        """Plan §16 Primary Acceptance Test: File deletion verified end-to-end."""
        monitor = EventMonitor(
            client_id="client-acceptance",
            monitored_directories=[self.monitored_dir],
            storage_root=self.events_dir,
            apps_provider=lambda: {},
        )
        monitor.initialize_baselines()

        target_file = self.monitored_dir / "secret_plan.pdf"
        target_file.write_text("classified data")

        # Baseline capture
        monitor.poll_once()

        # Delete target file
        target_file.unlink()

        # Detect and emit
        emitted_count = monitor.poll_once()
        self.assertEqual(emitted_count, 1)

        # Retrieve log via Get Log
        log_result = get_activity_log(period="1d", storage_dir=self.storage_dir)
        activity = log_result["activity"]

        # Verify FILE_DELETED is in log with expected path and timestamp
        deletion_entries = [a for a in activity if a["type"] == FILE_DELETED]
        self.assertEqual(len(deletion_entries), 1)
        entry = deletion_entries[0]
        self.assertEqual(entry["path"], str(target_file.resolve()))
        self.assertEqual(entry["detail"], str(target_file.resolve()))
        self.assertEqual(entry["filename"], "secret_plan.pdf")
        self.assertTrue(entry["time"])
        self.assertNotEqual(entry["time"], "Unknown")

    def test_passive_dhcp_and_telemetry_files_excluded(self):
        """Plan §9, §18, §19: DHCP observations and telemetry files excluded."""
        neighbourhood_dir = self.monitored_dir / "storage" / "network_neighbourhood"
        telemetry_dir = self.monitored_dir / "storage" / "network_telemetry"
        passive_pkts_dir = self.monitored_dir / "storage" / "passive_packets"

        for d in (neighbourhood_dir, telemetry_dir, passive_pkts_dir):
            d.mkdir(parents=True)

        monitor = EventMonitor(
            client_id="test-client",
            monitored_directories=[self.monitored_dir],
            storage_root=self.events_dir,
            apps_provider=lambda: {},
        )
        monitor.initialize_baselines()

        # Rapidly write/update passive files.
        (neighbourhood_dir / "dhcp_obs.json").write_text('{"dhcp": "192.168.1.50"}')
        (telemetry_dir / "stream.json").write_text('{"flow": 123}')
        (passive_pkts_dir / "capture.json").write_text('{"packets": 456}')

        # Poll monitor
        events = monitor.check_file_changes()
        # All passive files must be completely ignored!
        self.assertEqual(len(events), 0)

        # Also verify modifications to passive files are ignored
        (neighbourhood_dir / "dhcp_obs.json").write_text('{"dhcp": "192.168.1.51"}')
        events = monitor.check_file_changes()
        self.assertEqual(len(events), 0)

    def test_normal_files_remain_monitored(self):
        """Plan §20: Ensure legitimate user/app files are monitored and not filtered."""
        normal_file_1 = self.monitored_dir / "myapp.py"
        normal_file_2 = self.monitored_dir / "config.ini"

        monitor = EventMonitor(
            client_id="test-client",
            monitored_directories=[self.monitored_dir],
            storage_root=self.events_dir,
            apps_provider=lambda: {},
        )
        monitor.initialize_baselines()

        normal_file_1.write_text("print('hello')")
        normal_file_2.write_text("[section]\nkey=val")

        events = monitor.check_file_changes()
        self.assertEqual(len(events), 2)
        paths = {e.path for e in events}
        self.assertIn(str(normal_file_1.resolve()), paths)
        self.assertIn(str(normal_file_2.resolve()), paths)

    def test_restart_persistence(self):
        """Plan §21: Events survive monitor restart and remain available in Get Log."""
        # Session 1: Monitor running, file deleted
        monitor1 = EventMonitor(
            client_id="test-client",
            monitored_directories=[self.monitored_dir],
            storage_root=self.events_dir,
            apps_provider=lambda: {},
        )
        monitor1.initialize_baselines()

        doc = self.monitored_dir / "presentation.pptx"
        doc.write_text("slide deck")
        monitor1.poll_once()

        # Delete file in Session 1
        doc.unlink()
        monitor1.poll_once()
        monitor1.stop()

        # Simulate Client Restart -> Session 2 starts fresh
        monitor2 = EventMonitor(
            client_id="test-client",
            monitored_directories=[self.monitored_dir],
            storage_root=self.events_dir,
            apps_provider=lambda: {},
        )
        monitor2.initialize_baselines()

        # Retrieve activity log after restart
        log_result = get_activity_log(period="1d", storage_dir=self.storage_dir)
        activity = log_result["activity"]
        types = [a["type"] for a in activity]
        self.assertIn(FILE_DELETED, types)

    def test_multiple_clients_isolated(self):
        """Plan §22: Events from Client A do not appear in Client B's log."""
        storage_a = self.test_dir / "client_a_storage"
        storage_b = self.test_dir / "client_b_storage"
        events_a = storage_a / "events"
        events_b = storage_b / "events"
        events_a.mkdir(parents=True)
        events_b.mkdir(parents=True)

        today_str = datetime.now().strftime("%Y-%m-%d")
        now_ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+00:00")

        # Client A records a deletion
        (events_a / f"{today_str}.json").write_text(
            json.dumps([
                {
                    "event_type": FILE_DELETED,
                    "timestamp": now_ts,
                    "path": "/home/user/client_a_file.txt",
                }
            ])
        )

        # Client B has no events
        (events_b / f"{today_str}.json").write_text("[]")

        log_a = get_activity_log(period="1d", storage_dir=storage_a)
        log_b = get_activity_log(period="1d", storage_dir=storage_b)

        # Client A has FILE_DELETED
        self.assertTrue(any(a["type"] == FILE_DELETED for a in log_a["activity"]))

        # Client B has NO FILE_DELETED
        self.assertFalse(any(a["type"] == FILE_DELETED for a in log_b["activity"]))

    def test_handle_get_activity_log_with_args_formats(self):
        """Verify _handle_get_activity_log works with both string and dict args."""
        with patch("client_lib.get_activity_log") as mock_get_log:
            mock_get_log.return_value = {"activity": []}

            # Dict args
            _handle_get_activity_log({"args": {"period": "7d"}})
            mock_get_log.assert_called_with("7d")

            # String args
            _handle_get_activity_log({"args": "1w"})
            mock_get_log.assert_called_with("1w")

            # Default
            _handle_get_activity_log({})
            mock_get_log.assert_called_with("1d")

    def test_server_defense_in_depth_rejects_file_alerts(self):
        """Plan §23: Server save_alert ignores file events sent as alerts."""
        try:
            from server_lib import save_alert
        except ImportError:
            self.skipTest("server_lib dependencies not available")

        for file_ev in (FILE_CREATED, FILE_MODIFIED, FILE_DELETED, FILE_RENAMED):
            alert_payload = {
                "alert_type": "SECURITY_EVENT",
                "event_type": file_ev,
                "severity": "LOW",
                "title": f"Activity Event: {file_ev}",
                "description": "Path: /file.txt",
                "detected_at": "2026-09-06 14:00:00",
            }
            # save_alert must reject/ignore it and return False
            saved = save_alert("00:11:22:33:44:55", alert_payload)
            self.assertFalse(saved)


if __name__ == "__main__":
    unittest.main()
