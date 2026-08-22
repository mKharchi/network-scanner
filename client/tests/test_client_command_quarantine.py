"""Command-routing tests for quarantine and process-policy controls."""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock


CLIENT_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLIENT_DIRECTORY))

from client_lib import handle_command  # noqa: E402


class ClientCommandQuarantineTests(unittest.TestCase):
    def setUp(self):
        self.quarantine_manager = MagicMock()
        self.process_monitor = MagicMock()

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


if __name__ == "__main__":
    unittest.main()
