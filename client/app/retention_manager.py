"""Bounded Raw-File Retention & Storage Pruning Manager.

Implements the lifecycle and retention policy for passive packet captures and
intermediate telemetry artifacts described in docs/integrating-kismet-and-backup/plan.md (Phase 1):

    RAW FILE -> PENDING -> PROCESSING -> SUCCESS -> PROCESSED -> RETENTION WINDOW -> DELETE
    Failure: PROCESSING -> FAILED -> KEEP FILE -> RETRY

Ensures that raw packet files (client/storage/passive_packets/ and
client/storage/network_telemetry/<date>/packets/) are pruned safely once their
retention window has expired AND flow processing has completed successfully,
without deleting in-progress, pending, or failed captures.
"""

from __future__ import annotations

import enum
import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

LOG = logging.getLogger("retention_manager")

DEFAULT_RETENTION_HOURS = 48.0
DEFAULT_CLEANUP_INTERVAL_SECONDS = 3600.0  # 1 hour
DEFAULT_WRITE_GRACE_SECONDS = 300.0  # 5 minutes grace for recently modified files


class FileProcessingState(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    DELETED = "DELETED"


@dataclass
class CleanupSummary:
    evaluated_count: int = 0
    eligible_count: int = 0
    deleted_count: int = 0
    deleted_bytes: int = 0
    failed_count: int = 0
    preserved_count: int = 0
    dry_run: bool = False
    details: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RetentionStateTracker:
    """Tracks and persists the lifecycle states of capture files and date partitions."""

    def __init__(self, state_file_path: Path | str):
        self.state_file_path = Path(state_file_path)
        self._lock = threading.RLock()
        self._states: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.state_file_path.exists():
            return
        try:
            with open(self.state_file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    self._states = data
        except (OSError, json.JSONDecodeError) as err:
            LOG.warning("[RETENTION] Could not load retention state file %s: %s", self.state_file_path, err)

    def _save_locked(self) -> None:
        self.state_file_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.state_file_path.with_suffix(".tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(self._states, f, indent=2, ensure_ascii=False)
            os.replace(temp_path, self.state_file_path)
        except OSError as err:
            LOG.warning("[RETENTION] Could not save retention state file %s: %s", self.state_file_path, err)
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    def get_state(self, key: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._states.get(key)

    def set_state(
        self,
        key: str,
        state: FileProcessingState,
        *,
        error_message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self._lock:
            entry = self._states.setdefault(key, {})
            entry["state"] = state.value
            entry["updated_at"] = datetime.now(timezone.utc).isoformat()
            if error_message:
                entry["error_message"] = error_message
            elif "error_message" in entry and state == FileProcessingState.SUCCESS:
                del entry["error_message"]
            if metadata:
                entry.setdefault("metadata", {}).update(metadata)
            self._save_locked()

    def mark_pending(self, key: str) -> None:
        self.set_state(key, FileProcessingState.PENDING)

    def mark_processing(self, key: str) -> None:
        self.set_state(key, FileProcessingState.PROCESSING)

    def mark_success(self, key: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        self.set_state(key, FileProcessingState.SUCCESS, metadata=metadata)

    def mark_failed(self, key: str, error_message: str) -> None:
        self.set_state(key, FileProcessingState.FAILED, error_message=error_message)

    def mark_deleted(self, key: str) -> None:
        self.set_state(key, FileProcessingState.DELETED)


class RetentionManager:
    """Enforces bounded retention on raw packet files and intermediate storage.

    Rules:
    - Never delete FAILED, PENDING, or PROCESSING files.
    - Never delete files modified within write_grace_seconds or belonging to active date.
    - Delete eligible files ONLY after retention_hours have elapsed AND flow processing succeeded.
    - Support dry-run mode.
    - Gracefully handle permission and filesystem errors.
    - Clean up empty parent packet folders.
    """

    def __init__(
        self,
        storage_root: Path | str,
        *,
        retention_hours: Optional[float] = None,
        cleanup_interval_seconds: Optional[float] = None,
        dry_run: Optional[bool] = None,
        write_grace_seconds: float = DEFAULT_WRITE_GRACE_SECONDS,
        now_provider: Optional[Callable[[], datetime]] = None,
    ):
        self.storage_root = Path(storage_root)
        self.passive_packets_dir = self.storage_root / "passive_packets"
        self.network_telemetry_dir = self.storage_root / "network_telemetry"

        # Configurable settings (prefer explicit args -> env vars -> defaults)
        env_retention = os.getenv("RAW_CAPTURE_RETENTION_HOURS")
        if retention_hours is not None:
            self.retention_hours = max(0.1, float(retention_hours))
        elif env_retention:
            try:
                self.retention_hours = max(0.1, float(env_retention))
            except ValueError:
                self.retention_hours = DEFAULT_RETENTION_HOURS
        else:
            self.retention_hours = DEFAULT_RETENTION_HOURS

        env_interval = os.getenv("RAW_CAPTURE_CLEANUP_INTERVAL_SECONDS")
        if cleanup_interval_seconds is not None:
            self.cleanup_interval_seconds = max(1.0, float(cleanup_interval_seconds))
        elif env_interval:
            try:
                self.cleanup_interval_seconds = max(1.0, float(env_interval))
            except ValueError:
                self.cleanup_interval_seconds = DEFAULT_CLEANUP_INTERVAL_SECONDS
        else:
            self.cleanup_interval_seconds = DEFAULT_CLEANUP_INTERVAL_SECONDS

        env_dry_run = os.getenv("RAW_CAPTURE_CLEANUP_DRY_RUN", "").strip().lower()
        if dry_run is not None:
            self.dry_run = bool(dry_run)
        elif env_dry_run in ("1", "true", "yes", "on"):
            self.dry_run = True
        else:
            self.dry_run = False

        self.write_grace_seconds = write_grace_seconds
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))

        self.state_tracker = RetentionStateTracker(self.storage_root / "retention_state.json")
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.RLock()

    def _get_now(self) -> datetime:
        now = self._now_provider()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return now

    def _extract_date_str(self, path: Path) -> Optional[str]:
        """Extract YYYY-MM-DD from parent directory name or file stem."""
        # Case 1: network_telemetry/YYYY-MM-DD/packets/<protocol>.json
        parent_name = path.parent.parent.name
        if len(parent_name) == 10 and parent_name[4] == "-" and parent_name[7] == "-":
            return parent_name
        # Case 2: passive_packets/YYYY-MM-DD.json
        stem = path.stem
        if len(stem) == 10 and stem[4] == "-" and stem[7] == "-":
            return stem
        # Case 3: network_telemetry/YYYY-MM-DD/
        if len(path.name) == 10 and path.name[4] == "-" and path.name[7] == "-":
            return path.name
        return None

    def _is_flow_processing_successful(self, date_str: str, file_path: Path) -> bool:
        """Verify that flow processing has succeeded for the partition."""
        key = str(file_path.relative_to(self.storage_root)) if file_path.is_relative_to(self.storage_root) else file_path.name
        file_state = self.state_tracker.get_state(key)
        if file_state:
            state = file_state.get("state")
            if state == FileProcessingState.FAILED.value:
                return False
            if state == FileProcessingState.PROCESSING.value:
                return False
            if state == FileProcessingState.SUCCESS.value:
                return True

        # Check date-level state
        date_state = self.state_tracker.get_state(date_str)
        if date_state:
            state = date_state.get("state")
            if state == FileProcessingState.FAILED.value:
                return False
            if state == FileProcessingState.PROCESSING.value:
                return False
            if state == FileProcessingState.SUCCESS.value:
                return True

        # If not explicitly tracked, verify presence of flows.json in telemetry
        flows_file = self.network_telemetry_dir / date_str / "flows.json"
        if flows_file.exists() and flows_file.stat().st_size > 0:
            return True

        # For passive_packets: if date is strictly in the past (closed day)
        today_str = self._get_now().strftime("%Y-%m-%d")
        if date_str < today_str:
            return True

        return False

    def check_file_eligibility(self, file_path: Path, now: Optional[datetime] = None) -> Tuple[bool, str]:
        """Evaluate whether a raw packet file is eligible for deletion according to all safety rules."""
        if not file_path.exists():
            return False, "File does not exist"

        now_dt = now or self._get_now()
        date_str = self._extract_date_str(file_path)
        if not date_str:
            return False, "Unable to determine date partition"

        today_str = now_dt.strftime("%Y-%m-%d")
        rel_key = str(file_path.relative_to(self.storage_root)) if file_path.is_relative_to(self.storage_root) else file_path.name

        # Rule 1: Check tracked state
        file_state_entry = self.state_tracker.get_state(rel_key) or self.state_tracker.get_state(date_str)
        if file_state_entry:
            current_state = file_state_entry.get("state")
            if current_state == FileProcessingState.FAILED.value:
                return False, f"File is marked FAILED: {file_state_entry.get('error_message', 'processing error')}; preserved for recovery"
            if current_state == FileProcessingState.PROCESSING.value:
                return False, "File is currently marked as PROCESSING"
            if current_state == FileProcessingState.PENDING.value and date_str == today_str:
                return False, "File is currently PENDING in the active partition"

        # Rule 2: Active file write grace period (check modification time)
        try:
            stat = file_path.stat()
            file_mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            seconds_since_mtime = (now_dt - file_mtime).total_seconds()
            if seconds_since_mtime < self.write_grace_seconds and date_str == today_str:
                return False, f"File was modified recently ({seconds_since_mtime:.0f}s ago < {self.write_grace_seconds}s grace)"
        except OSError as err:
            return False, f"Could not stat file: {err}"

        # Rule 3: Age vs retention period
        # Age is computed from date partition or file mtime, whichever represents file age accurately
        try:
            partition_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
            file_age_hours = (now_dt - partition_dt).total_seconds() / 3600.0
        except ValueError:
            file_age_hours = (now_dt - file_mtime).total_seconds() / 3600.0

        if file_age_hours < self.retention_hours:
            return False, f"Retention window of {self.retention_hours:.1f}h has not elapsed (elapsed: {file_age_hours:.1f}h)"

        # Rule 4: Flow processing verification
        if not self._is_flow_processing_successful(date_str, file_path):
            return False, f"Flow processing has not been verified for partition {date_str}"

        return True, f"Retention window of {self.retention_hours:.1f}h elapsed and flow processing succeeded for {date_str}"

    def collect_candidate_files(self) -> List[Path]:
        """Gather all raw packet capture files across passive_packets and network_telemetry."""
        candidates: List[Path] = []

        # 1. V1 flat daily captures: client/storage/passive_packets/*.json
        if self.passive_packets_dir.exists():
            for p in self.passive_packets_dir.glob("*.json"):
                if p.is_file():
                    candidates.append(p)

        # 2. V2 per-protocol packet captures: client/storage/network_telemetry/<date>/packets/*.json
        if self.network_telemetry_dir.exists():
            for date_dir in self.network_telemetry_dir.iterdir():
                if date_dir.is_dir():
                    packets_dir = date_dir / "packets"
                    if packets_dir.is_dir():
                        for p in packets_dir.glob("*.json"):
                            if p.is_file():
                                candidates.append(p)

        return sorted(candidates)

    def prune_expired_files(self, *, dry_run: Optional[bool] = None) -> CleanupSummary:
        """Scan, evaluate, and prune all expired raw packet files."""
        is_dry_run = self.dry_run if dry_run is None else bool(dry_run)
        summary = CleanupSummary(dry_run=is_dry_run)
        now_dt = self._get_now()

        with self._lock:
            candidates = self.collect_candidate_files()
            summary.evaluated_count = len(candidates)

            for file_path in candidates:
                eligible, reason = self.check_file_eligibility(file_path, now=now_dt)
                rel_key = str(file_path.relative_to(self.storage_root)) if file_path.is_relative_to(self.storage_root) else file_path.name
                file_size = 0
                try:
                    file_size = file_path.stat().st_size
                except OSError:
                    pass

                detail = {
                    "file": str(file_path),
                    "relative_path": rel_key,
                    "size_bytes": file_size,
                    "eligible": eligible,
                    "reason": reason,
                }

                if not eligible:
                    summary.preserved_count += 1
                    detail["action"] = "PRESERVED"
                    summary.details.append(detail)
                    continue

                summary.eligible_count += 1

                if is_dry_run:
                    detail["action"] = "DRY_RUN_DELETE"
                    summary.deleted_count += 1
                    summary.deleted_bytes += file_size
                    LOG.info("[RETENTION DRY-RUN] Would delete %s (%d bytes): %s", rel_key, file_size, reason)
                    summary.details.append(detail)
                    continue

                # Real deletion
                try:
                    file_path.unlink(missing_ok=True)
                    summary.deleted_count += 1
                    summary.deleted_bytes += file_size
                    self.state_tracker.mark_deleted(rel_key)
                    detail["action"] = "DELETED"
                    LOG.info("[RETENTION] Deleted %s (%d bytes): %s", rel_key, file_size, reason)
                    summary.details.append(detail)
                except OSError as err:
                    summary.failed_count += 1
                    detail["action"] = "DELETE_FAILED"
                    detail["error"] = str(err)
                    LOG.warning("[RETENTION] Failed to delete %s: %s", rel_key, err)
                    summary.details.append(detail)

            # Clean up empty packets directories
            self._cleanup_empty_dirs(is_dry_run)

        return summary

    def _cleanup_empty_dirs(self, is_dry_run: bool) -> None:
        """Remove empty packet directories after files are pruned."""
        if not self.network_telemetry_dir.exists():
            return
        try:
            for date_dir in self.network_telemetry_dir.iterdir():
                if not date_dir.is_dir():
                    continue
                packets_dir = date_dir / "packets"
                if packets_dir.is_dir():
                    try:
                        if not any(packets_dir.iterdir()):
                            if not is_dry_run:
                                packets_dir.rmdir()
                                LOG.info("[RETENTION] Removed empty directory %s", packets_dir)
                    except OSError as err:
                        LOG.debug("[RETENTION] Could not clean empty dir %s: %s", packets_dir, err)
        except OSError as err:
            LOG.debug("[RETENTION] Directory scan error: %s", err)

    def run_once(self) -> CleanupSummary:
        """Execute one complete pruning cycle."""
        LOG.info("[RETENTION] Pruning cycle started (retention=%0.1fh, dry_run=%s)", self.retention_hours, self.dry_run)
        summary = self.prune_expired_files()
        LOG.info(
            "[RETENTION] Pruning cycle finished: evaluated=%d eligible=%d deleted=%d deleted_bytes=%d preserved=%d failed=%d",
            summary.evaluated_count,
            summary.eligible_count,
            summary.deleted_count,
            summary.deleted_bytes,
            summary.preserved_count,
            summary.failed_count,
        )
        return summary

    def start(self) -> None:
        """Start the background periodic pruning thread."""
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._loop,
                daemon=True,
                name="raw-capture-retention",
            )
            self._thread.start()
            LOG.info("[RETENTION] Background retention worker started (interval=%0.1fs)", self.cleanup_interval_seconds)

    def stop(self) -> None:
        """Stop the background retention worker thread."""
        with self._lock:
            if self._thread:
                self._stop_event.set()
                self._thread.join(timeout=3.0)
                self._thread = None
                LOG.info("[RETENTION] Background retention worker stopped")

    def _loop(self) -> None:
        # Run one initial pass shortly after start, then periodically
        time.sleep(2.0)
        while not self._stop_event.is_set():
            try:
                self.run_once()
            except Exception as err:  # pragma: no cover - defensive
                LOG.error("[RETENTION] Unexpected error in retention loop: %s", err, exc_info=True)
            if self._stop_event.wait(self.cleanup_interval_seconds):
                break
