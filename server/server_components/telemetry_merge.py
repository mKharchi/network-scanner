"""Server-side v2 telemetry delta merge service (v2 §3.5, §5, §7.7).

Only compact device identity/discovery and activity-window summaries are accepted.
Raw packets, flow records, location data, and scoring data are deliberately rejected.
"""

from __future__ import annotations

import ipaddress
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

try:
    from database import get_connection
except ImportError:  # pragma: no cover
    from ..database import get_connection


_MAC_RE = re.compile(r"^[0-9a-f]{12}$")
_DEVICE_FIELDS = {"mac", "ip", "hostname", "vendor", "os_guess", "last_seen", "discovery", "activity"}
_ACTIVITY_FIELDS = {
    "device_mac", "window_id", "window_start", "window_end", "active",
    "flow_count", "packet_count", "bytes", "protocols", "ports",
    "connections", "unique_destinations",
}
_TOP_LEVEL_FIELDS = {"client_id", "sync_timestamp", "window_id", "updated_devices"}
_FORBIDDEN_FIELDS = {
    "packets", "raw_packets", "flows", "flow_records", "packet_count_raw",
    "location", "position", "coordinates", "risk", "risk_level", "score",
    "rogue_score", "classification", "ml_score",
}


def _normalise_mac(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("device.mac must be a MAC address")
    compact = re.sub(r"[:-]", "", value.strip().lower())
    if not _MAC_RE.fullmatch(compact):
        raise ValueError(f"Invalid MAC address: {value!r}")
    return ":".join(compact[index:index + 2] for index in range(0, 12, 2)).upper()


def _optional_ip(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError("device.ip must be a string or null")
    try:
        ipaddress.ip_address(value)
    except ValueError as exc:
        raise ValueError(f"Invalid device.ip: {value!r}") from exc
    return value


def _parse_datetime(value: Any, field: str, *, required: bool = False) -> Optional[datetime]:
    if value is None or value == "":
        if required:
            raise ValueError(f"{field} is required")
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _ensure_allowed(fields: set[str], allowed: set[str], label: str) -> None:
    forbidden = fields & _FORBIDDEN_FIELDS
    if forbidden:
        raise ValueError(f"{label} contains forbidden fields: {', '.join(sorted(forbidden))}")
    unknown = fields - allowed
    if unknown:
        raise ValueError(f"{label} contains unsupported fields: {', '.join(sorted(unknown))}")


def validate_delta_payload(payload: Any) -> Dict[str, Any]:
    """Validate and normalize a v2 §3.5 delta without accepting raw data."""
    if not isinstance(payload, dict):
        raise ValueError("Telemetry sync payload must be an object")
    _ensure_allowed(set(payload), _TOP_LEVEL_FIELDS, "payload")
    client_id = payload.get("client_id")
    window_id = payload.get("window_id")
    devices = payload.get("updated_devices")
    if not isinstance(client_id, str) or not client_id.strip():
        raise ValueError("client_id is required")
    if not isinstance(window_id, str) or not window_id.strip():
        raise ValueError("window_id is required")
    _parse_datetime(payload.get("sync_timestamp"), "sync_timestamp", required=True)
    if not isinstance(devices, list):
        raise ValueError("updated_devices must be an array")

    normalized_devices = []
    for index, source in enumerate(devices):
        if not isinstance(source, dict):
            raise ValueError(f"updated_devices[{index}] must be an object")
        _ensure_allowed(set(source), _DEVICE_FIELDS, f"updated_devices[{index}]")
        mac = _normalise_mac(source.get("mac"))
        activity = source.get("activity")
        if not isinstance(activity, dict):
            raise ValueError(f"updated_devices[{index}].activity is required")
        _ensure_allowed(set(activity), _ACTIVITY_FIELDS, f"updated_devices[{index}].activity")
        if activity.get("device_mac", "").lower() != mac.lower():
            raise ValueError(f"updated_devices[{index}].activity.device_mac does not match mac")
        if activity.get("window_id") != window_id:
            raise ValueError(f"updated_devices[{index}].activity.window_id does not match payload window_id")
        for field in ("window_start", "window_end"):
            _parse_datetime(activity.get(field), f"activity.{field}", required=True)
        if not isinstance(activity.get("active"), bool):
            raise ValueError(f"updated_devices[{index}].activity.active must be boolean")
        for field in ("flow_count", "packet_count", "bytes", "unique_destinations"):
            value = activity.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"activity.{field} must be a non-negative integer")
        for field in ("protocols", "ports", "connections"):
            if not isinstance(activity.get(field), dict):
                raise ValueError(f"activity.{field} must be an object")
        discovery = source.get("discovery", {})
        if not isinstance(discovery, dict):
            raise ValueError(f"updated_devices[{index}].discovery must be an object")
        normalized_devices.append({
            "mac": mac,
            "ip": _optional_ip(source.get("ip")),
            "hostname": source.get("hostname"),
            "vendor": source.get("vendor"),
            "os_guess": source.get("os_guess"),
            "last_seen": _parse_datetime(source.get("last_seen"), "last_seen"),
            "discovery": discovery,
            "activity": {
                **activity,
                "device_mac": mac,
            },
        })

    return {
        "client_id": client_id.strip(),
        "sync_timestamp": _parse_datetime(payload.get("sync_timestamp"), "sync_timestamp", required=True),
        "window_id": window_id.strip(),
        "updated_devices": normalized_devices,
    }


def _row_value(row: Any, key: str, index: int = 0) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    return row[index]


def merge_telemetry_delta(payload: Any, *, conn=None) -> Dict[str, Any]:
    """Atomically merge one validated delta and deduplicate activity windows."""
    data = validate_delta_payload(payload)
    owns_connection = conn is None
    connection = conn or get_connection()
    if connection is None:
        raise RuntimeError("Database connection unavailable")
    cursor = connection.cursor()
    inserted_windows = 0
    updated_devices = 0
    try:
        for device in data["updated_devices"]:
            last_seen = device["last_seen"] or data["sync_timestamp"]
            cursor.execute(
                """
                INSERT INTO network_devices
                    (mac_address, ip_address, hostname, vendor, first_seen, last_seen)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    ip_address = COALESCE(VALUES(ip_address), ip_address),
                    hostname = COALESCE(VALUES(hostname), hostname),
                    vendor = COALESCE(VALUES(vendor), vendor),
                    first_seen = LEAST(first_seen, VALUES(first_seen)),
                    last_seen = GREATEST(last_seen, VALUES(last_seen)),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (device["mac"], device["ip"], device["hostname"], device["vendor"], last_seen, last_seen),
            )
            cursor.execute(
                """
                INSERT INTO telemetry_devices
                    (observer_client_id, device_mac, os_guess, discovery_json, last_seen)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    os_guess = COALESCE(VALUES(os_guess), os_guess),
                    discovery_json = VALUES(discovery_json),
                    last_seen = GREATEST(last_seen, VALUES(last_seen)),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (data["client_id"], device["mac"], device["os_guess"], json.dumps(device["discovery"]), last_seen),
            )
            activity = device["activity"]
            cursor.execute(
                "SELECT id FROM telemetry_activity_windows WHERE device_mac = %s AND window_id = %s LIMIT 1",
                (device["mac"], data["window_id"]),
            )
            if cursor.fetchone() is not None:
                continue
            cursor.execute(
                """
                INSERT INTO telemetry_activity_windows
                    (device_mac, observer_client_id, window_id, window_start, window_end,
                     active, flow_count, packet_count, bytes, protocols_json, ports_json,
                     connections_json, unique_destinations)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    device["mac"], data["client_id"], data["window_id"],
                    _parse_datetime(activity["window_start"], "activity.window_start", required=True),
                    _parse_datetime(activity["window_end"], "activity.window_end", required=True),
                    activity["active"], activity["flow_count"], activity["packet_count"], activity["bytes"],
                    json.dumps(activity["protocols"]), json.dumps(activity["ports"]),
                    json.dumps(activity["connections"]), activity["unique_destinations"],
                ),
            )
            inserted_windows += 1
            updated_devices += 1
        connection.commit()
        return {
            "status": "ack",
            "client_id": data["client_id"],
            "window_id": data["window_id"],
            "updated_devices": updated_devices,
            "inserted_windows": inserted_windows,
            "duplicate": inserted_windows == 0 and bool(data["updated_devices"]),
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        if owns_connection:
            connection.close()
