"""In-memory flow aggregation and idle-timeout finalization (v2 §3.2, §7.2).

Consumes the same normalized per-packet observation records produced by
``packet_extractor.extract_metadata_from_scapy`` (already used by the V1
``PacketObserver`` for raw packet storage) and aggregates them into flow
records. A flow is keyed by the unordered 5-tuple
``(src_ip, dst_ip, src_port, dst_port, protocol)`` so that both directions of
one conversation map to a single flow. Flows are finalized (removed from the
in-memory table and appended to ``flows.json``) after an idle timeout with no
matching packets.

This module has no knowledge of packet capture (Scapy) or storage rotation
details beyond calling into ``telemetry_storage.RotatingJSONAppendStore``.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from telemetry_storage import RotatingJSONAppendStore, get_flows_path

LOG = logging.getLogger("flow_aggregator")

DEFAULT_FLOW_IDLE_TIMEOUT_SECONDS = 45.0
DEFAULT_SWEEP_INTERVAL_SECONDS = 5.0


def _iso_to_epoch_ms(timestamp: str) -> int:
    """Convert an ISO-8601 'Z' timestamp string to epoch milliseconds."""
    try:
        dt = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%fZ")
        dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except (ValueError, TypeError):
        return int(time.time() * 1000)


def _parse_iso(timestamp: str) -> Optional[datetime]:
    try:
        dt = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%fZ")
        return dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _flow_key(obs: Dict[str, Any]):
    """Return an unordered key so both directions of one conversation collide."""
    protocol = obs.get("protocol") or "UNKNOWN"
    src_ip = obs.get("src_ip")
    dst_ip = obs.get("dst_ip")
    src_port = obs.get("src_port")
    dst_port = obs.get("dst_port")
    endpoint_a = (src_ip, src_port)
    endpoint_b = (dst_ip, dst_port)
    if endpoint_a <= endpoint_b:
        return (protocol, endpoint_a, endpoint_b)
    return (protocol, endpoint_b, endpoint_a)


class _ActiveFlow:
    """Mutable in-progress flow accumulator."""

    __slots__ = (
        "observer_client_id",
        "first_seen",
        "last_seen",
        "src_mac",
        "dst_mac",
        "src_ip",
        "dst_ip",
        "src_port",
        "dst_port",
        "protocol",
        "application_protocol",
        "direction",
        "packet_count",
        "bytes_total",
        "packet_sizes_sum",
        "min_packet_size",
        "max_packet_size",
        "tcp_syn",
        "tcp_fin",
        "tcp_rst",
        "inbound_packets",
        "outbound_packets",
        "inbound_bytes",
        "outbound_bytes",
        "last_packet_monotonic",
        "inter_arrival_sum",
        "inter_arrival_count",
        "last_seen_monotonic",
    )

    def __init__(self, obs: Dict[str, Any], observer_client_id: Optional[str]):
        self.observer_client_id = observer_client_id or obs.get("observer_client_id")
        self.first_seen = obs.get("timestamp")
        self.last_seen = obs.get("timestamp")
        self.src_mac = obs.get("src_mac")
        self.dst_mac = obs.get("dst_mac")
        self.src_ip = obs.get("src_ip")
        self.dst_ip = obs.get("dst_ip")
        self.src_port = obs.get("src_port")
        self.dst_port = obs.get("dst_port")
        self.protocol = obs.get("protocol") or "UNKNOWN"
        self.application_protocol = _application_protocol(obs)
        self.direction = obs.get("direction", "unknown")
        self.packet_count = 0
        self.bytes_total = 0
        self.packet_sizes_sum = 0
        self.min_packet_size: Optional[int] = None
        self.max_packet_size: Optional[int] = None
        self.tcp_syn = 0
        self.tcp_fin = 0
        self.tcp_rst = 0
        self.inbound_packets = 0
        self.outbound_packets = 0
        self.inbound_bytes = 0
        self.outbound_bytes = 0
        self.last_packet_monotonic = time.monotonic()
        self.inter_arrival_sum = 0.0
        self.inter_arrival_count = 0
        self.last_seen_monotonic = time.monotonic()

    def update(self, obs: Dict[str, Any]) -> None:
        now_mono = time.monotonic()
        gap = now_mono - self.last_packet_monotonic
        if self.packet_count > 0 and gap >= 0:
            self.inter_arrival_sum += gap
            self.inter_arrival_count += 1
        self.last_packet_monotonic = now_mono
        self.last_seen_monotonic = now_mono

        packet_length = obs.get("packet_length") or 0
        self.packet_count += 1
        self.bytes_total += packet_length
        self.packet_sizes_sum += packet_length
        if self.min_packet_size is None or packet_length < self.min_packet_size:
            self.min_packet_size = packet_length
        if self.max_packet_size is None or packet_length > self.max_packet_size:
            self.max_packet_size = packet_length

        timestamp = obs.get("timestamp")
        if timestamp:
            if not self.first_seen:
                self.first_seen = timestamp
            self.last_seen = timestamp

        direction = obs.get("direction", "unknown")
        if direction == "outbound":
            self.outbound_packets += 1
            self.outbound_bytes += packet_length
        elif direction == "inbound":
            self.inbound_packets += 1
            self.inbound_bytes += packet_length

        tcp_flags = obs.get("tcp_flags") or ""
        if "S" in tcp_flags:
            self.tcp_syn += 1
        if "F" in tcp_flags:
            self.tcp_fin += 1
        if "R" in tcp_flags:
            self.tcp_rst += 1

        if not self.application_protocol:
            self.application_protocol = _application_protocol(obs)

    def idle_seconds(self) -> float:
        return time.monotonic() - self.last_seen_monotonic

    def to_record(self, observer_client_id: Optional[str]) -> Dict[str, Any]:
        first_seen = self.first_seen or datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.%f"
        )[:-3] + "Z"
        last_seen = self.last_seen or first_seen
        duration = 0.0
        first_dt = _parse_iso(first_seen)
        last_dt = _parse_iso(last_seen)
        if first_dt and last_dt:
            duration = max(0.0, (last_dt - first_dt).total_seconds())

        avg_packet_size = (
            round(self.packet_sizes_sum / self.packet_count, 2)
            if self.packet_count
            else 0.0
        )
        avg_inter_arrival_time = (
            round(self.inter_arrival_sum / self.inter_arrival_count, 3)
            if self.inter_arrival_count
            else 0.0
        )

        record: Dict[str, Any] = {
            "flow_id": f"{observer_client_id or self.observer_client_id or 'unknown'}-{_iso_to_epoch_ms(first_seen)}",
            "observer_client_id": observer_client_id or self.observer_client_id,
            "first_seen": first_seen,
            "last_seen": last_seen,
            "src_mac": self.src_mac,
            "src_ip": self.src_ip,
            "dst_mac": self.dst_mac,
            "dst_ip": self.dst_ip,
            "src_port": self.src_port,
            "dst_port": self.dst_port,
            "protocol": self.protocol,
            "application_protocol": self.application_protocol,
            "direction": self.direction,
            "packet_count": self.packet_count,
            "bytes": self.bytes_total,
            "duration": round(duration, 3),
            "avg_packet_size": avg_packet_size,
            "min_packet_size": self.min_packet_size or 0,
            "max_packet_size": self.max_packet_size or 0,
            "tcp_syn": self.tcp_syn,
            "tcp_fin": self.tcp_fin,
            "tcp_rst": self.tcp_rst,
            "inbound_packets": self.inbound_packets,
            "outbound_packets": self.outbound_packets,
            "inbound_bytes": self.inbound_bytes,
            "outbound_bytes": self.outbound_bytes,
            "avg_inter_arrival_time": avg_inter_arrival_time,
        }
        return record


_APPLICATION_PROTOCOL_BY_PORT = {
    80: "HTTP",
    443: "HTTPS",
    53: "DNS",
    67: "DHCP",
    68: "DHCP",
    5353: "MDNS",
    5355: "LLMNR",
    137: "NBNS",
    1900: "SSDP",
}


def _application_protocol(obs: Dict[str, Any]) -> Optional[str]:
    """Best-effort application-layer label reusing packet_extractor's classification."""
    protocol = obs.get("protocol")
    if protocol and protocol.upper() not in ("TCP", "UDP", "IP", "UNKNOWN"):
        # packet_extractor already classified this as DHCP/mDNS/LLMNR/NBNS/SSDP/DNS/TLS
        return protocol.upper()
    for port in (obs.get("src_port"), obs.get("dst_port")):
        if port in _APPLICATION_PROTOCOL_BY_PORT:
            return _APPLICATION_PROTOCOL_BY_PORT[port]
    return None


class FlowAggregator:
    """Maintains in-memory active flows and finalizes them to flows.json on idle timeout."""

    def __init__(
        self,
        *,
        observer_client_id: Optional[str] = None,
        idle_timeout_seconds: float = DEFAULT_FLOW_IDLE_TIMEOUT_SECONDS,
        sweep_interval_seconds: float = DEFAULT_SWEEP_INTERVAL_SECONDS,
        date_provider=None,
        root=None,
    ):
        self.observer_client_id = observer_client_id
        self.idle_timeout_seconds = idle_timeout_seconds
        self.sweep_interval_seconds = sweep_interval_seconds
        self._date_provider = date_provider or (
            lambda: datetime.now().astimezone().date().isoformat()
        )
        self._root = root

        self._lock = threading.RLock()
        self._flows: Dict[Any, _ActiveFlow] = {}
        self._stores: Dict[str, RotatingJSONAppendStore] = {}

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def _store_for_today(self) -> RotatingJSONAppendStore:
        date_str = self._date_provider()
        store = self._stores.get(date_str)
        if store is None:
            kwargs = {}
            if self._root is not None:
                kwargs["root"] = self._root
            path = get_flows_path(date_str, **kwargs)
            store = RotatingJSONAppendStore(path)
            self._stores[date_str] = store
        return store

    def record_packet(self, obs: Dict[str, Any]) -> None:
        """Update (or create) the flow matching this normalized packet observation."""
        if not isinstance(obs, dict):
            return
        with self._lock:
            key = _flow_key(obs)
            flow = self._flows.get(key)
            if flow is None:
                flow = _ActiveFlow(obs, self.observer_client_id)
                self._flows[key] = flow
            flow.update(obs)

    def _finalize_flow(self, key) -> None:
        """Remove one flow from the table and append its record. Caller holds lock."""
        flow = self._flows.pop(key, None)
        if flow is None or flow.packet_count == 0:
            return
        record = flow.to_record(self.observer_client_id)
        try:
            self._store_for_today().append(record)
        except OSError as error:
            LOG.warning("[FLOW_AGGREGATOR] Could not persist finalized flow: %s", error)

    def sweep_idle_flows(self) -> int:
        """Finalize and persist all flows idle longer than the configured timeout."""
        finalized = 0
        with self._lock:
            expired_keys = [
                key
                for key, flow in self._flows.items()
                if flow.idle_seconds() >= self.idle_timeout_seconds
            ]
            for key in expired_keys:
                self._finalize_flow(key)
                finalized += 1
        return finalized

    def flush_all(self) -> int:
        """Finalize every active flow regardless of idle time (used on shutdown)."""
        finalized = 0
        with self._lock:
            for key in list(self._flows.keys()):
                self._finalize_flow(key)
                finalized += 1
        return finalized

    @property
    def active_flow_count(self) -> int:
        with self._lock:
            return len(self._flows)

    def start(self) -> None:
        """Start the background idle-timeout sweep thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._sweep_loop, daemon=True, name="flow-aggregator-sweep"
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the sweep thread and flush all remaining flows."""
        if self._thread:
            self._stop_event.set()
            self._thread.join(timeout=3.0)
            self._thread = None
        self.flush_all()

    def _sweep_loop(self) -> None:
        while not self._stop_event.wait(self.sweep_interval_seconds):
            try:
                self.sweep_idle_flows()
            except Exception as error:  # pragma: no cover - defensive
                LOG.debug("[FLOW_AGGREGATOR] Sweep error: %s", error)
