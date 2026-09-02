"""Server-side tests for the v2 telemetry merge contract."""

import sys
import unittest
from pathlib import Path

SERVER_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIRECTORY))

from server_components.telemetry_merge import merge_telemetry_delta, validate_delta_payload  # noqa: E402


PAYLOAD = {
    "client_id": "client_07",
    "sync_timestamp": "2026-09-02T13:15:03Z",
    "window_id": "2026-09-02T13:00:00Z_2026-09-02T13:15:00Z",
    "updated_devices": [
        {
            "mac": "aa:bb:cc:dd:ee:01",
            "ip": "172.16.2.110",
            "hostname": "DESKTOP-XYZ",
            "vendor": "Dell",
            "os_guess": None,
            "last_seen": "2026-09-02T13:14:58Z",
            "discovery": {"dhcp": {"seen": True, "last_seen": "2026-09-02T13:14:58Z"}},
            "activity": {
                "device_mac": "aa:bb:cc:dd:ee:01",
                "window_id": "2026-09-02T13:00:00Z_2026-09-02T13:15:00Z",
                "window_start": "2026-09-02T13:00:00Z",
                "window_end": "2026-09-02T13:15:00Z",
                "active": True,
                "flow_count": 2,
                "packet_count": 10,
                "bytes": 1000,
                "protocols": {"TCP": 10},
                "ports": {"443": 2},
                "connections": {"internal": 1, "external": 1},
                "unique_destinations": 2,
            },
        }
    ],
}


class FakeCursor:
    def __init__(self, duplicate=False):
        self.queries = []
        self.params = []
        self.duplicate = duplicate

    def execute(self, query, params=()):
        self.queries.append(query)
        self.params.append(params)

    def fetchone(self):
        if self.queries and "SELECT id FROM telemetry_activity_windows" in self.queries[-1]:
            return (1,) if self.duplicate else None
        return None

    def close(self):
        pass


class FakeConnection:
    def __init__(self, duplicate=False):
        self.cursor_instance = FakeCursor(duplicate=duplicate)
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class TelemetryMergeTests(unittest.TestCase):
    def test_validation_normalizes_mac_and_rejects_forbidden_fields(self):
        normalized = validate_delta_payload(PAYLOAD)
        self.assertEqual(normalized["updated_devices"][0]["mac"], "AA:BB:CC:DD:EE:01")
        forbidden = {**PAYLOAD, "location": {"floor": 1}}
        with self.assertRaisesRegex(ValueError, "forbidden fields"):
            validate_delta_payload(forbidden)

    def test_merge_inserts_identity_and_activity_once(self):
        connection = FakeConnection()
        result = merge_telemetry_delta(PAYLOAD, conn=connection)
        self.assertEqual(result["status"], "ack")
        self.assertEqual(result["inserted_windows"], 1)
        self.assertFalse(result["duplicate"])
        self.assertTrue(connection.committed)
        self.assertTrue(any("INSERT INTO telemetry_devices" in query for query in connection.cursor_instance.queries))
        self.assertTrue(any("INSERT INTO telemetry_activity_windows" in query for query in connection.cursor_instance.queries))
        for query in connection.cursor_instance.queries:
            self.assertNotIn("location", query.lower())

    def test_duplicate_window_is_idempotent(self):
        connection = FakeConnection(duplicate=True)
        result = merge_telemetry_delta(PAYLOAD, conn=connection)
        self.assertEqual(result["status"], "ack")
        self.assertEqual(result["inserted_windows"], 0)
        self.assertTrue(result["duplicate"])
        self.assertTrue(connection.committed)
        self.assertFalse(any("INSERT INTO telemetry_activity_windows" in query for query in connection.cursor_instance.queries))

    def test_unknown_and_scoring_fields_are_rejected(self):
        for field in ("flow_records", "rogue_score", "ml_score"):
            payload = {**PAYLOAD, field: 1}
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_delta_payload(payload)


if __name__ == "__main__":
    unittest.main()
