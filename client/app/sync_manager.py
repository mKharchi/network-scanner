"""Client-side v2 telemetry delta synchronization (v2 §3.5, §5, §7.6).

The Sync Manager accepts already-aggregated activity-window records. It never
reads or transmits raw packet files. Each window is persisted before sending so
an interrupted client can retry it after reconnecting without rebuilding the
window from packets.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from telemetry_storage import atomic_write_json, get_devices_path, read_json

LOG = logging.getLogger("sync_manager")

SYNC_MESSAGE_TYPE = "TELEMETRY_SYNC"
SYNC_ACK_TYPE = "SYNC_ACK"
SYNC_NACK_TYPE = "SYNC_NACK"
SEED_MESSAGE_TYPE = "TELEMETRY_SEED"
DEFAULT_SYNC_INTERVAL_SECONDS = 900
DEFAULT_RETRY_BASE_SECONDS = 5.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_ACK_TIMEOUT_SECONDS = 15.0

_DEVICE_FIELDS = ("mac", "ip", "hostname", "vendor", "os_guess", "last_seen", "discovery")
_ACTIVITY_FIELDS = (
    "device_mac", "window_id", "window_start", "window_end", "active",
    "flow_count", "packet_count", "bytes", "protocols", "ports",
    "connections", "unique_destinations",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_window_key(window_id: str) -> str:
    digest = hashlib.sha256(window_id.encode("utf-8")).hexdigest()[:24]
    return f"{digest}.json"


def _copy_allowed(source: Dict[str, Any], fields: tuple[str, ...]) -> Dict[str, Any]:
    return {field: source[field] for field in fields if field in source}


def build_delta_payload(
    *,
    client_id: str,
    window_id: str,
    activity_records: List[Dict[str, Any]],
    devices: Optional[List[Dict[str, Any]]] = None,
    sync_timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a v2 §3.5 payload from device identity and activity summaries.

    Activity records are already the explicit per-device window output. The
    whitelist deliberately prevents packet/flow-level fields from crossing
    the sync boundary.
    """
    device_by_mac = {}
    for device in devices or []:
        if isinstance(device, dict) and isinstance(device.get("mac"), str):
            device_by_mac[device["mac"].lower()] = device

    updated_devices: List[Dict[str, Any]] = []
    seen_macs = set()
    for activity in activity_records:
        if not isinstance(activity, dict):
            continue
        mac = activity.get("device_mac")
        if not isinstance(mac, str) or not mac.strip():
            continue
        mac_key = mac.lower()
        if mac_key in seen_macs:
            continue
        if activity.get("window_id") not in (None, window_id):
            continue

        device = _copy_allowed(device_by_mac.get(mac_key, {"mac": mac_key}), _DEVICE_FIELDS)
        device["mac"] = str(device.get("mac") or mac_key).lower()
        safe_activity = _copy_allowed(activity, _ACTIVITY_FIELDS)
        safe_activity["device_mac"] = device["mac"]
        safe_activity["window_id"] = window_id
        device["activity"] = safe_activity
        updated_devices.append(device)
        seen_macs.add(mac_key)

    return {
        "client_id": str(client_id),
        "sync_timestamp": sync_timestamp or _utc_now_iso(),
        "window_id": str(window_id),
        "updated_devices": updated_devices,
    }


def build_seed_payload(
    *,
    client_id: str,
    devices: Optional[List[Dict[str, Any]]] = None,
    sync_timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a device-only initial inventory seed from local v2 device records.

    The seed uses the same identity/discovery allowlist as a delta but deliberately
    contains no activity window, raw packets, or flow-level data.
    """
    updated_devices: List[Dict[str, Any]] = []
    seen_macs = set()
    for device in devices or []:
        if not isinstance(device, dict) or not isinstance(device.get("mac"), str):
            continue
        mac = device["mac"].strip().lower()
        if not mac or mac in seen_macs:
            continue
        safe_device = _copy_allowed(device, _DEVICE_FIELDS)
        safe_device["mac"] = mac
        updated_devices.append(safe_device)
        seen_macs.add(mac)
    return {
        "client_id": str(client_id),
        "sync_timestamp": sync_timestamp or _utc_now_iso(),
        "updated_devices": updated_devices,
    }


class SyncManager:
    """Build, persist, send, and retry one delta per activity window."""

    def __init__(
        self,
        *,
        client_id: str,
        send_message: Callable[[Dict[str, Any]], None],
        root: Path | str | None = None,
        date_provider: Optional[Callable[[], str]] = None,
        now_provider: Optional[Callable[[], str]] = None,
        retry_base_seconds: float = DEFAULT_RETRY_BASE_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        ack_timeout_seconds: float = DEFAULT_ACK_TIMEOUT_SECONDS,
    ):
        if not str(client_id).strip():
            raise ValueError("client_id is required")
        self.client_id = str(client_id)
        self._send_message = send_message
        self._root = Path(root) if root is not None else None
        self._date_provider = date_provider or (lambda: datetime.now().astimezone().date().isoformat())
        self._now_provider = now_provider or _utc_now_iso
        self.retry_base_seconds = max(0.0, float(retry_base_seconds))
        self.max_retries = max(0, int(max_retries))
        self.ack_timeout_seconds = max(0.01, float(ack_timeout_seconds))
        self._lock = threading.RLock()
        self._ack_events: Dict[str, threading.Event] = {}
        self._ack_results: Dict[str, Dict[str, Any]] = {}
        self._workers: Dict[str, threading.Thread] = {}

    @property
    def _state_root(self) -> Path:
        root = self._root or (Path(__file__).resolve().parent.parent / "storage" / "network_telemetry")
        return root / "sync_pending"

    @property
    def _completed_path(self) -> Path:
        return self._state_root / "completed.json"

    def _pending_path(self, window_id: str) -> Path:
        return self._state_root / _safe_window_key(window_id)

    def _load_completed(self) -> List[str]:
        value = read_json(self._completed_path, default=[])
        return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []

    def _mark_completed(self, window_id: str) -> None:
        with self._lock:
            completed = self._load_completed()
            if window_id not in completed:
                completed.append(window_id)
            atomic_write_json(self._completed_path, completed[-500:])
            self._pending_path(window_id).unlink(missing_ok=True)

    def _load_devices(self) -> List[Dict[str, Any]]:
        devices = read_json(get_devices_path(self._date_provider(), root=self._telemetry_root()), default=[])
        return devices if isinstance(devices, list) else []

    def _telemetry_root(self) -> Path:
        if self._root is not None:
            return self._root
        return Path(__file__).resolve().parent.parent / "storage" / "network_telemetry"

    def build_payload(self, window_id: str, activity_records: List[Dict[str, Any]]) -> Dict[str, Any]:
        return build_delta_payload(
            client_id=self.client_id,
            window_id=window_id,
            activity_records=activity_records,
            devices=self._load_devices(),
            sync_timestamp=self._now_provider(),
        )

    def build_seed_payload(self) -> Dict[str, Any]:
        return build_seed_payload(
            client_id=self.client_id,
            devices=self._load_devices(),
            sync_timestamp=self._now_provider(),
        )

    def seed_devices(self) -> Dict[str, Any]:
        """Send the current local v2 device base once after registration."""
        payload = self.build_seed_payload()
        self._send_message({"type": SEED_MESSAGE_TYPE, "data": payload})
        return payload

    def _enqueue_payload(self, payload: Dict[str, Any]) -> None:
        window_id = payload["window_id"]
        with self._lock:
            if window_id in self._load_completed():
                return
            atomic_write_json(self._pending_path(window_id), payload)
            worker = self._workers.get(window_id)
            if worker is None or not worker.is_alive():
                worker = threading.Thread(
                    target=self._send_with_retries,
                    args=(payload,),
                    daemon=True,
                    name=f"telemetry-sync-{_safe_window_key(window_id)[:8]}",
                )
                self._workers[window_id] = worker
                worker.start()

    def handle_window_closed(self, window_id: str, activity_records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Persist and asynchronously send a completed activity window."""
        payload = self.build_payload(window_id, activity_records)
        self._enqueue_payload(payload)
        return payload

    def _send_with_retries(self, payload: Dict[str, Any]) -> None:
        window_id = payload["window_id"]
        event = threading.Event()
        with self._lock:
            self._ack_events[window_id] = event
        try:
            for attempt in range(self.max_retries + 1):
                with self._lock:
                    self._ack_results.pop(window_id, None)
                try:
                    self._send_message({"type": SYNC_MESSAGE_TYPE, "data": payload})
                except Exception as error:
                    LOG.warning("[SYNC] Send attempt %s failed for %s: %s", attempt + 1, window_id, error)
                if event.wait(self.ack_timeout_seconds):
                    with self._lock:
                        result = self._ack_results.get(window_id, {})
                    if result.get("status") == "ack":
                        self._mark_completed(window_id)
                        return
                if attempt < self.max_retries:
                    delay = self.retry_base_seconds * (2 ** attempt)
                    if delay:
                        time.sleep(delay)
        finally:
            with self._lock:
                self._ack_events.pop(window_id, None)
                self._ack_results.pop(window_id, None)

    def handle_ack(self, message: Dict[str, Any]) -> bool:
        """Deliver a server ACK/NACK to the matching send worker."""
        if not isinstance(message, dict):
            return False
        window_id = message.get("window_id")
        if not isinstance(window_id, str):
            return False
        status = str(message.get("status") or "").lower()
        if status not in {"ack", "nack"}:
            return False
        with self._lock:
            event = self._ack_events.get(window_id)
            if event is None:
                return window_id in self._load_completed()
            self._ack_results[window_id] = message
            event.set()
        return True

    def retry_pending(self) -> int:
        """Start workers for durable pending windows after a reconnect/restart."""
        started = 0
        for path in sorted(self._state_root.glob("*.json")):
            if path.name == self._completed_path.name:
                continue
            payload = read_json(path, default=None)
            if not isinstance(payload, dict) or not isinstance(payload.get("window_id"), str):
                continue
            self._enqueue_payload(payload)
            started += 1
        return started

    def wait_for_window(self, window_id: str, timeout: float = 30.0) -> bool:
        worker = self._workers.get(window_id)
        if worker:
            worker.join(timeout=max(0.0, timeout))
        return window_id in self._load_completed()

    def stop(self) -> None:
        """Stop accepting new work; active sends finish according to their timeout."""
        for worker in list(self._workers.values()):
            if worker.is_alive():
                worker.join(timeout=0.1)
