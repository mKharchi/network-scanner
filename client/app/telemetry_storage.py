"""Storage scaffolding for the v2 network telemetry pipeline.

Implements the layered on-disk layout described in
``docs/network_observation/v2.md`` §2:

    client/storage/network_telemetry/<YYYY-MM-DD>/
        packets/<protocol>.json          (owned by other components; helpers only)
        flows.json                       (+ flows.1.json, flows.2.json, ... on rotation)
        devices.json
        activity/<HH-MM>_<HH-MM>.json

This module intentionally has no knowledge of packet capture, flow
aggregation logic, or device correlation — it only provides:

    * day-scoped path helpers
    * a size-bounded rotating JSON append store (used by the Flow Aggregator
      for ``flows.json`` and reused for per-protocol packet files if ever
      needed)
    * a small atomic single-object JSON writer/reader (used by
      ``devices.json`` and activity window files)

This keeps the v2 telemetry tree fully separate from the V1
``client/storage/passive_packets/`` tree per the non-goals in v2.md and the
"do not mix" guidance carried over from plan.md §30.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

CLIENT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TELEMETRY_ROOT = CLIENT_ROOT / "storage" / "network_telemetry"

# Default per-file rotation limit (v2 §2: "config value, e.g. 50 MB or N packets").
DEFAULT_FILE_MAX_BYTES = 50 * 1024 * 1024

_WRITE_LOCK = threading.RLock()


def _read_max_bytes_env(var_name: str, default: int) -> int:
    value = os.getenv(var_name)
    if not value:
        return default
    try:
        parsed = int(value)
        return parsed if parsed > 0 else default
    except ValueError:
        return default


def telemetry_file_max_bytes() -> int:
    """Return the configured per-file rotation threshold in bytes."""
    return _read_max_bytes_env("TELEMETRY_FILE_MAX_BYTES", DEFAULT_FILE_MAX_BYTES)


# ---------------------------------------------------------------------------
# Day-scoped path helpers
# ---------------------------------------------------------------------------


def get_day_dir(date_str: str, *, root: Path | str = DEFAULT_TELEMETRY_ROOT) -> Path:
    """Return (and create) the storage directory for one calendar day."""
    day_dir = Path(root) / date_str
    day_dir.mkdir(parents=True, exist_ok=True)
    return day_dir


def get_packets_dir(date_str: str, *, root: Path | str = DEFAULT_TELEMETRY_ROOT) -> Path:
    """Return (and create) the per-protocol packet directory for one day."""
    packets_dir = get_day_dir(date_str, root=root) / "packets"
    packets_dir.mkdir(parents=True, exist_ok=True)
    return packets_dir


def get_protocol_packet_path(
    date_str: str, protocol: str, *, root: Path | str = DEFAULT_TELEMETRY_ROOT
) -> Path:
    """Return the base path for one protocol's packet file for one day."""
    safe_protocol = "".join(
        ch for ch in (protocol or "unknown").lower() if ch.isalnum() or ch in "-_"
    ) or "unknown"
    return get_packets_dir(date_str, root=root) / f"{safe_protocol}.json"


def get_flows_path(date_str: str, *, root: Path | str = DEFAULT_TELEMETRY_ROOT) -> Path:
    """Return the base ``flows.json`` path for one day (rotation-suffixed siblings may also exist)."""
    return get_day_dir(date_str, root=root) / "flows.json"


def get_devices_path(date_str: str, *, root: Path | str = DEFAULT_TELEMETRY_ROOT) -> Path:
    """Return the ``devices.json`` path for one day."""
    return get_day_dir(date_str, root=root) / "devices.json"


def get_activity_dir(date_str: str, *, root: Path | str = DEFAULT_TELEMETRY_ROOT) -> Path:
    """Return (and create) the activity-window directory for one day."""
    activity_dir = get_day_dir(date_str, root=root) / "activity"
    activity_dir.mkdir(parents=True, exist_ok=True)
    return activity_dir


def get_activity_window_path(
    date_str: str, window_start_label: str, window_end_label: str,
    *, root: Path | str = DEFAULT_TELEMETRY_ROOT,
) -> Path:
    """Return the path for one activity window file, e.g. ``11-00_11-15.json``."""
    return get_activity_dir(date_str, root=root) / f"{window_start_label}_{window_end_label}.json"


# ---------------------------------------------------------------------------
# Atomic single-object JSON helpers (devices.json / activity window files)
# ---------------------------------------------------------------------------


def atomic_write_json(target_path: Path, data: Any) -> None:
    """Write JSON payload to a temp file and atomically replace the target."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(
        prefix=".telemetry_", suffix=".tmp", dir=target_path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(temp_path, target_path)
    finally:
        if os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass


def read_json(path: Path, default: Any = None) -> Any:
    """Best-effort JSON read; returns ``default`` on any I/O or parse error."""
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return default


# ---------------------------------------------------------------------------
# Size-bounded rotating JSON append store (used for flows.json)
# ---------------------------------------------------------------------------


class RotatingJSONAppendStore:
    """Append dict records into a JSON array file, rotating on a size limit.

    The file format is a JSON array of records (not JSON-lines), matching the
    project's existing convention (see ``packet_storage.DailyPacketStorage``).
    When the active file would exceed ``max_bytes`` after an append, it is
    rolled to the next numbered sibling (``flows.json`` -> ``flows.1.json`` ->
    ``flows.2.json`` ...), and a fresh empty active file is started at the
    base name. This keeps ``base_path`` always the "current" writable file to
    simplify the common append path, while numbered siblings retain history.
    """

    def __init__(self, base_path: Path | str, *, max_bytes: Optional[int] = None):
        self.base_path = Path(base_path)
        self.max_bytes = max_bytes if max_bytes is not None else telemetry_file_max_bytes()
        self._lock = threading.RLock()

    def _next_rotation_index(self) -> int:
        """Return the next unused numbered-sibling index for rotation."""
        index = 1
        while True:
            candidate = self.base_path.with_name(
                f"{self.base_path.stem}.{index}{self.base_path.suffix}"
            )
            if not candidate.exists():
                return index
            index += 1

    def append(self, record: Dict[str, Any]) -> None:
        """Append one record, rotating the file first if it is already oversized."""
        self.append_many([record])

    def append_many(self, records: List[Dict[str, Any]]) -> None:
        """Append multiple records in one write, rotating first if needed."""
        if not records:
            return
        with self._lock:
            self.base_path.parent.mkdir(parents=True, exist_ok=True)
            existing: List[Dict[str, Any]] = []
            if self.base_path.exists():
                if self.base_path.stat().st_size >= self.max_bytes:
                    # Roll the oversized active file out of the way first.
                    rotation_index = self._next_rotation_index()
                    rotated_path = self.base_path.with_name(
                        f"{self.base_path.stem}.{rotation_index}{self.base_path.suffix}"
                    )
                    os.replace(self.base_path, rotated_path)
                else:
                    existing = read_json(self.base_path, default=[]) or []
                    if not isinstance(existing, list):
                        existing = []
            existing.extend(records)
            atomic_write_json(self.base_path, existing)

    def read_all(self) -> List[Dict[str, Any]]:
        """Return all records in the *active* file only (not rotated siblings)."""
        if not self.base_path.exists():
            return []
        data = read_json(self.base_path, default=[])
        return data if isinstance(data, list) else []

    def read_all_including_rotated(self) -> List[Dict[str, Any]]:
        """Return records from the active file plus all rotated siblings, oldest first."""
        records: List[Dict[str, Any]] = []
        index = 1
        while True:
            candidate = self.base_path.with_name(
                f"{self.base_path.stem}.{index}{self.base_path.suffix}"
            )
            if not candidate.exists():
                break
            data = read_json(candidate, default=[])
            if isinstance(data, list):
                records.extend(data)
            index += 1
        records.extend(self.read_all())
        return records
