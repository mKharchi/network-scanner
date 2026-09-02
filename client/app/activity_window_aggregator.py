"""Activity Window Aggregator — 15-minute per-device flow summary (v2 §3.4, §7.5).

Every 15 minutes, consumes ``flows.json`` entries whose ``last_seen`` falls
inside the just-closed window, groups them by device MAC (a flow's
participant MACs are whichever of its ``src_mac``/``dst_mac`` match a known
local device from ``devices.json``), and emits one activity-window record per
known device — including an explicit ``active: false`` record with all
counters at zero for devices with no matching flows this window, per v2's
explicit requirement not to omit idle devices.

This module does **not** re-scan raw packet files (v2 §3.4 / §7.5
instruction); it only reads the already-aggregated ``flows.json``.
"""

from __future__ import annotations

import ipaddress
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from telemetry_storage import (
    RotatingJSONAppendStore,
    atomic_write_json,
    get_activity_window_path,
    get_devices_path,
    get_flows_path,
    read_json,
)

LOG = logging.getLogger("activity_window_aggregator")

DEFAULT_WINDOW_SECONDS = 900  # 15 minutes


def _parse_iso(timestamp: Optional[str]) -> Optional[datetime]:
    if not isinstance(timestamp, str):
        return None
    try:
        dt = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%fZ")
        return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            dt = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None


def _format_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z"


def _format_file_label(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%H-%M")


def _is_private_ip(ip_str: Optional[str]) -> Optional[bool]:
    if not ip_str:
        return None
    try:
        return ipaddress.ip_address(ip_str).is_private
    except ValueError:
        return None


def compute_window_bounds(window_end: datetime, window_seconds: int = DEFAULT_WINDOW_SECONDS):
    """Return (window_start, window_end) aligned so window_end - window_start == window_seconds."""
    window_start = window_end - timedelta(seconds=window_seconds)
    return window_start, window_end


def _flow_participant_macs(flow: Dict[str, Any], known_macs: set) -> List[str]:
    """Return which of a flow's src/dst MACs correspond to known local devices."""
    participants = []
    for mac_field in ("src_mac", "dst_mac"):
        mac = flow.get(mac_field)
        if isinstance(mac, str) and mac.lower() in known_macs:
            participants.append(mac.lower())
    return participants


class _DeviceAccumulator:
    __slots__ = (
        "flow_count",
        "packet_count",
        "bytes_total",
        "protocols",
        "ports",
        "internal",
        "external",
        "unique_destinations",
    )

    def __init__(self):
        self.flow_count = 0
        self.packet_count = 0
        self.bytes_total = 0
        self.protocols: Dict[str, int] = {}
        self.ports: Dict[str, int] = {}
        self.internal = 0
        self.external = 0
        self.unique_destinations: set = set()

    def add_flow(self, flow: Dict[str, Any], device_mac: str) -> None:
        self.flow_count += 1
        packet_count = flow.get("packet_count") or 0
        self.packet_count += packet_count
        self.bytes_total += flow.get("bytes") or 0

        protocol = flow.get("protocol") or "UNKNOWN"
        self.protocols[protocol] = self.protocols.get(protocol, 0) + packet_count

        # Classify the "other side" port as the relevant service port for this device.
        src_mac = (flow.get("src_mac") or "").lower()
        if src_mac == device_mac:
            other_port = flow.get("dst_port")
            other_ip = flow.get("dst_ip")
        else:
            other_port = flow.get("src_port")
            other_ip = flow.get("src_ip")

        if other_port is not None:
            port_key = str(other_port)
            self.ports[port_key] = self.ports.get(port_key, 0) + 1

        if other_ip:
            self.unique_destinations.add(other_ip)

        src_private = _is_private_ip(flow.get("src_ip"))
        dst_private = _is_private_ip(flow.get("dst_ip"))
        if src_private is True and dst_private is True:
            self.internal += 1
        elif src_private is False or dst_private is False:
            self.external += 1
        # Unknown IP family/parse failures are neither counted as internal nor external.

    def to_record(self, device_mac: str, window_id: str, window_start_iso: str, window_end_iso: str) -> Dict[str, Any]:
        return {
            "device_mac": device_mac,
            "window_id": window_id,
            "window_start": window_start_iso,
            "window_end": window_end_iso,
            "active": self.flow_count > 0,
            "flow_count": self.flow_count,
            "packet_count": self.packet_count,
            "bytes": self.bytes_total,
            "protocols": dict(self.protocols),
            "ports": dict(self.ports),
            "connections": {"internal": self.internal, "external": self.external},
            "unique_destinations": len(self.unique_destinations),
        }


def _inactive_record(device_mac: str, window_id: str, window_start_iso: str, window_end_iso: str) -> Dict[str, Any]:
    return {
        "device_mac": device_mac,
        "window_id": window_id,
        "window_start": window_start_iso,
        "window_end": window_end_iso,
        "active": False,
        "flow_count": 0,
        "packet_count": 0,
        "bytes": 0,
        "protocols": {},
        "ports": {},
        "connections": {"internal": 0, "external": 0},
        "unique_destinations": 0,
    }


def build_activity_window_records(
    flows: List[Dict[str, Any]],
    known_device_macs: List[str],
    window_start: datetime,
    window_end: datetime,
) -> List[Dict[str, Any]]:
    """Build one activity-window record per known device for the given window.

    ``flows`` should already be filtered to those whose last_seen falls
    inside [window_start, window_end). Devices with no matching flows still
    get an explicit inactive record.
    """
    window_id = f"{_format_iso(window_start)}_{_format_iso(window_end)}"
    window_start_iso = _format_iso(window_start)
    window_end_iso = _format_iso(window_end)

    known_macs_lower = {mac.lower() for mac in known_device_macs if isinstance(mac, str)}
    accumulators: Dict[str, _DeviceAccumulator] = {mac: _DeviceAccumulator() for mac in known_macs_lower}

    for flow in flows:
        if not isinstance(flow, dict):
            continue
        for mac in _flow_participant_macs(flow, known_macs_lower):
            accumulators[mac].add_flow(flow, mac)

    records = []
    for mac in sorted(known_macs_lower):
        accumulator = accumulators[mac]
        if accumulator.flow_count > 0:
            records.append(accumulator.to_record(mac, window_id, window_start_iso, window_end_iso))
        else:
            records.append(_inactive_record(mac, window_id, window_start_iso, window_end_iso))
    return records


def _flow_in_window(flow: Dict[str, Any], window_start: datetime, window_end: datetime) -> bool:
    last_seen = _parse_iso(flow.get("last_seen"))
    if last_seen is None:
        return False
    return window_start <= last_seen < window_end


class ActivityWindowAggregator:
    """Runs the 15-minute activity window aggregation cycle on a background thread."""

    def __init__(
        self,
        *,
        interval_seconds: float = DEFAULT_WINDOW_SECONDS,
        date_provider=None,
        now_provider: Optional[Callable[[], datetime]] = None,
        root=None,
        on_window_closed: Optional[Callable[[str, List[Dict[str, Any]]], None]] = None,
    ):
        self.interval_seconds = interval_seconds
        self._date_provider = date_provider or (
            lambda: datetime.now().astimezone().date().isoformat()
        )
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self._root = root
        self._on_window_closed = on_window_closed

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def _kwargs(self):
        return {"root": self._root} if self._root is not None else {}

    def _load_known_device_macs(self, date_str: str) -> List[str]:
        devices_path = get_devices_path(date_str, **self._kwargs())
        devices = read_json(devices_path, default=[]) or []
        return [d.get("mac") for d in devices if isinstance(d, dict) and d.get("mac")]

    def _load_flows(self, date_str: str) -> List[Dict[str, Any]]:
        flows_path = get_flows_path(date_str, **self._kwargs())
        store = RotatingJSONAppendStore(flows_path)
        return store.read_all()

    def run_once(self, *, window_end: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """Execute one aggregation cycle synchronously; returns the written records."""
        window_end = window_end or self._now_provider()
        window_start, window_end = compute_window_bounds(window_end, int(self.interval_seconds))
        date_str = self._date_provider()

        known_macs = self._load_known_device_macs(date_str)
        all_flows = self._load_flows(date_str)
        windowed_flows = [f for f in all_flows if _flow_in_window(f, window_start, window_end)]

        records = build_activity_window_records(windowed_flows, known_macs, window_start, window_end)

        window_path = get_activity_window_path(
            date_str,
            _format_file_label(window_start),
            _format_file_label(window_end),
            **self._kwargs(),
        )
        atomic_write_json(window_path, records)

        window_id = f"{_format_iso(window_start)}_{_format_iso(window_end)}"
        if self._on_window_closed:
            try:
                self._on_window_closed(window_id, records)
            except Exception as error:  # pragma: no cover - defensive
                LOG.warning("[ACTIVITY_WINDOW] on_window_closed callback failed: %s", error)

        return records

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="activity-window-aggregator"
        )
        self._thread.start()

    def stop(self) -> None:
        if self._thread:
            self._stop_event.set()
            self._thread.join(timeout=3.0)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop_event.wait(self.interval_seconds):
            try:
                self.run_once()
            except Exception as error:  # pragma: no cover - defensive
                LOG.warning("[ACTIVITY_WINDOW] Cycle failed: %s", error)
