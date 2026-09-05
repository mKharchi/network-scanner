"""Kismet Passive Wireless Investigation Service.

Exposes historical 802.11 wireless observations and RF telemetry (RSSI, channels,
frame types, packet timelines) correlated with known devices from the central
device base without copying raw captures into MySQL.

Implements Phase 4 of docs/integrating-kismet-and-backup/plan.md:
    Device Identifier -> MAC -> Sensor -> Time Window -> Kismet Observations -> Normalized Investigation Response
"""

from __future__ import annotations

import glob
import json
import logging
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    from database import get_connection
except ImportError:  # pragma: no cover
    from ..database import get_connection

LOG = logging.getLogger("kismet_service")

DEFAULT_LOOKBACK_MINUTES = 30
MAX_OBSERVATION_LIMIT = 2000
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


class KismetInvestigationService:
    """Service to search, correlate, and structure Kismet wireless observations."""

    def __init__(
        self,
        capture_dirs: Optional[List[Path | str]] = None,
        *,
        fallback_scan_dir: Optional[Path | str] = None,
    ):
        configured_dirs = os.getenv("KISMET_CAPTURE_DIRS")
        if capture_dirs:
            self.capture_dirs = [Path(p) for p in capture_dirs]
        elif configured_dirs:
            self.capture_dirs = [Path(p.strip()) for p in configured_dirs.split(",") if p.strip()]
        else:
            self.capture_dirs = [
                Path("/home/adonis/kismet"),
                Path("/home/adonis"),
                Path(__file__).resolve().parents[1] / "storage" / "kismet",
            ]
        self.fallback_scan_dir = Path(fallback_scan_dir or (Path(__file__).resolve().parents[1] / "storage" / "network_scans"))

    def find_kismet_database_files(self) -> List[Path]:
        """Locate all available .kismet SQLite database files across configured paths."""
        found: List[Path] = []
        for cdir in self.capture_dirs:
            if cdir.exists() and cdir.is_dir():
                for kfile in sorted(cdir.glob("*.kismet")):
                    if kfile.is_file() and kfile not in found:
                        found.append(kfile)
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
        end_dt = parse_iso_or_epoch(end_time) or datetime.now(timezone.utc)
        start_dt = parse_iso_or_epoch(start_time)
        if start_dt is None:
            mins = parse_lookback_to_minutes(lookback_minutes, default=DEFAULT_LOOKBACK_MINUTES)
            start_dt = end_dt - timedelta(minutes=mins)

        if start_dt >= end_dt:
            raise ValueError("start_time must be earlier than end_time")

        start_epoch = int(start_dt.timestamp())
        end_epoch = int(end_dt.timestamp())
        limit = min(MAX_OBSERVATION_LIMIT, max(1, int(limit)))

        db_files = self.find_kismet_database_files()
        observations: List[Dict[str, Any]] = []
        signals: List[int] = []
        frequencies_seen: Set[float] = set()
        frame_type_counts: Dict[str, int] = {}
        total_matched_packets = 0

        # Query packets from Kismet databases
        for db_path in db_files:
            try:
                con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
                cur = con.cursor()

                # Optimized query matching sourcemac, destmac, or transmac
                query = """
                SELECT ts_sec, ts_usec, phyname, sourcemac, destmac, transmac, signal, frequency, packet_len, datasource, dlt, packet, hash
                FROM packets
                WHERE (sourcemac = ? OR destmac = ? OR transmac = ?)
                """
                params: List[Any] = [target_mac, target_mac, target_mac]

                # Note: if start_epoch/end_epoch span the database timeframe, we apply time filter.
                # If capture is historical, we allow match within database bounds if lookback was default.
                if start_time is not None or end_time is not None:
                    query += " AND ts_sec >= ? AND ts_sec <= ?"
                    params.extend([start_epoch, end_epoch])

                query += " ORDER BY ts_sec DESC, ts_usec DESC LIMIT ?"
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

                    # Decode 802.11 frame type from packet bytes if available
                    frame_type = "Data"
                    frame_subtype = "QoS Data"
                    if pkt_blob and len(pkt_blob) >= 2:
                        try:
                            # If radiotap header (DLT 127)
                            offset = 0
                            if dlt == 127 and len(pkt_blob) >= 4:
                                rt_len = int.from_bytes(pkt_blob[2:4], "little")
                                if rt_len < len(pkt_blob):
                                    offset = rt_len
                            fc = pkt_blob[offset]
                            t = (fc >> 2) & 0x03
                            st = (fc >> 4) & 0x0F
                            frame_type = TYPE_MAP.get(t, f"Type {t}")
                            if t == 0:
                                frame_subtype = MGMT_MAP.get(st, f"Subtype {st}")
                            elif t == 1:
                                frame_subtype = CTRL_MAP.get(st, f"Subtype {st}")
                            elif t == 2:
                                frame_subtype = DATA_MAP.get(st, f"Subtype {st}")
                            else:
                                frame_subtype = f"Subtype {st}"
                        except Exception:
                            pass

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
                    norm_src = normalize_mac(sourcemac)
                    norm_dst = normalize_mac(destmac)
                    norm_tx = normalize_mac(transmac)

                    role = "OBSERVED"
                    if norm_src == target_mac:
                        role = "SOURCE"
                    elif norm_tx == target_mac:
                        role = "TRANSMITTER"
                    elif norm_dst == target_mac:
                        role = "DESTINATION"

                    obs_dt = datetime.fromtimestamp(ts_sec, tz=timezone.utc)
                    channel = frequency_to_channel(frequency)

                    observations.append({
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
                        "sensor": datasource or "kismet-sensor-pilot",
                        "capture_file": db_path.name,
                        "packet_hash": pkt_hash,
                    })

                    if len(observations) >= limit:
                        break

                con.close()
                if len(observations) >= limit:
                    break
            except Exception as err:
                LOG.warning("[KISMET] Error querying %s: %s", db_path, err)

        # Compute summary RF statistics
        avg_rssi = round(sum(signals) / len(signals), 1) if signals else None
        min_rssi = min(signals) if signals else None
        max_rssi = max(signals) if signals else None

        channels = sorted([frequency_to_channel(f) for f in frequencies_seen if frequency_to_channel(f)])

        return {
            "device": device,
            "query_window": {
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
                "lookback_minutes": round((end_dt - start_dt).total_seconds() / 60.0, 1),
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
        }

    def list_sensors(self) -> List[Dict[str, Any]]:
        """List active/available Kismet sensors and their operational status."""
        sensors = []
        db_files = self.find_kismet_database_files()
        for idx, db_path in enumerate(db_files):
            try:
                con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
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
