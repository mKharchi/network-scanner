"""Comprehensive tests for Phase 2 Wi-Fi neutral activity inference (activity-features-v2)."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from server_components.device_activity import (
    ACTIVITY_FEATURE_SCHEMA_V1,
    ACTIVITY_FEATURE_SCHEMA_V2,
    ACTIVITY_FEATURE_SCHEMA_VERSION,
    ACTIVITY_MODEL_V1,
    ACTIVITY_MODEL_V2,
    ACTIVITY_MODEL_VERSION,
    ActivityMajorityBaseline,
    ActivityModelArtifactMetadata,
    ActivityModelCompatibilityError,
    ActivityModelRegistry,
    ActivityPrediction,
    ActivityPredictionStore,
    ActivityRandomForestClassifier,
    TemporalActivitySmoother,
    activity_feature_vector,
    load_labeled_activity_windows,
    prediction_from_window,
    split_activity_windows,
)
from server_components.activity_inference import ActivityInferenceService
from server_components.kismet_ml_pipeline import KismetMLDerivedStore


def _sample_window(
    window_id: str,
    *,
    client: str = "AA:BB:CC:DD:EE:01",
    start: int | None = None,
    retry_count: int = 0,
    mgmt_count: int = 0,
    ctrl_count: int = 0,
    data_count: int = 100,
    session: str = "sess-1",
) -> dict:
    if start is None:
        start = int(time.time() * 1000) - 1000
    return {
        "window_id": window_id,
        "client_mac": client,
        "window_start_ms": start,
        "window_end_ms": start + 30_000,
        "total_frame_count": data_count + mgmt_count + ctrl_count,
        "total_byte_count": 10_000,
        "uplink_frame_count": 50,
        "downlink_frame_count": 50,
        "uplink_byte_count": 5_000,
        "downlink_byte_count": 5_000,
        "retry_frame_count": retry_count,
        "data_frame_count": data_count,
        "mgmt_frame_count": mgmt_count,
        "ctrl_frame_count": ctrl_count,
        "derived_features_json": {
            "kismet-ml-v1.packet_rate": 3.33,
            "kismet-ml-v1.byte_rate": 333.3,
            "kismet-ml-v1.mean_packet_size": 100.0,
            "kismet-ml-v1.median_packet_size": 100.0,
            "kismet-ml-v1.packet_size_std": 10.0,
            "kismet-ml-v1.mean_interarrival_ms": 300.0,
            "kismet-ml-v1.median_interarrival_ms": 300.0,
            "kismet-ml-v1.interarrival_std_ms": 20.0,
            "kismet-ml-v1.uplink_ratio": 0.5,
            "kismet-ml-v1.downlink_ratio": 0.5,
            "kismet-ml-v1.burst_rate": 0.1,
            "kismet-ml-v1.burst_duration_ms": 5.0,
            "kismet-ml-v1.periodicity_score": 0.2,
        },
        "capture_session": session,
    }


class TestActivityV2Features(unittest.TestCase):
    def test_v2_schema_excludes_radio_counters(self):
        w = _sample_window("w1", retry_count=50, mgmt_count=20, ctrl_count=10)
        vec_v2 = activity_feature_vector(w, schema_version=ACTIVITY_FEATURE_SCHEMA_V2)
        self.assertEqual(vec_v2.feature_schema_version, "activity-features-v2")

        # Excluded features
        self.assertNotIn("retry_packet_count", vec_v2.feature_values)
        self.assertNotIn("retry_packet_ratio", vec_v2.feature_values)
        self.assertNotIn("management_packet_count", vec_v2.feature_values)
        self.assertNotIn("control_packet_count", vec_v2.feature_values)
        self.assertNotIn("data_packet_count", vec_v2.feature_values)

        # Retained portable transport/shape features
        self.assertIn("packet_count", vec_v2.feature_values)
        self.assertIn("byte_count", vec_v2.feature_values)
        self.assertIn("packet_rate", vec_v2.feature_values)
        self.assertIn("byte_rate", vec_v2.feature_values)
        self.assertIn("derived_mean_packet_size", vec_v2.feature_values)
        self.assertIn("derived_mean_interarrival_ms", vec_v2.feature_values)
        self.assertIn("derived_periodicity_score", vec_v2.feature_values)

    def test_v2_features_are_invariant_to_retry_and_mgmt_noise(self):
        # In v1, retries changed the feature vector; in v2, retries alone do not alter features
        w_clean = _sample_window("w1", retry_count=0)
        w_noisy = _sample_window("w1", retry_count=500)

        v_clean = activity_feature_vector(w_clean, schema_version=ACTIVITY_FEATURE_SCHEMA_V2)
        v_noisy = activity_feature_vector(w_noisy, schema_version=ACTIVITY_FEATURE_SCHEMA_V2)

        self.assertEqual(v_clean.feature_values, v_noisy.feature_values)

        # Under legacy v1, they would differ
        v1_clean = activity_feature_vector(w_clean, schema_version=ACTIVITY_FEATURE_SCHEMA_V1)
        v1_noisy = activity_feature_vector(w_noisy, schema_version=ACTIVITY_FEATURE_SCHEMA_V1)
        self.assertNotEqual(v1_clean.feature_values, v1_noisy.feature_values)


class TestDomainShiftDetection(unittest.TestCase):
    def test_domain_shift_detected_on_extreme_rates(self):
        # Create classifier with reference statistics
        classifier = ActivityRandomForestClassifier(model_version="activity-rf-v2")
        classifier.reference_statistics = {
            "packet_rate": {"min": 1.0, "max": 50.0, "mean": 10.0, "std": 5.0, "p01": 1.0, "p99": 45.0},
            "byte_rate": {"min": 100.0, "max": 50000.0, "mean": 10000.0, "std": 5000.0, "p01": 100.0, "p99": 45000.0},
            "derived_mean_packet_size": {"min": 60.0, "max": 1500.0, "mean": 500.0, "std": 200.0, "p01": 64.0, "p99": 1400.0},
        }

        # Normal vector within training domain
        normal_vec = activity_feature_vector(_sample_window("w1"))
        # Add normal rate
        normal_vec.feature_values["packet_rate"] = 12.0
        normal_vec.feature_values["byte_rate"] = 12000.0
        normal_vec.feature_values["derived_mean_packet_size"] = 1000.0
        is_shift, detail = classifier.check_domain_shift(normal_vec)
        self.assertFalse(is_shift)

        # Extreme outlier vector (severe domain shift: 100x max packet rate and byte rate)
        shifted_vec = activity_feature_vector(_sample_window("w2"))
        shifted_vec.feature_values["packet_rate"] = 5000.0  # 100x max
        shifted_vec.feature_values["byte_rate"] = 5000000.0 # 100x max
        is_shift, detail = classifier.check_domain_shift(shifted_vec)
        self.assertTrue(is_shift)
        self.assertIn("domain_shift", detail)


class TestActivityModelRegistryV2(unittest.TestCase):
    def test_registry_rejects_v1_artifact_on_v2_pipeline(self):
        registry = ActivityModelRegistry()
        v1_artifact = ActivityModelArtifactMetadata(
            "activity-rf-v1", "activity-rf-v1", "activity-features-v1",
            "vnat-v1", ("packet_count",), ("streaming", "file_transfer", "chat", "voip", "other"), (5,),
        )
        with self.assertRaises(ActivityModelCompatibilityError):
            registry.register(v1_artifact, expected_dataset_version="vnat-v2", expected_feature_columns=("packet_count",))

    def test_registry_accepts_valid_v2_artifact(self):
        registry = ActivityModelRegistry()
        v2_artifact = ActivityModelArtifactMetadata(
            "activity-rf-v2", "activity-rf-v2", "activity-features-v2",
            "vnat-v2", ("packet_count",), ("streaming", "file_transfer", "chat", "voip", "other"), (5,),
        )
        registry.register(v2_artifact, expected_dataset_version="vnat-v2", expected_feature_columns=("packet_count",))
        self.assertEqual(registry.get("activity-rf-v2").model_version, "activity-rf-v2")


class TestReadOnlyInferenceAndIntervalPersistence(unittest.TestCase):
    def test_predict_device_is_strictly_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            w = _sample_window("w1")
            KismetMLDerivedStore(directory).persist_many("traffic_windows", [w])
            service = ActivityInferenceService(storage_dir=directory)

            class MockClassifier:
                model_version = "activity-rf-v2"
                def predict(self, vec):
                    return "streaming", {"streaming": 0.85, "file_transfer": 0.05, "chat": 0.05, "voip": 0.03, "other": 0.02}
                def check_domain_shift(self, vec):
                    return False, None

            service._classifier = MockClassifier()

            # Calling predict_device in default read_only mode
            res = service.predict_device("AA:BB:CC:DD:EE:01")
            self.assertEqual(res["status"], "ok")
            self.assertEqual(res["current"]["activity"], "streaming")
            self.assertTrue(res["read_only"])

            # Verify no database file created
            db_path = Path(directory) / "activity_predictions.sqlite"
            self.assertFalse(db_path.exists())

    def test_interval_processor_persists_and_smooths(self):
        with tempfile.TemporaryDirectory() as directory:
            service = ActivityInferenceService(storage_dir=directory)

            class MockClassifier:
                model_version = "activity-rf-v2"
                def predict(self, vec):
                    return "chat", {"streaming": 0.1, "file_transfer": 0.05, "chat": 0.8, "voip": 0.03, "other": 0.02}
                def check_domain_shift(self, vec):
                    return False, None

            service._classifier = MockClassifier()

            now = int(time.time() * 1000)
            windows = [
                _sample_window("w1", start=now - 20_000),
                _sample_window("w2", start=now - 10_000),
            ]
            predictions = service.predict_interval(windows, persist=True)
            self.assertEqual(len(predictions), 2)
            self.assertEqual(predictions[0]["activity"], "chat")

            # Check persisted in sqlite
            store = ActivityPredictionStore(Path(directory) / "activity_predictions.sqlite")
            persisted = store.query_device("AA:BB:CC:DD:EE:01")
            self.assertEqual(len(persisted), 2)
            self.assertEqual(persisted[0].activity, "chat")

            # Subsequent read-only query serves from DB
            res = service.predict_device("AA:BB:CC:DD:EE:01")
            self.assertEqual(res["status"], "ok")
            self.assertEqual(res["current"]["activity"], "chat")


if __name__ == "__main__":
    unittest.main()
