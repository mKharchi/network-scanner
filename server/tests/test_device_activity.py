"""Plan 2 activity feature, split, model-contract, and smoothing tests."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SERVER_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIRECTORY))

from server_components.device_activity import (
    ACTIVITY_FEATURE_SCHEMA_VERSION,
    ActivityMajorityBaseline,
    ActivityModelArtifactMetadata,
    ActivityModelCompatibilityError,
    ActivityModelRegistry,
    ActivityPrediction,
    ActivityPredictionStore,
    TemporalActivitySmoother,
    activity_feature_vector,
    load_labeled_activity_windows,
    label_windows_from_sessions,
    split_activity_windows,
)


def _window(window_id: str, *, client: str = "AA:BB:CC:DD:EE:01", start: int = 1_700_000_000_000, session: str = "session-1"):
    return {
        "window_id": window_id,
        "client_mac": client,
        "window_start_ms": start,
        "window_end_ms": start + 30_000,
        "total_frame_count": 100,
        "total_byte_count": 10_000,
        "uplink_frame_count": 40,
        "downlink_frame_count": 60,
        "uplink_byte_count": 4_000,
        "downlink_byte_count": 6_000,
        "retry_frame_count": 2,
        "data_frame_count": 90,
        "mgmt_frame_count": 8,
        "ctrl_frame_count": 2,
        "derived_features_json": {
            "kismet-ml-v1.packet_rate": 3.33,
            "kismet-ml-v1.byte_rate": 333.3,
            "kismet-ml-v1.mean_packet_size": 100.0,
            "kismet-ml-v1.median_packet_size": 95.0,
            "kismet-ml-v1.packet_size_std": 10.0,
            "kismet-ml-v1.mean_interarrival_ms": 300.0,
            "kismet-ml-v1.median_interarrival_ms": 250.0,
            "kismet-ml-v1.interarrival_std_ms": 30.0,
            "kismet-ml-v1.uplink_ratio": 0.4,
            "kismet-ml-v1.downlink_ratio": 0.6,
            "kismet-ml-v1.burst_rate": 0.2,
            "kismet-ml-v1.burst_duration_ms": 5.0,
            "kismet-ml-v1.periodicity_score": 0.1,
        },
        "capture_session": session,
    }


class ActivityFeatureTests(unittest.TestCase):
    def test_features_are_fixed_and_exclude_mac(self):
        vector = activity_feature_vector(_window("window-1"))
        self.assertEqual(vector.feature_schema_version, ACTIVITY_FEATURE_SCHEMA_VERSION)
        self.assertGreater(vector.feature_values["packet_count"], 0)
        self.assertFalse(any("mac" in key.lower() for key in vector.feature_values))

    def test_labels_and_group_split_keep_adjacent_windows_together(self):
        windows = [_window("w1", start=1_700_000_000_000), _window("w2", start=1_700_000_000_030), _window("w3", start=1_700_086_400_000, session="session-2")]
        labels = [
            {"target_id": "w1", "label_family": "activity", "label": "browsing", "capture_session": "session-1"},
            {"target_id": "w2", "label_family": "activity", "label": "browsing", "capture_session": "session-1"},
            {"target_id": "w3", "label_family": "activity", "label": "idle", "capture_session": "session-2"},
        ]
        rows = load_labeled_activity_windows(windows, labels)
        splits, _metadata = split_activity_windows(rows)
        locations = {row.window_id: split for split, members in splits.items() for row in members}
        self.assertEqual(locations["w1"], locations["w2"])
        self.assertEqual(len(rows), 3)

    def test_majority_baseline_is_deterministic(self):
        rows = load_labeled_activity_windows(
            [_window("w1"), _window("w2", session="session-2")],
            [{"target_id": "w1", "label": "browsing", "capture_session": "session-1"}, {"target_id": "w2", "label": "idle", "capture_session": "session-2"}],
        )
        baseline = ActivityMajorityBaseline().fit(rows)
        self.assertEqual(baseline.label, "browsing")
        self.assertEqual(baseline.predict(rows[0].feature_vector)[0], "browsing")

    def test_session_intervals_expand_only_fully_contained_windows(self):
        windows = [_window("inside", start=1_700_000_000_000), _window("boundary", start=1_700_000_030_000)]
        sessions = [{
            "client_mac": "AA:BB:CC:DD:EE:01", "capture_session": "browse-01",
            "label": "browsing", "start_utc": "2023-11-14T22:13:20Z",
            "end_utc": "2023-11-14T22:14:00Z",
        }]
        labels = label_windows_from_sessions(windows, sessions)
        self.assertEqual([row["target_id"] for row in labels], ["inside"])


class ActivityContractTests(unittest.TestCase):
    def test_registry_rejects_wrong_dataset(self):
        registry = ActivityModelRegistry()
        artifact = ActivityModelArtifactMetadata(
            "activity-rf-v1", "activity-rf-v1", ACTIVITY_FEATURE_SCHEMA_VERSION,
            "dataset-a", ("packet_count",), ("idle", "browsing", "streaming", "file_transfer", "other"), (5,),
        )
        with self.assertRaises(ActivityModelCompatibilityError):
            registry.register(artifact, expected_dataset_version="dataset-b", expected_feature_columns=("packet_count",))

    def test_smoother_returns_unknown_below_confidence(self):
        smoother = TemporalActivitySmoother(history_size=2, minimum_confidence=0.8)
        prediction = ActivityPrediction("w1", "device-1", 0, 30_000, "browsing", 0.5, {
            "idle": 0.5, "browsing": 0.5, "streaming": 0.0, "file_transfer": 0.0, "other": 0.0,
        }, "activity-rf-v1")
        self.assertEqual(smoother.update(prediction).activity, "unknown")

    def test_prediction_store_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ActivityPredictionStore(Path(directory) / "activity.sqlite")
            prediction = ActivityPrediction("w1", "device-1", 0, 30_000, "idle", 0.9, {"idle": 0.9}, "activity-rf-v1")
            store.persist(prediction)
            store.persist(prediction)
            import sqlite3
            with sqlite3.connect(Path(directory) / "activity.sqlite") as con:
                self.assertEqual(con.execute("select count(*) from activity_predictions").fetchone()[0], 1)
                self.assertEqual(json.loads(con.execute("select probabilities_json from activity_predictions").fetchone()[0])["idle"], 0.9)


if __name__ == "__main__":
    unittest.main()
