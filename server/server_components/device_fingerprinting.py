"""Phase 1 device-fingerprinting primitives.

The first implementation is deliberately model-light: it creates a stable,
MAC-independent feature profile and an explainable similarity matcher.  The
matcher emits shadow evidence only; it never changes ``network_devices``.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .kismet_ml_foundation import (
    FEATURE_SCHEMA_VERSION,
    FingerprintObservation,
    is_randomized_mac,
)

FINGERPRINT_FEATURE_SCHEMA_VERSION = "fingerprint-v1"
FINGERPRINT_MODEL_VERSION = "fingerprint-baseline-v1"
STANDARD_IE_TAGS = (0, 1, 5, 45, 48, 50, 70, 107, 127, 191, 221, 255)
FRAME_SUBTYPES = (
    "Probe Request", "Probe Response", "Association Request",
    "Reassociation Request", "Association Response",
)
CAPABILITY_BITS = 128


def _safe_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _mean(values: Sequence[float]) -> Optional[float]:
    return statistics.fmean(values) if values else None


def _std(values: Sequence[float]) -> Optional[float]:
    return statistics.pstdev(values) if len(values) > 1 else (0.0 if values else None)


def _hex_bits(value: Optional[str], width: int = CAPABILITY_BITS) -> Dict[str, float]:
    bits = {str(index): 0.0 for index in range(width)}
    if not value:
        return bits
    try:
        raw = bytes.fromhex(value)
    except (TypeError, ValueError):
        return bits
    integer = int.from_bytes(raw, "little")
    for index in range(min(width, len(raw) * 8)):
        bits[str(index)] = float((integer >> index) & 1)
    return bits


def _hash_bucket(value: str, buckets: int = 32) -> int:
    digest = hashlib.sha256(value.encode("ascii", errors="ignore")).digest()
    return int.from_bytes(digest[:4], "big") % buckets


@dataclass(frozen=True)
class FingerprintFeatureVector:
    """Fixed-column numeric vector with no MAC-derived predictive columns."""

    feature_schema_version: str
    source_observation_ids: Tuple[str, ...]
    feature_values: Dict[str, float]
    observed_macs: Tuple[str, ...] = ()
    first_seen_epoch_ms: Optional[int] = None
    last_seen_epoch_ms: Optional[int] = None


@dataclass(frozen=True)
class LabeledFingerprintExample:
    profile_id: str
    physical_device_guid: str
    capture_session: str
    feature_vector: FingerprintFeatureVector

    @property
    def split_group(self) -> str:
        return f"{self.physical_device_guid}|{self.capture_session}"


@dataclass(frozen=True)
class FingerprintPair:
    pair_id: str
    left_profile_id: str
    right_profile_id: str
    label_same_device: bool
    split_group: str


@dataclass(frozen=True)
class IdentityMatch:
    candidate_identity_id: Optional[str]
    confidence: float
    decision: str
    model_version: str
    evidence: Dict[str, float]


@dataclass(frozen=True)
class FingerprintThresholds:
    high_confidence: float = 0.82
    medium_confidence: float = 0.62

    def __post_init__(self) -> None:
        if not 0.0 <= self.medium_confidence < self.high_confidence <= 1.0:
            raise ValueError("thresholds must satisfy 0 <= medium < high <= 1")


def _empty_feature_values() -> Dict[str, float]:
    values: Dict[str, float] = {}
    for tag in STANDARD_IE_TAGS:
        values[f"ie_count_{tag}"] = 0.0
    for position in range(16):
        for tag in STANDARD_IE_TAGS:
            values[f"ie_sequence_{position}_{tag}"] = 0.0
    for bucket in range(32):
        values[f"vendor_oui_bucket_{bucket}"] = 0.0
    for capability in ("ht", "vht", "he"):
        values[f"{capability}_present"] = 0.0
        for bit in range(CAPABILITY_BITS):
            values[f"{capability}_bit_{bit}"] = 0.0
    values.update({
        "wmm_present": 0.0,
        "observation_count": 0.0,
        "probe_request_ratio": 0.0,
        "probe_response_ratio": 0.0,
        "association_ratio": 0.0,
        "mean_interarrival_ms": 0.0,
        "interarrival_std_ms": 0.0,
        "mean_signal_dbm": 0.0,
        "signal_std_db": 0.0,
        "mean_frequency_mhz": 0.0,
        "frequency_std_mhz": 0.0,
        "sequence_delta_mean": 0.0,
        "sequence_delta_std": 0.0,
        "sequence_wrap_ratio": 0.0,
    })
    for subtype in FRAME_SUBTYPES:
        values[f"frame_subtype_{subtype.lower().replace(' ', '_')}"] = 0.0
    return values


def fingerprint_feature_vector(observations: Iterable[FingerprintObservation]) -> FingerprintFeatureVector:
    """Aggregate one or more observations into a fixed, MAC-independent vector."""
    items = sorted(observations, key=lambda item: item.timestamp_epoch_ms)
    values = _empty_feature_values()
    if not items:
        return FingerprintFeatureVector(FINGERPRINT_FEATURE_SCHEMA_VERSION, (), values)
    ids = tuple(item.observation_id for item in items)
    timestamps = [item.timestamp_epoch_ms for item in items]
    signals = [float(item.signal_dbm) for item in items if item.signal_dbm is not None]
    frequencies = [float(item.frequency_mhz) for item in items if item.frequency_mhz is not None]
    sequence_numbers = [item.sequence_number for item in items if item.sequence_number is not None]
    interarrivals = [right - left for left, right in zip(timestamps, timestamps[1:])]
    sequence_deltas = [((right - left) % 4096) for left, right in zip(sequence_numbers, sequence_numbers[1:])]
    wraps = [delta for delta in sequence_deltas if delta > 2048]
    values["observation_count"] = float(len(items))
    values["mean_interarrival_ms"] = _mean(interarrivals) or 0.0
    values["interarrival_std_ms"] = _std(interarrivals) or 0.0
    values["mean_signal_dbm"] = _mean(signals) or 0.0
    values["signal_std_db"] = _std(signals) or 0.0
    values["mean_frequency_mhz"] = _mean(frequencies) or 0.0
    values["frequency_std_mhz"] = _std(frequencies) or 0.0
    values["sequence_delta_mean"] = _mean(sequence_deltas) or 0.0
    values["sequence_delta_std"] = _std(sequence_deltas) or 0.0
    values["sequence_wrap_ratio"] = len(wraps) / len(sequence_deltas) if sequence_deltas else 0.0
    counts: Dict[str, int] = {}
    for item in items:
        counts[item.frame_subtype] = counts.get(item.frame_subtype, 0) + 1
        values[f"frame_subtype_{item.frame_subtype.lower().replace(' ', '_')}"] = 1.0
        for tag in item.ie_tag_sequence:
            if tag in STANDARD_IE_TAGS:
                values[f"ie_count_{tag}"] += 1.0
        for position, tag in enumerate(item.ie_tag_sequence[:16]):
            if tag in STANDARD_IE_TAGS:
                values[f"ie_sequence_{position}_{tag}"] = 1.0
        for oui in item.ie_vendor_ouis:
            values[f"vendor_oui_bucket_{_hash_bucket(oui)}"] += 1.0
        for capability, hex_value in (("ht", item.ht_capabilities_hex), ("vht", item.vht_capabilities_hex), ("he", item.he_capabilities_hex)):
            if hex_value:
                values[f"{capability}_present"] = 1.0
                for bit, state in _hex_bits(hex_value).items():
                    values[f"{capability}_bit_{bit}"] = max(values[f"{capability}_bit_{bit}"], state)
        if item.wmm_capabilities_present:
            values["wmm_present"] = 1.0
    total = float(len(items))
    values["probe_request_ratio"] = counts.get("Probe Request", 0) / total
    values["probe_response_ratio"] = counts.get("Probe Response", 0) / total
    values["association_ratio"] = sum(counts.get(name, 0) for name in ("Association Request", "Association Response", "Reassociation Request")) / total
    observed_macs = tuple(sorted({item.source_mac for item in items if item.source_mac}))
    return FingerprintFeatureVector(
        FINGERPRINT_FEATURE_SCHEMA_VERSION, ids, values, observed_macs,
        min(timestamps), max(timestamps),
    )


def _group_similarity(left: Mapping[str, float], right: Mapping[str, float], prefix: str) -> Optional[float]:
    keys = [key for key in left.keys() if key.startswith(prefix)]
    if not keys or not any(left[key] or right.get(key, 0.0) for key in keys):
        return None
    binary = all(left[key] in (0.0, 1.0) and right.get(key, 0.0) in (0.0, 1.0) for key in keys)
    if binary:
        union = sum(1 for key in keys if left[key] or right.get(key, 0.0))
        intersection = sum(1 for key in keys if left[key] and right.get(key, 0.0))
        return intersection / union if union else None
    left_norm = math.sqrt(sum(left[key] ** 2 for key in keys))
    right_norm = math.sqrt(sum(right.get(key, 0.0) ** 2 for key in keys))
    if not left_norm or not right_norm:
        return None
    return max(0.0, min(1.0, sum(left[key] * right.get(key, 0.0) for key in keys) / (left_norm * right_norm)))


def fingerprint_similarity(left: FingerprintFeatureVector, right: FingerprintFeatureVector) -> Tuple[float, Dict[str, float]]:
    """Return an explainable weighted similarity score in [0, 1]."""
    groups = {
        "information_elements": ("ie_", 0.35),
        "capabilities": ("ht_", 0.20),
        "vht_capabilities": ("vht_", 0.15),
        "he_capabilities": ("he_", 0.10),
        "vendor_and_wmm": ("vendor_", 0.10),
        "behavior": ("", 0.10),
    }
    evidence: Dict[str, float] = {}
    weighted = 0.0
    total_weight = 0.0
    for name, (prefix, weight) in groups.items():
        if name == "behavior":
            behavior_keys = ("mean_", "sequence_", "probe_", "association_", "frame_subtype_", "observation_count")
            keys = [key for key in left.feature_values if key.startswith(behavior_keys)]
            if not keys:
                continue
            left_values = {key: left.feature_values[key] for key in keys}
            right_values = {key: right.feature_values.get(key, 0.0) for key in keys}
            score = _group_similarity(left_values, right_values, "")
        else:
            score = _group_similarity(left.feature_values, right.feature_values, prefix)
        if score is not None:
            evidence[name] = score
            weighted += weight * score
            total_weight += weight
    return (weighted / total_weight if total_weight else 0.0), evidence


def match_identity(
    observation: FingerprintFeatureVector,
    candidates: Mapping[str, FingerprintFeatureVector],
    *, thresholds: FingerprintThresholds = FingerprintThresholds(),
    model_version: str = FINGERPRINT_MODEL_VERSION,
) -> IdentityMatch:
    best_id: Optional[str] = None
    best_score = 0.0
    best_evidence: Dict[str, float] = {}
    for identity_id, candidate in candidates.items():
        score, evidence = fingerprint_similarity(observation, candidate)
        if score > best_score:
            best_id, best_score, best_evidence = identity_id, score, evidence
    if best_score >= thresholds.high_confidence:
        decision = "high_confidence_link"
    elif best_score >= thresholds.medium_confidence:
        decision = "medium_confidence_candidate"
    else:
        decision, best_id = "low_confidence_new_candidate", None
    return IdentityMatch(best_id, best_score, decision, model_version, best_evidence)


def build_pair_records(examples: Sequence[LabeledFingerprintExample]) -> List[FingerprintPair]:
    """Build all labeled positive/negative candidates for an evaluation split."""
    pairs: List[FingerprintPair] = []
    for left, right in combinations(examples, 2):
        same = left.physical_device_guid == right.physical_device_guid
        identity = f"{left.profile_id}|{right.profile_id}|{int(same)}"
        pairs.append(FingerprintPair(
            pair_id=hashlib.sha256(identity.encode()).hexdigest()[:24],
            left_profile_id=left.profile_id,
            right_profile_id=right.profile_id,
            label_same_device=same,
            split_group=f"{left.split_group}|{right.split_group}",
        ))
    return pairs


class ShadowIdentityRegistry:
    """Persistent logical identities and reviewable evidence, never authority."""

    def __init__(self, path: Path | str):
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.path)
        con.executescript("""
            CREATE TABLE IF NOT EXISTS device_identities (
                device_identity_id TEXT PRIMARY KEY, first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL, confidence REAL NOT NULL, fingerprint_version TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS identity_identifiers (
                device_identity_id TEXT NOT NULL, identifier_type TEXT NOT NULL,
                identifier_value TEXT NOT NULL, provenance TEXT NOT NULL,
                confidence REAL NOT NULL, observed_at TEXT NOT NULL,
                PRIMARY KEY (device_identity_id, identifier_type, identifier_value)
            );
            CREATE TABLE IF NOT EXISTS identity_evidence (
                evidence_id TEXT PRIMARY KEY, observation_id TEXT NOT NULL,
                candidate_identity_id TEXT, observed_mac TEXT, timestamp_epoch_ms INTEGER NOT NULL,
                confidence REAL NOT NULL, decision TEXT NOT NULL, model_version TEXT NOT NULL,
                evidence_json TEXT NOT NULL
            );
        """)
        con.commit()
        return con

    def record_match(
        self, *, observation_id: str, observed_mac: Optional[str], timestamp_epoch_ms: int,
        match: IdentityMatch, identity_id: Optional[str] = None,
    ) -> str:
        evidence_id = hashlib.sha256(f"{observation_id}|{match.model_version}|{match.decision}".encode()).hexdigest()[:24]
        con = self._connect()
        try:
            now = datetime.now(timezone.utc).isoformat()
            # Only a high-confidence decision may attach an observation to an
            # existing logical identity. Medium/low decisions remain reviewable
            # evidence and cannot silently create or merge identity records.
            selected = match.candidate_identity_id if match.decision == "high_confidence_link" else None
            proposed = match.candidate_identity_id or identity_id
            if selected:
                con.execute(
                    "INSERT INTO device_identities VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(device_identity_id) DO UPDATE SET last_seen=excluded.last_seen, confidence=excluded.confidence",
                    (selected, now, now, match.confidence, match.model_version),
                )
                if observed_mac:
                    con.execute(
                        "INSERT INTO identity_identifiers VALUES (?, 'MAC', ?, ?, ?, ?) "
                        "ON CONFLICT(device_identity_id, identifier_type, identifier_value) DO UPDATE SET confidence=excluded.confidence, observed_at=excluded.observed_at",
                        (selected, observed_mac, "kismet-fingerprint-shadow", match.confidence, now),
                    )
            con.execute(
                "INSERT OR REPLACE INTO identity_evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (evidence_id, observation_id, proposed, observed_mac, timestamp_epoch_ms,
                 match.confidence, match.decision, match.model_version, json.dumps(match.evidence, sort_keys=True)),
            )
            con.commit()
        finally:
            con.close()
        return evidence_id

    def list_evidence(self, limit: int = 100) -> List[Dict[str, Any]]:
        con = self._connect()
        try:
            con.row_factory = sqlite3.Row
            rows = con.execute("SELECT * FROM identity_evidence ORDER BY timestamp_epoch_ms DESC LIMIT ?", (max(1, min(limit, 1000)),)).fetchall()
            return [dict(row) for row in rows]
        finally:
            con.close()


def split_fingerprint_examples(
    examples: Sequence[LabeledFingerprintExample], *, validation_fraction: float = 0.2,
    test_fraction: float = 0.2,
) -> Tuple[Dict[str, List[LabeledFingerprintExample]], Dict[str, Any]]:
    """Split profiles by physical-device/session group before making pairs."""
    from .kismet_ml_foundation import group_aware_split

    rows = [{"profile": example, "split_group": example.split_group} for example in examples]
    split, metadata = group_aware_split(
        rows, group_field="split_group", validation_fraction=validation_fraction,
        test_fraction=test_fraction,
    )
    return {name: [row["profile"] for row in rows] for name, rows in split.items()}, metadata


def pair_feature_vector(left: FingerprintFeatureVector, right: FingerprintFeatureVector) -> Tuple[float, ...]:
    """Encode a pair using absolute differences and products, never raw MACs."""
    keys = sorted(set(left.feature_values) | set(right.feature_values))
    values: List[float] = []
    for key in keys:
        left_value, right_value = left.feature_values.get(key, 0.0), right.feature_values.get(key, 0.0)
        values.extend((abs(left_value - right_value), left_value * right_value))
    return tuple(values)


@dataclass(frozen=True)
class FingerprintEvaluation:
    threshold: float
    true_positive: int
    false_positive: int
    false_negative: int
    true_negative: int
    precision: float
    recall: float
    f1: float
    false_merge_rate: float
    false_split_rate: float


class FingerprintModelCompatibilityError(ValueError):
    """Raised when a fingerprint artifact cannot consume current features."""


@dataclass(frozen=True)
class FingerprintModelArtifactMetadata:
    model_id: str
    model_version: str
    feature_schema_version: str
    dataset_version: str
    feature_columns: Tuple[str, ...]
    prediction_output_shape: Tuple[int, ...]


class FingerprintModelRegistry:
    """In-process compatibility gate for fingerprint model artifacts."""

    def __init__(self) -> None:
        self._models: Dict[str, FingerprintModelArtifactMetadata] = {}

    def register(
        self, artifact: FingerprintModelArtifactMetadata, *, expected_dataset_version: str,
        expected_feature_columns: Sequence[str],
    ) -> None:
        if artifact.feature_schema_version != FINGERPRINT_FEATURE_SCHEMA_VERSION:
            raise FingerprintModelCompatibilityError("fingerprint feature schema is incompatible")
        if artifact.dataset_version != expected_dataset_version:
            raise FingerprintModelCompatibilityError("fingerprint dataset version is incompatible")
        if tuple(artifact.feature_columns) != tuple(expected_feature_columns):
            raise FingerprintModelCompatibilityError("fingerprint feature columns are incompatible")
        if artifact.prediction_output_shape != (2,):
            raise FingerprintModelCompatibilityError("fingerprint output shape is incompatible")
        self._models[artifact.model_id] = artifact

    def get(self, model_id: str) -> FingerprintModelArtifactMetadata:
        return self._models[model_id]


def evaluate_similarity(
    examples: Sequence[LabeledFingerprintExample], *, threshold: float = 0.5,
) -> FingerprintEvaluation:
    """Evaluate the explainable similarity baseline on one split."""
    by_id = {example.profile_id: example for example in examples}
    pairs = build_pair_records(examples)
    counts = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    for pair in pairs:
        left = by_id[pair.left_profile_id].feature_vector
        right = by_id[pair.right_profile_id].feature_vector
        guess = fingerprint_similarity(left, right)[0] >= threshold
        if pair.label_same_device and guess:
            counts["tp"] += 1
        elif pair.label_same_device:
            counts["fn"] += 1
        elif guess:
            counts["fp"] += 1
        else:
            counts["tn"] += 1
    tp, fp, fn, tn = (counts[name] for name in ("tp", "fp", "fn", "tn"))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return FingerprintEvaluation(
        threshold, tp, fp, fn, tn, precision, recall,
        2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        fp / (fp + tn) if fp + tn else 0.0,
        fn / (fn + tp) if fn + tp else 0.0,
    )


class PairwiseFingerprintClassifier:
    """CPU-friendly random-forest pair classifier with versioned artifacts."""

    def __init__(self, *, model_version: str = "fingerprint-rf-v1", random_state: int = 42, n_estimators: int = 160):
        self.model_version = model_version
        self.random_state = random_state
        self.n_estimators = n_estimators
        self._model = None
        self._feature_columns: Optional[Tuple[str, ...]] = None
        self.dataset_version: Optional[str] = None

    @staticmethod
    def _pairs(examples: Sequence[LabeledFingerprintExample]) -> Tuple[List[Tuple[float, ...]], List[int], List[FingerprintPair]]:
        by_id = {example.profile_id: example for example in examples}
        pairs = build_pair_records(examples)
        features = [pair_feature_vector(by_id[pair.left_profile_id].feature_vector, by_id[pair.right_profile_id].feature_vector) for pair in pairs]
        labels = [int(pair.label_same_device) for pair in pairs]
        return features, labels, pairs

    def fit(self, examples: Sequence[LabeledFingerprintExample], *, dataset_version: str) -> "PairwiseFingerprintClassifier":
        try:
            from sklearn.ensemble import RandomForestClassifier
        except ImportError as error:  # pragma: no cover - dependency environment
            raise RuntimeError("Phase 1 classifier requires scikit-learn") from error
        features, labels, _ = self._pairs(examples)
        if not features or len(set(labels)) < 2:
            raise ValueError("training requires both same-device and different-device pairs")
        self._model = RandomForestClassifier(
            n_estimators=self.n_estimators, random_state=self.random_state,
            class_weight="balanced", n_jobs=1, min_samples_leaf=2,
        )
        self._model.fit(features, labels)
        self._feature_columns = tuple(f"pair_{index}" for index in range(len(features[0])))
        self.dataset_version = dataset_version
        return self

    def score(self, left: FingerprintFeatureVector, right: FingerprintFeatureVector) -> float:
        if self._model is None:
            raise RuntimeError("classifier is not fitted")
        probabilities = self._model.predict_proba([pair_feature_vector(left, right)])[0]
        classes = list(self._model.classes_)
        return float(probabilities[classes.index(1)]) if 1 in classes else 0.0

    def evaluate(
        self, examples: Sequence[LabeledFingerprintExample], *, threshold: float = 0.5,
    ) -> FingerprintEvaluation:
        by_id = {example.profile_id: example for example in examples}
        _features, labels, pairs = self._pairs(examples)
        predicted = [self.score(by_id[pair.left_profile_id].feature_vector, by_id[pair.right_profile_id].feature_vector) >= threshold for pair in pairs]
        tp = sum(actual and guess for actual, guess in zip(labels, predicted))
        fp = sum(not actual and guess for actual, guess in zip(labels, predicted))
        fn = sum(actual and not guess for actual, guess in zip(labels, predicted))
        tn = sum(not actual and not guess for actual, guess in zip(labels, predicted))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        return FingerprintEvaluation(
            threshold, tp, fp, fn, tn, precision, recall,
            2 * precision * recall / (precision + recall) if precision + recall else 0.0,
            fp / (fp + tn) if fp + tn else 0.0,
            fn / (fn + tp) if fn + tp else 0.0,
        )

    def save(self, directory: Path | str) -> Dict[str, Path]:
        if self._model is None or self._feature_columns is None or not self.dataset_version:
            raise RuntimeError("classifier is not fitted")
        try:
            import joblib
        except ImportError as error:  # pragma: no cover
            raise RuntimeError("Phase 1 artifact persistence requires joblib") from error
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        model_path = target / f"{self.model_version}.joblib"
        metadata_path = target / f"{self.model_version}.json"
        joblib.dump(self._model, model_path)
        metadata_path.write_text(json.dumps({
            "model_version": self.model_version,
            "feature_schema_version": FINGERPRINT_FEATURE_SCHEMA_VERSION,
            "dataset_version": self.dataset_version,
            "feature_columns": self._feature_columns,
            "prediction_output_shape": [2],
        }, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return {"model": model_path, "metadata": metadata_path}

    @classmethod
    def load(
        cls, model_path: Path | str, metadata_path: Path | str, *,
        expected_dataset_version: Optional[str] = None,
    ) -> "PairwiseFingerprintClassifier":
        """Load a versioned artifact only after validating its feature contract."""
        try:
            import joblib
        except ImportError as error:  # pragma: no cover
            raise RuntimeError("Phase 1 artifact persistence requires joblib") from error
        metadata = json.loads(Path(metadata_path).read_text(encoding="utf-8"))
        feature_columns = tuple(str(value) for value in metadata.get("feature_columns", ()))
        if metadata.get("feature_schema_version") != FINGERPRINT_FEATURE_SCHEMA_VERSION:
            raise FingerprintModelCompatibilityError("fingerprint feature schema is incompatible")
        if expected_dataset_version is not None and metadata.get("dataset_version") != expected_dataset_version:
            raise FingerprintModelCompatibilityError("fingerprint dataset version is incompatible")
        if tuple(metadata.get("prediction_output_shape", ())) != (2,):
            raise FingerprintModelCompatibilityError("fingerprint output shape is incompatible")
        model = joblib.load(model_path)
        expected_width = getattr(model, "n_features_in_", None)
        if expected_width is not None and expected_width != len(feature_columns):
            raise FingerprintModelCompatibilityError("fingerprint feature width is incompatible")
        classifier = cls(model_version=str(metadata.get("model_version", "fingerprint-rf-v1")))
        classifier._model = model
        classifier._feature_columns = feature_columns
        classifier.dataset_version = str(metadata["dataset_version"])
        return classifier
