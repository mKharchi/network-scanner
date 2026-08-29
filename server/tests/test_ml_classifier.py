"""Unit tests for RuleBaseline, ML Ensemble Classifier, and Model Evaluation."""

import sys
import types
import unittest
from pathlib import Path

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

from server_components.device_features import CLASSIFICATION_CLASSES
from server_components.ml_classifier import (
    DeviceMLClassifier,
    RuleBasedDeviceClassifier,
    evaluate_classifier,
    generate_benchmark_dataset,
)


class MLClassifierTests(unittest.TestCase):
    def setUp(self):
        self.rule_classifier = RuleBasedDeviceClassifier()
        self.ml_classifier = DeviceMLClassifier()

    def test_rule_baseline_predictions(self):
        # 1. Windows PC
        win_sample = {
            "vendor_family": "microsoft",
            "hostname_pattern": "desktop_win",
            "dhcp_opt60_family": "msft",
            "dhcp_opt55_sig": "windows",
        }
        cls, conf, ev = self.rule_classifier.predict(win_sample)
        self.assertEqual(cls, "WINDOWS_WORKSTATION")
        self.assertGreaterEqual(conf, 0.85)

        # 2. iPhone
        iphone_sample = {
            "vendor_family": "apple",
            "hostname_pattern": "iphone",
            "dhcp_opt55_sig": "apple",
            "mdns_has_apple_companion": 1,
        }
        cls, conf, ev = self.rule_classifier.predict(iphone_sample)
        self.assertEqual(cls, "APPLE_MOBILE")
        self.assertGreaterEqual(conf, 0.90)

        # 3. Printer
        printer_sample = {
            "vendor_family": "hp",
            "hostname_pattern": "printer",
            "mdns_has_printer": 1,
            "dhcp_opt55_sig": "printer",
        }
        cls, conf, ev = self.rule_classifier.predict(printer_sample)
        self.assertEqual(cls, "PRINTER")
        self.assertGreaterEqual(conf, 0.90)

    def test_ml_ensemble_predictions_and_calibration(self):
        sample = {
            "vendor_family": "samsung",
            "hostname_pattern": "android_galaxy",
            "dhcp_opt60_family": "android",
            "dhcp_opt55_sig": "android",
        }
        pred_cls, conf, probs = self.ml_classifier.predict(sample)
        self.assertEqual(pred_cls, "ANDROID_MOBILE")
        self.assertGreaterEqual(conf, 0.80)
        self.assertIn("ANDROID_MOBILE", probs)
        self.assertAlmostEqual(sum(probs.values()), 1.0, places=2)

    def test_benchmark_dataset_and_evaluation(self):
        dataset = generate_benchmark_dataset(sample_count=100)
        self.assertEqual(len(dataset), 100)

        eval_result = evaluate_classifier(self.ml_classifier.predict, dataset)
        self.assertIn("accuracy", eval_result)
        self.assertGreaterEqual(eval_result["accuracy"], 0.85)
        self.assertIn("per_class", eval_result)
        self.assertIn("confusion_matrix", eval_result)

        # Check precision and recall calculated for all classes
        for c in CLASSIFICATION_CLASSES:
            self.assertIn(c, eval_result["per_class"])
            self.assertIn("f1_score", eval_result["per_class"][c])

    def test_model_serialization_and_deserialization(self):
        import tempfile
        from pathlib import Path

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            self.ml_classifier.save(tmp_path)
            loaded_model = DeviceMLClassifier.load(tmp_path)
            self.assertEqual(loaded_model.model_version, self.ml_classifier.model_version)
            self.assertEqual(len(loaded_model.trees), len(self.ml_classifier.trees))

            # Verify predictions match exactly
            sample = {"vendor_family": "roku", "ssdp_is_media": 1}
            p1, c1, _ = self.ml_classifier.predict(sample)
            p2, c2, _ = loaded_model.predict(sample)
            self.assertEqual(p1, p2)
            self.assertEqual(c1, c2)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()


if __name__ == "__main__":
    unittest.main()
