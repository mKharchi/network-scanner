"""Unit tests for Phase 2 Event Monitoring layer."""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

CLIENT_APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(CLIENT_APP_DIR))

from event_monitor import (
    APP_INSTALLED,
    APP_UNINSTALLED,
    APP_UPDATED,
    FILE_CREATED,
    FILE_DELETED,
    FILE_MODIFIED,
    ClientEvent,
    EventDeduplicator,
    EventMonitor,
    EventRateLimiter,
)


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

        events = monitor.check_file_changes()
        self.assertEqual(len(events), 0)

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


if __name__ == "__main__":
    unittest.main()
