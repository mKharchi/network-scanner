"""Focused tests for persisted v2 observation-scope assignment and live push."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SERVER_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIRECTORY))

from server_components import server_lib  # noqa: E402


class FakeCursor:
    def __init__(self, row=None, rowcount=1):
        self.row = row
        self.rowcount = rowcount
        self.executions = []
        self.closed = False

    def execute(self, query, params=()):
        self.executions.append((query, params))

    def fetchone(self):
        return self.row

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, cursor):
        self.cursor_instance = cursor
        self.committed = False
        self.closed = False

    def cursor(self, **_kwargs):
        return self.cursor_instance

    def commit(self):
        self.committed = True

    def is_connected(self):
        return not self.closed

    def close(self):
        self.closed = True


class ObservationScopeTests(unittest.TestCase):
    def setUp(self):
        server_lib.clients.clear()

    def tearDown(self):
        server_lib.clients.clear()

    def test_set_scope_normalizes_and_persists_cidrs(self):
        cursor = FakeCursor(rowcount=1)
        connection = FakeConnection(cursor)
        with patch.object(server_lib, "get_connection", return_value=connection):
            result = server_lib.set_client_observation_scope(
                "client-07", ["172.16.2.1/26", "2001:db8::1/64"]
            )

        self.assertEqual(result, ["172.16.2.0/26", "2001:db8::/64"])
        self.assertTrue(connection.committed)
        self.assertIn("UPDATE clients", cursor.executions[0][0])
        self.assertEqual(cursor.executions[0][1][1], "client-07")

    def test_get_scope_returns_empty_for_missing_or_invalid_policy(self):
        for stored in (None, "not-json", '["not-a-cidr"]'):
            with self.subTest(stored=stored):
                cursor = FakeCursor(row={"observation_scope": stored})
                connection = FakeConnection(cursor)
                with patch.object(server_lib, "get_connection", return_value=connection):
                    self.assertEqual(server_lib.get_client_observation_scope("client-07"), [])

    def test_live_push_targets_only_the_registered_client(self):
        sent = []
        connection = object()
        server_lib.clients["AA:BB:CC:DD:EE:01"] = {
            "client_id": "client-07",
            "connection": connection,
            "send_lock": __import__("threading").Lock(),
        }
        with patch.object(server_lib, "send_message", side_effect=lambda conn, message: sent.append((conn, message))):
            result = server_lib.broadcast_observation_scope("client-07", ["10.0.0.1/24"])

        self.assertEqual(result["sent"], 1)
        self.assertEqual(sent, [(connection, {"type": "SCOPE_ASSIGNED", "observation_scope": ["10.0.0.0/24"]})])

    def test_invalid_scope_is_rejected_before_database_write(self):
        with self.assertRaises(ValueError):
            server_lib.set_client_observation_scope("client-07", ["not-a-cidr"])


if __name__ == "__main__":
    unittest.main()
