"""Device Intelligence Service.

Unified service boundary managing:
- Feature extraction from device observations
- Rule-based heuristic evaluation
- ML ensemble model inference
- Hybrid decision reconciliation & conflict resolution
- Confidence calibration & UNKNOWN handling
- Human verification & training feedback loops
- Storage and API integration
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .device_classification_storage import (
    get_all_human_labels,
    get_classification_summary_statistics,
    get_device_classification,
    get_devices_needing_review,
    get_latest_human_label,
    save_device_classification,
    save_human_label,
)
from .device_features import CLASSIFICATION_CLASSES, extract_device_features
from .ml_classifier import (
    MODEL_VERSION,
    ClassificationResult,
    DeviceMLClassifier,
    RuleBasedDeviceClassifier,
    evaluate_classifier,
    generate_benchmark_dataset,
)

try:
    from database import get_connection
except ImportError:
    from ..database import get_connection

LOGGER = logging.getLogger(__name__)


class DeviceIntelligenceService:
    """Core intelligence engine for device categorization and assurance."""

    def __init__(self, model: Optional[DeviceMLClassifier] = None):
        self.rule_classifier = RuleBasedDeviceClassifier()
        self.ml_classifier = model or DeviceMLClassifier.load()
        self.model_version = self.ml_classifier.model_version or MODEL_VERSION

    # ========================================================================
    # 1. CLASSIFICATION & DECISION LOGIC
    # ========================================================================

    def classify_features(
        self,
        features: Mapping[str, Any],
        existing_human_label: Optional[str] = None,
    ) -> ClassificationResult:
        """Run hybrid decision engine on normalized feature vector."""
        # 1. Check for Human Verified Ground Truth
        if existing_human_label and existing_human_label in CLASSIFICATION_CLASSES:
            return ClassificationResult(
                predicted_class=existing_human_label,
                confidence=1.0,
                source="HUMAN",
                model_version=self.model_version,
                probabilities={c: (1.0 if c == existing_human_label else 0.0) for c in CLASSIFICATION_CLASSES},
                evidence=["human.verified_label"],
                rule_prediction=None,
                ml_prediction=None,
                status="ACTIVE",
            )

        # 2. Evaluate Rule Baseline
        rule_class, rule_conf, rule_evidence = self.rule_classifier.predict(features)

        # 3. Evaluate ML Classifier
        ml_class, ml_conf, ml_probs = self.ml_classifier.predict(features)

        evidence: List[str] = list(rule_evidence)
        evidence.append(f"ml.prediction:{ml_class}:{ml_conf:.2f}")

        # 4. Reconcile Rule vs ML (Hybrid Decision Engine)
        if rule_class == ml_class:
            # Full Agreement
            final_class = ml_class
            if final_class == "UNKNOWN":
                final_confidence = 0.40
                source = "HYBRID"
                status = "NEEDS_REVIEW"
                evidence.append("decision.unknown_insufficient_evidence")
            else:
                # Confidence boost for consensus
                boosted_conf = min(0.99, max(rule_conf, ml_conf) * 1.05)
                final_confidence = round(boosted_conf, 4)
                source = "HYBRID"
                status = "ACTIVE"
                evidence.append("decision.consensus_agreement")
        elif rule_class == "UNKNOWN":
            # Rule has no strong heuristic, rely on ML
            final_class = ml_class
            final_confidence = ml_conf
            source = "ML"
            status = "ACTIVE" if ml_conf >= 0.70 else "NEEDS_REVIEW"
            evidence.append("decision.ml_fallback_from_unknown_rule")
        elif ml_class == "UNKNOWN":
            # ML is uncertain, rely on Rule
            final_class = rule_class
            final_confidence = rule_conf
            source = "RULE"
            status = "ACTIVE" if rule_conf >= 0.75 else "NEEDS_REVIEW"
            evidence.append("decision.rule_fallback_from_unknown_ml")
        else:
            # Conflict between Rule and ML
            status = "NEEDS_REVIEW"
            source = "HYBRID"
            evidence.append(f"decision.conflict:rule={rule_class}_vs_ml={ml_class}")

            # Resolve based on confidence weights and protocol specificity
            if rule_conf >= 0.92 and ml_conf < 0.85:
                final_class = rule_class
                final_confidence = round(rule_conf * 0.85, 4)
                evidence.append("decision.resolved_by_high_confidence_rule")
            elif ml_conf >= 0.90 and rule_conf < 0.80:
                final_class = ml_class
                final_confidence = round(ml_conf * 0.85, 4)
                evidence.append("decision.resolved_by_high_confidence_ml")
            else:
                # Ambiguous conflict -> mark as UNKNOWN or top probability with reduced confidence
                if max(rule_conf, ml_conf) < 0.80:
                    final_class = "UNKNOWN"
                    final_confidence = 0.45
                    evidence.append("decision.conflict_unresolved_marked_unknown")
                else:
                    final_class = ml_class if ml_conf >= rule_conf else rule_class
                    final_confidence = round(min(rule_conf, ml_conf) * 0.75, 4)

        # 5. Low Confidence UNKNOWN Thresholding
        if final_confidence < 0.50 and final_class != "UNKNOWN":
            evidence.append(f"confidence.below_threshold:{final_confidence:.2f}")
            final_class = "UNKNOWN"
            final_confidence = round(final_confidence, 4)
            status = "NEEDS_REVIEW"

        return ClassificationResult(
            predicted_class=final_class,
            confidence=final_confidence,
            source=source,
            model_version=self.model_version,
            probabilities=ml_probs,
            evidence=evidence,
            rule_prediction=rule_class,
            ml_prediction=ml_class,
            status=status,
        )

    # ========================================================================
    # 2. DEVICE DATA LOADING & CLASSIFICATION EXECUTION
    # ========================================================================

    def get_device_data(self, device_id: int) -> Optional[Tuple[Dict[str, Any], List[Dict[str, Any]], Optional[Dict[str, Any]]]]:
        """Fetch device record, observations, and registered client metadata."""
        connection = None
        cursor = None
        try:
            connection = get_connection()
            cursor = connection.cursor(dictionary=True)

            cursor.execute(
                """
                SELECT id, mac_address, ip_address, hostname, vendor, first_seen, last_seen
                FROM network_devices
                WHERE id = %s
                """,
                (device_id,),
            )
            device = cursor.fetchone()
            if not device:
                return None

            cursor.execute(
                """
                SELECT id, device_id, source_type, ip_address, interface_name,
                       entry_type, rssi, switch_port, raw_data, observed_at
                FROM network_device_observations
                WHERE device_id = %s
                ORDER BY observed_at DESC
                LIMIT 50
                """,
                (device_id,),
            )
            observations = cursor.fetchall() or []

            # Check if this MAC is a registered managed client
            cursor.execute(
                """
                SELECT id, client_id, hostname, mac, os_system, os_release, os_version, os_machine
                FROM clients
                WHERE mac = %s
                """,
                (device.get("mac_address"),),
            )
            client_meta = cursor.fetchone()

            return device, observations, client_meta
        except Exception as error:
            LOGGER.warning("Could not fetch device data for device_id=%s: %s", device_id, error)
            return None
        finally:
            if cursor:
                cursor.close()
            if connection and connection.is_connected():
                connection.close()

    def classify_device(self, device_id: int, force: bool = False) -> Optional[Dict[str, Any]]:
        """Classify a single network device by ID, store result, and return summary."""
        # 1. Check if human label exists
        human_label_rec = get_latest_human_label(device_id)
        human_label = human_label_rec.get("label") if human_label_rec else None

        # 2. Check if recent active classification already exists unless forced
        if not force and not human_label:
            existing = get_device_classification(device_id)
            if existing and existing.get("status") == "ACTIVE" and existing.get("confidence", 0) >= 0.70:
                return existing

        # 3. Load device metadata and observations
        device_bundle = self.get_device_data(device_id)
        if not device_bundle:
            return None
        device, observations, client_meta = device_bundle

        # 4. Extract features
        features = extract_device_features(
            device_data=device,
            observations=observations,
            client_metadata=client_meta,
        )

        # 5. Run classification decision engine
        result = self.classify_features(features, existing_human_label=human_label)
        result_dict = result.to_dict()
        result_dict["device_id"] = device_id
        result_dict["features_version"] = features.get("features_version", "v1")

        # 6. Save to storage
        save_device_classification(device_id, result_dict)

        return result_dict

    def classify_all_devices(self, limit: int = 200, unclassified_only: bool = True) -> Dict[str, Any]:
        """Batch classify network devices."""
        connection = None
        cursor = None
        classified_count = 0
        failed_count = 0
        try:
            connection = get_connection()
            cursor = connection.cursor(dictionary=True)

            if unclassified_only:
                cursor.execute(
                    """
                    SELECT nd.id
                    FROM network_devices nd
                    LEFT JOIN device_classifications dc ON dc.device_id = nd.id
                    WHERE dc.id IS NULL OR dc.status = 'NEEDS_REVIEW'
                    LIMIT %s
                    """,
                    (limit,),
                )
            else:
                cursor.execute("SELECT id FROM network_devices LIMIT %s", (limit,))

            device_ids = [row["id"] for row in cursor.fetchall() or []]
        except Exception as error:
            LOGGER.warning("Could not query devices for batch classification: %s", error)
            device_ids = []
        finally:
            if cursor:
                cursor.close()
            if connection and connection.is_connected():
                connection.close()

        for dev_id in device_ids:
            res = self.classify_device(dev_id, force=True)
            if res:
                classified_count += 1
            else:
                failed_count += 1

        return {
            "processed": len(device_ids),
            "classified": classified_count,
            "failed": failed_count,
        }

    # ========================================================================
    # 3. HUMAN VERIFICATION & GROUND TRUTH
    # ========================================================================

    def verify_device_label(
        self,
        device_id: int,
        label: str,
        confirmed_by: Optional[str] = "admin",
        notes: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Record verified human label and immediately update classification."""
        if label not in CLASSIFICATION_CLASSES:
            raise ValueError(f"Invalid label '{label}'. Must be one of {CLASSIFICATION_CLASSES}")

        # Store human label
        save_human_label(
            device_id=device_id,
            label=label,
            source="ADMIN",
            confirmed_by=confirmed_by,
            notes=notes,
        )

        # Re-run classification with human label priority
        return self.classify_device(device_id, force=True)

    # ========================================================================
    # 4. METRICS, REVIEWS & RETRAINING
    # ========================================================================

    def get_review_queue(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return devices requiring administrator review."""
        return get_devices_needing_review(limit=limit)

    def get_statistics(self) -> Dict[str, Any]:
        """Return classification summary statistics."""
        return get_classification_summary_statistics()

    def evaluate_against_benchmark(self, sample_count: int = 150) -> Dict[str, Any]:
        """Evaluate ML and Rule models against standard benchmark dataset."""
        dataset = generate_benchmark_dataset(sample_count=sample_count)

        rule_eval = evaluate_classifier(self.rule_classifier.predict, dataset)
        ml_eval = evaluate_classifier(self.ml_classifier.predict, dataset)

        return {
            "dataset_size": sample_count,
            "rule_baseline": {
                "accuracy": rule_eval["accuracy"],
                "per_class": rule_eval["per_class"],
            },
            "ml_model": {
                "model_version": self.model_version,
                "accuracy": ml_eval["accuracy"],
                "per_class": ml_eval["per_class"],
                "confusion_matrix": ml_eval["confusion_matrix"],
            },
            "improvement_delta": round(ml_eval["accuracy"] - rule_eval["accuracy"], 4),
        }

    def retrain_model_pipeline(self) -> Dict[str, Any]:
        """Execute retraining evaluation and model version checkpointing."""
        eval_results = self.evaluate_against_benchmark(sample_count=200)

        # Save model checkpoint
        self.ml_classifier.save()

        human_labels = get_all_human_labels()

        return {
            "status": "SUCCESS",
            "model_version": self.model_version,
            "human_labels_count": len(human_labels),
            "benchmark_evaluation": eval_results,
        }


# Singleton service instance
_DEVICE_INTELLIGENCE_SERVICE: Optional[DeviceIntelligenceService] = None


def get_device_intelligence_service() -> DeviceIntelligenceService:
    """Return the global DeviceIntelligenceService singleton."""
    global _DEVICE_INTELLIGENCE_SERVICE
    if _DEVICE_INTELLIGENCE_SERVICE is None:
        _DEVICE_INTELLIGENCE_SERVICE = DeviceIntelligenceService()
    return _DEVICE_INTELLIGENCE_SERVICE
