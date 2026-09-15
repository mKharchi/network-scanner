"""Phase 3: Continuous 10-minute UTC interval processing for Kismet captures.

Aligns processing strictly to 10-minute UTC clock boundaries (00:00-00:10, 00:10-00:20, ...),
producing up to 20 complete, non-overlapping 30-second windows per observed identity.
Ensures zero cross-interval window leakage, durable atomic output, idempotent retries,
and strict safety gates before marking raw captures safe for cleanup.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple

from .device_activity import (
    ACTIVITY_FEATURE_SCHEMA_VERSION,
    ACTIVITY_MODEL_VERSION,
    ActivityPrediction,
    ActivityPredictionStore,
    ActivityRandomForestClassifier,
    TemporalActivitySmoother,
    prediction_from_window,
)
from .activity_inference import ActivityInferenceService
from .kismet_ml_foundation import (
    KismetMLExtractor,
    StructuredObservation,
    TrafficWindow,
    WindowConfig,
    _as_int,
    _as_number,
    _frequency_mhz,
    _make_traffic_window,
    is_randomized_mac,
    normalize_mac,
    parse_80211_packet,
)
from .kismet_ml_pipeline import get_ml_storage_dir


INTERVAL_DURATION_SECONDS = 600       # 10 minutes
WINDOW_DURATION_SECONDS = 30          # 30 seconds
SLOTS_PER_INTERVAL = 20               # 600 / 30 = 20


@dataclass(frozen=True)
class IntervalBounds:
    """UTC wall-clock-aligned 10-minute interval."""

    start_epoch_ms: int
    end_epoch_ms: int
    interval_id: str
    start_utc: str
    end_utc: str
    day_utc: str

    def __post_init__(self) -> None:
        duration = self.end_epoch_ms - self.start_epoch_ms
        if duration != INTERVAL_DURATION_SECONDS * 1000:
            raise ValueError(f"interval duration must be exactly {INTERVAL_DURATION_SECONDS}s, got {duration/1000}s")
        if self.start_epoch_ms % (INTERVAL_DURATION_SECONDS * 1000) != 0:
            raise ValueError(f"interval start must align to {INTERVAL_DURATION_SECONDS}s clock boundary")

    @classmethod
    def from_epoch_ms(cls, epoch_ms: int) -> IntervalBounds:
        interval_ms = INTERVAL_DURATION_SECONDS * 1000
        start_ms = (epoch_ms // interval_ms) * interval_ms
        end_ms = start_ms + interval_ms
        start_dt = datetime.fromtimestamp(start_ms / 1000, timezone.utc)
        end_dt = datetime.fromtimestamp(end_ms / 1000, timezone.utc)
        start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_iso = end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        interval_id = f"{start_iso}_{end_iso}"
        day_utc = start_dt.strftime("%Y-%m-%d")
        return cls(start_ms, end_ms, interval_id, start_iso, end_iso, day_utc)

    @classmethod
    def from_iso(cls, iso_str: str) -> IntervalBounds:
        clean = iso_str.strip()
        if clean.endswith("Z"):
            clean = clean[:-1] + "+00:00"
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return cls.from_epoch_ms(int(dt.timestamp() * 1000))

    @classmethod
    def from_interval_id(cls, interval_id: str) -> IntervalBounds:
        parts = interval_id.strip().split("_")
        if len(parts) != 2:
            raise ValueError(f"invalid interval_id format: '{interval_id}', expected '<START_ISO>_<END_ISO>'")
        start_bounds = cls.from_iso(parts[0])
        if start_bounds.interval_id != interval_id:
            raise ValueError(f"interval_id '{interval_id}' does not match aligned bounds '{start_bounds.interval_id}'")
        return start_bounds

    @classmethod
    def previous_completed(cls, now_ms: Optional[int] = None, margin_seconds: int = 60) -> IntervalBounds:
        """Return the most recently closed 10-minute interval before (now - margin)."""
        current_ms = int(time.time() * 1000) if now_ms is None else now_ms
        target_ms = current_ms - (margin_seconds * 1000)
        interval_ms = INTERVAL_DURATION_SECONDS * 1000
        # Snap to end of previous interval
        end_ms = (target_ms // interval_ms) * interval_ms
        return cls.from_epoch_ms(end_ms - interval_ms)

    def window_slots(self) -> List[Tuple[int, int, int]]:
        """Return the 20 complete, non-overlapping (index, start_ms, end_ms) window slots."""
        slots = []
        slot_len_ms = WINDOW_DURATION_SECONDS * 1000
        for i in range(SLOTS_PER_INTERVAL):
            s_start = self.start_epoch_ms + i * slot_len_ms
            s_end = s_start + slot_len_ms
            slots.append((i, s_start, s_end))
        return slots


@dataclass(frozen=True)
class IntervalPredictionRecord:
    interval_id: str
    interval_start_utc: str
    interval_end_utc: str
    window_id: str
    window_index: int
    window_start_utc: str
    window_end_utc: str
    window_start_ms: int
    window_end_ms: int
    observed_mac: str
    is_randomized_mac: bool
    activity: str
    confidence: float
    probabilities: Dict[str, float]
    status: str
    status_detail: Optional[str]
    model_version: str
    feature_schema_version: str
    source_captures: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class IntervalManifest:
    interval_id: str
    interval_start_utc: str
    interval_end_utc: str
    day_utc: str
    status: str                         # "COMPLETED", "FAILED", "EMPTY"
    status_detail: Optional[str]
    source_captures: List[Dict[str, Any]]
    source_observation_count: int
    window_count: int
    prediction_count: int
    unique_devices_count: int
    observed_macs: List[str]
    model_version: str
    feature_schema_version: str
    predictions_file: str
    predictions_sha256: str
    safe_for_raw_cleanup: bool
    completed_at_utc: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class KismetIntervalProcessor:
    """Manages interval extraction, inference, atomic output, and manifest creation."""

    def __init__(
        self,
        capture_dirs: Optional[Sequence[Path | str]] = None,
        *,
        storage_dir: Path | str | None = None,
        model_dir: Path | str | None = None,
        model_version: str = ACTIVITY_MODEL_VERSION,
        active_capture_margin_seconds: int = 120,
    ) -> None:
        self.storage_dir = Path(storage_dir or get_ml_storage_dir()).resolve()
        self.intervals_dir = self.storage_dir / "intervals"
        self.intervals_dir.mkdir(parents=True, exist_ok=True)
        self.model_version = model_version
        self.model_dir = Path(model_dir) if model_dir else (self.storage_dir / "activity_models" / self.model_version)
        self.active_margin_seconds = active_capture_margin_seconds

        from .kismet_paths import get_capture_dirs

        self.capture_dirs = get_capture_dirs(capture_dirs)

        self.prediction_store = ActivityPredictionStore(self.storage_dir / "activity_predictions.sqlite")
        self.inference_service = ActivityInferenceService(
            model_dir=self.model_dir,
            model_version=self.model_version,
            storage_dir=self.storage_dir,
        )

    def find_all_capture_files(self) -> List[Path]:
        files: List[Path] = []
        for directory in self.capture_dirs:
            try:
                if directory.is_file() and directory.suffix == ".kismet":
                    files.append(directory)
                elif directory.is_dir():
                    files.extend(path for path in directory.glob("*.kismet") if path.is_file())
            except OSError:
                continue
        # Deduplicate by resolved path and sort newest first
        unique = {p.resolve(): p for p in files}
        return sorted(unique.values(), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)

    def is_capture_active(self, path: Path) -> bool:
        """Check if a capture file has active journal sidecars or recent writes."""
        if not path.exists():
            return False
        # Check SQLite journal/wal sidecars
        wal = path.with_name(path.name + "-wal")
        journal = path.with_name(path.name + "-journal")
        if wal.exists() or journal.exists():
            return True
        try:
            mtime = path.stat().st_mtime
            if (time.time() - mtime) < self.active_margin_seconds:
                return True
        except OSError:
            return True
        return False

    def find_captures_for_interval(self, interval: IntervalBounds) -> List[Path]:
        """Find capture files that overlap the interval time range."""
        start_sec = interval.start_epoch_ms // 1000
        end_sec = interval.end_epoch_ms // 1000
        matching = []
        for capture in self.find_all_capture_files():
            try:
                con = sqlite3.connect(f"file:{capture}?mode=ro", uri=True)
                try:
                    # Quick range check on packets
                    row = con.execute("SELECT min(ts_sec), max(ts_sec) FROM packets").fetchone()
                    if row and row[0] is not None and row[1] is not None:
                        file_min_sec, file_max_sec = int(row[0]), int(row[1])
                        # Overlaps if not (file_max < start or file_min > end)
                        if not (file_max_sec < start_sec or file_min_sec >= end_sec):
                            matching.append(capture)
                finally:
                    con.close()
            except (sqlite3.DatabaseError, OSError):
                continue
        return matching

    def extract_interval_observations(
        self, capture_file: Path, interval: IntervalBounds,
    ) -> Tuple[List[StructuredObservation], int]:
        """Stream observations from one capture file strictly within the interval bounds."""
        start_sec = interval.start_epoch_ms // 1000
        end_sec = interval.end_epoch_ms // 1000
        observations: List[StructuredObservation] = []
        raw_packet_count = 0

        con: Optional[sqlite3.Connection] = None
        try:
            con = sqlite3.connect(f"file:{capture_file}?mode=ro", uri=True)
            con.row_factory = sqlite3.Row
            cursor = con.execute(
                "SELECT rowid AS _kismet_rowid, ts_sec, ts_usec, sourcemac, destmac, transmac, "
                "frequency, signal, packet_len, dlt, packet "
                "FROM packets WHERE ts_sec >= ? AND ts_sec <= ? ORDER BY ts_sec ASC, ts_usec ASC",
                (start_sec, end_sec),
            )
            for row in cursor:
                raw_packet_count += 1
                try:
                    epoch_ms = int(row["ts_sec"]) * 1000 + int((row["ts_usec"] or 0) / 1000)
                except (TypeError, ValueError):
                    continue
                # Strict interval boundary check
                if not (interval.start_epoch_ms <= epoch_ms < interval.end_epoch_ms):
                    continue

                parsed = parse_80211_packet(
                    row["packet"], dlt=row["dlt"], source_mac=row["sourcemac"],
                    destination_mac=row["destmac"], transmitter_mac=row["transmac"],
                )
                if not parsed:
                    continue

                packet_hash = hashlib.sha256(bytes(row["packet"])).hexdigest()
                identity = f"{capture_file.name}|{row['_kismet_rowid']}|{epoch_ms}|{packet_hash}"
                obs_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]

                observations.append(StructuredObservation(
                    observation_id=obs_id,
                    timestamp_epoch_ms=epoch_ms,
                    source_mac=parsed["source_mac"],
                    destination_mac=parsed["destination_mac"],
                    transmitter_mac=parsed["transmitter_mac"],
                    bssid=parsed["bssid"],
                    frame_type=parsed["frame_type"],
                    frame_subtype=parsed["frame_subtype"],
                    frame_length=_as_int(row["packet_len"]),
                    signal_dbm=_as_number(row["signal"]),
                    frequency_mhz=_frequency_mhz(row["frequency"]),
                    sequence_number=parsed["sequence_number"],
                    to_ds=parsed["to_ds"],
                    from_ds=parsed["from_ds"],
                    retry=parsed["retry"],
                    power_management=parsed["power_management"],
                    ie_tag_sequence=tuple(parsed["tags"]),
                    ie_vendor_ouis=tuple(parsed["vendor_ouis"]),
                    ht_capabilities_hex=parsed["ht"],
                    vht_capabilities_hex=parsed["vht"],
                    he_capabilities_hex=parsed["he"],
                    wmm_capabilities_present=parsed["wmm"],
                    capture_file=capture_file.name,
                ))
        except (sqlite3.DatabaseError, OSError):
            pass
        finally:
            if con is not None:
                con.close()
        return observations, raw_packet_count

    def build_interval_windows(
        self, observations: Sequence[StructuredObservation], interval: IntervalBounds,
    ) -> List[Tuple[int, TrafficWindow]]:
        """Construct deterministic 30s windows aligned strictly to the 20 interval slots."""
        config = WindowConfig(length_seconds=WINDOW_DURATION_SECONDS, hop_seconds=WINDOW_DURATION_SECONDS)
        slots = interval.window_slots()

        # Discover all observed MAC identities
        observed_identities = set()
        for obs in observations:
            for m in (obs.source_mac, obs.destination_mac, obs.transmitter_mac):
                norm = normalize_mac(m)
                if norm:
                    observed_identities.add(norm)

        windows: List[Tuple[int, TrafficWindow]] = []
        for identity in sorted(observed_identities):
            id_obs = [
                obs for obs in observations
                if identity in {obs.source_mac, obs.destination_mac, obs.transmitter_mac}
            ]
            for slot_idx, slot_start, slot_end in slots:
                slot_members = [
                    obs for obs in id_obs if slot_start <= obs.timestamp_epoch_ms < slot_end
                ]
                if slot_members:
                    tw = _make_traffic_window(identity, slot_start, slot_end, slot_members, config)
                    windows.append((slot_idx, tw))
        return windows

    def manifest_path(self, interval: IntervalBounds) -> Path:
        day_dir = self.intervals_dir / interval.day_utc
        day_dir.mkdir(parents=True, exist_ok=True)
        return day_dir / f"{interval.interval_id}.manifest.json"

    def predictions_path(self, interval: IntervalBounds) -> Path:
        day_dir = self.intervals_dir / interval.day_utc
        day_dir.mkdir(parents=True, exist_ok=True)
        return day_dir / f"{interval.interval_id}.predictions.jsonl"

    def get_manifest(self, interval: IntervalBounds) -> Optional[IntervalManifest]:
        mpath = self.manifest_path(interval)
        if not mpath.exists():
            return None
        try:
            data = json.loads(mpath.read_text(encoding="utf-8"))
            return IntervalManifest(**data)
        except (json.JSONDecodeError, TypeError, OSError):
            return None

    def process_interval(self, interval: IntervalBounds, *, force: bool = False) -> IntervalManifest:
        """Process one 10-minute interval with atomic outputs and idempotent retries."""
        existing = self.get_manifest(interval)
        if existing and existing.status == "COMPLETED" and not force:
            return existing

        captures = self.find_captures_for_interval(interval)
        has_active = any(self.is_capture_active(c) for c in captures)

        all_observations: List[StructuredObservation] = []
        capture_records = []
        for c in captures:
            obs, raw_count = self.extract_interval_observations(c, interval)
            all_observations.extend(obs)
            capture_records.append({
                "capture_file": c.name,
                "path": str(c),
                "is_active": self.is_capture_active(c),
                "packets_in_interval": raw_count,
                "observations_extracted": len(obs),
            })

        # Build 30-second windows
        slotted_windows = self.build_interval_windows(all_observations, interval)

        # Load classifier
        classifier, err = self.inference_service._load_classifier()
        if classifier is None:
            manifest = IntervalManifest(
                interval_id=interval.interval_id,
                interval_start_utc=interval.start_utc,
                interval_end_utc=interval.end_utc,
                day_utc=interval.day_utc,
                status="FAILED",
                status_detail=f"model load failed: {err}",
                source_captures=capture_records,
                source_observation_count=len(all_observations),
                window_count=len(slotted_windows),
                prediction_count=0,
                unique_devices_count=0,
                observed_macs=[],
                model_version=self.model_version,
                feature_schema_version=ACTIVITY_FEATURE_SCHEMA_VERSION,
                predictions_file="",
                predictions_sha256="",
                safe_for_raw_cleanup=False,
                completed_at_utc=datetime.now(timezone.utc).isoformat(),
            )
            self._write_manifest(interval, manifest)
            return manifest

        # Group windows by device for rolling smoothing
        by_device: Dict[str, List[Tuple[int, TrafficWindow]]] = {}
        for slot_idx, tw in slotted_windows:
            by_device.setdefault(tw.client_mac, []).append((slot_idx, tw))

        prediction_records: List[IntervalPredictionRecord] = []
        prediction_store_records: List[ActivityPrediction] = []

        for dev, dev_windows in by_device.items():
            # Sort chronologically by slot index
            dev_windows.sort(key=lambda item: item[0])
            smoother = TemporalActivitySmoother(history_size=3, minimum_confidence=0.55)
            for slot_idx, tw in dev_windows:
                raw = prediction_from_window(tw, classifier, device_id=dev)
                smoothed = smoother.update(raw)
                prediction_store_records.append(smoothed)

                start_dt = datetime.fromtimestamp(tw.window_start_ms / 1000, timezone.utc)
                end_dt = datetime.fromtimestamp(tw.window_end_ms / 1000, timezone.utc)
                prediction_records.append(IntervalPredictionRecord(
                    interval_id=interval.interval_id,
                    interval_start_utc=interval.start_utc,
                    interval_end_utc=interval.end_utc,
                    window_id=tw.window_id,
                    window_index=slot_idx,
                    window_start_utc=start_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    window_end_utc=end_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    window_start_ms=tw.window_start_ms,
                    window_end_ms=tw.window_end_ms,
                    observed_mac=dev,
                    is_randomized_mac=is_randomized_mac(dev),
                    activity=smoothed.activity,
                    confidence=round(float(smoothed.confidence), 6),
                    probabilities={k: round(float(v), 6) for k, v in smoothed.probabilities.items()},
                    status=smoothed.status,
                    status_detail=smoothed.status_detail,
                    model_version=smoothed.model_version,
                    feature_schema_version=ACTIVITY_FEATURE_SCHEMA_VERSION,
                    source_captures=[c.name for c in captures],
                ))

        # 1. Write atomic JSONL predictions
        pred_file = self.predictions_path(interval)
        pred_tmp = pred_file.with_suffix(".jsonl.tmp")
        hasher = hashlib.sha256()
        with pred_tmp.open("w", encoding="utf-8") as handle:
            for prec in prediction_records:
                line = json.dumps(prec.to_dict(), sort_keys=True, separators=(",", ":"))
                handle.write(line + "\n")
                hasher.update((line + "\n").encode("utf-8"))
        pred_tmp.replace(pred_file)
        predictions_sha256 = hasher.hexdigest()

        # 2. Persist to SQLite ActivityPredictionStore idempotently
        if prediction_store_records:
            self.prediction_store.persist_batch(prediction_store_records)

        # 3. Determine completion and raw cleanup safety
        status = "COMPLETED"
        # Raw cleanup is allowed only when processing succeeded AND no active journal/capture exists
        safe_cleanup = (status == "COMPLETED") and (not has_active) and (len(captures) > 0)

        unique_macs = sorted(by_device.keys())
        manifest = IntervalManifest(
            interval_id=interval.interval_id,
            interval_start_utc=interval.start_utc,
            interval_end_utc=interval.end_utc,
            day_utc=interval.day_utc,
            status=status,
            status_detail=None,
            source_captures=capture_records,
            source_observation_count=len(all_observations),
            window_count=len(slotted_windows),
            prediction_count=len(prediction_records),
            unique_devices_count=len(unique_macs),
            observed_macs=unique_macs,
            model_version=self.model_version,
            feature_schema_version=ACTIVITY_FEATURE_SCHEMA_VERSION,
            predictions_file=str(pred_file.relative_to(self.storage_dir)),
            predictions_sha256=predictions_sha256,
            safe_for_raw_cleanup=safe_cleanup,
            completed_at_utc=datetime.now(timezone.utc).isoformat(),
        )
        self._write_manifest(interval, manifest)
        return manifest

    def _write_manifest(self, interval: IntervalBounds, manifest: IntervalManifest) -> None:
        mpath = self.manifest_path(interval)
        mtmp = mpath.with_suffix(".json.tmp")
        mtmp.write_text(json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        mtmp.replace(mpath)

    def retry_interval(self, interval_id: str) -> IntervalManifest:
        """Force retry of a failed or partial interval without duplicate predictions."""
        interval = IntervalBounds.from_interval_id(interval_id)
        return self.process_interval(interval, force=True)

    def list_intervals(self, date: Optional[str] = None, limit: int = 50) -> List[IntervalManifest]:
        """List stored interval manifests, optionally filtered by UTC day."""
        manifests = []
        if date:
            target_days = [self.intervals_dir / date]
        else:
            target_days = sorted(self.intervals_dir.glob("????-??-??"), reverse=True)

        for day_dir in target_days:
            if not day_dir.is_dir():
                continue
            for mpath in sorted(day_dir.glob("*.manifest.json"), reverse=True):
                try:
                    data = json.loads(mpath.read_text(encoding="utf-8"))
                    manifests.append(IntervalManifest(**data))
                    if len(manifests) >= limit:
                        return manifests
                except (json.JSONDecodeError, TypeError, OSError):
                    continue
        return manifests

    def finalize_day(self, date: str) -> Dict[str, Any]:
        """Verify that all intervals for a UTC day are completed and durable for Phase 4."""
        day_dir = self.intervals_dir / date
        if not day_dir.exists():
            return {"date": date, "status": "no_data", "completed_intervals": 0, "total_predictions": 0}

        manifest_files = sorted(day_dir.glob("*.manifest.json"))
        completed = []
        failed = []
        total_predictions = 0
        total_windows = 0
        device_set = set()

        for mf in manifest_files:
            try:
                m = IntervalManifest(**json.loads(mf.read_text(encoding="utf-8")))
                if m.status == "COMPLETED":
                    completed.append(m)
                    total_predictions += m.prediction_count
                    total_windows += m.window_count
                    device_set.update(m.observed_macs)
                else:
                    failed.append(m)
            except Exception:
                pass

        summary = {
            "date": date,
            "status": "ready_for_daily_summary" if (completed and not failed) else ("partial" if completed else "empty"),
            "completed_intervals_count": len(completed),
            "failed_intervals_count": len(failed),
            "total_windows": total_windows,
            "total_predictions": total_predictions,
            "unique_observed_identities": len(device_set),
            "manifest_hashes": [m.predictions_sha256 for m in completed],
            "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        (day_dir / "day_finalization.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8",
        )
        return summary
