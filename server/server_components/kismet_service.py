"""Kismet Passive Wireless Investigation Service.

Exposes historical 802.11 wireless observations and RF telemetry (RSSI, channels,
frame types, packet timelines) correlated with known devices from the central
device base without copying raw captures into MySQL.

Implements Phase 4 of docs/integrating-kismet-and-backup/plan.md:
    Device Identifier -> MAC -> Sensor -> Time Window -> Kismet Observations -> Normalized Investigation Response
"""

from __future__ import annotations

import json
import hashlib
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from server_components.kismet_ml_foundation import is_randomized_mac, parse_80211_packet

try:
    from database import get_connection
except ImportError:  # pragma: no cover
    from ..database import get_connection

LOG = logging.getLogger("kismet_service")

DEFAULT_LOOKBACK_MINUTES = 180
MAX_OBSERVATION_LIMIT = 2000
MAX_PROBE_SCAN_ROWS_PER_CAPTURE = 10000
PROBE_SCAN_BATCH_ROWS = 700
CAPTURE_MTIME_LOOKBACK_SLACK_SECONDS = 300
DEFAULT_CAPTURE_ROOT = Path("/home/adonis/kismet")
MAC_RE = re.compile(r"^[0-9A-F]{2}(?::[0-9A-F]{2}){5}$")

# Standard 802.11 frame type mappings
TYPE_MAP = {0: "Management", 1: "Control", 2: "Data", 3: "Extension"}
MGMT_MAP = {
    0: "Association Request",
    1: "Association Response",
    2: "Reassociation Request",
    3: "Reassociation Response",
    4: "Probe Request",
    5: "Probe Response",
    8: "Beacon",
    10: "Disassociation",
    11: "Authentication",
    12: "Deauthentication",
    13: "Action",
}
CTRL_MAP = {
    8: "Block Ack Request",
    9: "Block Ack",
    10: "PS-Poll",
    11: "RTS",
    12: "CTS",
    13: "ACK",
    14: "CF-End",
}
DATA_MAP = {
    0: "Data",
    4: "Null Data",
    8: "QoS Data",
    12: "QoS Null",
}

CONTROL_NOISE_SUBTYPES = {"ACK", "CTS", "RTS", "Block Ack"}
PROBE_SUBTYPES = {"Probe Request", "Probe Response"}


def normalize_mac(mac: Any) -> Optional[str]:
    """Return uppercase colon-separated MAC address or None."""
    if not isinstance(mac, str):
        return None
    compact = re.sub(r"[:-]", "", mac.strip()).upper()
    if len(compact) != 12 or not re.fullmatch(r"[0-9A-F]{12}", compact):
        return None
    return ":".join(compact[i:i + 2] for i in range(0, 12, 2))


def frequency_to_channel(freq_khz: float) -> Optional[int]:
    """Convert radio frequency in kHz or MHz to standard Wi-Fi channel."""
    if not freq_khz or freq_khz <= 0:
        return None
    freq_mhz = freq_khz / 1000.0 if freq_khz > 100_000 else freq_khz
    # 2.4 GHz
    if freq_mhz == 2484:
        return 14
    if 2412 <= freq_mhz <= 2472:
        return int((freq_mhz - 2412) / 5) + 1
    # 5 GHz
    if 5170 <= freq_mhz <= 5825:
        return int((freq_mhz - 5000) / 5)
    return None


def parse_lookback_to_minutes(lookback: Any, default: int = DEFAULT_LOOKBACK_MINUTES) -> int:
    """Parse string lookback like '15m', '1h', '24h', '30' into integer minutes."""
    if lookback is None or lookback == "":
        return default
    if isinstance(lookback, (int, float)):
        return max(1, int(lookback))
    s = str(lookback).strip().lower()
    if s.endswith("m"):
        try:
            return max(1, int(s[:-1]))
        except ValueError:
            return default
    if s.endswith("h"):
        try:
            return max(1, int(s[:-1]) * 60)
        except ValueError:
            return default
    if s.endswith("d"):
        try:
            return max(1, int(s[:-1]) * 1440)
        except ValueError:
            return default
    try:
        return max(1, int(s))
    except ValueError:
        return default


def parse_iso_or_epoch(value: Any) -> Optional[datetime]:
    """Parse ISO-8601 string or epoch number into UTC datetime."""
    if not value:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (ValueError, OSError):
            return None
    if isinstance(value, str):
        val = value.strip()
        try:
            # ISO format
            normalized = val.replace("Z", "+00:00")
            dt = datetime.fromisoformat(normalized)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            try:
                epoch = float(val)
                return datetime.fromtimestamp(epoch, tz=timezone.utc)
            except ValueError:
                return None
    return None


def destination_kind(mac: Optional[str]) -> str:
    """Classify a normalized 802.11 destination without relying on IP data."""
    if not mac:
        return "unknown"
    if mac == "FF:FF:FF:FF:FF:FF":
        return "broadcast"
    try:
        return "multicast" if int(mac[:2], 16) & 1 else "unicast"
    except ValueError:
        return "unknown"


def _capability_digest(value: Any) -> Optional[str]:
    """Return a short stable display digest for a parsed capability field."""
    if not isinstance(value, str) or not value:
        return None
    return hashlib.sha256(value.encode("ascii", errors="ignore")).hexdigest()[:16]


def _probe_subtype_filter(value: Any) -> Optional[Set[str]]:
    """Normalize the optional probe subtype filter used by the global API."""
    if value in (None, "", "all", "ALL"):
        return None
    normalized = str(value).strip().lower().replace("_", " ").replace("-", " ")
    aliases = {
        "request": "Probe Request", "probe request": "Probe Request",
        "response": "Probe Response", "probe response": "Probe Response",
    }
    subtype = aliases.get(normalized)
    if subtype is None:
        raise ValueError("subtype must be request, response, or all")
    return {subtype}


def _format_query_window(
    *, start_time: Optional[Any], end_time: Optional[Any], lookback_minutes: Optional[Any]
) -> Tuple[Optional[datetime], datetime, bool, Optional[float], Optional[float]]:
    """Resolve the shared Kismet query-window contract."""
    if end_time not in (None, "") and parse_iso_or_epoch(end_time) is None:
        raise ValueError("Invalid end_time; expected UTC ISO-8601 or epoch.")
    if start_time not in (None, "") and parse_iso_or_epoch(start_time) is None:
        raise ValueError("Invalid start_time; expected UTC ISO-8601 or epoch.")
    end_dt = parse_iso_or_epoch(end_time) or datetime.now(timezone.utc)
    start_dt = parse_iso_or_epoch(start_time)
    has_time_filter = True
    if start_dt is None:
        if lookback_minutes is not None and str(lookback_minutes).strip().lower() in {"all", "none", "unlimited"}:
            has_time_filter = False
        else:
            start_dt = end_dt - timedelta(minutes=parse_lookback_to_minutes(lookback_minutes, DEFAULT_LOOKBACK_MINUTES))
    if has_time_filter and start_dt is not None and start_dt >= end_dt:
        raise ValueError("start_time must be earlier than end_time")
    return (
        start_dt,
        end_dt,
        has_time_filter,
        start_dt.timestamp() if has_time_filter and start_dt is not None else None,
        end_dt.timestamp() if has_time_filter else None,
    )


def _probe_metadata(parsed: Dict[str, Any]) -> Dict[str, Any]:
    """Project parsed 802.11 information elements into a payload-safe schema."""
    return {
        "ie_tag_sequence": list(parsed.get("tags") or ()),
        "supported_rates_mbps": list(parsed.get("supported_rates") or ()),
        "vendor_ouis": list(parsed.get("vendor_ouis") or ()),
        "ht_capabilities_digest": _capability_digest(parsed.get("ht")),
        "vht_capabilities_digest": _capability_digest(parsed.get("vht")),
        "he_capabilities_digest": _capability_digest(parsed.get("he")),
        "wmm_capabilities_present": bool(parsed.get("wmm")),
        "rsn_capabilities_present": bool(parsed.get("rsn")),
        "ssid_present": bool(parsed.get("ssid_present")),
        "ssid_length": parsed.get("ssid_length"),
        "ssid_hidden": bool(parsed.get("ssid_hidden")),
    }


def _probe_signature(observation: Dict[str, Any]) -> str:
    """Build a candidate fingerprint signature without any MAC-address input."""
    feature_values = {
        "subtype": observation.get("frame_subtype"),
        "tags": observation.get("ie_tag_sequence") or [],
        "rates": observation.get("supported_rates_mbps") or [],
        "ouis": observation.get("vendor_ouis") or [],
        "ht": observation.get("ht_capabilities_digest"),
        "vht": observation.get("vht_capabilities_digest"),
        "he": observation.get("he_capabilities_digest"),
        "wmm": observation.get("wmm_capabilities_present"),
        "rsn": observation.get("rsn_capabilities_present"),
        "ssid_shape": [observation.get("ssid_present"), observation.get("ssid_length"), observation.get("ssid_hidden")],
    }
    serialized = json.dumps(feature_values, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]


def _stale_journal_reason(db_path: Path, *, stale_after_seconds: float = 30.0) -> Optional[str]:
    """Identify an abandoned rollback journal without touching the capture.

    SQLite needs write access to replay a rollback journal.  Kismet capture
    files are intentionally read-only to the API process, so an old sidecar
    must be reported/skipped rather than opened with immutable mode (which can
    produce a misleading ``database disk image is malformed`` error).
    """
    journal = Path(f"{db_path}-journal")
    if not journal.exists():
        return None
    try:
        db_mtime = db_path.stat().st_mtime
        journal_mtime = journal.stat().st_mtime
    except OSError:
        return "capture or rollback journal cannot be stat'ed"
    journal_age = time.time() - max(db_mtime, journal_mtime)
    if journal_age > stale_after_seconds:
        return "stale SQLite rollback journal is present; restart Kismet to recover it"
    return "active SQLite rollback journal is present; wait for Kismet to rotate or close this capture"


def _probe_capture_connection(
    db_path: Path,
) -> Tuple[sqlite3.Connection, Optional[str]]:
    """Open a capture for probe inspection and report any degraded mode.

    Kismet keeps the active capture in SQLite's rollback-journal mode. A
    normal read-only connection cannot replay that journal, while ``nolock``
    can fail with ``database disk image is malformed`` during a write. An
    immutable connection can inspect the last committed main-db pages without
    replaying or modifying the journal. It may lag the live capture, so callers
    expose a warning to the UI. Both active and abandoned journals are opened
    this way when possible; the result is always labeled degraded because it
    may lag the journal state.
    """
    journal_reason = _stale_journal_reason(db_path)
    if journal_reason:
        connection = sqlite3.connect(
            f"file:{db_path}?mode=ro&immutable=1", uri=True, timeout=2.0,
        )
        if journal_reason.startswith("active "):
            return connection, "active rollback journal; showing last committed snapshot"
        return connection, "stale rollback journal; showing last committed snapshot; restart Kismet to recover it"
    connection = sqlite3.connect(
        f"file:{db_path}?mode=ro&nolock=1", uri=True, timeout=2.0,
    )
    return connection, None


class KismetInvestigationService:
    """Service to search, correlate, and structure Kismet wireless observations."""

    def __init__(
        self,
        capture_dirs: Optional[List[Path | str]] = None,
        *,
        fallback_scan_dir: Optional[Path | str] = None,
    ):
        configured_dirs = os.getenv("KISMET_CAPTURE_DIRS")
        if capture_dirs is not None:
            self.capture_dirs = [Path(p) for p in capture_dirs]
        elif configured_dirs:
            self.capture_dirs = [Path(p.strip()) for p in configured_dirs.split(",") if p.strip()]
        else:
            configured_root = os.getenv("KISMET_CAPTURE_ROOT")
            self.capture_dirs = [Path(configured_root) if configured_root else DEFAULT_CAPTURE_ROOT]
        self.fallback_scan_dir = Path(fallback_scan_dir or (Path(__file__).resolve().parents[1] / "storage" / "network_scans"))

    def find_kismet_database_files(self) -> List[Path]:
        """Locate all available .kismet SQLite database files across configured paths."""
        found: List[Path] = []
        for cdir in self.capture_dirs:
            try:
                if cdir.exists() and cdir.is_dir():
                    for kfile in cdir.glob("*.kismet"):
                        if kfile.is_file() and kfile not in found:
                            found.append(kfile)
            except OSError as err:
                LOG.warning("[KISMET] Cannot inspect capture directory %s: %s", cdir, err)
        found.sort(key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True)
        return found

    def resolve_device(self, device_identifier: Any) -> Optional[Dict[str, Any]]:
        """Lookup device record from MySQL or fallback local network scan inventory."""
        normalized_id = str(device_identifier).strip() if device_identifier is not None else ""
        if not normalized_id:
            return None

        # 1. Try MySQL database
        conn = get_connection()
        if conn:
            try:
                cur = conn.cursor(dictionary=True)
                if normalized_id.isdigit():
                    cur.execute(
                        "SELECT id, mac_address, ip_address, hostname, vendor, first_seen, last_seen "
                        "FROM network_devices WHERE id = %s",
                        (int(normalized_id),),
                    )
                else:
                    mac = normalize_mac(normalized_id)
                    if mac:
                        cur.execute(
                            "SELECT id, mac_address, ip_address, hostname, vendor, first_seen, last_seen "
                            "FROM network_devices WHERE mac_address = %s",
                            (mac,),
                        )
                    else:
                        cur.execute(
                            "SELECT id, mac_address, ip_address, hostname, vendor, first_seen, last_seen "
                            "FROM network_devices WHERE hostname = %s OR ip_address = %s LIMIT 1",
                            (normalized_id, normalized_id),
                        )
                row = cur.fetchone()
                if row:
                    return {
                        "id": row.get("id"),
                        "mac": normalize_mac(row.get("mac_address")),
                        "ip": row.get("ip_address"),
                        "hostname": row.get("hostname"),
                        "vendor": row.get("vendor"),
                        "first_seen": row.get("first_seen").isoformat() if isinstance(row.get("first_seen"), datetime) else str(row.get("first_seen") or ""),
                        "last_seen": row.get("last_seen").isoformat() if isinstance(row.get("last_seen"), datetime) else str(row.get("last_seen") or ""),
                    }
            except Exception as err:
                LOG.debug("[KISMET] MySQL device lookup failed: %s", err)
            finally:
                conn.close()

        # 2. Fallback: Search latest network scan files
        if self.fallback_scan_dir.exists():
            for scan_file in sorted(self.fallback_scan_dir.glob("*.json"), reverse=True):
                try:
                    with open(scan_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        for dev in data.get("devices", []):
                            dev_mac = normalize_mac(dev.get("mac_address") or dev.get("mac"))
                            dev_ip = dev.get("ip_address") or dev.get("ip")
                            dev_host = dev.get("hostname")
                            if (
                                (dev_mac and (dev_mac == normalize_mac(normalized_id) or normalized_id == dev_mac.replace(":", "")))
                                or (dev_ip and dev_ip == normalized_id)
                                or (dev_host and dev_host.lower() == normalized_id.lower())
                            ):
                                return {
                                    "id": None,
                                    "mac": dev_mac,
                                    "ip": dev_ip,
                                    "hostname": dev_host,
                                    "vendor": dev.get("vendor"),
                                    "first_seen": dev.get("first_seen"),
                                    "last_seen": dev.get("last_seen"),
                                }
                except (OSError, json.JSONDecodeError):
                    continue

        # 3. Direct MAC address if valid format
        direct_mac = normalize_mac(normalized_id)
        if direct_mac:
            return {
                "id": None,
                "mac": direct_mac,
                "ip": None,
                "hostname": None,
                "vendor": None,
                "first_seen": None,
                "last_seen": None,
            }

        return None

    def query_wireless_observations(
        self,
        device_identifier: Any,
        *,
        start_time: Optional[Any] = None,
        end_time: Optional[Any] = None,
        lookback_minutes: Optional[Any] = None,
        limit: int = 500,
        include_noise: bool = False,
    ) -> Dict[str, Any]:
        """Retrieve and format Kismet wireless observations for a device."""
        device = self.resolve_device(device_identifier)
        if not device:
            raise ValueError(f"Device '{device_identifier}' could not be resolved.")

        target_mac = device["mac"]
        if not target_mac:
            raise ValueError(f"No valid MAC address found for device '{device_identifier}'.")

        # Resolve time bounds
        # Resolve time bounds (Plan §5.3, §5.4)
        if end_time not in (None, "") and parse_iso_or_epoch(end_time) is None:
            raise ValueError("Invalid end_time; expected UTC ISO-8601 or epoch.")
        if start_time not in (None, "") and parse_iso_or_epoch(start_time) is None:
            raise ValueError("Invalid start_time; expected UTC ISO-8601 or epoch.")

        end_dt = parse_iso_or_epoch(end_time) or datetime.now(timezone.utc)
        start_dt = parse_iso_or_epoch(start_time)
        has_time_filter = True
        if start_dt is None:
            if lookback_minutes is not None and str(lookback_minutes).strip().lower() in ("all", "none", "unlimited"):
                has_time_filter = False
            else:
                mins = parse_lookback_to_minutes(lookback_minutes, default=DEFAULT_LOOKBACK_MINUTES)
                start_dt = end_dt - timedelta(minutes=mins)

        start_epoch = None
        end_epoch = None
        start_ts = None
        end_ts = None
        if has_time_filter and start_dt is not None:
            if start_dt >= end_dt:
                raise ValueError("start_time must be earlier than end_time")
            start_ts = start_dt.timestamp()
            end_ts = end_dt.timestamp()
            start_epoch = int(start_ts)
            end_epoch = int(end_ts) + 1

        try:
            if isinstance(limit, bool):
                raise ValueError
            limit = min(MAX_OBSERVATION_LIMIT, max(1, int(limit)))
        except (TypeError, ValueError):
            raise ValueError("limit must be an integer between 1 and 2000") from None

        db_files = self.find_kismet_database_files()
        observations: List[Dict[str, Any]] = []
        signals: List[int] = []
        frequencies_seen: Set[float] = set()
        frame_type_counts: Dict[str, int] = {}
        total_matched_packets = 0
        rejected_captures: Dict[str, str] = {}
        degraded_captures: Dict[str, str] = {}

        # Query packets from every configured Kismet database. The final sort is
        # performed after merging files so rotation cannot change chronology.
        for db_path in db_files:
            con = None
            try:
                con, degraded_reason = _probe_capture_connection(db_path)
                if degraded_reason:
                    degraded_captures[db_path.name] = degraded_reason
                con.execute("PRAGMA query_only = ON")
                cur = con.cursor()

                # Optimized query matching sourcemac, destmac, or transmac (case-insensitive for Kismet databases)
                query = """
                SELECT ts_sec, ts_usec, phyname, sourcemac, destmac, transmac, signal, frequency, packet_len, datasource, dlt, packet, hash
                FROM packets
                WHERE (sourcemac = ? COLLATE NOCASE OR destmac = ? COLLATE NOCASE OR transmac = ? COLLATE NOCASE)
                """
                params: List[Any] = [target_mac, target_mac, target_mac]

                # Apply time filtering so lookback strictly excludes out-of-window packets
                if has_time_filter and start_epoch is not None and end_epoch is not None:
                    query += " AND ts_sec >= ? AND ts_sec <= ?"
                    params.extend([start_epoch, end_epoch])

                # Kismet captures can be multi-gigabyte SQLite files without
                # a timestamp index.  Rowid follows append order, so using it
                # avoids a temporary sort (which is unsafe while Kismet owns
                # the active database); Python performs the final strict sort.
                query += " ORDER BY rowid DESC LIMIT ?"
                params.append(limit * 2)

                cur.execute(query, params)
                rows = cur.fetchall()

                for row in rows:
                    (
                        ts_sec,
                        ts_usec,
                        phyname,
                        sourcemac,
                        destmac,
                        transmac,
                        signal,
                        frequency,
                        packet_len,
                        datasource,
                        dlt,
                        pkt_blob,
                        pkt_hash,
                    ) = row

                    # Microsecond-exact boundary enforcement
                    pkt_ts = ts_sec + (ts_usec / 1_000_000.0 if ts_usec else 0.0)
                    if has_time_filter and start_ts is not None and end_ts is not None:
                        if pkt_ts < start_ts or pkt_ts > end_ts:
                            continue

                    # Decode through the shared ML-safe 802.11 parser.  This
                    # keeps the device investigation and probe browser in
                    # lockstep while raw packet bytes stay in SQLite only.
                    frame_type = "Data"
                    frame_subtype = "QoS Data"
                    parsed = parse_80211_packet(
                        pkt_blob, dlt=dlt, source_mac=sourcemac,
                        destination_mac=destmac, transmitter_mac=transmac,
                    )
                    if parsed:
                        frame_type = parsed["frame_type"]
                        frame_subtype = parsed["frame_subtype"]

                    # Noise filtering: skip standalone ACK/CTS control frames unless requested
                    if not include_noise and frame_subtype in CONTROL_NOISE_SUBTYPES:
                        continue

                    total_matched_packets += 1
                    ft_key = f"{frame_type}: {frame_subtype}"
                    frame_type_counts[ft_key] = frame_type_counts.get(ft_key, 0) + 1

                    if signal and signal != 0:
                        signals.append(signal)
                    if frequency:
                        frequencies_seen.add(frequency)

                    # Determine frame role for this device
                    norm_src = parsed.get("source_mac") if parsed else normalize_mac(sourcemac)
                    norm_dst = parsed.get("destination_mac") if parsed else normalize_mac(destmac)
                    norm_tx = parsed.get("transmitter_mac") if parsed else normalize_mac(transmac)

                    role = "OBSERVED"
                    if norm_src == target_mac:
                        role = "SOURCE"
                    elif norm_tx == target_mac:
                        role = "TRANSMITTER"
                    elif norm_dst == target_mac:
                        role = "DESTINATION"

                    obs_dt = datetime.fromtimestamp(ts_sec, tz=timezone.utc).replace(
                        microsecond=max(0, min(999999, int(ts_usec or 0)))
                    )
                    channel = frequency_to_channel(frequency)

                    observation = {
                        "timestamp": obs_dt.isoformat(),
                        "epoch_sec": ts_sec,
                        "epoch_usec": ts_usec,
                        "role": role,
                        "source_mac": norm_src,
                        "destination_mac": norm_dst,
                        "transmitter_mac": norm_tx,
                        "frame_type": frame_type,
                        "frame_subtype": frame_subtype,
                        "signal_dbm": signal if signal != 0 else None,
                        "frequency_khz": frequency,
                        "channel": channel,
                        "packet_length": packet_len,
                        "sensor": datasource or "kismet-server",
                        "source": "KISMET_SERVER",
                        "capture_file": db_path.name,
                        "packet_hash": pkt_hash,
                    }
                    if parsed:
                        observation.update({
                            "bssid": parsed.get("bssid"),
                            "is_randomized_mac": is_randomized_mac(norm_src),
                            "destination_kind": destination_kind(norm_dst),
                            "sequence_number": parsed.get("sequence_number"),
                            "retry": parsed.get("retry"),
                            "power_management": parsed.get("power_management"),
                            **_probe_metadata(parsed),
                        })
                    observations.append(observation)

            except Exception as err:
                degraded_captures.pop(db_path.name, None)
                rejected_captures[db_path.name] = str(err)
                LOG.warning("[KISMET] Error querying %s: %s", db_path, err)
            finally:
                if con is not None:
                    con.close()

        observations.sort(
            key=lambda item: (
                item["epoch_sec"],
                item["epoch_usec"],
                str(item.get("packet_hash") or ""),
            ),
            reverse=True,
        )
        observations = observations[:limit]

        # Compute summary RF statistics
        avg_rssi = round(sum(signals) / len(signals), 1) if signals else None
        min_rssi = min(signals) if signals else None
        max_rssi = max(signals) if signals else None

        channels = sorted([frequency_to_channel(f) for f in frequencies_seen if frequency_to_channel(f)])

        return {
            "status": "ok",
            "device": device,
            "source": "KISMET_SERVER",
            "query_window": {
                "start": start_dt.isoformat() if start_dt else "unbounded",
                "end": end_dt.isoformat(),
                "lookback_minutes": round((end_dt - start_dt).total_seconds() / 60.0, 1) if start_dt else None,
            },
            "summary": {
                "observation_count": len(observations),
                "total_matched_packets": total_matched_packets,
                "avg_signal_dbm": avg_rssi,
                "min_signal_dbm": min_rssi,
                "max_signal_dbm": max_rssi,
                "channels": channels,
                "frame_types": frame_type_counts,
                "noise_filtered": not include_noise,
            },
            "observations": observations,
            "capture_files_scanned": len(db_files),
            "rejected_captures": rejected_captures,
            "degraded_captures": degraded_captures,
        }

    def query_recent_probes(
        self,
        *,
        start_time: Optional[Any] = None,
        end_time: Optional[Any] = None,
        lookback_minutes: Optional[Any] = "15m",
        limit: int = 500,
        subtype: Optional[Any] = None,
        randomized: Optional[bool] = None,
        channel: Optional[Any] = None,
        bssid: Optional[Any] = None,
        source_mac: Optional[Any] = None,
        capture_file: Optional[Any] = None,
        min_signal: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Return bounded, decoded Probe Request/Response observations.

        The query deliberately opens every Kismet database read-only and
        parses candidate frames only in memory.  It never returns the SQLite
        packet BLOB or the plaintext SSID information element.
        """
        try:
            if isinstance(limit, bool):
                raise ValueError
            limit = min(MAX_OBSERVATION_LIMIT, max(1, int(limit)))
        except (TypeError, ValueError):
            raise ValueError("limit must be an integer between 1 and 2000") from None
        probe_subtypes = _probe_subtype_filter(subtype)
        try:
            channel_filter = int(channel) if channel not in (None, "") else None
        except (TypeError, ValueError):
            raise ValueError("channel must be an integer") from None
        try:
            min_signal_filter = float(min_signal) if min_signal not in (None, "") else None
        except (TypeError, ValueError):
            raise ValueError("min_signal must be numeric") from None
        bssid_filter = normalize_mac(bssid) if bssid not in (None, "") else None
        source_filter = normalize_mac(source_mac) if source_mac not in (None, "") else None
        if bssid not in (None, "") and not bssid_filter:
            raise ValueError("bssid must be a valid MAC address")
        if source_mac not in (None, "") and not source_filter:
            raise ValueError("source_mac must be a valid MAC address")
        if randomized is not None and not isinstance(randomized, bool):
            raise ValueError("randomized must be a boolean")
        capture_filter = str(capture_file).strip() if capture_file not in (None, "") else None
        if capture_filter and (Path(capture_filter).name != capture_filter or not capture_filter.endswith(".kismet")):
            raise ValueError("capture_file must be a Kismet capture filename")

        start_dt, end_dt, has_time_filter, start_ts, end_ts = _format_query_window(
            start_time=start_time, end_time=end_time, lookback_minutes=lookback_minutes,
        )
        start_epoch = int(start_ts) if start_ts is not None else None
        end_epoch = int(end_ts) + 1 if end_ts is not None else None
        observations: List[Dict[str, Any]] = []
        scanned_files = 0
        rejected_captures: Dict[str, str] = {}
        degraded_captures: Dict[str, str] = {}
        truncated_captures: Dict[str, str] = {}
        # Result ``limit`` only caps returned rows. The scan budget must stay
        # large enough to walk past bursts of non-probe traffic; otherwise a
        # modest UI limit recreates the old newest-slice miss.
        scan_rows = MAX_PROBE_SCAN_ROWS_PER_CAPTURE

        for db_path in self.find_kismet_database_files():
            if capture_filter and db_path.name != capture_filter:
                continue
            scanned_files += 1
            if has_time_filter and start_ts is not None:
                try:
                    # Rotated captures whose file mtime predates the query
                    # window cannot contain packets from that window.  This
                    # prevents a 15-minute UI refresh from opening every old
                    # multi-gigabyte capture in the archive.
                    if db_path.stat().st_mtime < start_ts - CAPTURE_MTIME_LOOKBACK_SLACK_SECONDS:
                        continue
                except OSError:
                    rejected_captures[db_path.name] = "capture cannot be stat'ed"
                    continue
            con: Optional[sqlite3.Connection] = None
            try:
                con, degraded_reason = _probe_capture_connection(db_path)
                if degraded_reason:
                    degraded_captures[db_path.name] = degraded_reason
                con.execute("PRAGMA query_only = ON")
                cur = con.cursor()
                columns = {str(row[1]) for row in cur.execute("PRAGMA table_info(packets)")}
                if not {"ts_sec", "sourcemac", "destmac", "transmac", "dlt", "packet"}.issubset(columns):
                    continue
                hash_column = "hash" if "hash" in columns else None
                # Kismet packet tables commonly have no timestamp index. Walk
                # newest-to-oldest by rowid in bounded chunks instead of using
                # a timestamp predicate that would force a full-table scan.
                # This prevents a short probe burst from being lost behind a
                # large volume of newer data traffic.
                scanned_rows = 0
                file_matches = 0
                next_rowid: Optional[int] = None
                reached_window_start = False
                exhausted_table = False
                while scanned_rows < scan_rows and not reached_window_start and file_matches < limit:
                    batch_size = min(PROBE_SCAN_BATCH_ROWS, scan_rows - scanned_rows)
                    query = (
                        "SELECT rowid, ts_sec, ts_usec, sourcemac, destmac, transmac, signal, frequency, "
                        "packet_len, datasource, dlt, packet"
                        + (", hash" if hash_column else ", NULL AS hash")
                        + " FROM packets"
                    )
                    params: List[Any] = []
                    if next_rowid is not None:
                        query += " WHERE rowid < ?"
                        params.append(next_rowid)
                    query += " ORDER BY rowid DESC LIMIT ?"
                    params.append(batch_size)
                    rows = cur.execute(query, params).fetchall()
                    if not rows:
                        exhausted_table = True
                        break
                    scanned_rows += len(rows)
                    next_rowid = int(rows[-1][0])
                    oldest_packet_ts: Optional[float] = None
                    for row in rows:
                        (
                            _rowid, ts_sec, ts_usec, sourcemac, destmac, transmac, signal, frequency,
                            packet_len, datasource, dlt, pkt_blob, pkt_hash,
                        ) = row
                        try:
                            pkt_ts = float(ts_sec) + (float(ts_usec or 0) / 1_000_000.0)
                        except (TypeError, ValueError):
                            continue
                        oldest_packet_ts = pkt_ts if oldest_packet_ts is None else min(oldest_packet_ts, pkt_ts)
                        if has_time_filter and start_ts is not None and end_ts is not None and not (start_ts <= pkt_ts <= end_ts):
                            continue
                        parsed = parse_80211_packet(
                            pkt_blob, dlt=dlt, source_mac=sourcemac,
                            destination_mac=destmac, transmitter_mac=transmac,
                        )
                        if not parsed or parsed.get("frame_type") != "Management":
                            continue
                        frame_subtype = parsed.get("frame_subtype")
                        if frame_subtype not in PROBE_SUBTYPES or (probe_subtypes and frame_subtype not in probe_subtypes):
                            continue
                        norm_source = parsed.get("source_mac")
                        norm_bssid = parsed.get("bssid")
                        normalized_randomized = is_randomized_mac(norm_source)
                        observed_channel = frequency_to_channel(frequency)
                        signal_value = signal if isinstance(signal, (int, float)) and signal != 0 else None
                        if randomized is not None and normalized_randomized != randomized:
                            continue
                        if channel_filter is not None and observed_channel != channel_filter:
                            continue
                        if bssid_filter and norm_bssid != bssid_filter:
                            continue
                        if source_filter and norm_source != source_filter:
                            continue
                        if min_signal_filter is not None and (signal_value is None or signal_value < min_signal_filter):
                            continue
                        try:
                            observed_dt = datetime.fromtimestamp(int(ts_sec), tz=timezone.utc).replace(
                                microsecond=max(0, min(999999, int(ts_usec or 0))),
                            )
                        except (OSError, TypeError, ValueError):
                            continue
                        identity = "|".join((db_path.name, str(ts_sec), str(ts_usec or 0), str(pkt_hash or ""), str(norm_source or "")))
                        observation = {
                            "observation_id": hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24],
                            "timestamp": observed_dt.isoformat(),
                            "epoch_sec": int(ts_sec),
                            "epoch_usec": int(ts_usec or 0),
                            "frame_type": "Management",
                            "frame_subtype": frame_subtype,
                            "source_mac": norm_source,
                            "destination_mac": parsed.get("destination_mac"),
                            "transmitter_mac": parsed.get("transmitter_mac"),
                            "bssid": norm_bssid,
                            "destination_kind": destination_kind(parsed.get("destination_mac")),
                            "is_randomized_mac": normalized_randomized,
                            "sequence_number": parsed.get("sequence_number"),
                            "retry": parsed.get("retry"),
                            "power_management": parsed.get("power_management"),
                            "signal_dbm": signal_value,
                            "frequency_khz": frequency,
                            "channel": observed_channel,
                            "packet_length": packet_len,
                            "sensor": datasource or "kismet-server",
                            "source": "KISMET_SERVER",
                            "capture_file": db_path.name,
                            **_probe_metadata(parsed),
                        }
                        observation["fingerprint_signature"] = _probe_signature(observation)
                        observations.append(observation)
                        file_matches += 1
                        if file_matches >= limit:
                            break
                    if has_time_filter and start_ts is not None and oldest_packet_ts is not None:
                        reached_window_start = oldest_packet_ts < start_ts
                    if len(rows) < batch_size:
                        exhausted_table = True
                        break
                if (
                    scanned_rows >= scan_rows
                    and not reached_window_start
                    and not exhausted_table
                    and file_matches < limit
                ):
                    truncated_captures[db_path.name] = (
                        f"probe scan reached its {scan_rows:,}-row safety limit before the requested window"
                    )
            except (OSError, sqlite3.DatabaseError) as err:
                degraded_captures.pop(db_path.name, None)
                rejected_captures[db_path.name] = str(err)
                LOG.warning("[KISMET] Error querying probe observations from %s: %s", db_path, err)
            finally:
                if con is not None:
                    con.close()

        observations.sort(
            key=lambda item: (item["epoch_sec"], item["epoch_usec"], item["observation_id"]), reverse=True,
        )
        observations = observations[:limit]
        signals = [item["signal_dbm"] for item in observations if item.get("signal_dbm") is not None]
        channels = sorted({item["channel"] for item in observations if item.get("channel") is not None})
        source_macs = {item["source_mac"] for item in observations if item.get("source_mac")}
        randomized_macs = {item["source_mac"] for item in observations if item.get("is_randomized_mac") and item.get("source_mac")}
        request_count = sum(item["frame_subtype"] == "Probe Request" for item in observations)
        response_count = sum(item["frame_subtype"] == "Probe Response" for item in observations)
        groups: Dict[str, Dict[str, Any]] = {}
        for item in observations:
            signature = item["fingerprint_signature"]
            group = groups.setdefault(signature, {
                "fingerprint_signature": signature, "probe_count": 0, "mac_addresses": set(),
                "first_seen": item["timestamp"], "last_seen": item["timestamp"], "frame_subtypes": {},
                "channels": set(), "signals": [],
            })
            group["probe_count"] += 1
            if item.get("source_mac"):
                group["mac_addresses"].add(item["source_mac"])
            group["frame_subtypes"][item["frame_subtype"]] = group["frame_subtypes"].get(item["frame_subtype"], 0) + 1
            if item.get("channel") is not None:
                group["channels"].add(item["channel"])
            if item.get("signal_dbm") is not None:
                group["signals"].append(item["signal_dbm"])
            group["first_seen"] = min(group["first_seen"], item["timestamp"])
            group["last_seen"] = max(group["last_seen"], item["timestamp"])
        candidate_groups = []
        for group in groups.values():
            group["mac_addresses"] = sorted(group["mac_addresses"])
            group["unique_mac_count"] = len(group["mac_addresses"])
            group["channels"] = sorted(group["channels"])
            group["min_signal_dbm"] = min(group["signals"]) if group["signals"] else None
            group["max_signal_dbm"] = max(group["signals"]) if group["signals"] else None
            del group["signals"]
            candidate_groups.append(group)
        candidate_groups.sort(key=lambda group: (group["probe_count"], group["last_seen"]), reverse=True)

        return {
            "status": "ok",
            "source": "KISMET_SERVER",
            "query_window": {
                "start": start_dt.isoformat() if start_dt else "unbounded",
                "end": end_dt.isoformat(),
                "lookback_minutes": round((end_dt - start_dt).total_seconds() / 60.0, 1) if start_dt else None,
            },
            "summary": {
                "observation_count": len(observations),
                "probe_request_count": request_count,
                "probe_response_count": response_count,
                "unique_source_mac_count": len(source_macs),
                "randomized_source_mac_count": len(randomized_macs),
                "stable_source_mac_count": len(source_macs - randomized_macs),
                "channels": channels,
                "avg_signal_dbm": round(sum(signals) / len(signals), 1) if signals else None,
                "min_signal_dbm": min(signals) if signals else None,
                "max_signal_dbm": max(signals) if signals else None,
                "candidate_group_count": len(candidate_groups),
            },
            "observations": observations,
            "candidate_groups": candidate_groups,
            "capture_files_scanned": scanned_files,
            "rejected_captures": rejected_captures,
            "degraded_captures": degraded_captures,
            "truncated_captures": truncated_captures,
        }

    def list_sensors(self) -> List[Dict[str, Any]]:
        """List active/available Kismet sensors and their operational status."""
        sensors = []
        db_files = self.find_kismet_database_files()
        for idx, db_path in enumerate(db_files):
            try:
                con = sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True)
                cur = con.cursor()
                cur.execute("SELECT name, interface, definition, json FROM datasources LIMIT 1")
                row = cur.fetchone()
                ds_info = {}
                if row and row[3]:
                    try:
                        ds_info = json.loads(row[3].decode("utf-8"))
                    except Exception:
                        pass
                
                cur.execute("SELECT min(ts_sec), max(ts_sec), count(*) FROM packets")
                min_ts, max_ts, count = cur.fetchone()
                
                first_dt = datetime.fromtimestamp(min_ts, tz=timezone.utc).isoformat() if min_ts else None
                last_dt = datetime.fromtimestamp(max_ts, tz=timezone.utc).isoformat() if max_ts else None

                sensors.append({
                    "sensor_id": ds_info.get("kismet.datasource.uuid", f"sensor-{idx + 1}"),
                    "name": row[0] if row else db_path.stem,
                    "interface": row[1] if row else "wlp0s20f3mon",
                    "driver": ds_info.get("kismet.datasource.hardware", "iwlwifi"),
                    "status": "ONLINE" if idx == 0 else "OFFLINE",
                    "capture_file": db_path.name,
                    "packet_count": count,
                    "first_seen": first_dt,
                    "last_seen": last_dt,
                })
                con.close()
            except Exception as err:
                LOG.debug("[KISMET] Sensor info error on %s: %s", db_path, err)
        return sensors

    def get_sensor_health(self) -> Dict[str, Any]:
        """Check and report health for the local server Kismet sensor (Phase 8)."""
        process_running = False
        kismet_pid = None
        proc_path = Path("/proc")
        if proc_path.exists() and proc_path.is_dir():
            try:
                for entry in proc_path.iterdir():
                    if entry.name.isdigit():
                        try:
                            comm_path = entry / "comm"
                            if comm_path.exists():
                                comm = comm_path.read_text(encoding="utf-8", errors="ignore").strip()
                                if "kismet" in comm.lower():
                                    process_running = True
                                    kismet_pid = int(entry.name)
                                    break
                        except (OSError, PermissionError):
                            continue
            except (OSError, PermissionError):
                pass

        mon_iface = (
            os.getenv("KISMET_CAPTURE_INTERFACE")
            or os.getenv("KISMET_MONITOR_INTERFACE")
            or "wlp0s20f3mon"
        )
        iface_exists = Path(f"/sys/class/net/{mon_iface}").exists()
        iface_state = "UNKNOWN"
        if iface_exists:
            try:
                oper_path = Path(f"/sys/class/net/{mon_iface}/operstate")
                if oper_path.exists():
                    iface_state = oper_path.read_text(encoding="utf-8", errors="ignore").strip().upper()
            except (OSError, PermissionError):
                iface_state = "UP"

        from server_components.kismet_retention import KismetRetentionManager
        primary_dir = self.capture_dirs[0] if self.capture_dirs else None
        retention_mgr = KismetRetentionManager(primary_dir)
        storage_metrics = retention_mgr.get_storage_metrics()

        db_files = self.find_kismet_database_files()
        latest_db = db_files[0] if db_files else None
        latest_packet_count = 0
        latest_obs_dt = None
        source_readable = False
        if latest_db:
            con = None
            try:
                con = sqlite3.connect(f"file:{latest_db}?mode=ro&immutable=1", uri=True)
                cur = con.cursor()
                cur.execute("SELECT max(ts_sec + (ts_usec / 1000000.0)), count(*) FROM packets")
                row = cur.fetchone()
                if row:
                    max_ts, count = row
                    latest_packet_count = count or 0
                    if max_ts is not None:
                        latest_obs_dt = datetime.fromtimestamp(float(max_ts), tz=timezone.utc).isoformat()
                    source_readable = True
            except Exception as err:
                LOG.debug("[KISMET] Health query error on %s: %s", latest_db, err)
            finally:
                if con is not None:
                    con.close()

        stale_seconds = max(1, int(os.getenv("KISMET_HEALTH_STALE_SECONDS", "300")))
        capture_fresh = False
        if latest_obs_dt:
            latest_dt = parse_iso_or_epoch(latest_obs_dt)
            capture_fresh = bool(
                latest_dt and (datetime.now(timezone.utc) - latest_dt).total_seconds() <= stale_seconds
            )

        storage_available = bool(storage_metrics.get("exists"))
        if process_running and iface_exists and source_readable and storage_available and capture_fresh:
            status = "ONLINE"
        elif process_running or iface_exists or db_files:
            status = "DEGRADED"
        else:
            status = "OFFLINE"

        # A bounded decoded probe sample tells operators whether the sensor is
        # receiving the management frames needed for fingerprinting.  It is
        # deliberately independent of the managed-device inventory.
        probe_summary: Dict[str, Any] = {
            "sample_limit": 1000,
            "probe_request_count": 0,
            "probe_response_count": 0,
            "latest_probe_time": None,
            "randomized_source_mac_count": 0,
            "channels": [],
        }
        if latest_db:
            try:
                probes = self.query_recent_probes(
                    lookback_minutes="all", limit=1000, capture_file=latest_db.name,
                )
                probe_summary.update({
                    "probe_request_count": probes["summary"]["probe_request_count"],
                    "probe_response_count": probes["summary"]["probe_response_count"],
                    "randomized_source_mac_count": probes["summary"]["randomized_source_mac_count"],
                    "channels": probes["summary"]["channels"],
                })
                if probes["observations"]:
                    probe_summary["latest_probe_time"] = probes["observations"][0]["timestamp"]
            except Exception as err:  # pragma: no cover - health must stay available
                LOG.debug("[KISMET] Probe health query failed: %s", err)

        return {
            "status": status,
            "sensor": "kismet-server",
            "source": "KISMET_SERVER",
            "process": {
                "running": process_running,
                "pid": kismet_pid,
            },
            "interface": {
                "name": mon_iface,
                "exists": iface_exists,
                "state": iface_state,
            },
            "source_health": {
                "readable": source_readable,
                "capture_fresh": capture_fresh,
                "stale_after_seconds": stale_seconds,
            },
            "storage_health": {
                "available": storage_available,
                "free_space_ok": (
                    storage_metrics.get("free_bytes") is None
                    or storage_metrics.get("free_bytes", 0) >= int(os.getenv("KISMET_MIN_FREE_BYTES", "0"))
                ),
            },
            "storage": storage_metrics,
            "latest_capture": {
                "file": latest_db.name if latest_db else None,
                "packet_count": latest_packet_count,
                "last_observation_time": latest_obs_dt,
            },
            "management_capture": probe_summary,
        }
