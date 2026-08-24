"""Command-routing tests for quarantine and process-policy controls."""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


CLIENT_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLIENT_DIRECTORY))

from client_lib import handle_command  # noqa: E402


class ClientCommandQuarantineTests(unittest.TestCase):
    def setUp(self):
        self.quarantine_manager = MagicMock()
        self.process_monitor = MagicMock()
        self.network_state_manager = MagicMock()

    def test_quarantine_command_routes_reason_duration_and_command_id(self):
        self.quarantine_manager.quarantine_endpoint.return_value = {"status": "ok"}

        result = handle_command(
            {
                "command": "QUARANTINE_CLIENT",
                "args": {
                    "reason": "Repeated violations",
                    "duration_minutes": 30,
                    "command_id": "cmd-quarantine-1",
                },
            },
            quarantine_manager=self.quarantine_manager,
        )

        self.assertEqual(result, {"status": "ok"})
        self.quarantine_manager.quarantine_endpoint.assert_called_once_with(
            reason="Repeated violations",
            duration_minutes=30,
            command_id="cmd-quarantine-1",
        )

    def test_release_and_status_commands_route_to_quarantine_manager(self):
        self.quarantine_manager.release_quarantine.return_value = {"status": "ok"}
        self.quarantine_manager.get_status.return_value = {"state": "QUARANTINED"}

        release = handle_command(
            {
                "command": "RELEASE_CLIENT",
                "args": {"reason": "Approved", "command_id": "cmd-release-1"},
            },
            quarantine_manager=self.quarantine_manager,
        )
        status = handle_command(
            {"command": "GET_QUARANTINE_STATUS"},
            quarantine_manager=self.quarantine_manager,
        )

        self.assertEqual(release, {"status": "ok"})
        self.assertEqual(status, {"state": "QUARANTINED"})
        self.quarantine_manager.release_quarantine.assert_called_once_with(
            reason="Approved", command_id="cmd-release-1"
        )
        self.quarantine_manager.get_status.assert_called_once_with()

    def test_policy_update_routes_rules_to_process_monitor(self):
        rules = [{"process_name": "discord.exe", "enabled": True}]

        result = handle_command(
            {"command": "UPDATE_FORBIDDEN_PROCESS_POLICY", "args": rules},
            process_monitor=self.process_monitor,
        )

        self.assertEqual(result, {"status": "ok", "rules_loaded": 1})
        self.process_monitor.set_rules.assert_called_once_with(rules)

    def test_quarantine_commands_fail_cleanly_without_a_manager(self):
        result = handle_command({"command": "GET_QUARANTINE_STATUS"})

        self.assertEqual(result["status"], "error")
        self.assertIn("not initialized", result["message"])

    def test_device_isolation_routes_to_the_separate_network_state_manager(self):
        self.network_state_manager.isolate_static_ip.return_value = {
            "status": "ok",
            "state": "ISOLATED",
        }
        self.network_state_manager.get_lifecycle_state.return_value = {"state": "ISOLATED"}

        isolate = handle_command(
            {"command": "ISOLATE_DEVICE", "args": {"reason": "Security response"}},
            network_state_manager=self.network_state_manager,
        )
        status = handle_command(
            {"command": "GET_DEVICE_ISOLATION_STATUS"},
            network_state_manager=self.network_state_manager,
        )

        self.assertEqual(isolate["state"], "ISOLATED")
        self.assertEqual(status, {"status": "ok", "data": {"state": "ISOLATED"}})
        self.network_state_manager.isolate_static_ip.assert_called_once_with(
            reason="Security response", enabled=True
        )

    def test_device_isolation_fails_cleanly_without_a_manager(self):
        result = handle_command({"command": "ISOLATE_DEVICE"})

        self.assertEqual(result["status"], "error")
        self.assertIn("Network state manager", result["message"])

    @patch("client_lib.threading.Timer")
    @patch("client_lib.platform.system", return_value="Windows")
    def test_shutdown_is_scheduled_and_acknowledged(self, _system, timer_class):
        result = handle_command({"command": "SHUTDOWN", "args": {"delay_seconds": 10}})

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["action"], "SHUTDOWN")
        timer_class.assert_called_once()
        timer_class.return_value.start.assert_called_once_with()

    @patch("client_lib.platform.system", return_value="UnknownOS")
    def test_restart_rejects_unsupported_platform(self, _system):
        result = handle_command({"command": "RESTART"})

        self.assertEqual(result["status"], "error")
        self.assertIn("not supported", result["message"])

    @patch("client_lib.psutil.cpu_percent", return_value=12.5)
    @patch("client_lib.psutil.virtual_memory")
    @patch("client_lib.psutil.disk_usage")
    def test_refresh_health_returns_standard_health_snapshot(self, disk_usage, virtual_memory, cpu_percent):
        virtual_memory.return_value.percent = 34.0
        disk_usage.return_value.percent = 45.0

        result = handle_command({"command": "REFRESH_HEALTH"})

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["health"]["cpu_percent"], 12.5)
        self.assertEqual(result["health"]["memory_percent"], 34.0)
        self.assertEqual(result["health"]["disk_percent"], 45.0)
        self.assertNotIn("location", result)

    @patch("client_lib.psutil.cpu_percent", return_value=12.5)
    @patch("client_lib.psutil.virtual_memory")
    @patch("client_lib.psutil.disk_usage")
    def test_refresh_health_includes_cached_location_in_telemetry(self, disk_usage, virtual_memory, cpu_percent):
        virtual_memory.return_value.percent = 34.0
        disk_usage.return_value.percent = 45.0
        location = {"id": 4, "floor": 1, "aisle": 2, "table": 1, "row": 2, "position": 4, "label": "F1-A2-T1-R2-P4"}

        with patch("client_lib.load_client_location", return_value=location):
            result = handle_command({"command": "REFRESH_HEALTH"})

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["location"], location)

    @patch("client_lib.os.replace")
    @patch("client_lib.open", create=True)
    def test_update_location_persists_valid_location(self, open_file, replace):
        location = {"id": 4, "label": "F1-A1-T1-P1", "floor": 1}

        result = handle_command({"command": "UPDATE_LOCATION", "args": location})

        self.assertEqual(result, {"status": "ok", "location": location})
        open_file.assert_called_once()
        replace.assert_called_once()


if __name__ == "__main__":
    unittest.main()
