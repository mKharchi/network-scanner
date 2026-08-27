"""Unit tests for hybrid location assignment helpers."""

import sys
import unittest
from pathlib import Path

SERVER_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIRECTORY))

from server_components.location_assignment import (  # noqa: E402
    ASSIGNMENT_METHOD_AUTO,
    ASSIGNMENT_STATUS_CONFIRMED,
    assignment_payload,
    normalize_assignment_method,
    normalize_assignment_status,
    parse_evidence,
    serialize_evidence,
)


class LocationAssignmentHelperTests(unittest.TestCase):
    def test_normalize_method_and_status(self):
        self.assertEqual(normalize_assignment_method("auto"), ASSIGNMENT_METHOD_AUTO)
        self.assertEqual(normalize_assignment_status("confirmed"), ASSIGNMENT_STATUS_CONFIRMED)

    def test_invalid_method_rejected(self):
        with self.assertRaises(ValueError):
            normalize_assignment_method("guess")

    def test_evidence_round_trip(self):
        raw = serialize_evidence(["sensor_match", {"rssi": -42}])
        self.assertEqual(parse_evidence(raw), ["sensor_match", {"rssi": -42}])

    def test_assignment_payload_omits_empty_state(self):
        self.assertIsNone(assignment_payload(method=None, status=None))

    def test_assignment_payload_includes_metadata(self):
        payload = assignment_payload(
            method="AUTO",
            status="ASSIGNED",
            confidence=0.88,
            verified=False,
            assigned_by="localization",
            source="localization_engine",
            evidence='["sensor_match"]',
        )
        self.assertEqual(payload["method"], "AUTO")
        self.assertEqual(payload["confidence"], 0.88)
        self.assertEqual(payload["evidence"], ["sensor_match"])
        self.assertFalse(payload["verified"])


if __name__ == "__main__":
    unittest.main()
