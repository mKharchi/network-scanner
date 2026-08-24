"""Unit tests for NetworkQuarantineManager."""

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from quarantine_manager import (
    NetworkQuarantineManager,
    QuarantineState,
    RULE_ALLOW_SERVER_OUT,
)


class NetworkQuarantineManagerTestCase(unittest.TestCase):
    def setUp(self):
        self.manager = NetworkQuarantineManager(
            server_ip="192.168.1.100",
            server_port=5000,
            default_max_duration_minutes=30,
            dry_run=True,
        )

    def test_initial_state_is_normal(self):
        self.assertEqual(self.manager.state, QuarantineState.NORMAL)
        self.assertFalse(self.manager.is_quarantined)
        status = self.manager.get_status()
        self.assertEqual(status["state"], QuarantineState.NORMAL)
        self.assertFalse(status["is_quarantined"])
        self.assertEqual(status["enforcement_method"], "SIMULATED_NO_FIREWALL")

    def test_quarantine_endpoint_success(self):
        events = []
        self.manager.event_callback = lambda ev: events.append(ev)

        res = self.manager.quarantine_endpoint(
            reason="Violation escalation",
            duration_minutes=15,
            command_id="cmd-quarantine-01",
        )

        self.assertEqual(res["status"], "ok")
        self.assertEqual(self.manager.state, QuarantineState.QUARANTINED)
        self.assertTrue(self.manager.is_quarantined)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "CLIENT_QUARANTINED")
        self.assertEqual(events[0]["reason"], "Violation escalation")
        self.assertEqual(events[0]["command_id"], "cmd-quarantine-01")

        status = self.manager.get_status()
        self.assertEqual(status["state"], QuarantineState.QUARANTINED)
        self.assertTrue(status["is_quarantined"])
        self.assertEqual(status["reason"], "Violation escalation")

    def test_release_quarantine(self):
        events = []
        self.manager.event_callback = lambda ev: events.append(ev)

        # Place in quarantine first
        self.manager.quarantine_endpoint(reason="Test isolate")
        self.assertEqual(self.manager.state, QuarantineState.QUARANTINED)

        # Release
        res = self.manager.release_quarantine(reason="Admin unblock", command_id="cmd-rel-01")
        self.assertEqual(res["status"], "ok")
        self.assertEqual(self.manager.state, QuarantineState.NORMAL)
        self.assertFalse(self.manager.is_quarantined)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[1]["event_type"], "CLIENT_QUARANTINE_RELEASED")
        self.assertEqual(events[1]["command_id"], "cmd-rel-01")

    @patch.object(NetworkQuarantineManager, "_apply_rules")
    def test_quarantine_failure_handling(self, mock_apply):
        mock_apply.return_value = (False, "Permission denied")
        events = []
        self.manager.event_callback = lambda ev: events.append(ev)

        res = self.manager.quarantine_endpoint(reason="Test fail")
        self.assertEqual(res["status"], "error")
        self.assertEqual(self.manager.state, QuarantineState.QUARANTINE_FAILED)

    @patch.object(NetworkQuarantineManager, "_remove_rules")
    def test_release_failure_keeps_the_endpoint_quarantined(self, mock_remove):
        self.manager.quarantine_endpoint(reason="Test isolate")
        mock_remove.return_value = (False, "Access denied")
        events = []
        self.manager.event_callback = events.append

        result = self.manager.release_quarantine(command_id="cmd-release-failed")

        self.assertEqual(result["status"], "error")
        self.assertEqual(self.manager.state, QuarantineState.QUARANTINED)
        self.assertEqual(events[0]["event_type"], "CLIENT_QUARANTINE_RELEASE_FAILED")
        self.assertEqual(events[0]["command_id"], "cmd-release-failed")
        self.assertEqual(len(events), 1)

    def test_missing_firewall_rules_are_ignored_in_french_and_mojibake(self):
        outputs = [
            "Aucune règle ne correspond aux critères spécifiés.",
            "Aucune rÃ¨gle ne correspond aux critÃ¨res spÃ©cifiÃ©s.",
        ]
        for output in outputs:
            with self.subTest(output=output):
                with patch.object(
                    self.manager,
                    "_run_cmd",
                    return_value=(1, output),
                ):
                    success, message = self.manager._delete_windows_firewall_rules(
                        ["AgentQuarantine-Server-Allow-Out"]
                    )
                self.assertTrue(success)
                self.assertEqual(message, "")

    def test_unexpected_firewall_delete_errors_are_preserved(self):
        with patch.object(
            self.manager,
            "_run_cmd",
            return_value=(1, "Access is denied."),
        ):
            success, message = self.manager._delete_windows_firewall_rules(
                ["AgentQuarantine-Server-Allow-Out"]
            )
        self.assertFalse(success)
        self.assertIn("Access is denied", message)

    @patch("quarantine_manager.platform.system", return_value="Windows")
    def test_windows_quarantine_uses_profile_default_deny_not_block_rules(self, _system):
        manager = NetworkQuarantineManager(
            server_ip="192.168.1.100", server_port=5000, dry_run=False
        )
        commands = []

        def run_command(command):
            commands.append(command)
            if command[0] == "powershell.exe":
                return 0, "Public|Block|Allow"
            return 0, "Ok"

        with patch.object(manager, "_run_cmd", side_effect=run_command):
            success, _message = manager._apply_windows_firewall_rules()

        self.assertTrue(success)
        self.assertIn(("Public", "BLOCK", "ALLOW"), [manager._windows_profile_policy])
        self.assertIn(
            [
                "netsh", "advfirewall", "set", "allprofiles",
                "firewallpolicy", "blockinbound,blockoutbound",
            ],
            commands,
        )
        self.assertFalse(
            any(
                command[:6] == [
                    "netsh", "advfirewall", "firewall", "add", "rule",
                    "name=AgentQuarantine-Outbound",
                ]
                for command in commands
            )
        )

    @patch("quarantine_manager.platform.system", return_value="Windows")
    def test_windows_release_restores_the_captured_profile_policy(self, _system):
        manager = NetworkQuarantineManager(dry_run=False)
        manager._windows_profile_policy = ("Public", "Block", "Allow")
        commands = []

        with patch.object(manager, "_run_cmd", side_effect=lambda command: (commands.append(command) or (0, "Ok"))):
            success, _message = manager._remove_windows_firewall_rules()

        self.assertTrue(success)
        self.assertIn(
            [
                "netsh", "advfirewall", "set", "allprofiles",
                "firewallpolicy", "blockinbound,allowoutbound",
            ],
            commands,
        )

    @patch("quarantine_manager.platform.system", return_value="Windows")
    def test_windows_quarantine_handles_not_configured_profile(self, _system):
        manager = NetworkQuarantineManager(
            server_ip="192.168.1.100", server_port=5000, dry_run=False
        )
        commands = []

        def run_command(command):
            commands.append(command)
            if command[0] == "powershell.exe":
                return 0, "NotConfigured|NotConfigured|NotConfigured"
            return 0, "Ok"

        with patch.object(manager, "_run_cmd", side_effect=run_command):
            success, _message = manager._apply_windows_firewall_rules()

        self.assertTrue(success)
        # Should fallback to Public profile and BlockInbound/AllowOutbound defaults
        self.assertEqual(manager._windows_profile_policy, ("Public", "BLOCK", "ALLOW"))
        self.assertIn(
            [
                "netsh", "advfirewall", "set", "allprofiles",
                "firewallpolicy", "blockinbound,blockoutbound",
            ],
            commands,
        )


if __name__ == "__main__":
    unittest.main()
