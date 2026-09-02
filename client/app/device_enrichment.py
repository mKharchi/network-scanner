"""Device Enrichment Job — 5-minute identity/presence/discovery snapshot (v2 §3.3, §7.4).

Builds/updates ``devices.json`` from discovery protocol observations already
collected in memory by the existing ``PassiveProtocolListener`` (its
``DeviceCorrelator``) and the existing ``DHCPListener``. This job does **not**
re-parse raw packets and does **not** invent activity numbers — it only
touches identity/presence/discovery fields, per v2 §3.3:

    "This job must not invent activity numbers. If nothing was observed,
     leave discovery fields as seen: false and don't touch last_seen for
     that device. This job only updates identity/presence/discovery —
     never flow stats."
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, List, Optional

from telemetry_storage import atomic_write_json, get_devices_path, read_json

LOG = logging.getLogger("device_enrichment")

DEFAULT_ENRICHMENT_INTERVAL_SECONDS = 300.0
DISCOVERY_PROTOCOLS = ("dhcp", "mdns", "llmnr", "nbns", "ssdp")


def _build_discovery_block(device: Dict[str, Any]) -> Dict[str, Any]:
    """Build the §3.3 ``discovery`` object from one DeviceCorrelator snapshot dict."""
    protocols_seen = set(device.get("protocols_seen") or [])
    last_seen = device.get("last_seen")
    discovery: Dict[str, Any] = {}

    for protocol in DISCOVERY_PROTOCOLS:
        seen = protocol in protocols_seen
        entry: Dict[str, Any] = {
            "seen": seen,
            # Per-protocol last_seen is not separately tracked upstream by
            # DeviceCorrelator; the device's overall last_seen is used as a
            # reasonable approximation only when that protocol was actually
            # observed (documented limitation — see v2-progress.md).
            "last_seen": last_seen if seen else None,
        }
        if protocol == "mdns" and seen:
            services = device.get("services") or []
            if services:
                entry["services"] = list(services)
        if protocol == "nbns" and seen:
            evidence = device.get("evidence") or {}
            hostname_evidence = evidence.get("hostname") or []
            if "nbns" in hostname_evidence and device.get("hostname"):
                entry["name"] = device.get("hostname")
        discovery[protocol] = entry
    return discovery


def build_device_record(device: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map one DeviceCorrelator snapshot dict into the v2 §3.3 device record shape."""
    mac = device.get("mac_address")
    if not mac:
        return None
    ip_addresses = device.get("ip_addresses") or []
    return {
        "mac": mac.lower(),
        "ip": ip_addresses[0] if ip_addresses else None,
        "hostname": device.get("hostname"),
        "vendor": device.get("vendor"),
        "os_guess": device.get("os_hint"),
        "first_seen": device.get("first_seen"),
        "last_seen": device.get("last_seen"),
        "discovery": _build_discovery_block(device),
    }


def merge_device_records(
    existing: List[Dict[str, Any]], fresh: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Merge freshly built records into the existing devices.json list, keyed by MAC.

    A device present in ``existing`` but absent from this cycle's ``fresh``
    snapshot is preserved unchanged — absence from one 5-minute cycle does not
    mean the device disappeared, and this job must not fabricate updated
    discovery state for devices it did not actually observe this cycle.
    """
    by_mac: Dict[str, Dict[str, Any]] = {}
    for record in existing or []:
        if isinstance(record, dict) and record.get("mac"):
            by_mac[record["mac"]] = record
    for record in fresh:
        by_mac[record["mac"]] = record
    return list(by_mac.values())


class DeviceEnrichmentJob:
    """Runs the 5-minute device enrichment cycle on a background thread."""

    def __init__(
        self,
        *,
        device_snapshot_provider: Callable[[], List[Dict[str, Any]]],
        interval_seconds: float = DEFAULT_ENRICHMENT_INTERVAL_SECONDS,
        date_provider=None,
        root=None,
    ):
        self._device_snapshot_provider = device_snapshot_provider
        self.interval_seconds = interval_seconds
        self._date_provider = date_provider or (
            lambda: __import__("datetime").datetime.now().astimezone().date().isoformat()
        )
        self._root = root

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def _devices_path(self):
        kwargs = {}
        if self._root is not None:
            kwargs["root"] = self._root
        return get_devices_path(self._date_provider(), **kwargs)

    def run_once(self) -> List[Dict[str, Any]]:
        """Execute one enrichment cycle synchronously; returns the merged device list."""
        try:
            raw_devices = self._device_snapshot_provider() or []
        except Exception as error:  # pragma: no cover - defensive
            LOG.warning("[DEVICE_ENRICHMENT] Snapshot provider failed: %s", error)
            raw_devices = []

        fresh_records = []
        for device in raw_devices:
            record = build_device_record(device)
            if record:
                fresh_records.append(record)

        target_path = self._devices_path()
        existing = read_json(target_path, default=[]) or []
        if not isinstance(existing, list):
            existing = []

        merged = merge_device_records(existing, fresh_records)
        atomic_write_json(target_path, merged)
        return merged

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="device-enrichment"
        )
        self._thread.start()

    def stop(self) -> None:
        if self._thread:
            self._stop_event.set()
            self._thread.join(timeout=3.0)
            self._thread = None

    def _loop(self) -> None:
        # Run one cycle immediately on start, then on the configured interval.
        try:
            self.run_once()
        except Exception as error:  # pragma: no cover - defensive
            LOG.warning("[DEVICE_ENRICHMENT] Initial cycle failed: %s", error)
        while not self._stop_event.wait(self.interval_seconds):
            try:
                self.run_once()
            except Exception as error:  # pragma: no cover - defensive
                LOG.warning("[DEVICE_ENRICHMENT] Cycle failed: %s", error)
