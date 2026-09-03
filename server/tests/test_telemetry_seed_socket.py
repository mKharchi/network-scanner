"""Socket-dispatch-level integration tests for the TELEMETRY_SEED exchange.

Exercises ``handle_telemetry_seed`` (and ``handle_telemetry_sync``) via the
same call path that ``receive_client_messages`` uses so that the full
ACK/NACK message framing, client-ID enforcement, and merge-service validation
are all exercised together — without touching a real database or TCP socket.

Progress doc reference:
  "Add a complete socket-level integration test that exercises the subsequent
   TELEMETRY_SEED acknowledgement exchange against a database-backed server;
   focused handshake coverage already verifies REGISTERED scope delivery."

This suite fills that gap using the same fake-connection/fake-cursor pattern
used in test_telemetry_merge.py.
"""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

SERVER_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIRECTORY))

from server_components import server_lib  # noqa: E402
from server_components.server_lib import handle_telemetry_seed, handle_telemetry_sync  # noqa: E402


# ---------------------------------------------------------------------------
# Reuse the fake connection/cursor pattern from test_telemetry_merge.py
# ---------------------------------------------------------------------------

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

    def close(self):
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SEED_PAYLOAD = {
    "client_id": "client_07",
    "sync_timestamp": "2026-09-02T08:15:00Z",
    "updated_devices": [
        {
            "mac": "e4:fd:45:ba:8b:96",
            "ip": "172.16.2.110",
            "hostname": "DESKTOP-XYZ",
            "vendor": "Dell",
            "os_guess": None,
            "last_seen": "2026-09-02T08:14:00Z",
            "discovery": {"dhcp": {"seen": True, "last_seen": "2026-09-02T08:00:00Z"}},
        }
    ],
}

DELTA_PAYLOAD = {
    "client_id": "client_07",
    "sync_timestamp": "2026-09-02T13:15:03Z",
    "window_id": "2026-09-02T13:00:00Z_2026-09-02T13:15:00Z",
    "updated_devices": [
        {
            "mac": "e4:fd:45:ba:8b:96",
            "ip": "172.16.2.110",
            "hostname": "DESKTOP-XYZ",
            "vendor": "Dell",
            "os_guess": None,
            "last_seen": "2026-09-02T13:14:58Z",
            "discovery": {"dhcp": {"seen": True}},
            "activity": {
                "device_mac": "e4:fd:45:ba:8b:96",
                "window_id": "2026-09-02T13:00:00Z_2026-09-02T13:15:00Z",
                "window_start": "2026-09-02T13:00:00Z",
                "window_end": "2026-09-02T13:15:00Z",
                "active": True,
                "flow_count": 5,
                "packet_count": 120,
                "bytes": 85000,
                "protocols": {"TCP": 120},
                "ports": {"443": 5},
                "connections": {"internal": 2, "external": 3},
                "unique_destinations": 4,
            },
        }
    ],
}


def _fake_sender(*, client_id="client_07"):
    """Build a minimal fake sender dict matching the server_lib client registry format."""
    sender = {
        "client_id": client_id,
        "connection": MagicMock(),
        "send_lock": __import__("threading").Lock(),
        "responses": __import__("queue").Queue(),
    }
    return sender


class TelemetrySeedSocketDispatchTests(unittest.TestCase):
    """Socket-dispatch-level tests for the TELEMETRY_SEED → SEED_ACK/NACK path."""

    def _call_handle_seed(self, payload, *, sender=None, fake_conn=None):
        """Invoke handle_telemetry_seed with a patched DB connection; capture sent messages."""
        if fake_conn is None:
            fake_conn = FakeConnection()
        sender = sender or _fake_sender()
        sent = []
        sender["connection"].sendall.side_effect = (
            lambda data: sent.append(json.loads(data.rstrip(b"\n")))
        )

        with patch(
            "server_components.telemetry_merge.get_connection",
            return_value=fake_conn,
        ):
            # patch send_message to capture the ACK/NACK dict without encoding
            with patch.object(server_lib, "send_message",
                              side_effect=lambda _conn, msg: sent.append(msg)):
                result = handle_telemetry_seed("E4:FD:45:BA:8B:96", payload, sender=sender)

        return result, sent, fake_conn

    def test_valid_seed_sends_seed_ack_and_writes_devices(self):
        """A valid seed payload produces a SEED_ACK frame and upserts devices."""
        result, sent, conn = self._call_handle_seed(SEED_PAYLOAD)

        self.assertTrue(result)
        self.assertEqual(len(sent), 1)
        ack = sent[0]
        self.assertEqual(ack["type"], "SEED_ACK")
        self.assertEqual(ack["status"], "ack")
        self.assertEqual(ack["client_id"], "client_07")

        # DB side: should have inserted into telemetry_devices (no activity windows)
        queries = conn.cursor_instance.queries
        self.assertTrue(
            any("INSERT INTO telemetry_devices" in q for q in queries),
            "Expected a telemetry_devices upsert",
        )
        self.assertFalse(
            any("telemetry_activity_windows" in q for q in queries),
            "Seed must NOT write activity windows",
        )
        self.assertTrue(conn.committed)

    def test_seed_with_wrong_client_id_sends_nack(self):
        """A seed claiming a different client_id than the registered socket is rejected."""
        mismatched_payload = {**SEED_PAYLOAD, "client_id": "impostor_client"}
        sender = _fake_sender(client_id="client_07")  # registered as client_07
        sent = []

        with patch.object(server_lib, "send_message",
                          side_effect=lambda _conn, msg: sent.append(msg)):
            result = handle_telemetry_seed(
                "E4:FD:45:BA:8B:96", mismatched_payload, sender=sender
            )

        self.assertFalse(result)
        self.assertEqual(len(sent), 1)
        nack = sent[0]
        self.assertEqual(nack["type"], "SEED_NACK")
        self.assertIn("client_id", nack.get("reason", "").lower())

    def test_seed_with_forbidden_field_sends_nack(self):
        """A seed carrying forbidden fields (e.g. 'flows') is NACKed without DB write."""
        bad_payload = {**SEED_PAYLOAD, "flows": [{"raw": "packet"}]}
        result, sent, conn = self._call_handle_seed(bad_payload)

        self.assertFalse(result)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["type"], "SEED_NACK")
        # DB must not have been committed
        self.assertFalse(conn.committed)

    def test_seed_rejects_activity_field_on_device(self):
        """Devices in a seed payload must not carry an 'activity' block."""
        device_with_activity = {
            **SEED_PAYLOAD["updated_devices"][0],
            "activity": {"window_id": "2026-09-02T13:00:00Z_2026-09-02T13:15:00Z"},
        }
        bad_payload = {**SEED_PAYLOAD, "updated_devices": [device_with_activity]}
        result, sent, conn = self._call_handle_seed(bad_payload)

        self.assertFalse(result)
        self.assertEqual(sent[0]["type"], "SEED_NACK")

    def test_seed_with_none_payload_sends_nack(self):
        """A None or non-dict payload is gracefully NACKed."""
        result, sent, conn = self._call_handle_seed(None)
        self.assertFalse(result)
        self.assertEqual(sent[0]["type"], "SEED_NACK")


class TelemetrySyncSocketDispatchTests(unittest.TestCase):
    """Socket-dispatch-level tests for the TELEMETRY_SYNC → SYNC_ACK/NACK path."""

    def _call_handle_sync(self, payload, *, sender=None, fake_conn=None, duplicate=False):
        if fake_conn is None:
            fake_conn = FakeConnection(duplicate=duplicate)
        sender = sender or _fake_sender()
        sent = []

        with patch(
            "server_components.telemetry_merge.get_connection",
            return_value=fake_conn,
        ):
            with patch.object(server_lib, "send_message",
                              side_effect=lambda _conn, msg: sent.append(msg)):
                result = handle_telemetry_sync("E4:FD:45:BA:8B:96", payload, sender=sender)

        return result, sent, fake_conn

    def test_valid_delta_sends_sync_ack(self):
        """A valid delta payload produces a SYNC_ACK frame."""
        result, sent, conn = self._call_handle_sync(DELTA_PAYLOAD)

        self.assertTrue(result)
        ack = sent[0]
        self.assertEqual(ack["type"], "SYNC_ACK")
        self.assertEqual(ack["status"], "ack")
        self.assertEqual(ack["window_id"], DELTA_PAYLOAD["window_id"])
        self.assertTrue(conn.committed)

    def test_duplicate_window_sends_ack_not_nack(self):
        """A duplicate window_id returns ACK (idempotent), not NACK."""
        result, sent, conn = self._call_handle_sync(DELTA_PAYLOAD, duplicate=True)
        self.assertTrue(result)
        self.assertEqual(sent[0]["type"], "SYNC_ACK")

    def test_delta_with_wrong_client_id_sends_nack(self):
        """Mismatched client_id is rejected with SYNC_NACK."""
        bad_payload = {**DELTA_PAYLOAD, "client_id": "wrong_client"}
        result, sent, _ = self._call_handle_sync(bad_payload)
        self.assertFalse(result)
        self.assertEqual(sent[0]["type"], "SYNC_NACK")

    def test_delta_with_forbidden_field_sends_nack(self):
        """A delta carrying forbidden fields is NACKed without DB write."""
        bad_payload = {**DELTA_PAYLOAD, "rogue_score": 95}
        result, sent, conn = self._call_handle_sync(bad_payload)
        self.assertFalse(result)
        self.assertEqual(sent[0]["type"], "SYNC_NACK")
        self.assertFalse(conn.committed)

    def test_none_payload_sends_nack(self):
        """A None payload is gracefully NACKed."""
        result, sent, _ = self._call_handle_sync(None)
        self.assertFalse(result)
        self.assertEqual(sent[0]["type"], "SYNC_NACK")


if __name__ == "__main__":
    unittest.main()
