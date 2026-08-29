"""Unit tests for Device Intelligence Service and Decision Engine."""

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

SERVER_DIRECTORY = Path(__file__).resolve().parents[1]
if str(SERVER_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SERVER_DIRECTORY))

try:
    import mysql.connector  # noqa: F401
except ModuleNotFoundError:
    mysql_module = types.ModuleType("mysql")
    mysql_module.connector = types.ModuleType("mysql.connector")
    sys.modules["mysql"] = mysql_module
    sys.modules["mysql.connector"] = mysql_module.connector

from server_components.device_intelligence import DeviceIntelligenceService
from server_components.ml_classifier import ClassificationResult


class DeviceIntelligenceServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = DeviceIntelligenceService()

    def test_human_verified_label_overrides_model(self):
        features = {
            "vendor_family": "microsoft",
            "hostname_pattern": "desktop_win",
            "dhcp_opt60_family": "msft",
        }
        # Model would predict WINDOWS_WORKSTATION, but human ground truth is SMART_TV_MEDIA
        result = self.service.classify_features(features, existing_human_label="SMART_TV_MEDIA")
        self.assertEqual(result.predicted_class, "SMART_TV_MEDIA")
        self.assertEqual(result.confidence, 1.0)
        self.assertEqual(result.source, "HUMAN")
        self.assertEqual(result.status, "ACTIVE")
        self.assertIn("human.verified_label", result.evidence)

    def test_consensus_agreement_boosts_confidence(self):
        features = {
            "vendor_family": "hp",
            "hostname_pattern": "printer",
            "mdns_has_printer": 1,
            "dhcp_opt55_sig": "printer",
        }
        result = self.service.classify_features(features)
        self.assertEqual(result.predicted_class, "PRINTER")
        self.assertEqual(result.source, "HYBRID")
        self.assertGreaterEqual(result.confidence, 0.90)
        self.assertIn("decision.consensus_agreement", result.evidence)

    def test_insufficient_evidence_produces_unknown(self):
        features = {
            "vendor_family": "unknown",
            "hostname_pattern": "unknown",
            "dhcp_opt60_family": "none",
            "dhcp_opt55_sig": "none",
            "dhcp_present": 0,
            "mdns_present": 0,
            "ssdp_present": 0,
        }
        result = self.service.classify_features(features)
        self.assertEqual(result.predicted_class, "UNKNOWN")
        self.assertLess(result.confidence, 0.70)

    def test_conflict_resolution_and_needs_review(self):
        # Craft a conflict: Apple vendor with Windows DHCP
        features = {
            "vendor_family": "apple",
            "hostname_pattern": "iphone",
            "dhcp_opt60_family": "msft",
            "dhcp_opt55_sig": "windows",
        }
        result = self.service.classify_features(features)
        self.assertIn(result.status, ("ACTIVE", "NEEDS_REVIEW"))
        self.assertIsNotNone(result.rule_prediction)
        self.assertIsNotNone(result.ml_prediction)

    def test_retraining_evaluation(self):
        retrain_summary = self.service.retrain_model_pipeline()
        self.assertEqual(retrain_summary["status"], "SUCCESS")
        self.assertIn("benchmark_evaluation", retrain_summary)
        self.assertGreaterEqual(retrain_summary["benchmark_evaluation"]["ml_model"]["accuracy"], 0.85)


if __name__ == "__main__":
    unittest.main()
