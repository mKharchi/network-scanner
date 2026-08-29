"""Shared recency helpers for live/active device views."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, List, Optional, Sequence, Tuple

# Default live window for twin, latest-scan, and rogue overlays.
DEFAULT_DEVICE_ACTIVE_MAX_AGE_SECONDS = 300  # 10 minutes


def get_device_active_max_age_seconds() -> int:
    raw = os.getenv(
        "NETWORK_DEVICE_ACTIVE_MAX_AGE_SECONDS",
        str(DEFAULT_DEVICE_ACTIVE_MAX_AGE_SECONDS),
    )
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_DEVICE_ACTIVE_MAX_AGE_SECONDS


def coerce_datetime(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def active_cutoff(
    *,
    now: Optional[datetime] = None,
    max_age_seconds: Optional[int] = None,
) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    age = (
        get_device_active_max_age_seconds()
        if max_age_seconds is None
        else max(1, int(max_age_seconds))
    )
    return current - timedelta(seconds=age)


def is_timestamp_active(
    value: Any,
    *,
    cutoff: datetime,
) -> bool:
    observed = coerce_datetime(value)
    if observed is None:
        return False
    cutoff_aware = cutoff if cutoff.tzinfo else cutoff.replace(tzinfo=timezone.utc)
    return observed >= cutoff_aware


def is_device_record_active(
    record: dict,
    *,
    cutoff: datetime,
    timestamp_fields: Sequence[str] = ("last_seen", "last_observed_at"),
) -> bool:
    return any(
        is_timestamp_active(record.get(field), cutoff=cutoff)
        for field in timestamp_fields
    )


def is_client_record_active(
    record: dict,
    *,
    cutoff: datetime,
) -> bool:
    return any(
        is_timestamp_active(record.get(field), cutoff=cutoff)
        for field in ("device_last_seen", "health_updated_at", "updated_at")
    )


def filter_active_devices(
    devices: Iterable[dict],
    *,
    max_age_seconds: Optional[int] = None,
    now: Optional[datetime] = None,
    timestamp_field: str = "last_observed_at",
) -> Tuple[List[dict], datetime, int]:
    """Return devices observed within the active window."""
    window = (
        get_device_active_max_age_seconds()
        if max_age_seconds is None
        else max(1, int(max_age_seconds))
    )
    cutoff = active_cutoff(now=now, max_age_seconds=window)
    active = [
        device
        for device in devices
        if is_timestamp_active(device.get(timestamp_field), cutoff=cutoff)
    ]
    return active, cutoff, window


def active_filter_metadata(
    *,
    enabled: bool,
    cutoff: Optional[datetime],
    max_age_seconds: int,
    total_before: int,
    total_after: int,
) -> dict:
    return {
        "enabled": enabled,
        "max_age_seconds": max_age_seconds,
        "cutoff": cutoff.isoformat() if cutoff else None,
        "total_before_filter": total_before,
        "total_after_filter": total_after,
    }
