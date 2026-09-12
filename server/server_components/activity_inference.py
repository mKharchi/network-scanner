"""Runtime activity inference over derived traffic windows only.

This service deliberately has no packet-capture access.  It loads a validated
versioned artifact, reads normalized ``traffic_windows`` records, smooths
probabilities per device, and persists only the resulting prediction metadata.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from .device_activity import (
    ACTIVITY_MODEL_VERSION,
    ActivityModelCompatibilityError,
    ActivityPredictionStore,
    ActivityRandomForestClassifier,
    TemporalActivitySmoother,
    prediction_from_window,
)
from .kismet_ml_foundation import normalize_mac
from .kismet_ml_pipeline import KismetMLDerivedStore, get_ml_storage_dir


class ActivityInferenceService:
    """Load one production candidate and infer from recent derived windows."""

    def __init__(
        self,
        *,
        model_dir: Path | str | None = None,
        dataset_version: str = "vnat-v1",
        storage_dir: Path | str | None = None,
        confidence_threshold: float = 0.55,
        history_size: int = 3,
    ) -> None:
        storage = Path(storage_dir or get_ml_storage_dir())
        self.model_dir = Path(model_dir or os.getenv(
            "KISMET_ACTIVITY_MODEL_DIR",
            str(storage / "activity_models" / ACTIVITY_MODEL_VERSION),
        ))
        self.dataset_version = dataset_version
        self.store = KismetMLDerivedStore(storage)
        self.prediction_store = ActivityPredictionStore(storage / "activity_predictions.sqlite")
        self.history_size = history_size
        self.confidence_threshold = confidence_threshold
        self._classifier: Optional[ActivityRandomForestClassifier] = None
        self._load_status: Optional[tuple[str, Optional[str]]] = None

    def _load_classifier(self) -> tuple[Optional[ActivityRandomForestClassifier], Optional[str]]:
        if self._classifier is not None:
            return self._classifier, None
        if self._load_status is not None:
            status, detail = self._load_status
            return None, detail if status != "ok" else None
        model_path = self.model_dir / f"{ACTIVITY_MODEL_VERSION}.joblib"
        metadata_path = self.model_dir / f"{ACTIVITY_MODEL_VERSION}.json"
        if not model_path.is_file() or not metadata_path.is_file():
            detail = f"activity artifact is unavailable at {self.model_dir}"
            self._load_status = ("model_unavailable", detail)
            return None, detail
        try:
            self._classifier = ActivityRandomForestClassifier.load(
                model_path, metadata_path, expected_dataset_version=self.dataset_version,
            )
        except (OSError, ValueError, RuntimeError, ActivityModelCompatibilityError) as error:
            detail = str(error)
            self._load_status = ("model_incompatible", detail)
            return None, detail
        self._load_status = ("ok", None)
        return self._classifier, None

    @staticmethod
    def _same_device(window: Mapping[str, Any], device_id: str, client_mac: Optional[str]) -> bool:
        candidate = str(window.get("client_mac") or "")
        if client_mac:
            return normalize_mac(candidate) == client_mac
        return candidate == device_id

    @staticmethod
    def _serialize(prediction: Any) -> Dict[str, Any]:
        return {
            "window_id": prediction.window_id,
            "window_start": datetime.fromtimestamp(prediction.window_start_ms / 1000, timezone.utc).isoformat(),
            "window_end": datetime.fromtimestamp(prediction.window_end_ms / 1000, timezone.utc).isoformat(),
            "activity": prediction.activity,
            "confidence": round(float(prediction.confidence), 6),
            "probabilities": {key: round(float(value), 6) for key, value in prediction.probabilities.items()},
            "model_version": prediction.model_version,
        }

    def predict_device(
        self,
        device_id: str,
        *,
        client_mac: Optional[str] = None,
        lookback_minutes: int = 15,
        limit: int = 20,
    ) -> Dict[str, Any]:
        classifier, detail = self._load_classifier()
        if classifier is None:
            status = self._load_status[0] if self._load_status else "model_unavailable"
            return {"device_id": device_id, "current": None, "recent": [], "status": status, "detail": detail}
        now_ms = int(time.time() * 1000)
        cutoff_ms = now_ms - max(1, min(24 * 60, lookback_minutes)) * 60 * 1000
        windows = [
            row for row in self.store.load_all("traffic_windows")
            if self._same_device(row, device_id, client_mac)
            and int(row.get("window_end_ms") or 0) >= cutoff_ms
        ]
        windows.sort(key=lambda row: (int(row.get("window_start_ms") or 0), str(row.get("window_id") or "")))
        if not windows:
            return {"device_id": device_id, "current": None, "recent": [], "status": "no_recent_window"}
        # Rebuild the short history from the bounded query on every request.
        # This keeps repeated reads idempotent instead of smoothing the same
        # window again merely because a UI refreshed.
        smoother = TemporalActivitySmoother(
            history_size=self.history_size, minimum_confidence=self.confidence_threshold,
        )
        predictions = []
        for window in windows[-max(1, min(limit, 100)):]:
            raw = prediction_from_window(window, classifier, device_id=device_id)
            smoothed = smoother.update(raw)
            self.prediction_store.persist(smoothed)
            predictions.append(self._serialize(smoothed))
        current = predictions[-1]
        status = "low_confidence" if current["activity"] == "unknown" else "ok"
        return {"device_id": device_id, "current": current, "recent": list(reversed(predictions)), "status": status}
