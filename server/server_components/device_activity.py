"""Phase 2 device-activity features, supervised models, and smoothing.

Activity inference consumes Phase 0 ``TrafficWindow`` records only.  The
client MAC is retained for grouping and provenance, never as a predictive
feature.  Training requires explicit window labels; ambient traffic is never
silently converted into an activity class.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .kismet_ml_foundation import TrafficWindow, group_aware_split, normalize_mac

ACTIVITY_FEATURE_SCHEMA_VERSION = "activity-features-v1"
ACTIVITY_MODEL_VERSION = "activity-rf-v1"
ACTIVITY_LABEL_ORDER = ("idle", "browsing", "streaming", "file_transfer", "other")
_DERIVED_FEATURE_NAMES = (
    "packet_rate", "byte_rate", "mean_packet_size", "median_packet_size",
    "packet_size_std", "mean_interarrival_ms", "median_interarrival_ms",
    "interarrival_std_ms", "uplink_ratio", "downlink_ratio", "burst_rate",
    "burst_duration_ms", "periodicity_score",
)


def _finite(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _window_value(window: TrafficWindow | Mapping[str, Any], name: str) -> Any:
    if isinstance(window, Mapping):
        return window.get(name)
    return getattr(window, name)


def _derived(window: TrafficWindow | Mapping[str, Any]) -> Mapping[str, Any]:
    value = _window_value(window, "derived_features_json")
    return value if isinstance(value, Mapping) else {}


def _window_features(window: TrafficWindow | Mapping[str, Any]) -> Dict[str, float]:
    """Create fixed numeric features without using the client MAC."""
    values: Dict[str, float] = {}
    count = float(_window_value(window, "total_frame_count") or 0)
    total_bytes = float(_window_value(window, "total_byte_count") or 0)
    duration_ms = max(1.0, float((_window_value(window, "window_end_ms") or 0) - (_window_value(window, "window_start_ms") or 0)))
    duration_seconds = duration_ms / 1000.0
    values.update({
        "packet_count": count,
        "byte_count": total_bytes,
        "packet_rate": count / duration_seconds,
        "byte_rate": total_bytes / duration_seconds,
        "uplink_packet_count": float(_window_value(window, "uplink_frame_count") or 0),
        "downlink_packet_count": float(_window_value(window, "downlink_frame_count") or 0),
        "uplink_byte_count": float(_window_value(window, "uplink_byte_count") or 0),
        "downlink_byte_count": float(_window_value(window, "downlink_byte_count") or 0),
        "retry_packet_count": float(_window_value(window, "retry_frame_count") or 0),
        "data_packet_count": float(_window_value(window, "data_frame_count") or 0),
        "management_packet_count": float(_window_value(window, "mgmt_frame_count") or 0),
        "control_packet_count": float(_window_value(window, "ctrl_frame_count") or 0),
    })
    values["uplink_packet_ratio"] = values["uplink_packet_count"] / count if count else 0.0
    values["downlink_packet_ratio"] = values["downlink_packet_count"] / count if count else 0.0
    values["retry_packet_ratio"] = values["retry_packet_count"] / count if count else 0.0
    for name in _DERIVED_FEATURE_NAMES:
        raw = _derived(window).get(name)
        if raw is None:
            raw = _derived(window).get(f"kismet-ml-v1.{name}")
        number = _finite(raw)
        values[f"derived_{name}"] = number if number is not None else 0.0
        values[f"missing_derived_{name}"] = 0.0 if number is not None else 1.0
    return values


@dataclass(frozen=True)
class ActivityFeatureVector:
    feature_schema_version: str
    source_window_id: str
    feature_values: Dict[str, float]


def activity_feature_vector(window: TrafficWindow | Mapping[str, Any]) -> ActivityFeatureVector:
    window_id = str(_window_value(window, "window_id"))
    return ActivityFeatureVector(ACTIVITY_FEATURE_SCHEMA_VERSION, window_id, _window_features(window))


@dataclass(frozen=True)
class ActivityLabeledWindow:
    window_id: str
    client_mac: str
    capture_session: str
    capture_day: str
    label: str
    feature_vector: ActivityFeatureVector
    probabilities: Dict[str, float]

    @property
    def split_group(self) -> str:
        # MAC is grouping/provenance only, never a model feature.
        return f"{self.client_mac}|{self.capture_session}|{self.capture_day}"


def load_labeled_activity_windows(
    windows: Iterable[TrafficWindow | Mapping[str, Any]],
    labels: Iterable[Mapping[str, Any]],
) -> List[ActivityLabeledWindow]:
    """Join explicit activity labels to windows, rejecting unlabeled records."""
    by_window = {str(_window_value(window, "window_id")): window for window in windows}
    result: List[ActivityLabeledWindow] = []
    for label_row in labels:
        if str(label_row.get("label_family", "activity")) != "activity":
            continue
        window_id = str(label_row.get("target_id", label_row.get("window_id", "")))
        window = by_window.get(window_id)
        label = label_row.get("label")
        if window is None or not label:
            continue
        if label not in ACTIVITY_LABEL_ORDER:
            raise ValueError(
                f"activity label '{label}' is outside the initial Plan 2 taxonomy "
                f"{ACTIVITY_LABEL_ORDER}"
            )
        start_ms = int(_window_value(window, "window_start_ms") or 0)
        capture_day = datetime.fromtimestamp(start_ms / 1000.0, timezone.utc).date().isoformat()
        probabilities = {str(key): float(value) for key, value in (label_row.get("probabilities") or {}).items()}
        if probabilities:
            if set(probabilities) - set(ACTIVITY_LABEL_ORDER) or any(not 0.0 <= value <= 1.0 for value in probabilities.values()):
                raise ValueError(f"invalid activity probabilities for window {window_id}")
            if not math.isclose(sum(probabilities.values()), 1.0, abs_tol=1e-6):
                raise ValueError(f"activity probabilities for window {window_id} must sum to one")
        capture_session = label_row.get("capture_session") or label_row.get("session_id")
        if not capture_session:
            raise ValueError(f"activity label {window_id} is missing capture_session")
        result.append(ActivityLabeledWindow(
            window_id=window_id,
            client_mac=str(_window_value(window, "client_mac") or "unknown"),
            capture_session=str(capture_session),
            capture_day=capture_day,
            label=str(label),
            feature_vector=activity_feature_vector(window),
            probabilities=probabilities,
        ))
    return result


def _epoch_ms(value: Any) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def label_windows_from_sessions(
    windows: Iterable[TrafficWindow | Mapping[str, Any]],
    sessions: Iterable[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Expand labelled activity intervals into window-level JSONL labels.

    A window is labelled only when it is fully contained in one explicit
    session interval for the same client. Boundary-overlapping windows are
    excluded so a label cannot bleed between adjacent experiments.
    """
    window_rows = list(windows)
    session_rows = []
    for session in sessions:
        client_mac = normalize_mac(session.get("client_mac"))
        if not client_mac:
            raise ValueError("activity session is missing a valid client_mac")
        label = str(session.get("label", ""))
        if label not in ACTIVITY_LABEL_ORDER:
            raise ValueError(f"activity session has unsupported label: {label}")
        session_id = str(session.get("capture_session") or session.get("session_id") or "")
        if not session_id:
            raise ValueError("activity session is missing capture_session")
        start_ms, end_ms = _epoch_ms(session["start_utc"]), _epoch_ms(session["end_utc"])
        if end_ms <= start_ms:
            raise ValueError(f"activity session {session_id} has an invalid time range")
        session_rows.append((client_mac, start_ms, end_ms, session_id, label, str(session.get("provenance", "ground_truth"))))
    output: List[Dict[str, Any]] = []
    for window in window_rows:
        client_mac = normalize_mac(_window_value(window, "client_mac"))
        start_ms = int(_window_value(window, "window_start_ms") or 0)
        end_ms = int(_window_value(window, "window_end_ms") or 0)
        matches = [row for row in session_rows if row[0] == client_mac and start_ms >= row[1] and end_ms <= row[2]]
        if len(matches) > 1:
            raise ValueError(f"window {_window_value(window, 'window_id')} matches overlapping activity sessions")
        if not matches:
            continue
        _client, _start, _end, session_id, label, provenance = matches[0]
        output.append({
            "target_id": str(_window_value(window, "window_id")),
            "label_family": "activity",
            "label": label,
            "provenance": provenance,
            "capture_session": session_id,
        })
    return output


def split_activity_windows(
    rows: Sequence[ActivityLabeledWindow], *, validation_fraction: float = 0.2,
    test_fraction: float = 0.2,
) -> Tuple[Dict[str, List[ActivityLabeledWindow]], Dict[str, Any]]:
    """Split complete device/session/day groups, never adjacent windows."""
    wrapped = [{"row": row, "split_group": row.split_group} for row in rows]
    splits, metadata = group_aware_split(
        wrapped, group_field="split_group", validation_fraction=validation_fraction,
        test_fraction=test_fraction,
    )
    return {name: [item["row"] for item in members] for name, members in splits.items()}, metadata


@dataclass(frozen=True)
class ActivityEvaluation:
    accuracy: float
    macro_f1: float
    per_class: Dict[str, Dict[str, float]]
    confusion_matrix: Dict[str, Dict[str, int]]


def _evaluate_predictions(actual: Sequence[str], predicted: Sequence[str]) -> ActivityEvaluation:
    labels = tuple(ACTIVITY_LABEL_ORDER)
    matrix = {label: {other: 0 for other in labels} for label in labels}
    for truth, guess in zip(actual, predicted):
        matrix.setdefault(truth, {other: 0 for other in labels})
        matrix[truth].setdefault(guess, 0)
        matrix[truth][guess] += 1
    per_class: Dict[str, Dict[str, float]] = {}
    f1_values: List[float] = []
    for label in labels:
        tp = matrix.get(label, {}).get(label, 0)
        fp = sum(matrix.get(other, {}).get(label, 0) for other in labels if other != label)
        fn = sum(matrix.get(label, {}).get(other, 0) for other in labels if other != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[label] = {"precision": precision, "recall": recall, "f1": f1, "support": float(tp + fn)}
        if tp + fn:
            f1_values.append(f1)
    return ActivityEvaluation(
        accuracy=sum(truth == guess for truth, guess in zip(actual, predicted)) / len(actual) if actual else 0.0,
        macro_f1=sum(f1_values) / len(f1_values) if f1_values else 0.0,
        per_class=per_class,
        confusion_matrix=matrix,
    )


class ActivityMajorityBaseline:
    """Deterministic majority-class baseline for honest comparison."""

    def __init__(self) -> None:
        self.label: Optional[str] = None
        self.probabilities: Dict[str, float] = {}

    def fit(self, rows: Sequence[ActivityLabeledWindow]) -> "ActivityMajorityBaseline":
        if not rows:
            raise ValueError("baseline requires labelled activity windows")
        counts = Counter(row.label for row in rows)
        self.label = sorted(counts, key=lambda label: (-counts[label], label))[0]
        total = sum(counts.values())
        self.probabilities = {label: counts[label] / total for label in ACTIVITY_LABEL_ORDER}
        return self

    def predict(self, _vector: ActivityFeatureVector) -> Tuple[str, Dict[str, float]]:
        if self.label is None:
            raise RuntimeError("baseline is not fitted")
        return self.label, dict(self.probabilities)

    def evaluate(self, rows: Sequence[ActivityLabeledWindow]) -> ActivityEvaluation:
        return _evaluate_predictions([row.label for row in rows], [self.predict(row.feature_vector)[0] for row in rows])


class ActivityModelCompatibilityError(ValueError):
    """Raised when an activity model artifact is incompatible with current features."""


@dataclass(frozen=True)
class ActivityModelArtifactMetadata:
    model_id: str
    model_version: str
    feature_schema_version: str
    dataset_version: str
    feature_columns: Tuple[str, ...]
    label_order: Tuple[str, ...]
    prediction_output_shape: Tuple[int, ...]


class ActivityModelRegistry:
    """Small in-process registry gate for activity artifacts."""

    def __init__(self) -> None:
        self._models: Dict[str, ActivityModelArtifactMetadata] = {}

    def register(self, artifact: ActivityModelArtifactMetadata, *, expected_dataset_version: str, expected_feature_columns: Sequence[str]) -> None:
        if artifact.feature_schema_version != ACTIVITY_FEATURE_SCHEMA_VERSION:
            raise ActivityModelCompatibilityError("activity feature schema is incompatible")
        if artifact.dataset_version != expected_dataset_version:
            raise ActivityModelCompatibilityError("activity dataset version is incompatible")
        if tuple(artifact.feature_columns) != tuple(expected_feature_columns):
            raise ActivityModelCompatibilityError("activity feature columns are incompatible")
        if artifact.label_order != ACTIVITY_LABEL_ORDER or artifact.prediction_output_shape != (len(ACTIVITY_LABEL_ORDER),):
            raise ActivityModelCompatibilityError("activity label/output schema is incompatible")
        self._models[artifact.model_id] = artifact

    def get(self, model_id: str) -> ActivityModelArtifactMetadata:
        return self._models[model_id]


class ActivityRandomForestClassifier:
    """CPU-friendly tabular activity classifier with versioned artifacts."""

    def __init__(self, *, model_version: str = ACTIVITY_MODEL_VERSION, random_state: int = 42, n_estimators: int = 160):
        self.model_version = model_version
        self.random_state = random_state
        self.n_estimators = n_estimators
        self._model = None
        self._feature_columns: Optional[Tuple[str, ...]] = None
        self.dataset_version: Optional[str] = None

    @staticmethod
    def _matrix(rows: Sequence[ActivityLabeledWindow]) -> Tuple[List[List[float]], List[str]]:
        if not rows:
            return [], []
        columns = tuple(sorted(rows[0].feature_vector.feature_values))
        return [[row.feature_vector.feature_values.get(column, 0.0) for column in columns] for row in rows], list(columns)

    def fit(self, rows: Sequence[ActivityLabeledWindow], *, dataset_version: str) -> "ActivityRandomForestClassifier":
        try:
            from sklearn.ensemble import RandomForestClassifier
        except ImportError as error:  # pragma: no cover
            raise RuntimeError("Plan 2 classifier requires scikit-learn") from error
        features, columns = self._matrix(rows)
        labels = [row.label for row in rows]
        if not features or len(set(labels)) < 2:
            raise ValueError("training requires labelled windows from at least two activity classes")
        self._model = RandomForestClassifier(
            n_estimators=self.n_estimators, random_state=self.random_state,
            class_weight="balanced", n_jobs=1, min_samples_leaf=2,
        )
        self._model.fit(features, labels)
        self._feature_columns = tuple(columns)
        self.dataset_version = dataset_version
        return self

    def predict(self, vector: ActivityFeatureVector) -> Tuple[str, Dict[str, float]]:
        if self._model is None or self._feature_columns is None:
            raise RuntimeError("activity classifier is not fitted")
        features = [[vector.feature_values.get(column, 0.0) for column in self._feature_columns]]
        probabilities_raw = self._model.predict_proba(features)[0]
        probabilities = {label: 0.0 for label in ACTIVITY_LABEL_ORDER}
        for label, probability in zip(self._model.classes_, probabilities_raw):
            probabilities[str(label)] = float(probability)
        label = max(ACTIVITY_LABEL_ORDER, key=lambda value: (probabilities[value], value))
        return label, probabilities

    def evaluate(self, rows: Sequence[ActivityLabeledWindow]) -> ActivityEvaluation:
        actual = [row.label for row in rows]
        predicted = [self.predict(row.feature_vector)[0] for row in rows]
        return _evaluate_predictions(actual, predicted)

    def save(self, directory: Path | str) -> Dict[str, Path]:
        if self._model is None or self._feature_columns is None or not self.dataset_version:
            raise RuntimeError("activity classifier is not fitted")
        try:
            import joblib
        except ImportError as error:  # pragma: no cover
            raise RuntimeError("activity artifact persistence requires joblib") from error
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        model_path = target / f"{self.model_version}.joblib"
        metadata_path = target / f"{self.model_version}.json"
        joblib.dump(self._model, model_path)
        metadata_path.write_text(json.dumps({
            "model_id": self.model_version,
            "model_version": self.model_version,
            "feature_schema_version": ACTIVITY_FEATURE_SCHEMA_VERSION,
            "dataset_version": self.dataset_version,
            "feature_columns": self._feature_columns,
            "label_order": ACTIVITY_LABEL_ORDER,
            "prediction_output_shape": [len(ACTIVITY_LABEL_ORDER)],
        }, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return {"model": model_path, "metadata": metadata_path}

    @classmethod
    def load(cls, model_path: Path | str, metadata_path: Path | str, *, expected_dataset_version: Optional[str] = None) -> "ActivityRandomForestClassifier":
        try:
            import joblib
        except ImportError as error:  # pragma: no cover
            raise RuntimeError("activity artifact persistence requires joblib") from error
        metadata = json.loads(Path(metadata_path).read_text(encoding="utf-8"))
        columns = tuple(str(value) for value in metadata.get("feature_columns", ()))
        if metadata.get("feature_schema_version") != ACTIVITY_FEATURE_SCHEMA_VERSION:
            raise ActivityModelCompatibilityError("activity feature schema is incompatible")
        if expected_dataset_version is not None and metadata.get("dataset_version") != expected_dataset_version:
            raise ActivityModelCompatibilityError("activity dataset version is incompatible")
        if tuple(metadata.get("label_order", ())) != ACTIVITY_LABEL_ORDER:
            raise ActivityModelCompatibilityError("activity label order is incompatible")
        model = joblib.load(model_path)
        if getattr(model, "n_features_in_", len(columns)) != len(columns):
            raise ActivityModelCompatibilityError("activity feature width is incompatible")
        classifier = cls(model_version=str(metadata.get("model_version", ACTIVITY_MODEL_VERSION)))
        classifier._model, classifier._feature_columns = model, columns
        classifier.dataset_version = str(metadata["dataset_version"])
        return classifier


@dataclass(frozen=True)
class ActivityPrediction:
    window_id: str
    device_id: str
    window_start_ms: int
    window_end_ms: int
    activity: str
    confidence: float
    probabilities: Dict[str, float]
    model_version: str


class TemporalActivitySmoother:
    """Separate rolling probability smoother for noisy window predictions."""

    def __init__(self, *, history_size: int = 3, minimum_confidence: float = 0.55):
        if history_size <= 0 or not 0.0 <= minimum_confidence <= 1.0:
            raise ValueError("invalid activity smoothing configuration")
        self.history_size = history_size
        self.minimum_confidence = minimum_confidence
        self._history: Dict[str, Deque[Dict[str, float]]] = defaultdict(lambda: deque(maxlen=history_size))

    def update(self, prediction: ActivityPrediction) -> ActivityPrediction:
        history = self._history[prediction.device_id]
        history.append(dict(prediction.probabilities))
        probabilities = {
            label: sum(item.get(label, 0.0) for item in history) / len(history)
            for label in ACTIVITY_LABEL_ORDER
        }
        activity = max(ACTIVITY_LABEL_ORDER, key=lambda value: (probabilities[value], value))
        confidence = probabilities[activity]
        if confidence < self.minimum_confidence:
            activity = "unknown"
        return ActivityPrediction(
            window_id=prediction.window_id, device_id=prediction.device_id,
            window_start_ms=prediction.window_start_ms, window_end_ms=prediction.window_end_ms,
            activity=activity, confidence=confidence, probabilities=probabilities,
            model_version=prediction.model_version,
        )


def prediction_from_window(
    window: TrafficWindow | Mapping[str, Any], classifier: ActivityRandomForestClassifier,
    *, device_id: Optional[str] = None,
) -> ActivityPrediction:
    label, probabilities = classifier.predict(activity_feature_vector(window))
    start_ms = int(_window_value(window, "window_start_ms") or 0)
    return ActivityPrediction(
        window_id=str(_window_value(window, "window_id")),
        device_id=device_id or str(_window_value(window, "client_mac") or "unknown"),
        window_start_ms=start_ms,
        window_end_ms=int(_window_value(window, "window_end_ms") or 0),
        activity=label, confidence=probabilities[label], probabilities=probabilities,
        model_version=classifier.model_version,
    )


class ActivityPredictionStore:
    """Derived-only SQLite storage for versioned activity predictions."""

    def __init__(self, path: Path | str):
        self.path = Path(path)

    def persist(self, prediction: ActivityPrediction) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.path)
        try:
            con.execute("""CREATE TABLE IF NOT EXISTS activity_predictions (
                window_id TEXT PRIMARY KEY, device_id TEXT NOT NULL,
                window_start_ms INTEGER NOT NULL, window_end_ms INTEGER NOT NULL,
                activity TEXT NOT NULL, confidence REAL NOT NULL,
                probabilities_json TEXT NOT NULL, model_version TEXT NOT NULL,
                persisted_at TEXT NOT NULL
            )""")
            con.execute(
                "INSERT INTO activity_predictions VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now')) "
                "ON CONFLICT(window_id) DO UPDATE SET activity=excluded.activity, confidence=excluded.confidence, "
                "probabilities_json=excluded.probabilities_json, model_version=excluded.model_version, persisted_at=excluded.persisted_at",
                (prediction.window_id, prediction.device_id, prediction.window_start_ms,
                 prediction.window_end_ms, prediction.activity, prediction.confidence,
                 json.dumps(prediction.probabilities, sort_keys=True), prediction.model_version),
            )
            con.commit()
        finally:
            con.close()
