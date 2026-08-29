"""Integration tests for Device Classification REST API endpoints."""

import json
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

from server_components import api_service


class DeviceClassificationApiTests(unittest.TestCase):
    @patch("server_components.device_intelligence.DeviceIntelligenceService.classify_device")
    @patch("server_components.api_service._resolve_device_db_id", return_value=42)
    def test_get_device_classification(self, mock_resolve, mock_classify):
        mock_classify.return_value = {
            "device_id": 42,
            "predicted_class": "ANDROID_MOBILE",
            "confidence": 0.94,
            "source": "HYBRID",
            "model_version": "device-classifier-v1",
            "status": "ACTIVE",
            "probabilities": {"ANDROID_MOBILE": 0.94, "UNKNOWN": 0.06},
            "evidence": ["decision.consensus_agreement"],
        }
        res = api_service.get_device_classification_by_identifier(42)
        self.assertIsNotNone(res)
        self.assertEqual(res["predicted_class"], "ANDROID_MOBILE")
        self.assertEqual(res["confidence"], 0.94)

    @patch("server_components.device_intelligence.DeviceIntelligenceService.verify_device_label")
    @patch("server_components.api_service._resolve_device_db_id", return_value=42)
    def test_record_human_label(self, mock_resolve, mock_verify):
        mock_verify.return_value = {
            "device_id": 42,
            "predicted_class": "PRINTER",
            "confidence": 1.0,
            "source": "HUMAN",
            "model_version": "device-classifier-v1",
            "status": "ACTIVE",
        }
        res = api_service.record_device_human_label_by_identifier(
            device_identifier=42,
            label="PRINTER",
            confirmed_by="admin",
            notes="Office HP Printer",
        )
        self.assertIsNotNone(res)
        self.assertEqual(res["predicted_class"], "PRINTER")
        self.assertEqual(res["source"], "HUMAN")

    @patch("server_components.device_intelligence.get_classification_summary_statistics")
    def test_get_classification_stats(self, mock_stats):
        mock_stats.return_value = {
            "total_devices": 100,
            "total_classified": 95,
            "class_distribution": {"WINDOWS_WORKSTATION": 50, "ANDROID_MOBILE": 45},
            "high_confidence_count": 80,
            "medium_confidence_count": 15,
            "low_confidence_count": 5,
            "needs_review_count": 5,
            "average_confidence": 0.92,
            "human_labels_count": 10,
            "model_version": "device-classifier-v1",
        }
        stats = api_service.get_classification_stats()
        self.assertEqual(stats["total_devices"], 100)
        self.assertEqual(stats["high_confidence_count"], 80)
        self.assertEqual(stats["model_version"], "device-classifier-v1")

    @patch("server_components.device_intelligence.get_devices_needing_review")
    def test_get_classification_review_queue(self, mock_review):
        mock_review.return_value = [
            {
                "device_id": 10,
                "mac_address": "11:22:33:44:55:66",
                "predicted_class": "UNKNOWN",
                "confidence": 0.45,
                "status": "NEEDS_REVIEW",
            }
        ]
        items = api_service.get_classification_review_queue(limit=10)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["status"], "NEEDS_REVIEW")


if __name__ == "__main__":
    unittest.main()
