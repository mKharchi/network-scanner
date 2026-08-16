"""Filesystem storage for completed network-discovery results.

This is intentionally temporary scan-result storage. Database-backed scan
history will replace it in the database milestone.
"""

import json
import os
from datetime import datetime, timezone


DEFAULT_STORAGE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "storage",
    "network_scans",
)


def store_network_scan(context, devices, completed_at=None):
    """Persist one completed scan and return its absolute JSON path."""
    completed_at = completed_at or datetime.now(timezone.utc)
    storage_dir = os.getenv("NETWORK_SCAN_STORAGE_DIR", DEFAULT_STORAGE_DIR)
    os.makedirs(storage_dir, exist_ok=True)

    timestamp = completed_at.strftime("%Y-%m-%d_%H-%M-%S_%f")
    file_path = os.path.abspath(os.path.join(storage_dir, f"{timestamp}.json"))
    payload = {
        "completed_at": completed_at.isoformat(),
        "network": context,
        "devices_found": len(devices),
        "devices": devices,
    }

    with open(file_path, "x", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, ensure_ascii=False)

    return file_path
