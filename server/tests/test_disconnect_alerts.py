"""Unit tests for Step 3 disconnect classification.

Run from the repository root:
    python3 server/tests/test_disconnect_alerts.py

No real network requests or MySQL operations are performed.
"""

import queue
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


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


class FakeConnection:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class DisconnectAlertTests(unittest.TestCase):
    def setUp(self):
        self.original_ping = server_lib.ping_client
        self.original_disconnect_alert = server_lib.create_disconnect_alert
        self.original_agent_alert = server_lib.create_agent_stopped_alert
        self.original_log_connection = server_lib.log_connection
        self.original_delay = server_lib.DISCONNECT_PING_DELAY_SECONDS
        server_lib.DISCONNECT_PING_DELAY_SECONDS = 0
        server_lib.clients.clear()
        server_lib.pending_disconnect_checks.clear()

    def tearDown(self):
        server_lib.ping_client = self.original_ping
        server_lib.create_disconnect_alert = self.original_disconnect_alert
        server_lib.create_agent_stopped_alert = self.original_agent_alert
        server_lib.log_connection = self.original_log_connection
        server_lib.DISCONNECT_PING_DELAY_SECONDS = self.original_delay
        server_lib.clients.clear()
        server_lib.pending_disconnect_checks.clear()

    @staticmethod
    def client():
        return {
            "client_id": "client-test",
            "hostname": "workstation-01",
            "mac": "aa:bb:cc:dd:ee:ff",
            "ip": "172.16.1.10",
            "connection": FakeConnection(),
            "responses": queue.Queue(),
        }

    def test_reachable_disconnected_client_creates_agent_stopped_alert(self):
        client = self.client()
        token = object()
        server_lib.pending_disconnect_checks[client["mac"]] = token
        server_lib.ping_client = lambda ip: True
        agent_alerts = []
        server_lib.create_agent_stopped_alert = lambda snapshot: (
            agent_alerts.append(snapshot) or True
        )

        server_lib.verify_client_disconnect(client["mac"], client, token)

        self.assertEqual(agent_alerts, [client])
        self.assertNotIn(client["mac"], server_lib.pending_disconnect_checks)

    def test_unreachable_client_keeps_only_the_informational_alert(self):
        client = self.client()
        token = object()
        server_lib.pending_disconnect_checks[client["mac"]] = token
        server_lib.ping_client = lambda ip: False
        agent_alerts = []
        server_lib.create_agent_stopped_alert = lambda snapshot: agent_alerts.append(snapshot)

        server_lib.verify_client_disconnect(client["mac"], client, token)

        self.assertEqual(agent_alerts, [])
        self.assertNotIn(client["mac"], server_lib.pending_disconnect_checks)

    def test_reconnect_during_grace_period_cancels_verification(self):
        client = self.client()
        token = object()
        server_lib.pending_disconnect_checks[client["mac"]] = token
        server_lib.clients[client["mac"]] = self.client()
        server_lib.ping_client = lambda ip: self.fail("reconnected client was pinged")

        server_lib.verify_client_disconnect(client["mac"], client, token)

        self.assertNotIn(client["mac"], server_lib.pending_disconnect_checks)

    def test_server_requested_disconnect_does_not_start_agent_check(self):
        client = self.client()
        client["disconnect_expected"] = True
        server_lib.clients[client["mac"]] = client
        disconnect_alerts = []
        server_lib.create_disconnect_alert = lambda snapshot, expected: (
            disconnect_alerts.append((snapshot, expected)) or True
        )
        server_lib.log_connection = lambda mac, status: None

        server_lib.remove_client(client["mac"])
        server_lib.remove_client(client["mac"])

        self.assertTrue(client["connection"].closed)
        self.assertEqual(disconnect_alerts, [(client, True)])
        self.assertNotIn(client["mac"], server_lib.pending_disconnect_checks)

    def test_reachability_ping_sends_exactly_two_packets(self):
        with patch.object(server_lib.platform, "system", return_value="Linux"), patch.object(
            server_lib.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0),
        ) as run:
            self.assertTrue(server_lib.ping_client("172.16.1.10"))

        self.assertEqual(run.call_args.args[0][:3], ["ping", "-c", "2"])
        self.assertEqual(
            run.call_args.kwargs["timeout"],
            (server_lib.DISCONNECT_PING_TIMEOUT_SECONDS * 2) + 1,
        )


if __name__ == "__main__":
    unittest.main()
