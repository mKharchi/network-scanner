"""Bounded on-demand flow detail queries for the v2 telemetry API.

Flow detail remains local until a server request explicitly asks for one device
and one activity window. This module only reads finalized flow JSON files; it
never reads or returns raw packet observations.
"""

from __future__ import annotations

import ipaddress
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from telemetry_storage import RotatingJSONAppendStore, get_flows_path


MAX_FLOW_QUERY_RESULTS = 10_000
_WINDOW_RE = re.compile(
    r"^(?P<start>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)"
    r"_(?P<end>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)$"
)


def _parse_iso(value: str) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_window_id(window_id: str) -> Tuple[datetime, datetime]:
    """Parse and validate a v2 ``<start>_<end>`` UTC window identifier."""
    match = _WINDOW_RE.fullmatch(window_id or "")
    if not match:
        raise ValueError("window must be '<start>_<end>' using UTC ISO-8601 timestamps")
    start = _parse_iso(match.group("start"))
    end = _parse_iso(match.group("end"))
    if start is None or end is None or end <= start:
        raise ValueError("window end must be later than window start")
    return start, end


def normalize_mac(mac: str) -> str:
    """Return a canonical uppercase colon-separated MAC address."""
    compact = re.sub(r"[:-]", "", mac or "").upper()
    if len(compact) != 12 or not re.fullmatch(r"[0-9A-F]{12}", compact):
        raise ValueError("device_mac must be a valid MAC address")
    return ":".join(compact[index:index + 2] for index in range(0, 12, 2))


def _date_range(start: datetime, end: datetime):
    current = start.date()
    last = end.date()
    while current <= last:
        yield current.isoformat()
        current += timedelta(days=1)


def _flow_timestamp(flow: Dict[str, Any]) -> Optional[datetime]:
    return _parse_iso(flow.get("last_seen"))


def query_flows(
    device_mac: str,
    window_id: str,
    *,
    root=None,
    max_results: int = MAX_FLOW_QUERY_RESULTS,
) -> List[Dict[str, Any]]:
    """Return finalized flows for one device whose ``last_seen`` is in a window.

    Both active and numbered rotated ``flows.json`` files are read for every
    calendar day touched by the requested window. Results are sorted by
    ``first_seen`` and capped before they can cross the client/server boundary.
    """
    normalized_mac = normalize_mac(device_mac).lower()
    start, end = parse_window_id(window_id)
    if not isinstance(max_results, int) or max_results <= 0:
        raise ValueError("max_results must be a positive integer")

    matched: List[Dict[str, Any]] = []
    for date_str in _date_range(start, end):
        kwargs = {"root": root} if root is not None else {}
        store = RotatingJSONAppendStore(get_flows_path(date_str, **kwargs))
        for flow in store.read_all_including_rotated():
            if not isinstance(flow, dict):
                continue
            participant_macs = {
                str(flow.get("src_mac") or "").replace("-", ":").lower(),
                str(flow.get("dst_mac") or "").replace("-", ":").lower(),
            }
            if normalized_mac not in participant_macs:
                continue
            timestamp = _flow_timestamp(flow)
            if timestamp is None or not (start <= timestamp < end):
                continue
            matched.append(flow)
            if len(matched) > max_results:
                raise ValueError("flow query result exceeds the configured result limit")

    matched.sort(key=lambda flow: (flow.get("first_seen") or "", flow.get("flow_id") or ""))
    return matched


def get_requested_flows(message: Dict[str, Any], *, root=None) -> Dict[str, Any]:
    """Validate a command and return its bounded response payload."""
    args = message.get("args") if isinstance(message, dict) else None
    if not isinstance(args, dict):
        raise ValueError("flow query arguments are required")
    device_mac = args.get("device_mac") or args.get("mac")
    window_id = args.get("window") or args.get("window_id")
    if not isinstance(device_mac, str) or not isinstance(window_id, str):
        raise ValueError("device_mac and window are required")
    normalize_mac(device_mac)
    parse_window_id(window_id)
    flows = query_flows(device_mac, window_id, root=root)
    return {
        "status": "ok",
        "device_mac": normalize_mac(device_mac).lower(),
        "window_id": window_id,
        "flows": flows,
        "flow_count": len(flows),
    }
