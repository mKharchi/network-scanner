
"""Filesystem audit storage for client passive-protocol snapshots.

Passive protocol advertisements are useful evidence but do not confirm a
network-device record. They are therefore retained in a separate, append-only
daily audit trail rather than the network scan/device storage pipeline.
"""

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path


SERVER_DIRECTORY = Path(__file__).resolve().parents[1]
PROJECT_DIRECTORY = SERVER_DIRECTORY.parent
DEFAULT_STORAGE_DIR = str(SERVER_DIRECTORY / "storage" / "passive_neighborhood")
_STORAGE_LOCK = threading.Lock()


def get_passive_neighbourhood_storage_dir():
    """Return the configured passive-neighbourhood storage directory."""
    configured_dir = Path(
        os.getenv("PASSIVE_NEIGHBOURHOOD_STORAGE_DIR", DEFAULT_STORAGE_DIR)
    )
    if configured_dir.is_absolute():
        return configured_dir
    return (PROJECT_DIRECTORY / configured_dir).resolve()


def _daily_snapshot_path(storage_dir, received_at):
    date = received_at.strftime("%Y-%m-%d")
    return storage_dir / f"passive_neighborhood_{date}.json"


def _write_json_atomically(file_path, payload):
    """Replace an audit file without exposing partially written JSON."""
    descriptor, temporary_path = tempfile.mkstemp(
        prefix=".passive_neighborhood_",
        suffix=".tmp",
        dir=file_path.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(payload, file, indent=2, ensure_ascii=False)
            file.write("\n")
        os.chmod(temporary_path, 0o644)
        os.replace(temporary_path, file_path)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)


def _load_daily_snapshot_file(file_path, received_at):
    date = received_at.strftime("%Y-%m-%d")
    if not file_path.exists():
        return {"date": date, "snapshots": []}

    with file_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if (
        not isinstance(payload, dict)
        or payload.get("date") != date
        or not isinstance(payload.get("snapshots"), list)
    ):
        raise ValueError(f"Invalid passive neighbourhood log: {file_path}")
    return payload


def append_passive_neighbourhood_snapshot(
    *, client_id, reporter, observed_at, observations, received_at=None
):
    """Append a validated passive snapshot and return its daily JSON path."""
    received_at = received_at or datetime.now(timezone.utc)
    if received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=timezone.utc)
    received_at = received_at.astimezone(timezone.utc)

    storage_dir = get_passive_neighbourhood_storage_dir()
    storage_dir.mkdir(parents=True, exist_ok=True)
    file_path = _daily_snapshot_path(storage_dir, received_at)
    entry = {
        "received_at": received_at.isoformat(),
        "client_id": client_id,
        "reporter": reporter,
        "observed_at": observed_at,
        "observation_count": len(observations),
        "observations": observations,
    }

    with _STORAGE_LOCK:
        payload = _load_daily_snapshot_file(file_path, received_at)
        payload["snapshots"].append(entry)
        _write_json_atomically(file_path, payload)

    return str(file_path)
