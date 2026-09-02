"""Crash-safe buffered daily JSON storage for passive packet observations.

Manages writing packet telemetry observations to storage/passive_packets/YYYY-MM-DD.json
with in-memory buffering, periodic flushing, atomic file operations, and automatic midnight date rotation.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

LOG = logging.getLogger("packet_storage")

DEFAULT_STORAGE_DIR = Path(__file__).resolve().parent.parent / "storage" / "passive_packets"
DEFAULT_FLUSH_INTERVAL_SECONDS = 5.0
DEFAULT_FLUSH_THRESHOLD_PACKETS = 50


class DailyPacketStorage:
    """Manages buffered, crash-safe daily JSON packet storage."""

    def __init__(
        self,
        storage_dir: Path | str = DEFAULT_STORAGE_DIR,
        *,
        observer_client_id: Optional[str] = None,
        flush_interval_seconds: float = DEFAULT_FLUSH_INTERVAL_SECONDS,
        flush_threshold: int = DEFAULT_FLUSH_THRESHOLD_PACKETS,
    ):
        self.storage_dir = Path(storage_dir)
        self.observer_client_id = observer_client_id
        self.flush_interval_seconds = flush_interval_seconds
        self.flush_threshold = flush_threshold

        self._lock = threading.Lock()
        self._buffer: List[Dict[str, Any]] = []
        self._current_date_str: Optional[str] = None
        self._last_flush_time = datetime.datetime.now(datetime.timezone.utc)

        # Runtime counters for diagnostics
        self._stats: Dict[str, int] = {
            "total_observed": 0,
            "total_stored": 0,
            "tcp_count": 0,
            "udp_count": 0,
            "icmp_count": 0,
            "arp_count": 0,
            "dhcp_count": 0,
            "dns_count": 0,
            "mdns_count": 0,
            "llmnr_count": 0,
            "nbns_count": 0,
            "ssdp_count": 0,
            "tls_count": 0,
            "other_count": 0,
        }

        self.storage_dir.mkdir(parents=True, exist_ok=True)

    @property
    def stats(self) -> Dict[str, int]:
        """Return a copy of the diagnostic statistics counters."""
        with self._lock:
            return dict(self._stats)

    def _get_packet_date_str(self, observation: Dict[str, Any]) -> str:
        """Extract YYYY-MM-DD date string from observation timestamp or current UTC."""
        ts = observation.get("timestamp")
        if isinstance(ts, str) and len(ts) >= 10 and ts[4] == "-" and ts[7] == "-":
            return ts[:10]
        return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    def record_observation(self, observation: Dict[str, Any]) -> None:
        """Add an observation to the in-memory buffer, flushing if threshold or date change occurs."""
        with self._lock:
            self._stats["total_observed"] += 1
            protocol = (observation.get("protocol") or "other").lower()

            if protocol == "tcp":
                self._stats["tcp_count"] += 1
            elif protocol == "udp":
                self._stats["udp_count"] += 1
            elif protocol == "icmp":
                self._stats["icmp_count"] += 1
            elif protocol == "arp":
                self._stats["arp_count"] += 1
            elif protocol == "dhcp":
                self._stats["dhcp_count"] += 1
            elif protocol == "dns":
                self._stats["dns_count"] += 1
            elif protocol == "mdns":
                self._stats["mdns_count"] += 1
            elif protocol == "llmnr":
                self._stats["llmnr_count"] += 1
            elif protocol == "nbns":
                self._stats["nbns_count"] += 1
            elif protocol == "ssdp":
                self._stats["ssdp_count"] += 1
            elif protocol == "tls":
                self._stats["tls_count"] += 1
            else:
                self._stats["other_count"] += 1

            packet_date = self._get_packet_date_str(observation)

            # Date rotation check: if date changed and we have buffered items from previous date
            if self._current_date_str and packet_date != self._current_date_str:
                self._flush_locked()

            self._current_date_str = packet_date
            self._buffer.append(observation)

            now = datetime.datetime.now(datetime.timezone.utc)
            should_flush = (
                len(self._buffer) >= self.flush_threshold
                or (now - self._last_flush_time).total_seconds() >= self.flush_interval_seconds
            )
            if should_flush:
                self._flush_locked()

    def flush(self) -> int:
        """Explicitly flush all buffered observations to disk. Returns number of flushed items."""
        with self._lock:
            return self._flush_locked()

    def _flush_locked(self) -> int:
        """Internal flush implementation under lock."""
        if not self._buffer:
            return 0

        date_str = self._current_date_str or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        items_to_write = list(self._buffer)
        self._buffer.clear()
        self._last_flush_time = datetime.datetime.now(datetime.timezone.utc)

        target_file = self.storage_dir / f"{date_str}.json"
        existing_data: Dict[str, Any] = {
            "date": date_str,
            "observer_client_id": self.observer_client_id,
            "packet_count": 0,
            "packets": [],
        }

        # Load existing observations if file exists
        if target_file.exists():
            try:
                with target_file.open("r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict) and "packets" in loaded:
                        existing_data = loaded
            except Exception as err:
                LOG.warning("Could not parse existing daily file %s: %s (will append to new file)", target_file, err)

        # Merge new observations
        existing_packets = existing_data.get("packets", [])
        if not isinstance(existing_packets, list):
            existing_packets = []

        existing_packets.extend(items_to_write)
        existing_data["packets"] = existing_packets
        existing_data["packet_count"] = len(existing_packets)
        if not existing_data.get("observer_client_id") and self.observer_client_id:
            existing_data["observer_client_id"] = self.observer_client_id

        # Atomic write
        self._write_json_atomically(target_file, existing_data)
        self._stats["total_stored"] += len(items_to_write)
        return len(items_to_write)

    def _write_json_atomically(self, target_path: Path, data: Dict[str, Any]) -> None:
        """Write JSON payload to temporary file and atomically replace target."""
        target_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(
            prefix=".packet_storage_",
            suffix=".tmp",
            dir=target_path.parent,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.replace(temp_path, target_path)
        finally:
            if os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

    def close(self) -> int:
        """Flush any remaining items and close storage."""
        return self.flush()
