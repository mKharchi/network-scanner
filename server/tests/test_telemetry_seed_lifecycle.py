"""Lifecycle integration tests for the TELEMETRY_SEED exchange (Plan Phase 13).

Covers:
- Test 1: Fresh client registration and subsequent seed acceptance.
- Test 2: Restart of same client with persisted identity and seed acceptance.
- Test 3: Reconnection after connection drop with preserved identity.
- Test 4: Two concurrent clients maintaining independent identities without cross-association.
- Test 5: Deliberate mismatch between connection identity and payload client_id is rejected.
"""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

SERVER_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIRECTORY))

from server_components import server_lib  # noqa: E402
from server_components.server_lib import (  # noqa: E402
    handle_telemetry_seed,
    register_client,
    remove_client,
)


class FakeCursor:
    def __init__(self):
        self.queries = []
        self.params = []

    def execute(self, query, params=()):
        self.queries.append(query)
        self.params.append(params)

    def close(self):
        pass


class FakeConnection:
    def __init__(self):
        self.cursor_instance = FakeCursor()
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


class TelemetrySeedLifecycleTests(unittest.TestCase):
    def setUp(self):
        server_lib.clients.clear()
        server_lib.interactive_clients.clear()
        self.mock_update_db = patch.object(server_lib, "update_client_db", return_value=True)
        self.mock_update_db.start()

    def tearDown(self):
        self.mock_update_db.stop()
        server_lib.clients.clear()
        server_lib.interactive_clients.clear()

    def _create_mock_conn(self):
        conn = MagicMock()
        conn.sendall = MagicMock()
        return conn

    def _client_info(self, mac, hostname="TEST-HOST", ip="192.168.1.50"):
        return {
            "mac": mac,
            "hostname": hostname,
            "ip": ip,
            "os": {"system": "Linux"},
            "client_version": "1.0.0",
        }

    def _seed_payload(self, client_id, mac="AA:BB:CC:DD:EE:01"):
        return {
            "client_id": client_id,
            "sync_timestamp": "2026-09-06T12:00:00Z",
            "updated_devices": [
                {
                    "mac": mac.lower(),
                    "ip": "192.168.1.100",
                    "hostname": "DEVICE-1",
                }
            ],
        }

    def test_1_fresh_client_registers_and_seed_accepted(self):
        """Test 1: New client -> register -> seed. Client_id matches, seed accepted."""
        conn = self._create_mock_conn()
        mac = "AA:BB:CC:DD:EE:01"
        info = self._client_info(mac)

        client_id = register_client(info, conn)
        self.assertEqual(client_id, "client-aabbccddee01")

        sent_messages = []
        with patch("server_components.telemetry_merge.get_connection", return_value=FakeConnection()):
            with patch.object(server_lib, "send_message", side_effect=lambda _c, msg: sent_messages.append(msg)):
                payload = self._seed_payload(client_id, mac)
                result = handle_telemetry_seed(mac, payload)

        self.assertTrue(result)
        self.assertEqual(len(sent_messages), 1)
        ack = sent_messages[0]
        self.assertEqual(ack["type"], "SEED_ACK")
        self.assertEqual(ack["status"], "ack")
        self.assertEqual(ack["client_id"], client_id)

    def test_2_restart_same_client_preserves_id_and_seed_accepted(self):
        """Test 2: Restart same client -> same persisted client_id -> new connection -> seed accepted."""
        mac = "AA:BB:CC:DD:EE:02"
        info = self._client_info(mac)

        # First connection
        conn1 = self._create_mock_conn()
        client_id1 = register_client(info, conn1)
        self.assertEqual(client_id1, "client-aabbccddee02")
        remove_client(mac, conn1)

        # Restart with new connection
        conn2 = self._create_mock_conn()
        client_id2 = register_client(info, conn2)
        self.assertEqual(client_id1, client_id2)

        sent_messages = []
        with patch("server_components.telemetry_merge.get_connection", return_value=FakeConnection()):
            with patch.object(server_lib, "send_message", side_effect=lambda _c, msg: sent_messages.append(msg)):
                payload = self._seed_payload(client_id2, mac)
                result = handle_telemetry_seed(mac, payload)

        self.assertTrue(result)
        self.assertEqual(len(sent_messages), 1)
        self.assertEqual(sent_messages[0]["type"], "SEED_ACK")
        self.assertEqual(sent_messages[0]["client_id"], client_id2)

    def test_3_reconnect_after_drop_preserves_identity_and_seed_accepted(self):
        """Test 3: Connection lost -> reconnect -> seed accepted."""
        mac = "AA:BB:CC:DD:EE:03"
        info = self._client_info(mac)

        conn1 = self._create_mock_conn()
        client_id = register_client(info, conn1)

        # Simulate reconnect without explicit remove (re-registration overwrites live connection)
        conn2 = self._create_mock_conn()
        reconnected_id = register_client(info, conn2)
        self.assertEqual(client_id, reconnected_id)

        sent_messages = []
        with patch("server_components.telemetry_merge.get_connection", return_value=FakeConnection()):
            with patch.object(server_lib, "send_message", side_effect=lambda _c, msg: sent_messages.append(msg)):
                payload = self._seed_payload(reconnected_id, mac)
                result = handle_telemetry_seed(mac, payload)

        self.assertTrue(result)
        self.assertEqual(len(sent_messages), 1)
        self.assertEqual(sent_messages[0]["type"], "SEED_ACK")
        self.assertEqual(sent_messages[0]["client_id"], client_id)

    def test_4_two_clients_maintain_isolated_seed_identities(self):
        """Test 4: Client A -> ID A, Client B -> ID B. Seeds route to respective connections without cross-association."""
        mac_a = "AA:BB:CC:DD:EE:0A"
        mac_b = "AA:BB:CC:DD:EE:0B"
        conn_a = self._create_mock_conn()
        conn_b = self._create_mock_conn()

        id_a = register_client(self._client_info(mac_a), conn_a)
        id_b = register_client(self._client_info(mac_b), conn_b)
        self.assertNotEqual(id_a, id_b)

        sent_to_a = []
        sent_to_b = []

        def mock_send(conn, msg):
            if conn is conn_a:
                sent_to_a.append(msg)
            elif conn is conn_b:
                sent_to_b.append(msg)

        with patch("server_components.telemetry_merge.get_connection", return_value=FakeConnection()):
            with patch.object(server_lib, "send_message", side_effect=mock_send):
                res_a = handle_telemetry_seed(mac_a, self._seed_payload(id_a, mac_a))
                res_b = handle_telemetry_seed(mac_b, self._seed_payload(id_b, mac_b))

        self.assertTrue(res_a)
        self.assertTrue(res_b)
        self.assertEqual(len(sent_to_a), 1)
        self.assertEqual(len(sent_to_b), 1)
        self.assertEqual(sent_to_a[0]["client_id"], id_a)
        self.assertEqual(sent_to_b[0]["client_id"], id_b)

    def test_5_deliberate_mismatch_is_rejected_with_seed_nack(self):
        """Test 5: Connection = A, Payload = B -> server rejects with SEED_NACK."""
        mac_a = "AA:BB:CC:DD:EE:05"
        conn_a = self._create_mock_conn()
        register_client(self._client_info(mac_a), conn_a)

        impostor_payload = self._seed_payload("client-impostor-999", mac_a)
        sent_messages = []

        with patch.object(server_lib, "send_message", side_effect=lambda _c, msg: sent_messages.append(msg)):
            result = handle_telemetry_seed(mac_a, impostor_payload)

        self.assertFalse(result)
        self.assertEqual(len(sent_messages), 1)
        nack = sent_messages[0]
        self.assertEqual(nack["type"], "SEED_NACK")
        self.assertEqual(nack["status"], "nack")
        self.assertIn("Payload client_id does not match the registered connection", nack.get("reason", ""))


if __name__ == "__main__":
    unittest.main()
