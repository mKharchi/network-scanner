"""Tests for automatic-location calibration comparisons and summaries."""

import sys
import unittest
from pathlib import Path


SERVER_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIRECTORY))

from server_components.calibration import build_calibration_report, compare_calibration_record  # noqa: E402


class CalibrationTests(unittest.TestCase):
    def test_compare_calibration_record_calculates_axis_and_distance_error(self):
        comparison = compare_calibration_record({
            "client_id": "client-a",
            "hostname": "PC-01",
            "history_id": 12,
            "location_id": 4,
            "location_label": "F1-A1-T1-R1-P1",
            "assignment_method": "AUTO",
            "assignment_status": "CONFIRMED",
            "verified": True,
            "assigned_at": "2026-08-27T10:00:00+00:00",
            "evidence": {"calculated_coordinates": {"x": 1.0, "y": 2.0, "z": 3.0}},
            "actual_x": 2.0,
            "actual_y": 4.0,
            "actual_z": 3.0,
        })

        self.assertIsNotNone(comparison)
        assert comparison is not None
        self.assertEqual(comparison["error"]["dx"], 1.0)
        self.assertEqual(comparison["error"]["dy"], 2.0)
        self.assertEqual(comparison["error"]["dz"], 0.0)
        self.assertAlmostEqual(comparison["error"]["distance"], 5 ** 0.5)

    def test_report_detects_consistent_axis_offset(self):
        report = build_calibration_report([
            {
                "client_id": "client-a",
                "evidence": {"calculated_coordinates": {"x": 0, "y": 0, "z": 0}},
                "actual_x": 1.0,
                "actual_y": 0.0,
                "actual_z": 0.0,
            },
            {
                "client_id": "client-b",
                "evidence": {"calculated_coordinates": {"x": 2, "y": 1, "z": 0}},
                "actual_x": 3.0,
                "actual_y": 1.0,
                "actual_z": 0.0,
            },
        ])

        self.assertEqual(report["sample_count"], 2)
        self.assertEqual(report["summary"]["mean_error"], {"x": 1.0, "y": 0.0, "z": 0.0})
        self.assertEqual(report["summary"]["mean_distance"], 1.0)
        self.assertTrue(report["summary"]["systematic_transformation_signal"])

    def test_report_ignores_records_without_complete_coordinates(self):
        report = build_calibration_report([
            {"client_id": "incomplete", "evidence": {"calculated_coordinates": {"x": 1}}},
        ])

        self.assertEqual(report["sample_count"], 0)
        self.assertEqual(report["summary"]["mean_distance"], 0.0)
        self.assertFalse(report["summary"]["systematic_transformation_signal"])


if __name__ == "__main__":
    unittest.main()
