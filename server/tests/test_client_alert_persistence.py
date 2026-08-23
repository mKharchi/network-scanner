"""Regression tests for alerts sent asynchronously by managed clients."""

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

SERVER_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIRECTORY))

try:
    import mysql.connector  # noqa: F401
except ModuleNotFoundError:
    mysql_module = types.ModuleType("mysql")
    mysql_module.connector = types.ModuleType("mysql.connector")
    sys.modules["mysql"] = mysql_module
    sys.modules["mysql.connector"] = mysql_module.connector

from server_components import server_lib


class ClientAlertPersistenceTests(unittest.TestCase):
    def _handle(self, alert, forbidden_rows=()):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = (7,)
        cursor.fetchall.return_value = list(forbidden_rows)

        with patch.object(server_lib, "get_connection", return_value=conn), patch(
            "server_components.event_broadcaster.broadcast_alert"
        ) as broadcast:
            self.assertTrue(server_lib.handle_client_alert("AA:BB", alert))

        self.assertTrue(any("INSERT INTO alerts" in str(call.args[0]) for call in cursor.execute.call_args_list))
        broadcast.assert_called_once()

    def test_quarantine_security_event_is_persisted(self):
        self._handle(
            {
                "alert_type": "SECURITY_EVENT",
                "event_type": "CLIENT_QUARANTINED",
                "severity": "LOW",
                "title": "Network Quarantine Event: CLIENT_QUARANTINED",
                "description": "Administrator requested network isolation",
                "detected_at": "2026-08-23T12:00:00+00:00",
                "activity_time": "2026-08-23T12:00:00+00:00",
            }
        )

    def test_terminated_executable_matches_configured_keyword(self):
        self._handle(
            {
                "alert_type": "FORBIDDEN_PROCESS",
                "event_type": "FORBIDDEN_PROCESS_DETECTED",
                "severity": "HIGH",
                "process_name": "Discord.exe",
                "action": "TERMINATED",
                "title": "Forbidden process terminated: Discord.exe",
                "description": "Process was terminated.",
                "detected_at": "2026-08-23T12:00:00+00:00",
                "activity_time": "2026-08-23T12:00:00+00:00",
            },
            [("discord", "HIGH", "Unauthorized chat client")],
        )


if __name__ == "__main__":
    unittest.main()
