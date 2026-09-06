"""Client Kismet Wireless Protocol Listener (Plan Phase 5).

Provides passive 802.11 wireless monitoring lifecycle management, health
reporting, event normalization, and observation storage integration matching the
rest of the client's passive listener family.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

LOG = logging.getLogger("kismet_listener")

# Lifecycle event constants (Plan §5.1)
KISMET_LISTENER_STARTING = "KISMET_LISTENER_STARTING"
KISMET_CONNECTED = "KISMET_CONNECTED"
KISMET_LISTENING = "KISMET_LISTENING"
KISMET_EVENT_RECEIVED = "KISMET_EVENT_RECEIVED"
KISMET_EVENT_PARSED = "KISMET_EVENT_PARSED"
KISMET_OBSERVATION_STORED = "KISMET_OBSERVATION_STORED"
KISMET_DISCONNECTED = "KISMET_DISCONNECTED"
KISMET_RECONNECTING = "KISMET_RECONNECTING"
KISMET_ERROR = "KISMET_ERROR"
KISMET_STOPPED = "KISMET_STOPPED"


@dataclass
class KismetObservation:
    """Normalized wireless observation record."""

    timestamp: str
    source_mac: str
    destination_mac: Optional[str]
    bssid: Optional[str]
    signal_dbm: Optional[int]
    frequency_khz: Optional[float]
    packet_length: int
    datasource: str
    sensor_id: str


class KismetListener:
    """Manages wireless observation ingestion and reports listener health."""

    def __init__(
        self,
        *,
        kismet_db_dir: Optional[Path | str] = None,
        poll_interval_seconds: float = 5.0,
        observation_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        sensor_id: str = "local-sensor",
    ) -> None:
        client_root = Path(__file__).resolve().parent.parent
        default_dir = kismet_db_dir or (client_root / "storage" / "kismet")
        self.kismet_db_dir = Path(default_dir).resolve()
        self.poll_interval = poll_interval_seconds
        self.observation_callback = observation_callback
        self.sensor_id = sensor_id

        self._status = "initialized"
        self._connected = False
        self._last_event: Optional[str] = None
        self._events_received = 0
        self._observations_stored = 0
        self._last_error: Optional[str] = None

        self._last_processed_timestamp = 0
        self._processed_hashes: set[int] = set()

        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def _log_lifecycle(self, event: str, **context: Any) -> None:
        """Structured component lifecycle logging (Plan §5.1)."""
        parts = [f"[KISMET] {event}"]
        for k, v in context.items():
            parts.append(f"{k}={v}")
        LOG.info(" ".join(parts))

    def get_health(self) -> Dict[str, Any]:
        """Report current listener operational health (Plan §5.2)."""
        with self._lock:
            return {
                "listener": "kismet",
                "status": self._status,
                "connected": self._connected,
                "last_event": self._last_event,
                "events_received": self._events_received,
                "observations_stored": self._observations_stored,
                "last_error": self._last_error,
            }

    def find_latest_database(self) -> Optional[Path]:
        """Locate the most recently modified .kismet SQLite database."""
        if not self.kismet_db_dir.exists():
            return None
        candidates = sorted(
            self.kismet_db_dir.glob("*.kismet"),
            key=lambda p: p.stat().st_mtime if p.is_file() else 0,
            reverse=True,
        )
        return candidates[0] if candidates else None

    def poll_new_observations(self, db_path: Path) -> List[Dict[str, Any]]:
        """Read newly recorded packets since last poll from the active database."""
        observations: List[Dict[str, Any]] = []
        try:
            con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            cur = con.cursor()
            cur.execute(
                """
                SELECT ts_sec, ts_usec, sourcemac, destmac, transmac, signal, frequency, packet_len, datasource, hash
                FROM packets
                WHERE ts_sec >= ?
                ORDER BY ts_sec ASC, ts_usec ASC
                LIMIT 500
                """,
                (self._last_processed_timestamp,),
            )
            rows = cur.fetchall()
            con.close()

            with self._lock:
                for row in rows:
                    (
                        ts_sec,
                        ts_usec,
                        src,
                        dst,
                        tx,
                        sig,
                        freq,
                        length,
                        ds,
                        pkt_hash,
                    ) = row

                    if pkt_hash and pkt_hash in self._processed_hashes:
                        continue

                    if pkt_hash:
                        self._processed_hashes.add(pkt_hash)
                        if len(self._processed_hashes) > 10000:
                            # Prune cache to keep bounded
                            self._processed_hashes = set(list(self._processed_hashes)[-5000:])

                    self._events_received += 1
                    obs_dt = datetime.fromtimestamp(ts_sec, tz=timezone.utc)
                    iso_time = obs_dt.isoformat()
                    self._last_event = iso_time
                    if ts_sec > self._last_processed_timestamp:
                        self._last_processed_timestamp = ts_sec

                    obs_dict = {
                        "timestamp": iso_time,
                        "epoch_sec": ts_sec,
                        "source_mac": src,
                        "destination_mac": dst,
                        "bssid": tx,
                        "signal_dbm": sig if sig != 0 else None,
                        "frequency_khz": freq,
                        "packet_length": length,
                        "datasource": ds or "kismet-sensor",
                        "sensor_id": self.sensor_id,
                    }
                    observations.append(obs_dict)
                    self._observations_stored += 1

                    if self.observation_callback:
                        try:
                            self.observation_callback(obs_dict)
                        except Exception as err:
                            LOG.debug("[KISMET] Observation callback error: %s", err)

        except Exception as err:
            with self._lock:
                self._last_error = str(err)
            self._log_lifecycle(KISMET_ERROR, error=str(err), db=str(db_path))

        return observations

    def start(self) -> None:
        """Start the Kismet background poller."""
        if self._thread and self._thread.is_alive():
            return

        self._log_lifecycle(KISMET_LISTENER_STARTING)
        with self._lock:
            self._status = "starting"
            self._last_processed_timestamp = int(time.time()) - 60

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="kismet-listener-loop",
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the Kismet background poller."""
        if self._thread:
            self._stop_event.set()
            self._thread.join(timeout=3.0)
            self._thread = None
            with self._lock:
                self._status = "stopped"
                self._connected = False
            self._log_lifecycle(KISMET_STOPPED)

    def _run_loop(self) -> None:
        active_db: Optional[Path] = None
        while not self._stop_event.wait(self.poll_interval):
            try:
                latest_db = self.find_latest_database()
                if latest_db is None:
                    if self._connected:
                        with self._lock:
                            self._connected = False
                            self._status = "disconnected"
                        self._log_lifecycle(KISMET_DISCONNECTED, reason="No Kismet database found")
                    continue

                if latest_db != active_db or not self._connected:
                    active_db = latest_db
                    with self._lock:
                        self._connected = True
                        self._status = "active"
                    self._log_lifecycle(KISMET_CONNECTED, database=latest_db.name)
                    self._log_lifecycle(KISMET_LISTENING)

                new_obs = self.poll_new_observations(latest_db)
                if new_obs:
                    self._log_lifecycle(
                        KISMET_OBSERVATION_STORED,
                        count=len(new_obs),
                        latest_time=self._last_event,
                    )
            except Exception as err:
                with self._lock:
                    self._last_error = str(err)
                self._log_lifecycle(KISMET_ERROR, error=str(err))
