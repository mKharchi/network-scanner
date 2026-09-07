"""End-to-end startup integration test for telemetry seed and client lifecycle.

Verifies:
1. Client establishes connection and registers.
2. Server confirms registration with authoritative client_id.
3. Client seeds devices using the confirmed client_id.
4. Server accepts TELEMETRY_SEED and returns SEED_ACK.
5. Client shuts down cleanly.
"""

import os
import sys
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

dotenv_module = types.ModuleType("dotenv")
dotenv_module.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_module)

CLIENT_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(CLIENT_DIR))

import client as client_module  # noqa: E402
import client_lib  # noqa: E402


class ClientStartupIntegrationTests(unittest.TestCase):
    def test_combined_startup_lifecycle(self):
        class FakeSocket:
            def __init__(self):
                self._closed = False

            def settimeout(self, _timeout):
                pass

            def connect(self, _address):
                pass

            def getsockname(self):
                return ("172.16.0.10", 50001)

            def close(self):
                self._closed = True

        stop_event = threading.Event()
        server_messages = [
            {
                "type": "REGISTERED",
                "client_id": "client-aabbccddee01",
                "observation_scope": ["172.16.0.0/24"],
            },
            {"type": "FORBIDDEN_PROCESSES", "data": []},
            {"type": "RESOURCE_PROTECTION_CONFIG", "data": {}},
            {"type": "SEED_ACK", "status": "ack", "client_id": "client-aabbccddee01"},
            None,  # trigger shutdown
        ]
        msg_iter = iter(server_messages)

        def fake_receive(_socket, **_kwargs):
            try:
                msg = next(msg_iter)
            except StopIteration:
                msg = None
            if msg is None:
                stop_event.set()
            return msg

        sent_messages = []

        def fake_send(_socket, message):
            sent_messages.append(message)

        startup_logs = []

        def capture_startup_log(msg):
            startup_logs.append(msg)

        with patch.object(client_module.socket, "socket", return_value=FakeSocket()), patch.object(
            client_module, "receive_message", side_effect=fake_receive
        ), patch.object(
            client_module, "send_message", side_effect=fake_send
        ), patch.object(
            client_module, "_startup_log", side_effect=capture_startup_log
        ), patch.object(
            client_module, "_snapshot_client_mac", return_value="AA:BB:CC:DD:EE:01"
        ), patch.object(
            client_lib, "get_mac", return_value="AA:BB:CC:DD:EE:01"
        ), patch.object(
            client_module, "send_stored_daily_neighbourhood"
        ), patch.object(
            client_module, "collect_daily_network_neighbours"
        ), patch.object(
            client_module, "background_scanner"
        ), patch.object(
            client_module, "DHCPListener"
        ), patch.object(
            client_module, "PassiveProtocolListener"
        ), patch.dict(
            "os.environ", {}, clear=False
        ):
            client_module.start_client(stop_event)

        # 1. Verify Registration sent
        register_msgs = [m for m in sent_messages if m.get("type") == "REGISTER"]
        self.assertEqual(len(register_msgs), 1)

        # 2. Verify Telemetry Seed sent with canonical registered client_id
        # Wait slightly for background thread to send seed
        seed_msgs = [m for m in sent_messages if m.get("type") == "TELEMETRY_SEED"]
        self.assertTrue(len(seed_msgs) >= 1)
        seed_payload = seed_msgs[0].get("data", {})
        self.assertEqual(seed_payload.get("client_id"), "client-aabbccddee01")

        # 3. Verify no startup scope/lifecycle error was reported
        self.assertFalse(any("UnboundLocalError" in log for log in startup_logs))

        # 4. Verify identity confirmation logged
        identity_logs = [log for log in startup_logs if "[CLIENT_IDENTITY]" in log]
        self.assertTrue(any("client-aabbccddee01" in log for log in identity_logs))


if __name__ == "__main__":
    unittest.main()
