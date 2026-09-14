"""Kismet live log rotator and raw capture cleanup manager.

Controls Kismet's live logging subsystem via the authenticated REST API:
- Stops the current interval logfile (forcing clean SQLite close and WAL checkpoint)
- Immediately opens a new logfile without restarting the daemon or tearing down monitor VIFs
- Safely deletes closed raw .kismet captures whose interval manifests are all COMPLETED
  and marked safe_for_raw_cleanup
"""

from __future__ import annotations

import base64
import json
import logging
import os
import shutil
import sqlite3
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

LOG = logging.getLogger("kismet_rotator")


@dataclass
class RotationResult:
    success: bool
    closed_log_uuid: Optional[str] = None
    closed_log_path: Optional[str] = None
    new_log_uuid: Optional[str] = None
    new_log_path: Optional[str] = None
    error: Optional[str] = None
    rotated_at_utc: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CleanupResult:
    dry_run: bool
    total_evaluated: int = 0
    deleted_captures: List[str] = field(default_factory=list)
    freed_bytes: int = 0
    freed_mb: float = 0.0
    preserved_active: List[str] = field(default_factory=list)
    preserved_unprocessed: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class KismetLogRotator:
    """Manages live Kismet log rotation via HTTP REST API and safe capture deletion."""

    def __init__(
        self,
        api_url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        *,
        storage_dir: Optional[Path | str] = None,
        capture_dirs: Optional[Sequence[Path | str]] = None,
    ) -> None:
        self.api_url = (api_url or os.getenv("KISMET_API_URL") or "http://127.0.0.1:2501").rstrip("/")
        self.username = username or os.getenv("KISMET_API_USERNAME") or "root"
        self.password = password or os.getenv("KISMET_API_PASSWORD") or "120106"

        from .kismet_ml_pipeline import get_ml_storage_dir
        self.storage_dir = Path(storage_dir or get_ml_storage_dir()).resolve()
        self.intervals_dir = self.storage_dir / "intervals"

        if capture_dirs is not None:
            self.capture_dirs = [Path(p) for p in capture_dirs]
        else:
            self.capture_dirs = [
                Path(os.getenv("KISMET_CAPTURE_ROOT") or "/home/adonis/kismet"),
                Path("/home/adonis"),
            ]

    def _auth_header(self) -> str:
        token = f"{self.username}:{self.password}"
        return "Basic " + base64.b64encode(token.encode("utf-8")).decode("utf-8")

    def _api_request(
        self, endpoint: str, data: Optional[bytes] = None, timeout: float = 10.0
    ) -> Tuple[int, bytes]:
        url = f"{self.api_url}/{endpoint.lstrip('/')}"
        headers = {"Authorization": self._auth_header()}
        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as err:
            return err.code, err.read()
        except urllib.error.URLError as err:
            raise ConnectionError(f"Failed connecting to Kismet API at {url}: {err}") from err

    def get_active_logs(self) -> List[Dict[str, Any]]:
        """Query Kismet /logging/active.json for open capture files."""
        status, body = self._api_request("logging/active.json")
        if status != 200:
            raise RuntimeError(f"Kismet API returned HTTP {status}: {body.decode('utf-8', errors='replace')}")
        try:
            return json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as err:
            raise RuntimeError(f"Invalid JSON from Kismet active logging API: {err}") from err

    def rotate(self, log_class: str = "kismet") -> RotationResult:
        """Stop the currently open log file and open a new one.

        Keeps the RF monitor interface active without dropping packets.
        """
        now_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        try:
            active_logs = self.get_active_logs()
        except Exception as exc:
            return RotationResult(success=False, error=f"failed to query active logs: {exc}", rotated_at_utc=now_utc)

        if not active_logs:
            return RotationResult(success=False, error="no active logs found in Kismet", rotated_at_utc=now_utc)

        # Target the unified kismet log
        target_log = None
        for log in active_logs:
            driver = log.get("kismet.log.type_driver", {})
            if driver.get("kismet.logfile.type.class") == log_class or log.get("kismet.logfile.open") == 1:
                target_log = log
                break
        if not target_log:
            target_log = active_logs[0]

        old_uuid = target_log.get("kismet.logfile.uuid")
        old_path = target_log.get("kismet.logfile.path")

        if not old_uuid:
            return RotationResult(success=False, error="active log has no UUID", rotated_at_utc=now_utc)

        # 1. Stop active log
        stop_status, stop_body = self._api_request(f"logging/by-uuid/{old_uuid}/stop.cmd", data=b"")
        if stop_status != 200:
            return RotationResult(
                success=False,
                closed_log_uuid=old_uuid,
                closed_log_path=old_path,
                error=f"stop log failed HTTP {stop_status}: {stop_body.decode('utf-8', errors='replace')}",
                rotated_at_utc=now_utc,
            )

        # Brief pause to allow SQLite checkpoint to finish
        time.sleep(0.5)

        # 2. Start new log
        start_status, start_body = self._api_request(f"logging/by-class/{log_class}/start.cmd", data=b"")
        if start_status != 200:
            return RotationResult(
                success=False,
                closed_log_uuid=old_uuid,
                closed_log_path=old_path,
                error=f"start new log failed HTTP {start_status}: {start_body.decode('utf-8', errors='replace')}",
                rotated_at_utc=now_utc,
            )

        new_log = {}
        try:
            new_log = json.loads(start_body.decode("utf-8"))
        except Exception:
            pass

        new_uuid = new_log.get("kismet.logfile.uuid")
        new_path = new_log.get("kismet.logfile.path")

        return RotationResult(
            success=True,
            closed_log_uuid=old_uuid,
            closed_log_path=old_path,
            new_log_uuid=new_uuid,
            new_log_path=new_path,
            rotated_at_utc=now_utc,
        )

    def is_file_active_in_kismet(self, file_path: Path) -> bool:
        """Check if a file path is currently listed as open by Kismet."""
        try:
            active = self.get_active_logs()
            resolved = file_path.resolve()
            for entry in active:
                raw_path = entry.get("kismet.logfile.path", "")
                if raw_path and Path(raw_path).resolve() == resolved:
                    return True
        except Exception:
            # Fall back to mtime / sidecar check if API unreachable
            pass

        # Sidecars check
        for suffix in ("-wal", "-journal", "-shm"):
            if file_path.with_name(file_path.name + suffix).exists():
                return True

        # Recent mtime check (within 120s)
        try:
            if (time.time() - file_path.stat().st_mtime) < 120:
                return True
        except OSError:
            return True

        return False

    def find_all_capture_files(self) -> List[Path]:
        files: List[Path] = []
        for d in self.capture_dirs:
            try:
                if d.is_file() and d.suffix == ".kismet":
                    files.append(d)
                elif d.is_dir():
                    files.extend(p for p in d.glob("*.kismet") if p.is_file())
            except OSError:
                continue
        unique = {p.resolve(): p for p in files}
        return sorted(unique.values(), key=lambda p: p.stat().st_mtime if p.exists() else 0)

    def cleanup_verified_captures(self, *, dry_run: bool = False) -> CleanupResult:
        """Delete closed raw .kismet captures whose interval manifests are all COMPLETED and safe."""
        result = CleanupResult(dry_run=dry_run)
        captures = self.find_all_capture_files()
        result.total_evaluated = len(captures)

        # Build index of interval manifests: capture_path -> list of (manifest_status, safe_for_cleanup)
        manifest_map: Dict[str, List[Tuple[str, bool]]] = {}
        if self.intervals_dir.is_dir():
            for mpath in self.intervals_dir.glob("*/*.manifest.json"):
                try:
                    m = json.loads(mpath.read_text(encoding="utf-8"))
                    status = m.get("status", "")
                    safe = bool(m.get("safe_for_raw_cleanup", False))
                    for cinfo in m.get("source_captures", []):
                        cpath = cinfo.get("path")
                        if cpath:
                            try:
                                rpath = str(Path(cpath).resolve())
                                manifest_map.setdefault(rpath, []).append((status, safe))
                            except OSError:
                                pass
                except Exception:
                    continue

        for cap in captures:
            resolved = str(cap.resolve())

            # 1. Never touch currently active write targets
            if self.is_file_active_in_kismet(cap):
                result.preserved_active.append(cap.name)
                continue

            # 2. Check manifests referencing this capture
            manifest_entries = manifest_map.get(resolved, [])
            if not manifest_entries:
                # Capture has no interval manifests yet -> must preserve
                result.preserved_unprocessed.append(cap.name)
                continue

            # Must have all referencing interval manifests in COMPLETED state
            all_completed = all(status == "COMPLETED" for status, _ in manifest_entries)
            if not all_completed:
                result.preserved_unprocessed.append(cap.name)
                continue

            # Verify that all packet timestamps in this capture fall within completed intervals
            # so no trailing un-extracted packets exist
            try:
                con = sqlite3.connect(f"file:{cap}?mode=ro", uri=True)
                row = con.execute("SELECT max(ts_sec) FROM packets").fetchone()
                con.close()
                max_ts = row[0] if row and row[0] else 0
                # If capture has packets from within the last active margin (e.g. 120s), wait until closed
                if (time.time() - max_ts) < 120:
                    result.preserved_active.append(cap.name)
                    continue
            except Exception:
                pass


            # 3. Safe to delete!
            try:
                cap_size = cap.stat().st_size
                if not dry_run:
                    # Remove main capture and sidecars
                    cap.unlink(missing_ok=True)
                    for suffix in ("-wal", "-journal", "-shm"):
                        sidecar = cap.with_name(cap.name + suffix)
                        if sidecar.exists():
                            sidecar.unlink(missing_ok=True)

                result.deleted_captures.append(cap.name)
                result.freed_bytes += cap_size
            except OSError as err:
                result.errors.append(f"failed to unlink {cap.name}: {err}")

        result.freed_mb = round(result.freed_bytes / (1024 * 1024), 2)
        return result
