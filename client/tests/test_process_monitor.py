"""Unit tests for ForbiddenProcessMonitor and ViolationTracker."""

import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from process_monitor import (
    ForbiddenProcessMonitor,
    ViolationTracker,
    normalize_process_name,
)


class ViolationTrackerTestCase(unittest.TestCase):
    def test_normalize_process_name(self):
        self.assertEqual(normalize_process_name("discord.exe"), "discord")
        self.assertEqual(normalize_process_name("DISCORD.EXE"), "discord")
        self.assertEqual(normalize_process_name("uTorrent"), "utorrent")
        self.assertEqual(normalize_process_name(None), "")

    def test_violation_tracking_and_escalation(self):
        tracker = ViolationTracker(threshold=3, window_seconds=120)
        now = datetime.now(timezone.utc)

        # 1st violation
        count, history, is_esc = tracker.record_violation("discord.exe", 101, timestamp=now)
        self.assertEqual(count, 1)
        self.assertFalse(is_esc)

        # 2nd violation
        count, history, is_esc = tracker.record_violation("Discord", 102, timestamp=now + timedelta(seconds=10))
        self.assertEqual(count, 2)
        self.assertFalse(is_esc)

        # 3rd violation -> escalation triggered!
        count, history, is_esc = tracker.record_violation("discord.EXE", 103, timestamp=now + timedelta(seconds=20))
        self.assertEqual(count, 3)
        self.assertTrue(is_esc)
        self.assertEqual(len(history), 3)

    def test_sliding_window_expiration(self):
        tracker = ViolationTracker(threshold=3, window_seconds=60)
        t0 = datetime.now(timezone.utc)

        # 2 violations at t0
        tracker.record_violation("utorrent.exe", 201, timestamp=t0)
        tracker.record_violation("utorrent.exe", 202, timestamp=t0 + timedelta(seconds=10))

        # 3rd violation 80 seconds later (outside 60s window)
        t_later = t0 + timedelta(seconds=80)
        count, history, is_esc = tracker.record_violation("utorrent.exe", 203, timestamp=t_later)
        # Only the 3rd violation is within [t_later - 60s, t_later]
        self.assertEqual(count, 1)
        self.assertFalse(is_esc)


class ForbiddenProcessMonitorTestCase(unittest.TestCase):
    def setUp(self):
        self.rules = [
            {
                "rule_id": "rule-01",
                "process_name": "discord.exe",
                "severity": "HIGH",
                "enabled": True,
                "description": "Chat app",
            },
            {
                "rule_id": "rule-02",
                "process_name": "utorrent",
                "severity": "CRITICAL",
                "enabled": True,
                "description": "Torrent client",
            },
        ]
        self.monitor = ForbiddenProcessMonitor(
            rules=self.rules,
            scan_interval_seconds=10.0,
            escalation_threshold=2,
            escalation_window_seconds=60,
            auto_terminate=True,
        )

    @patch("psutil.process_iter")
    @patch.object(ForbiddenProcessMonitor, "terminate_process")
    def test_scan_and_enforce_detects_and_terminates(self, mock_terminate, mock_proc_iter):
        mock_proc1 = MagicMock()
        mock_proc1.info = {"pid": 5001, "name": "discord.exe", "exe": "C:\\Discord\\discord.exe"}
        mock_proc2 = MagicMock()
        mock_proc2.info = {"pid": 5002, "name": "notepad.exe", "exe": "C:\\Windows\\notepad.exe"}

        mock_proc_iter.return_value = [mock_proc1, mock_proc2]
        mock_terminate.return_value = {"status": "SUCCESS", "action": "TERMINATED", "message": "Terminated OK"}

        alerts = self.monitor.scan_and_enforce()
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["event_type"], "FORBIDDEN_PROCESS_DETECTED")
        self.assertEqual(alerts[0]["process_name"], "discord.exe")
        self.assertEqual(alerts[0]["pid"], 5001)
        self.assertEqual(alerts[0]["action"], "TERMINATED")
        mock_terminate.assert_called_once_with(5001, "discord.exe")

    @patch("psutil.process_iter")
    @patch.object(ForbiddenProcessMonitor, "terminate_process")
    def test_scan_and_enforce_escalation_alert(self, mock_terminate, mock_proc_iter):
        mock_proc = MagicMock()
        mock_proc.info = {"pid": 7001, "name": "uTorrent.exe", "exe": "C:\\uTorrent\\uTorrent.exe"}
        mock_proc_iter.return_value = [mock_proc]
        mock_terminate.return_value = {"status": "SUCCESS", "action": "TERMINATED", "message": "Terminated"}

        # 1st scan
        alerts1 = self.monitor.scan_and_enforce()
        self.assertEqual(len(alerts1), 1)
        self.assertEqual(alerts1[0]["event_type"], "FORBIDDEN_PROCESS_DETECTED")

        # 2nd scan -> reaches threshold (2) -> generates both base alert and critical escalation alert
        alerts2 = self.monitor.scan_and_enforce()
        self.assertEqual(len(alerts2), 2)
        event_types = [a["event_type"] for a in alerts2]
        self.assertIn("FORBIDDEN_PROCESS_DETECTED", event_types)
        self.assertIn("CRITICAL_FORBIDDEN_PROCESS_REPEATED", event_types)

    @patch("psutil.process_iter")
    @patch.object(ForbiddenProcessMonitor, "terminate_process")
    def test_scan_and_enforce_isolation_callback(self, mock_terminate, mock_proc_iter):
        isolation_cb = MagicMock()
        monitor = ForbiddenProcessMonitor(
            rules=self.rules,
            scan_interval_seconds=10.0,
            escalation_threshold=2,
            escalation_window_seconds=60,
            isolation_callback=isolation_cb,
            auto_terminate=True,
        )
        mock_proc = MagicMock()
        mock_proc.info = {"pid": 7001, "name": "uTorrent.exe", "exe": "C:\\uTorrent\\uTorrent.exe"}
        mock_proc_iter.return_value = [mock_proc]
        mock_terminate.return_value = {"status": "SUCCESS", "action": "TERMINATED", "message": "Terminated"}

        # 1st scan -> no escalation, isolation callback not called
        monitor.scan_and_enforce()
        isolation_cb.assert_not_called()

        # 2nd scan -> reaches threshold (2) -> isolation callback fired
        monitor.scan_and_enforce()
        isolation_cb.assert_called_once()
        call_arg = isolation_cb.call_args[0][0]
        self.assertEqual(call_arg["event_type"], "CRITICAL_FORBIDDEN_PROCESS_REPEATED")
        self.assertEqual(call_arg["process_name"], "utorrent")


if __name__ == "__main__":
    unittest.main()
