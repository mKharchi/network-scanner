"""Registration handshake coverage for v2 observation-scope delivery."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SERVER_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIRECTORY))

import server  # noqa: E402


class FakeConnection:
    def close(self):
        pass


class FakeServer:
    def __init__(self):
        self._accepted = False

    def accept(self):
        if self._accepted:
            raise OSError("stop test server")
        self._accepted = True
        return FakeConnection(), ("127.0.0.1", 12345)


class RegistrationScopeDeliveryTests(unittest.TestCase):
    def test_registered_reply_includes_persisted_observation_scope(self):
        registration = {
            "type": "REGISTER",
            "data": {
                "hostname": "test-host",
                "ip": "10.0.0.2",
                "mac": "AA:BB:CC:DD:EE:01",
                "os": {"system": "test"},
            },
        }
        sent = []
        with patch.object(server, "receive_message", side_effect=[registration, {"type": "REQUEST", "command": "GET_FORBIDDEN_PROCESSES"}]), \
             patch.object(server, "register_client", return_value="client-aabbccddee01"), \
             patch.object(server, "get_client_observation_scope", return_value=["10.0.0.0/24"]), \
             patch.object(server, "get_forbidden_processes", return_value=[]), \
             patch.object(server, "send_message", side_effect=lambda _conn, message: sent.append(message)), \
             patch.object(server.threading, "Thread") as thread:
            server.accept_clients(FakeServer())

        self.assertEqual(
            sent[0],
            {
                "type": "REGISTERED",
                "client_id": "client-aabbccddee01",
                "observation_scope": ["10.0.0.0/24"],
            },
        )
        self.assertEqual(sent[1], {"type": "FORBIDDEN_PROCESSES", "data": []})
        thread.assert_called_once()


if __name__ == "__main__":
    unittest.main()
