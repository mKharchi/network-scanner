"""Phase 4: Daily activity summary generation, 7-day retention, and safe raw cleanup.

Reads verified per-window prediction JSONL files for a completed day, aggregates
per-identity statistics, merges consecutive windows into activity segments, and
writes durable summaries to the derived SQLite store. After successful summary
verification, per-window prediction files are deleted and raw Kismet captures
are eligible for deletion if all their interval manifests are marked
safe_for_raw_cleanup.

Summary generation is idempotent: re-running for the same date with the same
source manifests produces identical output.

Seven-day summary retention is enforced by a dry-run-first cleanup pass.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


SUMMARY_RETENTION_DAYS = 7


# ---------------------------------------------------------------------------
# Data contracts
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ActivitySegment:
    """One contiguous run of compatible activity windows for an identity."""
    activity: str
    start_utc: str
    end_utc: str
    start_ms: int
    end_ms: int
    duration_seconds: float
    window_count: int
    mean_confidence: float
    min_confidence: float
    max_confidence: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class IdentityDailySummary:
    """Aggregated activity statistics for one observed MAC identity over a UTC day."""
    date_utc: str
    observed_mac: str
    is_randomized_mac: bool
    first_observation_utc: str
    last_observation_utc: str
    first_observation_ms: int
    last_observation_ms: int
    total_window_count: int
    total_active_duration_seconds: float   # sum of non-unknown window durations
    unknown_duration_seconds: float         # sum of unknown-labelled window durations
    activity_durations: Dict[str, float]    # label -> total duration in seconds
    activity_counts: Dict[str, int]         # label -> window count
    mean_confidence: float
    min_confidence: float
    max_confidence: float
    low_confidence_window_count: int        # status == 'low_confidence'
    domain_shift_window_count: int          # status == 'domain_shift'
    segments: List[Dict[str, Any]]          # merged consecutive-activity segments
    source_interval_ids: List[str]
    source_manifest_hashes: List[str]       # SHA-256 of each predictions file
    model_version: str
    feature_schema_version: str
    summary_generated_at_utc: str
    idempotency_key: str                    # SHA-256 of sorted(source_manifest_hashes)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DayCompletionRecord:
    """Top-level record written after all summaries are verified for a UTC day."""
    date_utc: str
    status: str                     # 'completed', 'partial', 'empty'
    identity_count: int
    total_window_count: int
    total_active_duration_seconds: float
    unknown_duration_seconds: float
    source_interval_count: int
    source_manifest_hashes: List[str]
    idempotency_key: str
    raw_captures_eligible_for_deletion: List[str]
    per_window_files_deleted: bool
    verified_at_utc: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Summary store (SQLite)
# ---------------------------------------------------------------------------

class DailySummaryStore:
    """Derived-only SQLite store for per-identity daily activity summaries."""

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS daily_summaries (
        idempotency_key TEXT PRIMARY KEY,
        date_utc        TEXT NOT NULL,
        observed_mac    TEXT NOT NULL,
        summary_json    TEXT NOT NULL,
        created_at      TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS daily_summaries_date ON daily_summaries (date_utc);
    CREATE INDEX IF NOT EXISTS daily_summaries_mac  ON daily_summaries (observed_mac);

    CREATE TABLE IF NOT EXISTS day_completion_log (
        date_utc         TEXT PRIMARY KEY,
        completion_json  TEXT NOT NULL,
        created_at       TEXT NOT NULL
    );
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def _connect(self, read_only: bool = False) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if read_only and self.path.exists():
            con = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        else:
            con = sqlite3.connect(str(self.path))
        con.execute("PRAGMA journal_mode=WAL")
        return con

    def _ensure_schema(self, con: sqlite3.Connection) -> None:
        for stmt in self._SCHEMA.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                con.execute(stmt)
        con.commit()

    def upsert_summary(self, summary: IdentityDailySummary) -> None:
        con = self._connect()
        try:
            self._ensure_schema(con)
            con.execute(
                "INSERT INTO daily_summaries VALUES (?,?,?,?,datetime('now')) "
                "ON CONFLICT(idempotency_key) DO UPDATE SET "
                "summary_json=excluded.summary_json, created_at=excluded.created_at",
                (
                    summary.idempotency_key,
                    summary.date_utc,
                    summary.observed_mac,
                    json.dumps(summary.to_dict(), sort_keys=True),
                ),
            )
            con.commit()
        finally:
            con.close()

    def upsert_completion(self, record: DayCompletionRecord) -> None:
        con = self._connect()
        try:
            self._ensure_schema(con)
            con.execute(
                "INSERT INTO day_completion_log VALUES (?,?,datetime('now')) "
                "ON CONFLICT(date_utc) DO UPDATE SET "
                "completion_json=excluded.completion_json, created_at=excluded.created_at",
                (record.date_utc, json.dumps(record.to_dict(), sort_keys=True)),
            )
            con.commit()
        finally:
            con.close()

    def query_summaries(self, date_utc: str) -> List[IdentityDailySummary]:
        if not self.path.exists():
            return []
        con = self._connect(read_only=True)
        try:
            self._ensure_schema(con)
            rows = con.execute(
                "SELECT summary_json FROM daily_summaries WHERE date_utc=? ORDER BY observed_mac",
                (date_utc,),
            ).fetchall()
            return [IdentityDailySummary(**json.loads(r[0])) for r in rows]
        finally:
            con.close()

    def query_completion(self, date_utc: str) -> Optional[DayCompletionRecord]:
        if not self.path.exists():
            return None
        con = self._connect(read_only=True)
        try:
            self._ensure_schema(con)
            row = con.execute(
                "SELECT completion_json FROM day_completion_log WHERE date_utc=?",
                (date_utc,),
            ).fetchone()
            return DayCompletionRecord(**json.loads(row[0])) if row else None
        finally:
            con.close()

    def list_completed_dates(self) -> List[str]:
        if not self.path.exists():
            return []
        con = self._connect(read_only=True)
        try:
            self._ensure_schema(con)
            rows = con.execute(
                "SELECT DISTINCT date_utc FROM daily_summaries ORDER BY date_utc"
            ).fetchall()
            return [r[0] for r in rows]
        finally:
            con.close()

    def delete_date(self, date_utc: str) -> int:
        """Delete all summaries for a date. Returns deleted row count."""
        if not self.path.exists():
            return 0
        con = self._connect()
        try:
            self._ensure_schema(con)
            cur = con.execute(
                "DELETE FROM daily_summaries WHERE date_utc=?", (date_utc,)
            )
            con.commit()
            return cur.rowcount
        finally:
            con.close()


# ---------------------------------------------------------------------------
# Aggregation logic
# ---------------------------------------------------------------------------

def _merge_segments(windows: List[Dict[str, Any]]) -> List[ActivitySegment]:
    """Merge consecutive windows with the same activity label into segments."""
    if not windows:
        return []
    sorted_windows = sorted(windows, key=lambda w: w["window_start_ms"])
    segments: List[ActivitySegment] = []
    run: List[Dict[str, Any]] = [sorted_windows[0]]

    for w in sorted_windows[1:]:
        last = run[-1]
        same_activity = w["activity"] == last["activity"]
        # Consecutive if this window starts at or within 1ms of last window end
        contiguous = w["window_start_ms"] <= last["window_end_ms"] + 1
        if same_activity and contiguous:
            run.append(w)
        else:
            segments.append(_make_segment(run))
            run = [w]
    segments.append(_make_segment(run))
    return segments


def _make_segment(run: List[Dict[str, Any]]) -> ActivitySegment:
    confs = [w["confidence"] for w in run]
    start_ms = run[0]["window_start_ms"]
    end_ms = run[-1]["window_end_ms"]
    start_dt = datetime.fromtimestamp(start_ms / 1000, timezone.utc)
    end_dt = datetime.fromtimestamp(end_ms / 1000, timezone.utc)
    return ActivitySegment(
        activity=run[0]["activity"],
        start_utc=start_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        end_utc=end_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        start_ms=start_ms,
        end_ms=end_ms,
        duration_seconds=(end_ms - start_ms) / 1000.0,
        window_count=len(run),
        mean_confidence=round(sum(confs) / len(confs), 6),
        min_confidence=round(min(confs), 6),
        max_confidence=round(max(confs), 6),
    )


def _aggregate_identity(
    mac: str,
    date_utc: str,
    windows: List[Dict[str, Any]],
    source_interval_ids: List[str],
    source_manifest_hashes: List[str],
    model_version: str,
    feature_schema_version: str,
) -> IdentityDailySummary:
    from server_components.kismet_ml_foundation import is_randomized_mac

    sorted_windows = sorted(windows, key=lambda w: w["window_start_ms"])
    all_timestamps_ms = [w["window_start_ms"] for w in sorted_windows] + [w["window_end_ms"] for w in sorted_windows]
    first_ms = min(all_timestamps_ms)
    last_ms = max(all_timestamps_ms)

    activity_durations: Dict[str, float] = {}
    activity_counts: Dict[str, int] = {}
    confs = []
    low_conf_count = 0
    domain_shift_count = 0

    for w in sorted_windows:
        activity = w["activity"]
        status = w.get("status", "ok")
        conf = float(w["confidence"])
        dur = (w["window_end_ms"] - w["window_start_ms"]) / 1000.0
        activity_durations[activity] = activity_durations.get(activity, 0.0) + dur
        activity_counts[activity] = activity_counts.get(activity, 0) + 1
        confs.append(conf)
        if status == "low_confidence":
            low_conf_count += 1
        elif status == "domain_shift":
            domain_shift_count += 1

    unknown_dur = activity_durations.get("unknown", 0.0)
    active_dur = sum(v for k, v in activity_durations.items() if k != "unknown")
    segments = _merge_segments(sorted_windows)

    def _utc_str(ms: int) -> str:
        return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    idempotency_key = hashlib.sha256(
        json.dumps(
            {"date": date_utc, "mac": mac, "hashes": sorted(source_manifest_hashes)},
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    return IdentityDailySummary(
        date_utc=date_utc,
        observed_mac=mac,
        is_randomized_mac=is_randomized_mac(mac),
        first_observation_utc=_utc_str(first_ms),
        last_observation_utc=_utc_str(last_ms),
        first_observation_ms=first_ms,
        last_observation_ms=last_ms,
        total_window_count=len(sorted_windows),
        total_active_duration_seconds=round(active_dur, 3),
        unknown_duration_seconds=round(unknown_dur, 3),
        activity_durations={k: round(v, 3) for k, v in sorted(activity_durations.items())},
        activity_counts=dict(sorted(activity_counts.items())),
        mean_confidence=round(sum(confs) / len(confs), 6) if confs else 0.0,
        min_confidence=round(min(confs), 6) if confs else 0.0,
        max_confidence=round(max(confs), 6) if confs else 0.0,
        low_confidence_window_count=low_conf_count,
        domain_shift_window_count=domain_shift_count,
        segments=[s.to_dict() for s in segments],
        source_interval_ids=sorted(source_interval_ids),
        source_manifest_hashes=sorted(source_manifest_hashes),
        model_version=model_version,
        feature_schema_version=feature_schema_version,
        summary_generated_at_utc=datetime.now(timezone.utc).isoformat(),
        idempotency_key=idempotency_key,
    )


# ---------------------------------------------------------------------------
# Daily summarizer
# ---------------------------------------------------------------------------

class KismetDailySummarizer:
    """Reads Phase 3 prediction files for a day, produces Phase 4 daily summaries."""

    def __init__(
        self,
        storage_dir: Path | str | None = None,
        capture_dirs: Optional[Sequence[Path | str]] = None,
        *,
        summary_retention_days: int = SUMMARY_RETENTION_DAYS,
    ) -> None:
        from server_components.kismet_ml_pipeline import get_ml_storage_dir
        self.storage_dir = Path(storage_dir or get_ml_storage_dir()).resolve()
        self.intervals_dir = self.storage_dir / "intervals"
        self.summary_store = DailySummaryStore(self.storage_dir / "daily_summaries.sqlite")
        self.summary_retention_days = summary_retention_days

        configured_dirs = os.getenv("KISMET_CAPTURE_DIRS")
        if capture_dirs is not None:
            self.capture_dirs = [Path(p) for p in capture_dirs]
        elif configured_dirs:
            self.capture_dirs = [Path(p.strip()) for p in configured_dirs.split(",") if p.strip()]
        else:
            self.capture_dirs = [
                Path(os.getenv("KISMET_CAPTURE_ROOT") or os.getenv("KISMET_CAPTURE_DIR") or "~/kismet").expanduser(),
                Path("~").expanduser(),
            ]

    def _load_day_predictions(
        self, date_utc: str,
    ) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, str], List[str], str, str]:
        """Read all JSONL prediction files for a day.

        Returns:
          by_mac: mac -> list of prediction records
          manifest_hashes: interval_id -> predictions_sha256
          interval_ids: sorted list of interval IDs
          model_version: str
          feature_schema_version: str
        """
        day_dir = self.intervals_dir / date_utc
        by_mac: Dict[str, List[Dict[str, Any]]] = {}
        manifest_hashes: Dict[str, str] = {}
        model_version = "unknown"
        feature_schema_version = "unknown"

        if not day_dir.is_dir():
            return by_mac, manifest_hashes, [], model_version, feature_schema_version

        for mpath in sorted(day_dir.glob("*.manifest.json")):
            try:
                manifest = json.loads(mpath.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue

            if manifest.get("status") != "COMPLETED":
                continue

            interval_id = manifest["interval_id"]
            manifest_hashes[interval_id] = manifest.get("predictions_sha256", "")
            model_version = manifest.get("model_version", model_version)
            feature_schema_version = manifest.get("feature_schema_version", feature_schema_version)

            pred_path = day_dir / f"{interval_id}.predictions.jsonl"
            if not pred_path.exists():
                continue

            for line in pred_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                mac = record.get("observed_mac", "")
                if not mac:
                    continue
                by_mac.setdefault(mac, []).append(record)

        return (
            by_mac,
            manifest_hashes,
            sorted(manifest_hashes.keys()),
            model_version,
            feature_schema_version,
        )

    def summarize_day(
        self,
        date_utc: str,
        *,
        dry_run: bool = False,
        delete_per_window_files: bool = False,
    ) -> DayCompletionRecord:
        """Generate daily summaries for all identities seen on date_utc.

        Args:
            date_utc: UTC date string 'YYYY-MM-DD'.
            dry_run: If True, compute but do not write to SQLite or delete files.
            delete_per_window_files: If True (and not dry_run), delete prediction
                JSONL files after writing verified summaries.

        Returns:
            DayCompletionRecord with full verification details.
        """
        by_mac, manifest_hashes, interval_ids, model_version, feature_schema_version = (
            self._load_day_predictions(date_utc)
        )

        if not by_mac:
            record = DayCompletionRecord(
                date_utc=date_utc,
                status="empty",
                identity_count=0,
                total_window_count=0,
                total_active_duration_seconds=0.0,
                unknown_duration_seconds=0.0,
                source_interval_count=0,
                source_manifest_hashes=[],
                idempotency_key=hashlib.sha256(date_utc.encode()).hexdigest(),
                raw_captures_eligible_for_deletion=[],
                per_window_files_deleted=False,
                verified_at_utc=datetime.now(timezone.utc).isoformat(),
            )
            if not dry_run:
                self.summary_store.upsert_completion(record)
            return record

        hash_list = sorted(manifest_hashes.values())
        day_idempotency_key = hashlib.sha256(
            json.dumps({"date": date_utc, "hashes": hash_list}, sort_keys=True).encode()
        ).hexdigest()

        summaries: List[IdentityDailySummary] = []
        total_windows = 0
        total_active_dur = 0.0
        total_unknown_dur = 0.0

        for mac, windows in sorted(by_mac.items()):
            # Determine which intervals contributed to this identity
            mac_intervals = sorted({w.get("interval_id", "") for w in windows if w.get("interval_id")})
            mac_hashes = [manifest_hashes[i] for i in mac_intervals if i in manifest_hashes]

            summary = _aggregate_identity(
                mac=mac,
                date_utc=date_utc,
                windows=windows,
                source_interval_ids=mac_intervals,
                source_manifest_hashes=mac_hashes,
                model_version=model_version,
                feature_schema_version=feature_schema_version,
            )
            summaries.append(summary)
            total_windows += summary.total_window_count
            total_active_dur += summary.total_active_duration_seconds
            total_unknown_dur += summary.unknown_duration_seconds

            if not dry_run:
                self.summary_store.upsert_summary(summary)

        # Find raw captures eligible for deletion
        eligible_captures = self._find_eligible_captures(date_utc)

        # Delete per-window prediction files if requested and verified
        deleted_files = False
        if not dry_run and delete_per_window_files and summaries:
            deleted_files = self._delete_per_window_files(date_utc)

        record = DayCompletionRecord(
            date_utc=date_utc,
            status="completed" if summaries else "empty",
            identity_count=len(summaries),
            total_window_count=total_windows,
            total_active_duration_seconds=round(total_active_dur, 3),
            unknown_duration_seconds=round(total_unknown_dur, 3),
            source_interval_count=len(interval_ids),
            source_manifest_hashes=hash_list,
            idempotency_key=day_idempotency_key,
            raw_captures_eligible_for_deletion=eligible_captures,
            per_window_files_deleted=deleted_files,
            verified_at_utc=datetime.now(timezone.utc).isoformat(),
        )

        if not dry_run:
            self.summary_store.upsert_completion(record)

        return record

    def _find_eligible_captures(self, date_utc: str) -> List[str]:
        """Find Kismet capture files whose intervals are all safe_for_raw_cleanup."""
        day_dir = self.intervals_dir / date_utc
        if not day_dir.is_dir():
            return []

        # Build set of captures that appear in any interval for this day
        capture_intervals: Dict[str, List[bool]] = {}  # capture_path -> [safe flags]
        for mpath in sorted(day_dir.glob("*.manifest.json")):
            try:
                manifest = json.loads(mpath.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            safe = manifest.get("safe_for_raw_cleanup", False)
            for cap in manifest.get("source_captures", []):
                capture_file = cap.get("path", "")
                if capture_file:
                    capture_intervals.setdefault(capture_file, []).append(safe)

        # A capture is eligible only if ALL of its intervals are safe
        eligible = [
            path for path, flags in capture_intervals.items()
            if flags and all(flags)
        ]
        return sorted(eligible)

    def _delete_per_window_files(self, date_utc: str) -> bool:
        """Delete prediction JSONL files for a verified day. Returns True on success."""
        day_dir = self.intervals_dir / date_utc
        if not day_dir.is_dir():
            return False
        deleted_any = False
        for pred_file in day_dir.glob("*.predictions.jsonl"):
            try:
                pred_file.unlink()
                deleted_any = True
            except OSError:
                pass
        return deleted_any

    def enforce_retention(self, *, dry_run: bool = True) -> Dict[str, Any]:
        """Delete daily summaries older than summary_retention_days.

        Always dry_run=True by default to force explicit opt-in.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.summary_retention_days)
        cutoff_date = cutoff.strftime("%Y-%m-%d")

        dates = self.summary_store.list_completed_dates()
        to_delete = [d for d in dates if d < cutoff_date]
        results: Dict[str, Any] = {
            "dry_run": dry_run,
            "retention_days": self.summary_retention_days,
            "cutoff_date": cutoff_date,
            "total_dates_with_summaries": len(dates),
            "dates_to_delete": to_delete,
            "deleted_count": 0,
        }

        if not dry_run:
            deleted = 0
            for date in to_delete:
                n = self.summary_store.delete_date(date)
                deleted += n
            results["deleted_count"] = deleted

        return results

    def show_day_status(self, date_utc: str) -> Dict[str, Any]:
        """Return a summary of the day's processing status."""
        completion = self.summary_store.query_completion(date_utc)
        summaries = self.summary_store.query_summaries(date_utc)

        # Count intervals from disk
        day_dir = self.intervals_dir / date_utc
        interval_count = 0
        completed_count = 0
        safe_count = 0
        if day_dir.is_dir():
            for mpath in day_dir.glob("*.manifest.json"):
                try:
                    m = json.loads(mpath.read_text(encoding="utf-8"))
                    interval_count += 1
                    if m.get("status") == "COMPLETED":
                        completed_count += 1
                    if m.get("safe_for_raw_cleanup"):
                        safe_count += 1
                except (json.JSONDecodeError, OSError):
                    pass

        return {
            "date_utc": date_utc,
            "intervals_total": interval_count,
            "intervals_completed": completed_count,
            "intervals_safe_for_raw_cleanup": safe_count,
            "summaries_generated": len(summaries),
            "summary_status": completion.status if completion else "pending",
            "per_window_files_deleted": completion.per_window_files_deleted if completion else False,
            "raw_captures_eligible": completion.raw_captures_eligible_for_deletion if completion else [],
            "total_window_count": completion.total_window_count if completion else 0,
            "total_active_duration_seconds": completion.total_active_duration_seconds if completion else 0.0,
            "unknown_duration_seconds": completion.unknown_duration_seconds if completion else 0.0,
            "verified_at_utc": completion.verified_at_utc if completion else None,
        }
