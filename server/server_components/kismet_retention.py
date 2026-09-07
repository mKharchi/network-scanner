"""Server Kismet Storage Retention and Cleanup Manager (Phase 7).

Manages retention, safe pruning, and storage metrics for server-owned Kismet
capture databases (.kismet SQLite files).

Safety Invariants:
1. NEVER deletes the active write target (most recently modified capture file).
2. NEVER deletes active WAL/journal/sidecar files.
3. NEVER deletes files modified within the write grace period (default 15 minutes).
4. Supports dry-run simulation mode with detailed audit logs.
5. Guards filesystem free-space reserve.
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

LOG = logging.getLogger("kismet_retention")

DEFAULT_RETENTION_HOURS = 48.0  # 2 days retention
DEFAULT_WRITE_GRACE_SECONDS = 900.0  # 15 minutes grace for active capture files
DEFAULT_MIN_FREE_BYTES = 5 * 1024 * 1024 * 1024  # 5 GB safety reserve


@dataclass
class RetentionSummary:
    total_files: int = 0
    total_bytes: int = 0
    eligible_count: int = 0
    deleted_count: int = 0
    deleted_bytes: int = 0
    preserved_count: int = 0
    free_bytes_available: int = 0
    dry_run: bool = True
    details: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class KismetRetentionManager:
    """Safely prunes expired server Kismet capture databases."""

    def __init__(
        self,
        capture_dir: Optional[Path | str] = None,
        *,
        retention_hours: Optional[float] = None,
        min_free_bytes: Optional[int] = None,
        write_grace_seconds: float = DEFAULT_WRITE_GRACE_SECONDS,
        dry_run: Optional[bool] = None,
    ):
        configured_dir = os.getenv("KISMET_CAPTURE_ROOT") or os.getenv("KISMET_CAPTURE_DIR")
        if capture_dir:
            self.capture_dir = Path(capture_dir).resolve()
        elif configured_dir:
            self.capture_dir = Path(configured_dir).resolve()
        else:
            self.capture_dir = Path("/home/adonis/kismet").resolve()

        self.retention_hours = (
            float(retention_hours)
            if retention_hours is not None
            else float(os.getenv("KISMET_RETENTION_HOURS", DEFAULT_RETENTION_HOURS))
        )
        self.min_free_bytes = (
            int(min_free_bytes)
            if min_free_bytes is not None
            else int(os.getenv("KISMET_MIN_FREE_BYTES", DEFAULT_MIN_FREE_BYTES))
        )
        self.write_grace_seconds = write_grace_seconds
        if dry_run is None:
            self.dry_run = os.getenv("KISMET_CLEANUP_DRY_RUN", "true").strip().lower() in {
                "1", "true", "yes", "on"
            }
        else:
            self.dry_run = bool(dry_run)

    def get_storage_metrics(self) -> Dict[str, Any]:
        """Return capacity, file count, and byte consumption of Kismet captures."""
        if not self.capture_dir.exists() or not self.capture_dir.is_dir():
            return {
                "capture_dir": str(self.capture_dir),
                "exists": False,
                "total_kismet_files": 0,
                "total_kismet_bytes": 0,
                "free_bytes": 0,
                "total_bytes": 0,
            }

        kismet_files = [f for f in self.capture_dir.glob("*.kismet") if f.is_file()]
        total_kismet_bytes = sum(f.stat().st_size for f in kismet_files)

        disk_usage = shutil.disk_usage(self.capture_dir)
        newest_file = None
        oldest_file = None
        if kismet_files:
            sorted_files = sorted(kismet_files, key=lambda f: f.stat().st_mtime)
            oldest_file = sorted_files[0].name
            newest_file = sorted_files[-1].name

        return {
            "capture_dir": str(self.capture_dir),
            "exists": True,
            "total_kismet_files": len(kismet_files),
            "total_kismet_bytes": total_kismet_bytes,
            "total_kismet_mb": round(total_kismet_bytes / (1024 * 1024), 2),
            "free_bytes": disk_usage.free,
            "free_mb": round(disk_usage.free / (1024 * 1024), 2),
            "total_bytes": disk_usage.total,
            "oldest_file": oldest_file,
            "newest_file": newest_file,
            "retention_hours": self.retention_hours,
            "min_free_bytes": self.min_free_bytes,
        }

    @staticmethod
    def _sidecars_for(capture_file: Path) -> List[Path]:
        """Return SQLite/Kismet sidecars belonging to one capture file."""
        return [
            capture_file.with_name(capture_file.name + suffix)
            for suffix in ("-wal", "-shm", "-journal", ".wal", ".shm", ".journal")
        ]

    @staticmethod
    def _hold_markers_for(capture_file: Path) -> List[Path]:
        """Return explicit investigation-hold marker names."""
        return [
            capture_file.with_name(capture_file.name + ".hold"),
            capture_file.with_name(capture_file.name + ".investigation-hold"),
        ]

    def prune_expired_captures(self, *, dry_run: Optional[bool] = None) -> RetentionSummary:
        """Prune capture files exceeding retention window while preserving active targets."""
        is_dry_run = self.dry_run if dry_run is None else dry_run
        summary = RetentionSummary(dry_run=is_dry_run)

        if not self.capture_dir.exists() or not self.capture_dir.is_dir():
            LOG.info("[KISMET_RETENTION] Capture directory does not exist: %s", self.capture_dir)
            return summary

        disk_usage = shutil.disk_usage(self.capture_dir)
        summary.free_bytes_available = disk_usage.free

        kismet_files = [f for f in self.capture_dir.glob("*.kismet") if f.is_file()]
        summary.total_files = len(kismet_files)
        summary.total_bytes = sum(f.stat().st_size for f in kismet_files)

        if not kismet_files:
            return summary

        now_epoch = time.time()
        retention_threshold_epoch = now_epoch - (self.retention_hours * 3600.0)
        active_grace_threshold = now_epoch - self.write_grace_seconds

        # Sort files by modification time (most recent last)
        sorted_files = sorted(kismet_files, key=lambda f: f.stat().st_mtime)
        active_target = sorted_files[-1]  # The most recent file is always considered the active capture

        for kfile in sorted_files:
            try:
                stat = kfile.stat()
                file_size = stat.st_size
                mtime = stat.st_mtime

                # Safety rule 1: Never delete the active target file
                if kfile == active_target:
                    summary.preserved_count += 1
                    summary.details.append({
                        "file": kfile.name,
                        "size_bytes": file_size,
                        "reason": "ACTIVE_TARGET",
                        "action": "PRESERVED",
                    })
                    continue

                # Safety rule 2: Never delete files modified within the write grace period
                if mtime > active_grace_threshold:
                    summary.preserved_count += 1
                    summary.details.append({
                        "file": kfile.name,
                        "size_bytes": file_size,
                        "reason": "RECENT_WRITE_GRACE",
                        "action": "PRESERVED",
                    })
                    continue

                sidecars = [path for path in self._sidecars_for(kfile) if path.exists()]
                if sidecars:
                    summary.preserved_count += 1
                    summary.details.append({
                        "file": kfile.name,
                        "size_bytes": file_size,
                        "reason": "ACTIVE_SIDECAR",
                        "sidecars": [path.name for path in sidecars],
                        "action": "PRESERVED",
                    })
                    continue

                hold_markers = [path for path in self._hold_markers_for(kfile) if path.exists()]
                if hold_markers:
                    summary.preserved_count += 1
                    summary.details.append({
                        "file": kfile.name,
                        "size_bytes": file_size,
                        "reason": "INVESTIGATION_HOLD",
                        "markers": [path.name for path in hold_markers],
                        "action": "PRESERVED",
                    })
                    continue

                # Check if expired or disk pressure below minimum reserve
                is_expired = mtime < retention_threshold_epoch
                is_disk_pressure = disk_usage.free < self.min_free_bytes

                if is_expired or is_disk_pressure:
                    reason = "EXPIRED" if is_expired else "DISK_PRESSURE_RESERVE"
                    summary.eligible_count += 1

                    if is_dry_run:
                        summary.deleted_count += 1
                        summary.deleted_bytes += file_size
                        summary.details.append({
                            "file": kfile.name,
                            "size_bytes": file_size,
                            "reason": reason,
                            "action": "WOULD_DELETE",
                        })
                    else:
                        try:
                            kfile.unlink()
                        except OSError as err:
                            LOG.warning("[KISMET_RETENTION] Could not unlink capture %s: %s", kfile, err)
                            summary.preserved_count += 1
                            summary.details.append({
                                "file": kfile.name,
                                "size_bytes": file_size,
                                "reason": "DELETE_FAILED",
                                "action": "PRESERVED",
                            })
                            continue

                        summary.deleted_count += 1
                        summary.deleted_bytes += file_size
                        summary.details.append({
                            "file": kfile.name,
                            "size_bytes": file_size,
                            "reason": reason,
                            "action": "DELETED",
                        })
                else:
                    summary.preserved_count += 1
                    summary.details.append({
                        "file": kfile.name,
                        "size_bytes": file_size,
                        "reason": "WITHIN_RETENTION_WINDOW",
                        "action": "PRESERVED",
                    })
            except Exception as err:
                LOG.error("[KISMET_RETENTION] Error evaluating file %s: %s", kfile, err)

        LOG.info(
            "[KISMET_RETENTION] Completed cleanup (dry_run=%s): evaluated=%d eligible=%d deleted=%d freed=%d bytes",
            is_dry_run,
            summary.total_files,
            summary.eligible_count,
            summary.deleted_count,
            summary.deleted_bytes,
        )
        return summary
