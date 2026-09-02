"""Per-protocol v2 packet file writer (v2 §2, §7.1 integration).

Buffers scope-filtered, normalized packet observations (the same records
produced by ``packet_extractor.extract_metadata_from_scapy`` and already fed
to the v2 Flow Aggregator) and periodically flushes them into
``packets/<protocol>.json`` under the v2 telemetry tree, using
``telemetry_storage.RotatingJSONAppendStore`` for size-bounded rotation.

This module has no knowledge of packet capture or scope filtering; the
caller (``PacketObserver``) decides which observations reach ``record()``.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from telemetry_storage import RotatingJSONAppendStore, get_protocol_packet_path

LOG = logging.getLogger("telemetry_packet_writer")

DEFAULT_FLUSH_INTERVAL_SECONDS = 5.0
DEFAULT_FLUSH_THRESHOLD = 50


class TelemetryPacketWriter:
    """Buffers normalized packet observations and flushes them per protocol/day."""

    def __init__(
        self,
        *,
        flush_interval_seconds: float = DEFAULT_FLUSH_INTERVAL_SECONDS,
        flush_threshold: int = DEFAULT_FLUSH_THRESHOLD,
        date_provider=None,
        root=None,
    ):
        self.flush_interval_seconds = flush_interval_seconds
        self.flush_threshold = flush_threshold
        self._date_provider = date_provider or (
            lambda: datetime.now().astimezone().date().isoformat()
        )
        self._root = root

        self._lock = threading.RLock()
        self._buffers: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        self._stores: Dict[Tuple[str, str], RotatingJSONAppendStore] = {}
        self._last_flush_time = time.monotonic()

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def _store_for(self, date_str: str, protocol: str) -> RotatingJSONAppendStore:
        key = (date_str, protocol)
        store = self._stores.get(key)
        if store is None:
            kwargs = {}
            if self._root is not None:
                kwargs["root"] = self._root
            path = get_protocol_packet_path(date_str, protocol, **kwargs)
            store = RotatingJSONAppendStore(path)
            self._stores[key] = store
        return store

    def record(self, obs: Dict[str, Any]) -> None:
        """Buffer one normalized packet observation for its protocol/day."""
        if not isinstance(obs, dict):
            return
        protocol = (obs.get("protocol") or "unknown").lower()
        date_str = self._date_provider()
        key = (date_str, protocol)
        should_flush = False
        with self._lock:
            self._buffers.setdefault(key, []).append(obs)
            now = time.monotonic()
            if (
                len(self._buffers[key]) >= self.flush_threshold
                or (now - self._last_flush_time) >= self.flush_interval_seconds
            ):
                should_flush = True
        if should_flush:
            self.flush()

    def flush(self) -> int:
        """Flush all buffered observations to their rotating per-protocol files."""
        with self._lock:
            pending = self._buffers
            self._buffers = {}
            self._last_flush_time = time.monotonic()
        flushed = 0
        for (date_str, protocol), records in pending.items():
            if not records:
                continue
            try:
                self._store_for(date_str, protocol).append_many(records)
                flushed += len(records)
            except OSError as error:
                LOG.warning(
                    "[TELEMETRY_PACKET_WRITER] Could not persist %s packets for %s: %s",
                    protocol,
                    date_str,
                    error,
                )
        return flushed

    def start(self) -> None:
        """Start the background periodic-flush thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="telemetry-packet-writer"
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the flush thread and flush all remaining buffered records."""
        if self._thread:
            self._stop_event.set()
            self._thread.join(timeout=3.0)
            self._thread = None
        self.flush()

    def _loop(self) -> None:
        while not self._stop_event.wait(self.flush_interval_seconds):
            try:
                self.flush()
            except Exception as error:  # pragma: no cover - defensive
                LOG.debug("[TELEMETRY_PACKET_WRITER] Periodic flush error: %s", error)
