"""Phase 2 — Standalone latest-probe scanner.

Scans Kismet `.kismet` captures newest-to-oldest and emits exactly one
metadata-only JSON record: the latest accepted Probe Request found across
all files.

Key contracts
-------------
- Never emits raw packet bytes or plaintext SSIDs.
- Reuses ``parse_80211_packet``, ``_probe_metadata``, ``_probe_signature``,
  ``normalize_mac``, ``frequency_to_channel``, and ``is_randomized_mac`` from
  the canonical server modules.
- Applies the Phase 1 filter policy before accepting a probe.
- Respects a bounded scan budget (MAX_SCAN_ROWS_PER_CAPTURE) so very large
  captures do not block the CLI indefinitely.
- Returns a structured ``ScanResult`` dataclass; the CLI layer is responsible
  for JSON serialisation.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_SERVER_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "server")
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, os.path.abspath(_SERVER_DIR))

from server_components.kismet_ml_foundation import is_randomized_mac, parse_80211_packet  # noqa: E402
from server_components.kismet_service import (  # noqa: E402
    _probe_metadata,
    _probe_signature,
    destination_kind,
    frequency_to_channel,
    normalize_mac,
)
from tools.kismet_probe_scanner.capture_source import discover_capture_files, open_capture_readonly  # noqa: E402
from tools.kismet_probe_scanner.filter import Decision, classify_parsed  # noqa: E402

SCANNER_VERSION = "kismet-probe-scanner-v1"
MAX_SCAN_ROWS_PER_CAPTURE = 100_000
SCAN_BATCH_ROWS = 5_000


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class ProbeRecord:
    """Metadata-only representation of a single accepted Probe Request."""

    # --- identity & timing ---
    observation_id: str
    timestamp: str            # UTC ISO-8601
    epoch_sec: int
    epoch_usec: int

    # --- address roles ---
    source_mac: Optional[str]
    destination_mac: Optional[str]
    transmitter_mac: Optional[str]
    bssid: Optional[str]
    destination_kind: Optional[str]  # broadcast | multicast | unicast | unknown
    is_randomized_mac: bool

    # --- frame identity ---
    frame_type: str
    frame_subtype: str
    sequence_number: Optional[int]
    retry: Optional[bool]
    power_management: Optional[bool]

    # --- RF ---
    signal_dbm: Optional[float]
    frequency_khz: Optional[float]
    channel: Optional[int]
    packet_length: Optional[int]

    # --- IE / capability features (fingerprinting inputs) ---
    ie_tag_sequence: List[int]
    supported_rates_mbps: List[float]
    vendor_ouis: List[str]
    ht_capabilities_digest: Optional[str]
    vht_capabilities_digest: Optional[str]
    he_capabilities_digest: Optional[str]
    wmm_capabilities_present: bool
    rsn_capabilities_present: bool
    ssid_present: bool
    ssid_length: Optional[int]
    ssid_hidden: bool

    # --- provenance ---
    fingerprint_signature: str
    capture_file: str
    sensor: Optional[str]
    scanner_version: str = SCANNER_VERSION


@dataclass
class ScanStatus:
    """Envelope metadata for a completed scan."""

    scanner_version: str = SCANNER_VERSION
    capture_files_scanned: int = 0
    total_rows_scanned: int = 0
    found: bool = False
    no_result_reason: Optional[str] = None
    rejected_captures: Dict[str, str] = field(default_factory=dict)
    degraded_captures: Dict[str, str] = field(default_factory=dict)
    truncated_captures: Dict[str, str] = field(default_factory=dict)


@dataclass
class ScanResult:
    """Top-level result returned by ``scan_latest_probe``."""

    status: ScanStatus
    latest_probe: Optional[ProbeRecord]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": asdict(self.status),
            "latest_probe": asdict(self.latest_probe) if self.latest_probe else None,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_observation_id(capture_name: str, ts_sec: Any, ts_usec: Any, pkt_hash: Any, source_mac: Any) -> str:
    identity = "|".join((
        capture_name,
        str(ts_sec or ""),
        str(ts_usec or ""),
        str(pkt_hash or ""),
        str(source_mac or ""),
    ))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def _scan_single_capture(
    db_path: Path,
) -> Tuple[Optional[ProbeRecord], Optional[str], Optional[str], Optional[str], int]:
    """Scan one capture file newest-to-oldest for the latest Probe Request.

    Returns
    -------
    (probe_record, rejected_reason, degraded_reason, truncated_reason, rows_scanned)
    """
    con: Optional[sqlite3.Connection] = None
    try:
        con, degraded_reason = open_capture_readonly(db_path)
        con.execute("PRAGMA query_only = ON")
        cur = con.cursor()

        # Schema guard
        columns = {str(row[1]) for row in cur.execute("PRAGMA table_info(packets)")}
        required = {"ts_sec", "sourcemac", "destmac", "transmac", "dlt", "packet"}
        if not required.issubset(columns):
            return None, "missing required packet columns", None, None, 0

        hash_column = "hash" if "hash" in columns else None

        scanned_rows = 0
        next_rowid: Optional[int] = None
        exhausted = False
        best_probe: Optional[ProbeRecord] = None
        best_epoch: Tuple[int, int] = (-1, -1)

        while scanned_rows < MAX_SCAN_ROWS_PER_CAPTURE:
            batch = min(SCAN_BATCH_ROWS, MAX_SCAN_ROWS_PER_CAPTURE - scanned_rows)
            q = (
                "SELECT rowid, ts_sec, ts_usec, sourcemac, destmac, transmac, "
                "signal, frequency, packet_len, datasource, dlt, packet"
                + (", hash" if hash_column else ", NULL AS hash")
                + " FROM packets"
            )
            params: List[Any] = []
            if next_rowid is not None:
                q += " WHERE rowid < ?"
                params.append(next_rowid)
            q += " ORDER BY rowid DESC LIMIT ?"
            params.append(batch)

            rows = cur.execute(q, params).fetchall()
            if not rows:
                exhausted = True
                break

            scanned_rows += len(rows)
            next_rowid = int(rows[-1][0])

            for row in rows:
                (
                    _rowid, ts_sec, ts_usec, sourcemac, destmac, transmac,
                    signal, frequency, packet_len, datasource, dlt, pkt_blob, pkt_hash,
                ) = row

                if not isinstance(pkt_blob, (bytes, bytearray)):
                    continue

                parsed = parse_80211_packet(
                    pkt_blob, dlt=dlt,
                    source_mac=sourcemac, destination_mac=destmac, transmitter_mac=transmac,
                )
                if not parsed:
                    continue

                result = classify_parsed(parsed)
                if result.decision != Decision.KEEP:
                    continue

                # We only want Probe Requests for this scanner
                if parsed.get("frame_subtype") != "Probe Request":
                    continue

                try:
                    sec = int(ts_sec)
                    usec = int(ts_usec or 0)
                except (TypeError, ValueError):
                    continue

                epoch = (sec, usec)
                if epoch <= best_epoch:
                    continue  # already have something newer

                norm_src = parsed.get("source_mac")
                norm_dst = parsed.get("destination_mac")
                norm_tx = parsed.get("transmitter_mac")
                norm_bssid = parsed.get("bssid")
                signal_val: Optional[float] = float(signal) if isinstance(signal, (int, float)) and signal != 0 else None
                chan = frequency_to_channel(frequency)
                meta = _probe_metadata(parsed)

                try:
                    obs_dt = datetime.fromtimestamp(sec, tz=timezone.utc).replace(
                        microsecond=max(0, min(999999, usec))
                    )
                except (OSError, ValueError):
                    continue

                obs_id = _build_observation_id(db_path.name, ts_sec, ts_usec, pkt_hash, sourcemac)

                # Build a temporary dict to compute the fingerprint signature the
                # same way the server does (no MAC in signature).
                obs_dict: Dict[str, Any] = {
                    "frame_subtype": "Probe Request",
                    **meta,
                }
                signature = _probe_signature(obs_dict)

                best_epoch = epoch
                best_probe = ProbeRecord(
                    observation_id=obs_id,
                    timestamp=obs_dt.isoformat(),
                    epoch_sec=sec,
                    epoch_usec=usec,
                    source_mac=norm_src,
                    destination_mac=norm_dst,
                    transmitter_mac=norm_tx,
                    bssid=norm_bssid,
                    destination_kind=destination_kind(norm_dst),
                    is_randomized_mac=is_randomized_mac(norm_src),
                    frame_type="Management",
                    frame_subtype="Probe Request",
                    sequence_number=parsed.get("sequence_number"),
                    retry=parsed.get("retry"),
                    power_management=parsed.get("power_management"),
                    signal_dbm=signal_val,
                    frequency_khz=float(frequency) if frequency else None,
                    channel=chan,
                    packet_length=int(packet_len) if packet_len else None,
                    ie_tag_sequence=meta.get("ie_tag_sequence") or [],
                    supported_rates_mbps=meta.get("supported_rates_mbps") or [],
                    vendor_ouis=meta.get("vendor_ouis") or [],
                    ht_capabilities_digest=meta.get("ht_capabilities_digest"),
                    vht_capabilities_digest=meta.get("vht_capabilities_digest"),
                    he_capabilities_digest=meta.get("he_capabilities_digest"),
                    wmm_capabilities_present=bool(meta.get("wmm_capabilities_present")),
                    rsn_capabilities_present=bool(meta.get("rsn_capabilities_present")),
                    ssid_present=bool(meta.get("ssid_present")),
                    ssid_length=meta.get("ssid_length"),
                    ssid_hidden=bool(meta.get("ssid_hidden")),
                    fingerprint_signature=signature,
                    capture_file=db_path.name,
                    sensor=datasource or "kismet-server",
                )

            if len(rows) < batch:
                exhausted = True
                break

        truncated_reason: Optional[str] = None
        if not exhausted and scanned_rows >= MAX_SCAN_ROWS_PER_CAPTURE:
            truncated_reason = (
                f"scan budget of {MAX_SCAN_ROWS_PER_CAPTURE:,} rows reached before exhausting the capture"
            )

        return best_probe, None, degraded_reason, truncated_reason, scanned_rows

    except (OSError, sqlite3.DatabaseError) as err:
        return None, str(err), None, None, 0
    finally:
        if con is not None:
            con.close()


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def scan_latest_probe(
    capture_dirs: Optional[List[Path]] = None,
    capture_file: Optional[Path] = None,
) -> ScanResult:
    """Scan Kismet captures and return the single latest Probe Request.

    Parameters
    ----------
    capture_dirs:
        Override the list of directories to search.  Defaults to
        ``KISMET_CAPTURE_ROOT`` / ``KISMET_CAPTURE_DIRS`` environment values.
    capture_file:
        Scan only this specific file instead of discovering all captures.

    Returns
    -------
    ScanResult
        ``latest_probe`` is None when no Probe Request is found.
    """
    if capture_file is not None:
        files = [Path(capture_file)]
    else:
        files = discover_capture_files(capture_dirs)

    status = ScanStatus()
    best_probe: Optional[ProbeRecord] = None
    best_epoch: Tuple[int, int] = (-1, -1)

    for db_path in files:
        status.capture_files_scanned += 1
        probe, rejected, degraded, truncated, rows = _scan_single_capture(db_path)
        status.total_rows_scanned += rows

        if rejected:
            status.rejected_captures[db_path.name] = rejected
            continue
        if degraded:
            status.degraded_captures[db_path.name] = degraded
        if truncated:
            status.truncated_captures[db_path.name] = truncated

        if probe is not None:
            epoch = (probe.epoch_sec, probe.epoch_usec)
            if epoch > best_epoch:
                best_epoch = epoch
                best_probe = probe

    if best_probe is not None:
        status.found = True
    else:
        if not files:
            status.no_result_reason = "no capture files found"
        elif status.capture_files_scanned == len(status.rejected_captures):
            status.no_result_reason = "all captures were rejected"
        elif status.truncated_captures:
            status.no_result_reason = "probe may exist beyond scan budget; increase MAX_SCAN_ROWS_PER_CAPTURE"
        else:
            status.no_result_reason = "no Probe Request found in scanned captures"

    return ScanResult(status=status, latest_probe=best_probe)
