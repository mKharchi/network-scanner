"""Unit tests for database-backed, restart-safe client registration."""

import sys
import types
import unittest
from pathlib import Path


SERVER_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIRECTORY))

try:
    import mysql.connector  # noqa: F401
except ModuleNotFoundError:
    mysql_module = types.ModuleType("mysql")
    mysql_module.connector = types.ModuleType("mysql.connector")
    sys.modules["mysql"] = mysql_module
    sys.modules["mysql.connector"] = mysql_module.connector

from server_components import server_lib  # noqa: E402


class ClientRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.original_update = server_lib.update_client_db
        self.original_log = server_lib.log_connection
        self.original_alert = server_lib.create_connection_alert
        server_lib.clients.clear()
        server_lib.pending_disconnect_checks.clear()
        self.updates = []
        server_lib.update_client_db = lambda *args: self.updates.append(args) or True
        server_lib.log_connection = lambda *args: None
        server_lib.create_connection_alert = lambda *args: True

    def tearDown(self):
        server_lib.update_client_db = self.original_update
        server_lib.log_connection = self.original_log
        server_lib.create_connection_alert = self.original_alert
        server_lib.clients.clear()
        server_lib.pending_disconnect_checks.clear()

    @staticmethod
    def client_info():
        return {
            "hostname": "DESKTOP-DJP05CM",
            "ip": "172.16.0.102",
            "mac": "e4-fd-45-ba-8b-96",
            "os": {"system": "Windows"},
        }

    def test_registration_id_is_stable_and_mac_derived(self):
        client_id = server_lib.register_client(self.client_info(), object())

        self.assertEqual(client_id, "client-e4fd45ba8b96")
        self.assertIn("E4:FD:45:BA:8B:96", server_lib.clients)
        self.assertEqual(self.updates[0][0:2], ("E4:FD:45:BA:8B:96", client_id))

    def test_failed_database_write_does_not_register_in_memory_client(self):
        server_lib.update_client_db = lambda *args: False

        client_id = server_lib.register_client(self.client_info(), object())

        self.assertIsNone(client_id)
        self.assertEqual(server_lib.clients, {})


if __name__ == "__main__":
    unittest.main()
