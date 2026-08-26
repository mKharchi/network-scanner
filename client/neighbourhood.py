"""Client-side normalized neighbourhood observations."""

from __future__ import annotations

import ipaddress
import json
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path


MAC_ADDRESS_PATTERN = re.compile(r"^[0-9A-F]{2}(?::[0-9A-F]{2}){5}$")
VALID_SOURCES = {"arp", "dhcp"}
DEFAULT_NEIGHBOURHOOD_STORAGE_DIR = (
    Path(__file__).resolve().parent / "storage" / "network_neighbourhood"
)
_DAILY_STORAGE_LOCK = threading.RLock()


def _normalise_mac_address(value):
    if not isinstance(value, str):
        return None
    mac_address = value.strip().replace("-", ":").upper()
    if not MAC_ADDRESS_PATTERN.fullmatch(mac_address):
        return None
    first_octet = int(mac_address[:2], 16)
    if mac_address == "FF:FF:FF:FF:FF:FF" or first_octet & 1:
        return None
    return mac_address


def _normalise_text(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > 255 or any(character in value for character in "\r\n\x00"):
        return None
    return value


def _observed_at(value=None):
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    if not isinstance(value, str):
        return None
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value


def normalise_neighbourhood_observation(record, *, source, observed_at=None):
    """Return one normalized ARP or DHCP observation, or ``None`` if invalid."""
    if not isinstance(record, dict) or source not in VALID_SOURCES:
        return None
    try:
        ip_address = ipaddress.ip_address(str(record.get("ip_address")).strip())
    except (TypeError, ValueError):
        return None
    if (
        ip_address.version != 4
        or ip_address.is_multicast
        or ip_address.is_unspecified
        or ip_address.is_loopback
        or ip_address.is_reserved
    ):
        return None

    mac_address = _normalise_mac_address(record.get("mac_address"))
    entry_type = record.get("entry_type")
    timestamp = _observed_at(observed_at or record.get("observed_at"))
    if not mac_address or entry_type not in {"dynamic", "static"} or not timestamp:
        return None

    normalized = {
        "ip_address": str(ip_address),
        "mac_address": mac_address,
        "hostname": _normalise_text(record.get("hostname")),
        "vendor": _normalise_text(record.get("vendor")),
        "os": _normalise_text(record.get("os")),
        "entry_type": entry_type,
        "interface": _normalise_text(record.get("interface")),
        "source": source,
        "sources": [source],
        "observed_at": timestamp,
    }
    if "rssi" in record and record["rssi"] is not None:
        try:
            rssi_val = int(record["rssi"])
            if -130 <= rssi_val <= 30:
                normalized["rssi"] = rssi_val
        except (TypeError, ValueError):
            pass
    switch_port = _normalise_text(record.get("switch_port"))
    if switch_port:
        normalized["switch_port"] = switch_port

    if source == "dhcp":
        message_type = record.get("dhcp_message_type")
        if isinstance(message_type, int) and 1 <= message_type <= 8:
            normalized["dhcp_message_type"] = message_type
        for key in ("dhcp_vendor_class", "dhcp_client_id"):
            value = _normalise_text(record.get(key))
            if value:
                normalized[key] = value
    return normalized


def normalise_dhcp_observation(observation, *, vendor=None, observed_at=None):
    """Adapt a parsed DHCP packet to the normalized neighbourhood schema."""
    if not isinstance(observation, dict):
        return None
    return normalise_neighbourhood_observation(
        {
            "ip_address": observation.get("requested_ip"),
            "mac_address": observation.get("mac_address"),
            "hostname": observation.get("hostname"),
            "vendor": vendor,
            "entry_type": "dynamic",
            "dhcp_message_type": observation.get("dhcp_message_type"),
            "dhcp_vendor_class": observation.get("vendor_class"),
            "dhcp_client_id": observation.get("client_id"),
        },
        source="dhcp",
        observed_at=observed_at,
    )


def merge_neighbourhood_observations(observations):
    """Merge same-device observations by MAC and IP while preserving metadata."""
    merged = {}
    for observation in observations or []:
        if not isinstance(observation, dict):
            continue
        normalized = normalise_neighbourhood_observation(
            observation,
            source=observation.get("source"),
            observed_at=observation.get("observed_at"),
        )
        if not normalized:
            continue
        key = (normalized["mac_address"], normalized["ip_address"])
        existing = merged.get(key)
        if existing is None:
            merged[key] = normalized
            continue
        for field in (
            "hostname", "vendor", "os", "interface", "dhcp_message_type",
            "dhcp_vendor_class", "dhcp_client_id", "switch_port",
        ):
            if normalized.get(field) and not existing.get(field):
                existing[field] = normalized[field]
        if normalized.get("rssi") is not None:
            existing["rssi"] = normalized["rssi"]
        for source in normalized["sources"]:
            if source not in existing["sources"]:
                existing["sources"].append(source)
        if normalized["observed_at"] > existing["observed_at"]:
            existing["observed_at"] = normalized["observed_at"]
            existing["source"] = normalized["source"]
            existing["entry_type"] = normalized["entry_type"]
    return list(merged.values())


def _local_date_string(value=None):
    if value is None:
        return datetime.now().astimezone().date().isoformat()
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).date().isoformat()
        except ValueError:
            return None
    return None


def get_daily_neighbourhood_path(*, date=None, storage_dir=None):
    """Return the daily local-neighbourhood path without creating it."""
    date_string = _local_date_string(date)
    if not date_string:
        raise ValueError("date must be an ISO-8601 date or datetime")
    directory = Path(storage_dir) if storage_dir is not None else DEFAULT_NEIGHBOURHOOD_STORAGE_DIR
    return directory / f"{date_string}.json"


def ensure_daily_neighbourhood(*, date=None, storage_dir=None):
    """Create a day's storage directory and valid empty file when absent."""
    date_string = _local_date_string(date)
    if not date_string:
        raise ValueError("date must be an ISO-8601 date or datetime")
    file_path = get_daily_neighbourhood_path(
        date=date_string, storage_dir=storage_dir
    )
    with _DAILY_STORAGE_LOCK:
        if not file_path.exists():
            _write_daily_neighbourhood(
                file_path,
                {"date": date_string, "observations": []},
            )
    return file_path


def load_daily_neighbourhood(*, date=None, storage_dir=None):
    """Load a day's local observations, creating an empty file if absent."""
    date_string = _local_date_string(date)
    if not date_string:
        raise ValueError("date must be an ISO-8601 date or datetime")
    file_path = ensure_daily_neighbourhood(
        date=date_string, storage_dir=storage_dir
    )
    try:
        with file_path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Daily neighbourhood file cannot be read: {file_path}") from error
    if (
        not isinstance(payload, dict)
        or payload.get("date") != date_string
        or not isinstance(payload.get("observations"), list)
    ):
        raise ValueError(f"Daily neighbourhood file has an invalid format: {file_path}")
    return payload


def _write_daily_neighbourhood(file_path, payload):
    file_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_path = tempfile.mkstemp(
        prefix=".neighbourhood_", suffix=".tmp", dir=file_path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(payload, file, indent=2, ensure_ascii=False)
            file.write("\n")
        os.replace(temporary_path, file_path)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)


def update_daily_neighbourhood(observations, *, date=None, storage_dir=None):
    """Merge observations into one current-day file, deduplicating by MAC and IP.

    This storage primitive intentionally has no collector or socket knowledge.
    Collection callbacks will begin invoking it in the next phase.
    """
    date_string = _local_date_string(date)
    if not date_string:
        raise ValueError("date must be an ISO-8601 date or datetime")
    file_path = get_daily_neighbourhood_path(date=date_string, storage_dir=storage_dir)
    with _DAILY_STORAGE_LOCK:
        payload = load_daily_neighbourhood(date=date_string, storage_dir=storage_dir)
        payload["observations"] = merge_neighbourhood_observations(
            [*payload["observations"], *(observations or [])]
        )
        _write_daily_neighbourhood(file_path, payload)
    return file_path, payload
