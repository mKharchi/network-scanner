"""Passive packet observer engine.

Captures packets visible to the client network interface, extracts metadata,
and buffers normalized observations into crash-safe daily local JSON storage.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from packet_extractor import extract_metadata_from_scapy
from packet_storage import DailyPacketStorage, DEFAULT_STORAGE_DIR
from scope_filter import ScopeFilter

LOG = logging.getLogger("packet_observer")


class PacketObserver:
    """Passively observes network traffic on the local interface and stores daily telemetry.

    Beyond the V1 raw daily packet dump, this also applies the v2 subnet scope
    filter (v2 §6) right after classification and, when a fresh copy survives
    the filter, forwards the observation to the v2 Flow Aggregator and the v2
    per-protocol packet writer (v2 §7.1, §7.2, §7.3). V1 storage is always fed
    first and is never gated by the scope filter, preserving existing V1
    behavior for any deployment that has not yet been assigned a scope.
    """

    def __init__(
        self,
        interface: Optional[str] = None,
        *,
        observer_client_id: Optional[str] = None,
        storage_dir: Path | str = DEFAULT_STORAGE_DIR,
        storage: Optional[DailyPacketStorage] = None,
        local_mac: Optional[str] = None,
        local_ip: Optional[str] = None,
        log_interval_seconds: float = 60.0,
        scope_filter: Optional[ScopeFilter] = None,
        flow_aggregator: Optional[Any] = None,
        telemetry_packet_writer: Optional[Any] = None,
    ):
        self.interface = interface
        self.observer_client_id = observer_client_id or os.getenv("CLIENT_ID")
        self.local_mac = local_mac
        self.local_ip = local_ip
        self.log_interval_seconds = log_interval_seconds

        self.storage = storage or DailyPacketStorage(
            storage_dir=storage_dir,
            observer_client_id=self.observer_client_id,
        )

        # v2 consumers (optional — when omitted, behavior is unchanged from V1).
        self.scope_filter = scope_filter
        self.flow_aggregator = flow_aggregator
        self.telemetry_packet_writer = telemetry_packet_writer

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_log_time = time.monotonic()
        self._is_capturing = False

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        """Start the background packet observation thread."""
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        print("[PACKET_OBSERVER] Starting", flush=True)
        print(f"[PACKET_OBSERVER] Capture interface: {self.interface or 'default'}", flush=True)

        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="packet-observer",
        )
        self._thread.start()
        print("[PACKET_OBSERVER] Started", flush=True)

    def stop(self) -> None:
        """Stop the observation thread and flush all pending storage."""
        if self._thread:
            print("[PACKET_OBSERVER] Stopping", flush=True)
            self._stop_event.set()
            self._thread.join(timeout=3.0)
            self._thread = None
        flushed = self.storage.close()
        print(f"[PACKET_OBSERVER] Flushed {flushed} observations", flush=True)
        print("[PACKET_OBSERVER] Stopped", flush=True)

    def _handle_packet(self, packet: Any) -> None:
        """Process an observed raw packet, extract metadata, and record to storage."""
        try:
            obs = extract_metadata_from_scapy(
                packet,
                interface=self.interface,
                observer_client_id=self.observer_client_id,
                local_mac=self.local_mac,
                local_ip=self.local_ip,
            )
            # V1 raw daily storage is always fed, unfiltered — preserves
            # existing behavior regardless of v2 scope assignment.
            self.storage.record_observation(obs)

            # v2 pipeline (v2 §6): apply the scope filter right after
            # classification, before flow aggregation and per-protocol
            # packet file writes. Fail-open (keep everything) when no scope
            # filter is configured or no scope has been assigned yet.
            in_scope = True
            if self.scope_filter is not None:
                try:
                    in_scope = self.scope_filter.keep_observation(obs)
                except Exception as error:  # pragma: no cover - defensive
                    LOG.debug("[PACKET_OBSERVER] Scope filter error: %s", error)
                    in_scope = True

            if in_scope:
                if self.flow_aggregator is not None:
                    try:
                        self.flow_aggregator.record_packet(obs)
                    except Exception as error:  # pragma: no cover - defensive
                        LOG.debug("[PACKET_OBSERVER] Flow aggregator error: %s", error)
                if self.telemetry_packet_writer is not None:
                    try:
                        self.telemetry_packet_writer.record(obs)
                    except Exception as error:  # pragma: no cover - defensive
                        LOG.debug("[PACKET_OBSERVER] Telemetry packet writer error: %s", error)

            # Periodic diagnostic aggregate log
            now = time.monotonic()
            if now - self._last_log_time >= self.log_interval_seconds:
                self._last_log_time = now
                self._log_diagnostics()

        except Exception as err:
            LOG.debug("Failed to extract metadata from packet: %s", err)

    def _log_diagnostics(self) -> None:
        """Print concise diagnostic runtime counts without flooding console."""
        st = self.storage.stats
        print(
            f"[PACKET_OBSERVER] Observed={st['total_observed']} Stored={st['total_stored']} "
            f"TCP={st['tcp_count']} UDP={st['udp_count']} ICMP={st['icmp_count']} "
            f"ARP={st['arp_count']} DHCP={st['dhcp_count']} DNS={st['dns_count']} "
            f"mDNS={st['mdns_count']} SSDP={st['ssdp_count']} Other={st['other_count']}",
            flush=True,
        )

    def _run(self) -> None:
        """Capture loop using Scapy sniff with error handling."""
        try:
            from scapy.all import sniff  # type: ignore
        except Exception as scapy_err:
            print(f"[PACKET_OBSERVER] Scapy packet capture unavailable: {scapy_err}", flush=True)
            return

        sniff_kwargs: Dict[str, Any] = {
            "prn": self._handle_packet,
            "store": False,
            "timeout": 1.0,
        }
        if self.interface:
            sniff_kwargs["iface"] = self.interface

        self._is_capturing = True
        try:
            while not self._stop_event.is_set():
                try:
                    sniff(**sniff_kwargs)
                except Exception as loop_err:
                    # Check for permission or socket errors
                    err_str = str(loop_err).lower()
                    if "permission" in err_str or "access denied" in err_str:
                        print(
                            f"[PACKET_OBSERVER] Packet capture unavailable: permission denied ({loop_err})",
                            flush=True,
                        )
                        break
                    elif "no such device" in err_str or "invalid interface" in err_str:
                        print(
                            f"[PACKET_OBSERVER] Unable to capture on interface '{self.interface}': {loop_err}",
                            flush=True,
                        )
                        break
                    else:
                        LOG.debug("[PACKET_OBSERVER] Transient capture error: %s", loop_err)
                        time.sleep(1.0)
        finally:
            self._is_capturing = False
