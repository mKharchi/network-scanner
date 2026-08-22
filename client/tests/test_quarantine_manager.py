"""Unit tests for NetworkQuarantineManager."""

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from quarantine_manager import (
    NetworkQuarantineManager,
    QuarantineState,
    RULE_INBOUND,
    RULE_OUTBOUND,
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


if __name__ == "__main__":
    unittest.main()
