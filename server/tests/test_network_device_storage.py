"""Unit tests for client neighbour-report validation and storage.

Run from repository root:
    python3 server/tests/test_network_device_storage.py
"""

import sys
import types
import unittest
from datetime import datetime
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

from server_components import network_device_storage, server_lib  # noqa: E402


class FakeCursor:
    def __init__(self):
        self.executed = []
        self._last_query = ""

    def execute(self, query, params=None):
        self.executed.append((query, params))
        self._last_query = query

    def fetchone(self):
        if "FROM clients" in self._last_query:
            return (7,)
        if "FROM network_devices" in self._last_query:
            return (13,)
        return None

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

    def is_connected(self):
        return False


class NetworkDeviceStorageTests(unittest.TestCase):
    def test_validation_normalizes_entries_and_ignores_invalid_rows(self):
        neighbours = network_device_storage.validate_neighbour_report(
            {
                "observed_at": "2026-08-17T10:00:00Z",
                "neighbours": [
                    {
                        "ip_address": "172.16.0.102",
                        "mac_address": "aa-bb-cc-dd-ee-ff",
                        "entry_type": "dynamic",
                        "interface": " eth0 ",
                    },
                    {
                        "ip_address": "224.0.0.1",
                        "mac_address": "01:00:5e:00:00:01",
                        "entry_type": "dynamic",
                    },
                    {"ip_address": "not-an-ip", "mac_address": "11:22:33:44:55:66"},
                ],
            }
        )
        self.assertEqual(
            neighbours,
            [
                {
                    "ip_address": "172.16.0.102",
                    "mac_address": "AA:BB:CC:DD:EE:FF",
                    "entry_type": "dynamic",
                    "interface": "eth0",
                }
            ],
        )

    def test_validation_rejects_invalid_envelope(self):
        with self.assertRaisesRegex(ValueError, "observed_at"):
            network_device_storage.validate_neighbour_report({"neighbours": []})
        with self.assertRaisesRegex(ValueError, "neighbours"):
            network_device_storage.validate_neighbour_report(
                {"observed_at": "2026-08-17T10:00:00Z", "neighbours": {}}
            )

    def test_store_creates_device_and_source_attributed_observation(self):
        connection = FakeConnection()
        original_get_connection = network_device_storage.get_connection
        network_device_storage.get_connection = lambda: connection
        try:
            stored = network_device_storage.store_client_neighbour_observations(
                "AA:BB:CC:DD:EE:FF",
                [
                    {
                        "ip_address": "172.16.0.102",
                        "mac_address": "11:22:33:44:55:66",
                        "entry_type": "dynamic",
                        "interface": "eth0",
                    }
                ],
                observed_at=datetime(2026, 8, 17, 10, 0, 0),
            )
        finally:
            network_device_storage.get_connection = original_get_connection

        self.assertEqual(stored, 1)
        self.assertTrue(connection.committed)
        observation = next(
            params
            for query, params in connection.cursor_instance.executed
            if "INSERT INTO network_device_observations" in query
        )
        self.assertEqual(observation[:3], (13, 7, "172.16.0.102"))
        self.assertEqual(observation[4:6], ("dynamic", datetime(2026, 8, 17, 10, 0, 0)))

    def test_handler_uses_registered_connection_mac_not_payload_identity(self):
        received = {}

        accepted = server_lib.handle_network_neighbour_report(
            "AA:BB:CC:DD:EE:FF",
            {"client_id": "untrusted-client-value"},
            report_validator=lambda payload: [{"mac_address": "12:22:33:44:55:66"}],
            observation_storer=lambda reporter_mac, neighbours: (
                received.update({"reporter_mac": reporter_mac, "neighbours": neighbours})
                or len(neighbours)
            ),
        )

        self.assertTrue(accepted)
        self.assertEqual(received["reporter_mac"], "AA:BB:CC:DD:EE:FF")
        self.assertEqual(received["neighbours"], [{"mac_address": "12:22:33:44:55:66"}])


if __name__ == "__main__":
    unittest.main()
