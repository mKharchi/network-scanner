"""Runtime activity service tests without requiring a live capture sensor."""

from __future__ import annotations

import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from server_components.activity_inference import ActivityInferenceService
from server_components.kismet_ml_pipeline import KismetMLDerivedStore


class _FakeClassifier:
    model_version = "activity-rf-v1"

    def __init__(self, probabilities):
        self.probabilities = probabilities

    def predict(self, _vector):
        label = max(self.probabilities, key=self.probabilities.get)
        return label, dict(self.probabilities)


def _window() -> dict:
    now = int(time.time() * 1000)
    return {
        "window_id": "runtime-test-window",
        "client_mac": "AA:BB:CC:DD:EE:FF",
        "window_start_ms": now - 1000,
        "window_end_ms": now + 29000,
        "total_frame_count": 10,
        "total_byte_count": 1000,
        "uplink_frame_count": 5,
        "downlink_frame_count": 5,
        "uplink_byte_count": 500,
        "downlink_byte_count": 500,
        "retry_frame_count": 0,
        "data_frame_count": 10,
        "mgmt_frame_count": 0,
        "ctrl_frame_count": 0,
        "derived_features_json": {},
    }


class ActivityInferenceTests(unittest.TestCase):
    def test_missing_artifact_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = ActivityInferenceService(storage_dir=directory, model_dir=Path(directory) / "missing").predict_device("AA:BB:CC:DD:EE:FF")
            self.assertEqual(result["status"], "model_unavailable")

    def test_prediction_is_smoothed_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            KismetMLDerivedStore(directory).persist_many("traffic_windows", [_window()])
            service = ActivityInferenceService(storage_dir=directory)
            service._classifier = _FakeClassifier({
                "streaming": 0.8, "file_transfer": 0.05, "chat": 0.05,
                "voip": 0.05, "other": 0.05,
            })
            result = service.predict_device("AA:BB:CC:DD:EE:FF")
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["current"]["activity"], "streaming")
            with sqlite3.connect(Path(directory) / "activity_predictions.sqlite") as connection:
                self.assertEqual(connection.execute("SELECT count(*) FROM activity_predictions").fetchone()[0], 1)
            service.predict_device("AA:BB:CC:DD:EE:FF")
            with sqlite3.connect(Path(directory) / "activity_predictions.sqlite") as connection:
                self.assertEqual(connection.execute("SELECT count(*) FROM activity_predictions").fetchone()[0], 1)

    def test_low_confidence_returns_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            KismetMLDerivedStore(directory).persist_many("traffic_windows", [_window()])
            service = ActivityInferenceService(storage_dir=directory, confidence_threshold=0.9)
            service._classifier = _FakeClassifier({
                "streaming": 0.3, "file_transfer": 0.2, "chat": 0.2,
                "voip": 0.2, "other": 0.1,
            })
            result = service.predict_device("AA:BB:CC:DD:EE:FF")
            self.assertEqual(result["status"], "low_confidence")
            self.assertEqual(result["current"]["activity"], "unknown")


if __name__ == "__main__":
    unittest.main()
