"""Event Broadcaster for Real-Time SSE (Server-Sent Events) Stream.

Maintains thread-safe subscriber queues and broadcasts real-time telemetry,
alerts, and client connection state transitions to connected GUI clients.
"""

from __future__ import annotations

import json
import queue
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Set, Tuple


_SUBSCRIBERS_LOCK = threading.Lock()
_SUBSCRIBERS: Set[queue.Queue] = set()


def subscribe() -> queue.Queue:
    """Register a new client subscriber queue for SSE streaming."""
    q: queue.Queue = queue.Queue(maxsize=256)
    with _SUBSCRIBERS_LOCK:
        _SUBSCRIBERS.add(q)
    return q


def unsubscribe(q: queue.Queue) -> None:
    """Remove a disconnected client subscriber queue."""
    with _SUBSCRIBERS_LOCK:
        _SUBSCRIBERS.discard(q)


def broadcast(event_type: str, data: Dict[str, Any]) -> None:
    """Dispatch an event payload to all active subscriber queues."""
    payload = (event_type, data)
    with _SUBSCRIBERS_LOCK:
        dead_queues = []
        for q in _SUBSCRIBERS:
            try:
                q.put_nowait(payload)
            except queue.Full:
                # Discard stale or blocked subscriber
                dead_queues.append(q)

        for dq in dead_queues:
            _SUBSCRIBERS.discard(dq)


def broadcast_alert(alert_data: Dict[str, Any]) -> None:
    """Convenience helper to broadcast an alert event."""
    if "detected_at" not in alert_data:
        alert_data["detected_at"] = datetime.now(timezone.utc).isoformat()
    broadcast("alert", alert_data)


def broadcast_client_status(client_id: str, mac: str, hostname: str, state: str, ip: str = "") -> None:
    """Convenience helper to broadcast a client state transition (ONLINE / OFFLINE)."""
    broadcast("client_status", {
        "client_id": client_id,
        "mac_address": mac,
        "hostname": hostname,
        "state": state,
        "ip_address": ip,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


def broadcast_network_update(scan_id: str, devices_found: int) -> None:
    """Convenience helper to broadcast a completed network scan."""
    broadcast("network_update", {
        "scan_id": scan_id,
        "devices_found": devices_found,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


def broadcast_dhcp_update(dhcp_info: Dict[str, Any]) -> None:
    """Convenience helper to broadcast a new DHCP observation packet."""
    broadcast("dhcp_update", {
        "dhcp": dhcp_info,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
