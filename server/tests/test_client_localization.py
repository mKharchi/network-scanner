"""Tests for automatic managed-client localization and confidence gating."""

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

from server_components import client_localization  # noqa: E402


def _connection(cursor):
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn


class AutomaticClientLocalizationTests(unittest.TestCase):
    def test_threshold_defaults_and_clamps(self):
        with patch.dict("os.environ", {}, clear=False):
            if "CLIENT_LOCATION_AUTO_CONFIDENCE_THRESHOLD" in __import__("os").environ:
                del __import__("os").environ["CLIENT_LOCATION_AUTO_CONFIDENCE_THRESHOLD"]
            self.assertEqual(client_localization.get_auto_confidence_threshold(), 0.80)

        with patch.dict("os.environ", {"CLIENT_LOCATION_AUTO_CONFIDENCE_THRESHOLD": "1.5"}):
            self.assertEqual(client_localization.get_auto_confidence_threshold(), 1.0)

    @patch("server_components.client_localization.get_connection")
    def test_calculate_returns_insufficient_evidence_without_observations(self, get_connection):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [
            {
                "id": 1,
                "client_id": "client-a",
                "mac": "AA:BB:CC:DD:EE:01",
                "location_id": None,
                "location_assignment_method": None,
                "location_assignment_status": None,
                "location_verified": False,
            },
            None,
        ]
        get_connection.return_value = _connection(cursor)

        result = client_localization.calculate_client_location("client-a")

        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "insufficient_evidence")
        self.assertEqual(result["confidence"], 0.0)

    @patch("server_components.location_repository.submit_client_location_assignment")
    @patch("server_components.client_localization.calculate_client_location")
    @patch("server_components.client_localization._client_assignment_guard")
    def test_auto_assigns_when_confidence_meets_threshold(
        self, guard, calculate, assign_location
    ):
        guard.return_value = None
        calculate.return_value = {
            "success": True,
            "location_id": 4,
            "confidence": 0.91,
            "evidence": {"triangulation_method": "SWITCH_PORT"},
            "calculated_at": "2026-08-27T10:00:00+00:00",
        }
        assign_location.return_value = {"id": 4, "label": "F1-A1-T1-R1-P1"}

        outcome = client_localization.try_automatic_client_location_assignment("client-a")

        self.assertTrue(outcome["assigned"])
        self.assertEqual(outcome["location"]["label"], "F1-A1-T1-R1-P1")
        assign_location.assert_called_once()
        kwargs = assign_location.call_args.kwargs
        self.assertEqual(kwargs["method"], "AUTO")
        self.assertEqual(kwargs["confidence"], 0.91)
        self.assertFalse(kwargs["verified"])

    @patch("server_components.client_localization._record_assignment_failure")
    @patch("server_components.client_localization.calculate_client_location")
    @patch("server_components.client_localization._client_assignment_guard")
    def test_low_confidence_records_failure_reason(self, guard, calculate, record_failure):
        guard.return_value = None
        calculate.return_value = {
            "success": True,
            "location_id": 4,
            "location": {"id": 4, "label": "F1-A1-T1-R1-P1", "floor": 1},
            "confidence": 0.55,
            "evidence": {"triangulation_method": "NEAREST_SENSOR"},
            "calculated_at": "2026-08-27T10:00:00+00:00",
        }

        outcome = client_localization.try_automatic_client_location_assignment(
            "client-a",
            threshold=0.80,
        )

        self.assertFalse(outcome["assigned"])
        self.assertEqual(outcome["reason"], "low_confidence")
        self.assertEqual(outcome["proposed_location"]["label"], "F1-A1-T1-R1-P1")
        self.assertEqual(outcome["location_id"], 4)
        record_failure.assert_called_once()
        self.assertEqual(record_failure.call_args.kwargs["reason"], "low_confidence")

    @patch("server_components.client_localization._client_assignment_guard")
    def test_manual_verified_location_is_not_overwritten(self, guard):
        guard.return_value = {
            "success": False,
            "assigned": False,
            "reason": "manual_assignment_protected",
            "client_id": "client-a",
            "location_id": 4,
        }

        outcome = client_localization.try_automatic_client_location_assignment("client-a")

        self.assertFalse(outcome["assigned"])
        self.assertEqual(outcome["reason"], "manual_assignment_protected")

    @patch("server_components.client_localization.get_connection")
    def test_unconfirmed_auto_location_can_be_recalculated(self, get_connection):
        cursor = MagicMock()
        cursor.fetchone.return_value = {
            "client_id": "client-a",
            "location_id": 4,
            "location_assignment_method": "AUTO",
            "location_assignment_status": "ASSIGNED",
            "location_verified": False,
        }
        get_connection.return_value = _connection(cursor)

        self.assertIsNone(client_localization._client_assignment_guard("client-a"))

    @patch("server_components.client_localization.get_connection")
    def test_confirmed_auto_location_is_not_overwritten(self, get_connection):
        cursor = MagicMock()
        cursor.fetchone.return_value = {
            "client_id": "client-a",
            "location_id": 4,
            "location_assignment_method": "AUTO",
            "location_assignment_status": "CONFIRMED",
            "location_verified": True,
        }
        get_connection.return_value = _connection(cursor)

        guard = client_localization._client_assignment_guard("client-a")

        self.assertEqual(guard["reason"], "confirmed_assignment_protected")
        self.assertEqual(guard["location_id"], 4)


if __name__ == "__main__":
    unittest.main()
