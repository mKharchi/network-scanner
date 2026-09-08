"""Phase 1 fingerprint feature, matching, and shadow-registry contracts."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SERVER_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIRECTORY))

from server_components.device_fingerprinting import (
    FINGERPRINT_FEATURE_SCHEMA_VERSION,
    FingerprintThresholds,
    FingerprintModelArtifactMetadata,
    FingerprintModelCompatibilityError,
    FingerprintModelRegistry,
    IdentityMatch,
    LabeledFingerprintExample,
    ShadowIdentityRegistry,
    build_pair_records,
    evaluate_similarity,
    fingerprint_feature_vector,
    fingerprint_similarity,
    match_identity,
)
from server_components.kismet_ml_foundation import FingerprintObservation


def _observation(index: int, mac: str, *, vendor: str = "0050F2", missing: bool = False) -> FingerprintObservation:
    return FingerprintObservation(
        observation_id=f"obs-{index}", timestamp_epoch_ms=1_000 + index * 100,
        source_mac=mac, is_randomized_mac=mac.startswith("02"),
        frame_subtype="Probe Request", sequence_number=index + 1,
        signal_dbm=-50.0 - index, frequency_mhz=2412.0,
        ie_tag_sequence=() if missing else (0, 1, 45, 48, 221),
        ie_vendor_ouis=() if missing else (vendor,),
        ht_capabilities_hex=None if missing else "1122",
        vht_capabilities_hex=None if missing else "3344",
        he_capabilities_hex=None, wmm_capabilities_present=not missing,
        capture_file="capture-a.kismet",
    )


class FingerprintFeatureTests(unittest.TestCase):
    def test_vector_is_fixed_and_does_not_include_mac_columns(self):
        vector = fingerprint_feature_vector([_observation(1, "02:11:22:33:44:55")])
        self.assertEqual(vector.feature_schema_version, FINGERPRINT_FEATURE_SCHEMA_VERSION)
        self.assertTrue(vector.feature_values["ie_count_45"])
        self.assertTrue(vector.feature_values["ht_present"])
        self.assertFalse(any("mac" in name.lower() for name in vector.feature_values))
        self.assertEqual(vector.observed_macs, ("02:11:22:33:44:55",))

    def test_same_capabilities_with_changed_mac_match_and_missing_ie_is_safe(self):
        first = fingerprint_feature_vector([_observation(1, "02:11:22:33:44:55"), _observation(2, "06:11:22:33:44:55")])
        changed = fingerprint_feature_vector([_observation(3, "0A:11:22:33:44:55")])
        missing = fingerprint_feature_vector([_observation(4, "0A:AA:BB:CC:DD:EE", missing=True)])
        score, evidence = fingerprint_similarity(first, changed)
        self.assertGreater(score, 0.7)
        self.assertIn("information_elements", evidence)
        missing_score, _ = fingerprint_similarity(first, missing)
        self.assertLess(missing_score, score)

    def test_thresholds_keep_low_confidence_non_authoritative(self):
        candidate = fingerprint_feature_vector([_observation(1, "02:11:22:33:44:55")])
        unrelated = fingerprint_feature_vector([_observation(4, "0A:AA:BB:CC:DD:EE", missing=True)])
        result = match_identity(
            unrelated, {"identity-1": candidate},
            thresholds=FingerprintThresholds(high_confidence=0.99, medium_confidence=0.98),
        )
        self.assertIsNone(result.candidate_identity_id)
        self.assertEqual(result.decision, "low_confidence_new_candidate")

    def test_pairs_include_same_and_different_device_labels(self):
        examples = [
            LabeledFingerprintExample("a", "device-a", "session-1", fingerprint_feature_vector([_observation(1, "02:11:22:33:44:55")])),
            LabeledFingerprintExample("b", "device-a", "session-2", fingerprint_feature_vector([_observation(2, "06:11:22:33:44:55")])),
            LabeledFingerprintExample("c", "device-b", "session-1", fingerprint_feature_vector([_observation(3, "0A:AA:BB:CC:DD:EE")])),
        ]
        pairs = build_pair_records(examples)
        self.assertEqual(len(pairs), 3)
        self.assertEqual(sum(pair.label_same_device for pair in pairs), 1)
        self.assertEqual(len({pair.pair_id for pair in pairs}), 3)

    def test_similarity_baseline_evaluates_pair_errors(self):
        examples = [
            LabeledFingerprintExample("a", "device-a", "session-1", fingerprint_feature_vector([_observation(1, "02:11:22:33:44:55")])),
            LabeledFingerprintExample("b", "device-a", "session-2", fingerprint_feature_vector([_observation(2, "06:11:22:33:44:55")])),
            LabeledFingerprintExample("c", "device-b", "session-1", fingerprint_feature_vector([_observation(3, "0A:AA:BB:CC:DD:EE", missing=True)])),
        ]
        evaluation = evaluate_similarity(examples, threshold=0.8)
        self.assertEqual(evaluation.true_positive, 1)
        self.assertEqual(evaluation.false_negative, 0)


class ShadowIdentityRegistryTests(unittest.TestCase):
    def test_evidence_is_persisted_without_authoritative_device_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = ShadowIdentityRegistry(Path(directory) / "identity.sqlite")
            evidence_id = registry.record_match(
                observation_id="obs-1", observed_mac="02:11:22:33:44:55",
                timestamp_epoch_ms=1000,
                match=IdentityMatch("identity-1", 0.91, "high_confidence_link", "fingerprint-baseline-v1", {"information_elements": 0.95}),
            )
            evidence = registry.list_evidence()
            self.assertEqual(evidence[0]["evidence_id"], evidence_id)
            self.assertEqual(evidence[0]["candidate_identity_id"], "identity-1")
            self.assertEqual(evidence[0]["decision"], "high_confidence_link")
            self.assertEqual(evidence[0]["observed_mac"], "02:11:22:33:44:55")

    def test_medium_confidence_is_not_persisted_as_an_identity_link(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "identity.sqlite"
            registry = ShadowIdentityRegistry(path)
            registry.record_match(
                observation_id="obs-medium", observed_mac="02:11:22:33:44:55",
                timestamp_epoch_ms=1000,
                match=IdentityMatch("identity-1", 0.70, "medium_confidence_candidate", "fingerprint-baseline-v1", {}),
            )
            import sqlite3
            with sqlite3.connect(path) as connection:
                self.assertEqual(connection.execute("SELECT count(*) FROM device_identities").fetchone()[0], 0)
                self.assertEqual(connection.execute("SELECT candidate_identity_id FROM identity_evidence").fetchone()[0], "identity-1")


class FingerprintModelRegistryTests(unittest.TestCase):
    def test_registry_rejects_wrong_dataset_version(self):
        registry = FingerprintModelRegistry()
        artifact = FingerprintModelArtifactMetadata(
            "fingerprint-rf-v1", "fingerprint-rf-v1", FINGERPRINT_FEATURE_SCHEMA_VERSION,
            "dataset-a", ("pair_0",), (2,),
        )
        with self.assertRaises(FingerprintModelCompatibilityError):
            registry.register(artifact, expected_dataset_version="dataset-b", expected_feature_columns=("pair_0",))


if __name__ == "__main__":
    unittest.main()
