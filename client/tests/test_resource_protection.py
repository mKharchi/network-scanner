"""Unit tests for Automatic Resource Protection (ResourceProtectionMonitor, ProtectedProcessValidator, and ProcessManager)."""

import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

CLIENT_APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(CLIENT_APP_DIR) not in sys.path:
    sys.path.insert(0, str(CLIENT_APP_DIR))

from process_monitor import (
    ProtectedProcessValidator,
    ProcessManager,
    ResourceProtectionMonitor,
    normalize_process_name,
)


class ProtectedProcessValidatorTestCase(unittest.TestCase):
    def test_protected_system_pids(self):
        self.assertTrue(ProtectedProcessValidator.is_protected_system_process(0))
        self.assertTrue(ProtectedProcessValidator.is_protected_system_process(1))
        self.assertTrue(ProtectedProcessValidator.is_protected_system_process(2))

    def test_protected_system_process_names(self):
        self.assertTrue(ProtectedProcessValidator.is_protected_system_process(100, "systemd"))
        self.assertTrue(ProtectedProcessValidator.is_protected_system_process(101, "svchost.exe"))
        self.assertTrue(ProtectedProcessValidator.is_protected_system_process(102, "csrss.EXE"))
        self.assertTrue(ProtectedProcessValidator.is_protected_system_process(103, "init"))
        self.assertTrue(ProtectedProcessValidator.is_protected_system_process(104, "sshd"))
        self.assertTrue(ProtectedProcessValidator.is_protected_system_process(105, "explorer.exe"))

    def test_client_self_protection(self):
        current_pid = os.getpid()
        self.assertTrue(ProtectedProcessValidator.is_client_process(current_pid))
        is_safe, reason = ProtectedProcessValidator.is_safe_to_terminate(current_pid, "python")
        self.assertFalse(is_safe)
        self.assertEqual(reason, "client_process")

    def test_safe_unprotected_candidate(self):
        is_safe, reason = ProtectedProcessValidator.is_safe_to_terminate(9999, "my_rogue_task.exe")
        self.assertTrue(is_safe)
        self.assertEqual(reason, "safe")


class ProcessManagerTestCase(unittest.TestCase):
    @patch("psutil.Process")
    def test_graceful_termination_success(self, mock_psutil_proc):
        proc_instance = MagicMock()
        proc_instance.terminate.return_value = None
        proc_instance.wait.return_value = None
        mock_psutil_proc.return_value = proc_instance

        res = ProcessManager.terminate_process(9999, "worker_task")
        self.assertEqual(res["status"], "SUCCESS")
        self.assertEqual(res["action"], "TERMINATED")
        proc_instance.terminate.assert_called_once()

    @patch("psutil.Process")
    def test_force_kill_fallback_on_timeout(self, mock_psutil_proc):
        import psutil
        proc_instance = MagicMock()
        # Graceful terminate wait raises TimeoutExpired, kill succeeds
        proc_instance.wait.side_effect = [psutil.TimeoutExpired(1.5), None]
        mock_psutil_proc.return_value = proc_instance

        res = ProcessManager.terminate_process(9999, "hung_worker")
        self.assertEqual(res["status"], "SUCCESS")
        self.assertEqual(res["action"], "FORCE_KILLED")
        proc_instance.terminate.assert_called_once()
        proc_instance.kill.assert_called_once()

    def test_rejection_for_protected_pid(self):
        res = ProcessManager.terminate_process(1, "systemd")
        self.assertEqual(res["status"], "REJECTED_PROTECTED")


class ResourceProtectionMonitorTestCase(unittest.TestCase):
    def setUp(self):
        self.config = {
            "enabled": True,
            "cpu": {
                "enabled": True,
                "threshold": 80.0,
                "sustained_seconds": 10.0,
            },
            "memory": {
                "enabled": True,
                "threshold": 90.0,
                "sustained_seconds": 15.0,
            },
            "cooldown_seconds": 60.0,
            "max_interventions_per_hour": 5,
        }
        self.alert_callback = MagicMock()
        self.monitor = ResourceProtectionMonitor(
            config=self.config,
            scan_interval_seconds=1.0,
            alert_callback=self.alert_callback,
            auto_terminate=True,
        )

    def test_sustained_duration_logic(self):
        """Verify that evaluation does not trigger if resource spike has not lasted for sustained_seconds."""
        with patch("psutil.cpu_percent", return_value=85.0), \
             patch("psutil.virtual_memory") as mock_vmem, \
             patch.object(self.monitor, "_evaluate_candidates") as mock_eval:
            mock_vmem.return_value.percent = 50.0

            # 1st measurement: threshold crossed, timer initialized
            evs = self.monitor.evaluate_and_enforce()
            self.assertEqual(evs, [])
            mock_eval.assert_not_called()
            self.assertIsNotNone(self.monitor._cpu_high_since)

            # Advance high timestamp to simulate sustained condition
            self.monitor._cpu_high_since = time.time() - 12.0
            mock_eval.return_value = [{"event_type": "RESOURCE_PROTECTION_ACTION"}]

            evs2 = self.monitor.evaluate_and_enforce()
            self.assertEqual(len(evs2), 1)
            mock_eval.assert_called_once()
            # Timer reset after evaluation
            self.assertIsNone(self.monitor._cpu_high_since)

    @patch("psutil.process_iter")
    @patch("psutil.cpu_percent", return_value=20.0)
    @patch("psutil.virtual_memory")
    @patch.object(ProcessManager, "terminate_process")
    def test_forbidden_rule_priority_candidate_terminated(
        self, mock_terminate, mock_vmem, mock_cpu, mock_proc_iter
    ):
        mock_vmem.return_value.percent = 30.0
        mock_terminate.return_value = {"status": "SUCCESS", "action": "TERMINATED", "message": "OK"}

        self.monitor.set_rules([
            {
                "process_name": "crypto_miner",
                "resource_protection_eligible": True,
                "enabled": True,
            }
        ])

        p1 = MagicMock()
        p1.info = {"pid": 6001, "name": "crypto_miner.exe", "cpu_percent": 90.0, "memory_percent": 10.0, "exe": "/tmp/crypto_miner"}
        p2 = MagicMock()
        p2.info = {"pid": 6002, "name": "other_worker", "cpu_percent": 80.0, "memory_percent": 5.0, "exe": "/tmp/other_worker"}
        mock_proc_iter.return_value = [p1, p2]

        events = self.monitor._evaluate_candidates("cpu", 95.0, 80.0)
        self.assertTrue(any(e.get("event_type") == "RESOURCE_PROTECTION_ACTION" for e in events))
        mock_terminate.assert_called_once_with(6001, "crypto_miner.exe", timeout=1.5)

    @patch("psutil.process_iter")
    @patch("psutil.cpu_percent", return_value=95.0)
    @patch("psutil.virtual_memory")
    def test_ineligible_candidate_generates_skip_alert(
        self, mock_vmem, mock_cpu, mock_proc_iter
    ):
        mock_vmem.return_value.percent = 30.0
        # No forbidden rules and no resource_protection_eligible rules
        self.monitor.set_rules([])

        p1 = MagicMock()
        p1.info = {"pid": 6003, "name": "heavy_unmarked_task", "cpu_percent": 95.0, "memory_percent": 10.0, "exe": "/bin/heavy"}
        mock_proc_iter.return_value = [p1]

        events = self.monitor._evaluate_candidates("cpu", 95.0, 80.0)
        self.assertTrue(any(e.get("event_type") == "RESOURCE_PROTECTION_SKIP" for e in events))
        skip_event = [e for e in events if e.get("event_type") == "RESOURCE_PROTECTION_SKIP"][0]
        self.assertIn("not eligible", skip_event.get("reason", ""))

    @patch("psutil.process_iter")
    @patch("psutil.cpu_percent", return_value=90.0)
    @patch("psutil.virtual_memory")
    @patch.object(ProcessManager, "terminate_process")
    def test_cooldown_and_hourly_limit(
        self, mock_terminate, mock_vmem, mock_cpu, mock_proc_iter
    ):
        mock_vmem.return_value.percent = 30.0
        mock_terminate.return_value = {"status": "SUCCESS", "action": "TERMINATED", "message": "OK"}
        self.monitor.set_rules([{"process_name": "worker", "resource_protection_eligible": True, "enabled": True}])

        p1 = MagicMock()
        p1.info = {"pid": 7001, "name": "worker", "cpu_percent": 90.0, "memory_percent": 10.0, "exe": "/bin/worker"}
        mock_proc_iter.return_value = [p1]

        # 1st action succeeds
        events1 = self.monitor._evaluate_candidates("cpu", 92.0, 80.0)
        self.assertTrue(any(e.get("event_type") == "RESOURCE_PROTECTION_ACTION" for e in events1))

        # 2nd immediate attempt -> cooldown is active
        events2 = self.monitor._evaluate_candidates("cpu", 92.0, 80.0)
        self.assertTrue(any(e.get("event_type") == "RESOURCE_PROTECTION_SKIP" and e.get("reason") == "cooldown_active" for e in events2))


if __name__ == "__main__":
    unittest.main()
