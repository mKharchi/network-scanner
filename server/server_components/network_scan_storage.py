"""Filesystem storage for completed network-discovery results.

This is intentionally temporary scan-result storage. Database-backed scan
history will replace it in the database milestone.
"""

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path


SERVER_DIRECTORY = Path(__file__).resolve().parents[1]
PROJECT_DIRECTORY = SERVER_DIRECTORY.parent
DEFAULT_STORAGE_DIR = str(SERVER_DIRECTORY / "storage" / "network_scans")


def get_network_scan_storage_dir():
    """Return the configured scan directory as an absolute stable path."""
    configured_dir = Path(os.getenv("NETWORK_SCAN_STORAGE_DIR", DEFAULT_STORAGE_DIR))
    if configured_dir.is_absolute():
        return configured_dir
    return (PROJECT_DIRECTORY / configured_dir).resolve()


NETWORK_SCAN_STORAGE_DIR = get_network_scan_storage_dir()
_DAILY_LOG_LOCK = threading.Lock()


def _daily_dhcp_log_path(storage_dir, observed_at):
    """Return the server-local daily file path for DHCP observations."""
    date = observed_at.astimezone().strftime("%Y-%m-%d")
    return os.path.abspath(os.path.join(storage_dir, f"network_scan_{date}.json"))


def _safe_dhcp_details(dhcp):
    """Keep the optional DHCP metadata readable and bounded in the log."""
    if not isinstance(dhcp, dict):
        return {}

    details = {}
    message_type = dhcp.get("message_type")
    if isinstance(message_type, int) and 1 <= message_type <= 8:
        details["message_type"] = message_type
    for key in ("vendor_class", "client_id"):
        value = dhcp.get(key)
        if (
            isinstance(value, str)
            and value.strip()
            and len(value.strip()) <= 255
            and not any(character in value for character in "\r\n\x00")
        ):
            details[key] = value.strip()
    return details


def _write_json_atomically(file_path, payload):
    """Replace a JSON log without leaving a partially written file behind."""
    descriptor, temporary_path = tempfile.mkstemp(
        prefix=".network_scan_", suffix=".tmp", dir=os.path.dirname(file_path)
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(payload, file, indent=2, ensure_ascii=False)
            file.write("\n")
        # ``mkstemp`` creates files as owner-only (0600). The server can run
        # under a service account while VS Code runs as the developer, so make
        # the human-readable audit log readable after its atomic replacement.
        os.chmod(temporary_path, 0o644)
        os.replace(temporary_path, file_path)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)


def _load_daily_log(file_path, observed_at):
    """Load one daily log, including logs created by earlier DHCP-only code."""
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as file:
            payload = json.load(file)
        if not isinstance(payload, dict):
            raise ValueError(f"Daily network log has an invalid format: {file_path}")
    else:
        payload = {"date": observed_at.strftime("%Y-%m-%d")}

    if payload.get("date") != observed_at.strftime("%Y-%m-%d"):
        raise ValueError(f"Daily network log has an invalid date: {file_path}")
    if "dhcp_observations" not in payload:
        payload["dhcp_observations"] = []
    if "neighbour_snapshots" not in payload:
        payload["neighbour_snapshots"] = {}
    if not isinstance(payload["dhcp_observations"], list) or not isinstance(
        payload["neighbour_snapshots"], dict
    ):
        raise ValueError(f"Daily network log has an invalid format: {file_path}")
    return payload


def _daily_log_context(observed_at=None):
    observed_at = observed_at or datetime.now(timezone.utc)
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    observed_at = observed_at.astimezone()
    storage_dir = get_network_scan_storage_dir()
    os.makedirs(storage_dir, exist_ok=True)
    return observed_at, _daily_dhcp_log_path(storage_dir, observed_at)


def has_daily_neighbour_snapshot(reporter_mac, observed_at=None):
    """Return whether this client already supplied today's full snapshot."""
    observed_at, file_path = _daily_log_context(observed_at)
    with _DAILY_LOG_LOCK:
        if not os.path.exists(file_path):
            return False
        payload = _load_daily_log(file_path, observed_at)
        return reporter_mac in payload["neighbour_snapshots"]


def record_daily_neighbour_snapshot(reporter_mac, neighbours, observed_at=None):
    """Store one full neighbour snapshot per reporting client per day.

    Returns ``(file_path, created)``. A duplicate same-day snapshot is left
    unchanged, which lets the server enforce the once-per-day rule.
    """
    observed_at, file_path = _daily_log_context(observed_at)
    with _DAILY_LOG_LOCK:
        payload = _load_daily_log(file_path, observed_at)
        if reporter_mac in payload["neighbour_snapshots"]:
            return file_path, False
        payload["neighbour_snapshots"][reporter_mac] = {
            "received_at": observed_at.isoformat(),
            "neighbours": neighbours,
        }
        _write_json_atomically(file_path, payload)
    return file_path, True


def append_daily_dhcp_observation(
    reporter_mac, neighbours, dhcp=None, observed_at=None
):
    """Append one intercepted-DHCP report to ``network_scan_YYYY-MM-DD.json``.

    The database remains the source of truth. This file is a readable daily
    audit trail of the DHCP-derived observations that were accepted by it.
    """
    observed_at, file_path = _daily_log_context(observed_at)

    entry = {
        "received_at": observed_at.isoformat(),
        "reporting_client_mac": reporter_mac,
        "neighbours": neighbours,
    }
    details = _safe_dhcp_details(dhcp)
    if details:
        entry["dhcp"] = details

    with _DAILY_LOG_LOCK:
        payload = _load_daily_log(file_path, observed_at)
        payload["dhcp_observations"].append(entry)
        _write_json_atomically(file_path, payload)

    return file_path


def store_network_scan(context, devices, completed_at=None):
    """Persist one completed scan and return its absolute JSON path."""
    completed_at = completed_at or datetime.now(timezone.utc)
    storage_dir = get_network_scan_storage_dir()
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


def load_latest_network_scan():
    """Return the newest completed scan payload, or ``None`` when absent."""
    storage_dir = get_network_scan_storage_dir()
    if not storage_dir.is_dir():
        return None

    scan_files = sorted(
        (
            path
            for path in storage_dir.glob("*.json")
            if not path.name.startswith("network_scan_")
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for scan_file in scan_files:
        try:
            with open(scan_file, "r", encoding="utf-8") as file:
                payload = json.load(file)
            if isinstance(payload, dict) and isinstance(payload.get("devices"), list):
                return payload
        except (OSError, json.JSONDecodeError):
            continue
    return None
