"""Read-only, versioned ML extraction primitives for Kismet captures.

This module deliberately sits beside, rather than inside, the investigation
service.  It reads Kismet ``.kismet`` SQLite files read-only, parses packet
bytes only in memory, and returns normalized observations/aggregates.  No raw
packet payload is persisted by this module.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple

FEATURE_SCHEMA_VERSION = "kismet-ml-v1"
DATASET_MANIFEST_VERSION = "kismet-ml-dataset-v1"
LABEL_SCHEMA_VERSION = "kismet-ml-label-v1"
SUPPORTED_PACKET_COLUMNS = {
    "ts_sec", "ts_usec", "sourcemac", "destmac", "transmac", "frequency",
    "signal", "packet_len", "dlt", "packet",
}
FINGERPRINT_SUBTYPES = {
    "Probe Request", "Probe Response", "Association Request",
    "Reassociation Request", "Association Response",
}

TYPE_NAMES = {0: "Management", 1: "Control", 2: "Data", 3: "Extension"}
MGMT_NAMES = {
    0: "Association Request", 1: "Association Response", 2: "Reassociation Request",
    3: "Reassociation Response", 4: "Probe Request", 5: "Probe Response",
    8: "Beacon", 10: "Disassociation", 11: "Authentication", 12: "Deauthentication",
    13: "Action",
}
CONTROL_NAMES = {
    8: "Block Ack Request", 9: "Block Ack", 10: "PS-Poll", 11: "RTS",
    12: "CTS", 13: "ACK", 14: "CF-End",
}
DATA_NAMES = {0: "Data", 4: "Null Data", 8: "QoS Data", 12: "QoS Null"}


def normalize_mac(value: Any) -> Optional[str]:
    """Normalize a MAC address without treating it as an ML feature."""
    if not isinstance(value, str):
        return None
    compact = value.replace(":", "").replace("-", "").strip().upper()
    if len(compact) != 12 or any(ch not in "0123456789ABCDEF" for ch in compact):
        return None
    return ":".join(compact[index:index + 2] for index in range(0, 12, 2))


def is_randomized_mac(mac: Optional[str]) -> bool:
    """Return the locally-administered-address indication for a valid MAC."""
    normalized = normalize_mac(mac)
    return bool(normalized and (int(normalized[:2], 16) & 0x02))


def _frequency_mhz(value: Any) -> Optional[float]:
    try:
        frequency = float(value)
    except (TypeError, ValueError):
        return None
    if frequency <= 0:
        return None
    return frequency / 1000.0 if frequency > 100_000 else frequency


def _mac_from_bytes(value: bytes) -> str:
    return ":".join(f"{part:02X}" for part in value)


def _read_mac(blob: bytes, offset: int) -> Optional[str]:
    if offset < 0 or offset + 6 > len(blob):
        return None
    return _mac_from_bytes(blob[offset:offset + 6])


@dataclass(frozen=True)
class KismetSchemaReport:
    """Evidence of the local source schema used by an extraction run."""

    capture_file: str
    packets_columns: Tuple[str, ...]
    devices_columns: Tuple[str, ...]
    has_required_packet_columns: bool
    missing_packet_columns: Tuple[str, ...]
    bssid_is_packet_column: bool
    packet_payload_column: Optional[str]
    timestamp_columns: Tuple[str, ...]
    device_json_column: Optional[str]
    device_json_decodable: Optional[bool]


@dataclass(frozen=True)
class StructuredObservation:
    """Stable, raw-column-independent 802.11 observation for downstream ML."""

    observation_id: str
    timestamp_epoch_ms: int
    source_mac: Optional[str]
    destination_mac: Optional[str]
    transmitter_mac: Optional[str]
    bssid: Optional[str]
    frame_type: str
    frame_subtype: str
    frame_length: Optional[int]
    signal_dbm: Optional[float]
    frequency_mhz: Optional[float]
    sequence_number: Optional[int]
    to_ds: Optional[bool]
    from_ds: Optional[bool]
    retry: Optional[bool]
    power_management: Optional[bool]
    ie_tag_sequence: Tuple[int, ...] = ()
    ie_vendor_ouis: Tuple[str, ...] = ()
    ht_capabilities_hex: Optional[str] = None
    vht_capabilities_hex: Optional[str] = None
    he_capabilities_hex: Optional[str] = None
    wmm_capabilities_present: bool = False
    capture_file: str = ""


@dataclass(frozen=True)
class FingerprintObservation:
    observation_id: str
    timestamp_epoch_ms: int
    source_mac: Optional[str]
    is_randomized_mac: bool
    frame_subtype: str
    sequence_number: Optional[int]
    signal_dbm: Optional[float]
    frequency_mhz: Optional[float]
    ie_tag_sequence: Tuple[int, ...]
    ie_vendor_ouis: Tuple[str, ...]
    ht_capabilities_hex: Optional[str]
    vht_capabilities_hex: Optional[str]
    he_capabilities_hex: Optional[str]
    wmm_capabilities_present: bool
    capture_file: str = ""


@dataclass(frozen=True)
class ThreatTick:
    threat_tick_id: str
    timestamp_sec: int
    channel_frequency_mhz: Optional[float]
    bssid: Optional[str]
    rts_frame_count: int
    cts_frame_count: int
    deauth_frame_count: int
    disassoc_frame_count: int
    assoc_req_count: int
    auth_req_count: int
    null_data_frame_count: int
    retry_frame_count: int
    sequence_gap_delta_sum: int
    mean_rssi_dbm: Optional[float]
    rssi_std_dev: Optional[float]


@dataclass(frozen=True)
class TrafficWindow:
    window_id: str
    client_mac: str
    window_start_ms: int
    window_end_ms: int
    total_frame_count: int
    total_byte_count: int
    uplink_frame_count: int
    downlink_frame_count: int
    uplink_byte_count: int
    downlink_byte_count: int
    retry_frame_count: int
    data_frame_count: int
    mgmt_frame_count: int
    ctrl_frame_count: int
    derived_features_json: Dict[str, Optional[float]]


@dataclass(frozen=True)
class WindowConfig:
    length_seconds: int = 30
    hop_seconds: int = 5
    burst_iat_ms: float = 2.0
    burst_min_consecutive: int = 4
    periodicity_bin_seconds: int = 1
    periodicity_min_samples: int = 4
    periodicity_max_lag: int = 10

    def __post_init__(self) -> None:
        if self.length_seconds <= 0 or self.hop_seconds <= 0:
            raise ValueError("window length and hop must be positive")
        if self.periodicity_bin_seconds <= 0 or self.burst_min_consecutive < 2:
            raise ValueError("invalid feature aggregation configuration")


def inspect_kismet_schema(capture_file: Path | str) -> KismetSchemaReport:
    """Inspect a capture schema read-only; never infer columns from research."""
    path = Path(capture_file)
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        def columns(table: str) -> Tuple[str, ...]:
            try:
                return tuple(str(row[1]) for row in con.execute(f"PRAGMA table_info({table})"))
            except sqlite3.DatabaseError:
                return ()

        packets = columns("packets")
        devices = columns("devices")
        present = set(packets)
        missing = tuple(sorted(SUPPORTED_PACKET_COLUMNS - present))
        device_json_column = "device" if "device" in devices else None
        device_json_decodable: Optional[bool] = None
        if device_json_column:
            try:
                sample = con.execute("SELECT device FROM devices WHERE device IS NOT NULL LIMIT 1").fetchone()
                device_json_decodable = True if sample is None else decode_kismet_json(sample[0]) is not None
            except sqlite3.DatabaseError:
                device_json_decodable = False
        return KismetSchemaReport(
            capture_file=path.name,
            packets_columns=packets,
            devices_columns=devices,
            has_required_packet_columns=not missing,
            missing_packet_columns=missing,
            bssid_is_packet_column="bssid" in present,
            packet_payload_column="packet" if "packet" in present else None,
            timestamp_columns=tuple(name for name in ("ts_sec", "ts_usec") if name in present),
            device_json_column=device_json_column,
            device_json_decodable=device_json_decodable,
        )
    finally:
        con.close()


def decode_kismet_json(value: Any) -> Optional[Mapping[str, Any]]:
    """Decode Kismet JSON BLOB/TEXT safely for schema verification or enrichment."""
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if not isinstance(value, str):
        return None
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return None
    return decoded if isinstance(decoded, Mapping) else None


def _radiotap_offset(packet: bytes, dlt: Any) -> Optional[int]:
    """Return the validated 802.11 offset; do not assume radiotap is 4 bytes."""
    if not packet:
        return None
    if dlt == 127:
        if len(packet) < 4:
            return None
        length = int.from_bytes(packet[2:4], "little")
        return length if 4 <= length <= len(packet) - 2 else None
    return 0 if len(packet) >= 2 else None


def _frame_names(frame_type: int, subtype: int) -> Tuple[str, str]:
    if frame_type == 0:
        return TYPE_NAMES[0], MGMT_NAMES.get(subtype, f"Subtype {subtype}")
    if frame_type == 1:
        return TYPE_NAMES[1], CONTROL_NAMES.get(subtype, f"Subtype {subtype}")
    if frame_type == 2:
        return TYPE_NAMES[2], DATA_NAMES.get(subtype, f"Subtype {subtype}")
    return TYPE_NAMES.get(frame_type, f"Type {frame_type}"), f"Subtype {subtype}"


def _management_ie_offset(subtype: int, header_end: int) -> Optional[int]:
    fixed_lengths = {0: 4, 1: 6, 2: 10, 3: 6, 4: 0, 5: 12, 8: 12}
    fixed = fixed_lengths.get(subtype)
    return header_end + fixed if fixed is not None else None


def _parse_information_elements(packet: bytes, offset: Optional[int]) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "tags": [], "vendor_ouis": [], "supported_rates": [], "ht": None, "vht": None,
        "he": None, "wmm": False, "rsn": False, "ssid_present": False,
        "ssid_length": None, "ssid_hidden": False,
    }
    if offset is None or offset >= len(packet):
        return result
    while offset + 2 <= len(packet):
        tag, length = packet[offset], packet[offset + 1]
        offset += 2
        if offset + length > len(packet):
            break
        body = packet[offset:offset + length]
        offset += length
        result["tags"].append(tag)
        if tag == 0:
            # SSIDs can identify people, locations, or organisations.  Keep
            # only their observable shape; never return the SSID bytes.
            result["ssid_present"] = True
            result["ssid_length"] = length
            result["ssid_hidden"] = length == 0
        elif tag in {1, 50}:
            # The high bit means a basic rate; the remaining value is in
            # 500-kbit/s units.  Keep the normalized numeric rate pattern.
            result["supported_rates"].extend(
                sorted({(rate & 0x7F) / 2.0 for rate in body if rate & 0x7F})
            )
        elif tag == 45:
            result["ht"] = body.hex()
        elif tag == 191:
            result["vht"] = body.hex()
        elif tag == 255 and body and body[0] == 35:  # IEEE 802.11 HE Capabilities extension
            result["he"] = body[1:].hex()
        elif tag == 221 and len(body) >= 3:
            oui = body[:3].hex().upper()
            result["vendor_ouis"].append(oui)
            # Microsoft WMM vendor IE: 00:50:F2, type 2.
            if oui == "0050F2" and len(body) >= 4 and body[3] == 2:
                result["wmm"] = True
        elif tag == 48:
            result["rsn"] = True
    result["vendor_ouis"] = sorted(set(result["vendor_ouis"]))
    result["supported_rates"] = sorted(set(result["supported_rates"]))
    return result


def parse_80211_packet(
    packet: Any, *, dlt: Any, source_mac: Any = None, destination_mac: Any = None,
    transmitter_mac: Any = None,
) -> Optional[Dict[str, Any]]:
    """Parse the validated 802.11 header and management IEs from one payload.

    Kismet columns are retained as a fallback for source/destination identity,
    while BSSID and header flags always come from the frame when available.
    """
    if not isinstance(packet, (bytes, bytearray, memoryview)):
        return None
    blob = bytes(packet)
    offset = _radiotap_offset(blob, dlt)
    if offset is None or offset + 2 > len(blob):
        return None
    fc = int.from_bytes(blob[offset:offset + 2], "little")
    frame_type, subtype = (fc >> 2) & 0x03, (fc >> 4) & 0x0F
    frame_type_name, subtype_name = _frame_names(frame_type, subtype)
    to_ds, from_ds = bool(fc & 0x0100), bool(fc & 0x0200)
    retry, power_management = bool(fc & 0x0800), bool(fc & 0x1000)
    addr1, addr2, addr3 = _read_mac(blob, offset + 4), _read_mac(blob, offset + 10), _read_mac(blob, offset + 16)
    header_end: Optional[int] = None
    sequence_number: Optional[int] = None
    bssid: Optional[str] = None
    if frame_type in (0, 2) and addr1 and addr2 and addr3 and offset + 24 <= len(blob):
        sequence_number = int.from_bytes(blob[offset + 22:offset + 24], "little") >> 4
        header_end = offset + 24 + (6 if frame_type == 2 and to_ds and from_ds else 0)
        if frame_type == 0 or (not to_ds and not from_ds):
            bssid = addr3
        elif to_ds and not from_ds:
            bssid = addr1
        elif from_ds and not to_ds:
            bssid = addr2
    parsed_ies = _parse_information_elements(blob, _management_ie_offset(subtype, header_end) if frame_type == 0 and header_end else None)
    return {
        "frame_type": frame_type_name, "frame_subtype": subtype_name,
        "source_mac": normalize_mac(source_mac) or addr2,
        "destination_mac": normalize_mac(destination_mac) or addr1,
        "transmitter_mac": normalize_mac(transmitter_mac) or addr2,
        "bssid": bssid, "sequence_number": sequence_number,
        "to_ds": to_ds, "from_ds": from_ds, "retry": retry,
        "power_management": power_management, **parsed_ies,
    }


class KismetMLExtractor:
    """Extract dual-path ML observations from compatible Kismet captures.

    The caller may persist the returned derived objects, but this extractor
    never writes a capture or raw frame body.  A schema report is retained for
    each accepted capture so a dataset can prove the local schema it used.
    """

    def __init__(self, capture_files: Iterable[Path | str], *, max_observations: Optional[int] = None):
        self.capture_files = [Path(item) for item in capture_files]
        if max_observations is not None and max_observations <= 0:
            raise ValueError("max_observations must be positive")
        self.max_observations = max_observations
        self.schema_reports: List[KismetSchemaReport] = []
        self.rejected_captures: Dict[str, str] = {}

    def iter_structured_observations(self) -> Iterator[StructuredObservation]:
        remaining = self.max_observations
        for capture_file in self.capture_files:
            if remaining is not None and remaining <= 0:
                return
            try:
                report = inspect_kismet_schema(capture_file)
            except (OSError, sqlite3.DatabaseError) as error:
                self.rejected_captures[capture_file.name] = f"schema inspection failed: {error}"
                continue
            self.schema_reports.append(report)
            if not report.has_required_packet_columns:
                self.rejected_captures[capture_file.name] = (
                    "missing packet columns: " + ", ".join(report.missing_packet_columns)
                )
                continue
            for observation in self._read_capture(capture_file, limit=remaining):
                yield observation
                if remaining is not None:
                    remaining -= 1
                    if remaining <= 0:
                        return

    def _read_capture(self, capture_file: Path, *, limit: Optional[int] = None) -> Iterator[StructuredObservation]:
        con: Optional[sqlite3.Connection] = None
        try:
            con = sqlite3.connect(f"file:{capture_file}?mode=ro", uri=True)
            con.row_factory = sqlite3.Row
            packet_columns = {str(row[1]) for row in con.execute("PRAGMA table_info(packets)")}
            hash_column = "hash" if "hash" in packet_columns else None
            if limit is not None:
                # Select lightweight row IDs first.  Sorting packet BLOBs in
                # SQLite before applying LIMIT can consume hundreds of MB on
                # active captures.
                query = """
                    SELECT p.rowid AS _kismet_rowid, p.ts_sec, p.ts_usec,
                           p.sourcemac, p.destmac, p.transmac, p.frequency,
                           p.signal, p.packet_len, p.dlt, p.packet%s
                    FROM packets AS p
                    INNER JOIN (
                        SELECT rowid FROM packets
                        ORDER BY ts_sec DESC, ts_usec DESC, rowid DESC
                        LIMIT ?
                    ) AS recent ON recent.rowid = p.rowid
                """ % (", p.hash" if hash_column else "")
                cursor = con.execute(query, (limit,))
            else:
                query = """
                    SELECT rowid AS _kismet_rowid, ts_sec, ts_usec, sourcemac,
                           destmac, transmac, frequency, signal, packet_len,
                           dlt, packet%s
                    FROM packets
                    ORDER BY ts_sec ASC, ts_usec ASC, rowid ASC
                """ % (", hash" if hash_column else "")
                cursor = con.execute(query)
            for row in cursor:
                parsed = parse_80211_packet(
                    row["packet"], dlt=row["dlt"], source_mac=row["sourcemac"],
                    destination_mac=row["destmac"], transmitter_mac=row["transmac"],
                )
                if not parsed:
                    continue
                try:
                    epoch_ms = int(row["ts_sec"]) * 1000 + int((row["ts_usec"] or 0) / 1000)
                except (TypeError, ValueError):
                    continue
                packet_hash = str(row[hash_column] if hash_column and row[hash_column] is not None else "")
                # ``hash`` is optional in local Kismet variants.  A transient
                # digest supplies deterministic identity without persisting the
                # raw payload or assuming that optional column exists.
                packet_identity = packet_hash or hashlib.sha256(bytes(row["packet"])).hexdigest()
                identity = "|".join((capture_file.name, str(row["_kismet_rowid"]), str(epoch_ms), packet_identity, str(row["sourcemac"] or "")))
                observation_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
                signal = _as_number(row["signal"])
                length = _as_int(row["packet_len"])
                yield StructuredObservation(
                    observation_id=observation_id,
                    timestamp_epoch_ms=epoch_ms,
                    source_mac=parsed["source_mac"], destination_mac=parsed["destination_mac"],
                    transmitter_mac=parsed["transmitter_mac"], bssid=parsed["bssid"],
                    frame_type=parsed["frame_type"], frame_subtype=parsed["frame_subtype"],
                    frame_length=length, signal_dbm=signal, frequency_mhz=_frequency_mhz(row["frequency"]),
                    sequence_number=parsed["sequence_number"], to_ds=parsed["to_ds"],
                    from_ds=parsed["from_ds"], retry=parsed["retry"],
                    power_management=parsed["power_management"],
                    ie_tag_sequence=tuple(parsed["tags"]), ie_vendor_ouis=tuple(parsed["vendor_ouis"]),
                    ht_capabilities_hex=parsed["ht"], vht_capabilities_hex=parsed["vht"],
                    he_capabilities_hex=parsed["he"], wmm_capabilities_present=parsed["wmm"],
                    capture_file=capture_file.name,
                )
        except (OSError, sqlite3.DatabaseError) as error:
            self.rejected_captures[capture_file.name] = f"capture read failed: {error}"
        finally:
            if con is not None:
                con.close()

    def fingerprint_observations(self) -> Iterator[FingerprintObservation]:
        for observation in self.iter_structured_observations():
            fingerprint = to_fingerprint_observation(observation)
            if fingerprint:
                yield fingerprint

    def threat_ticks(self) -> List[ThreatTick]:
        """Aggregate high-frequency threat signals without retaining raw frames."""
        buckets: Dict[Tuple[int, Optional[float], Optional[str]], Dict[str, Any]] = {}
        previous_sequences: Dict[Tuple[Optional[str], Optional[str]], int] = {}
        observations = sorted(
            self.iter_structured_observations(),
            key=lambda item: (
                item.timestamp_epoch_ms,
                {"Management": 0, "Control": 1, "Data": 2, "Extension": 3}.get(item.frame_type, 9),
                item.sequence_number if item.sequence_number is not None else -1,
            ),
        )
        for observation in observations:
            key = (observation.timestamp_epoch_ms // 1000, observation.frequency_mhz, observation.bssid)
            bucket = buckets.setdefault(key, {"rssi": [], "rts": 0, "cts": 0, "deauth": 0,
                "disassoc": 0, "assoc": 0, "auth": 0, "null": 0, "retry": 0, "gap": 0})
            subtype = observation.frame_subtype
            if subtype == "RTS": bucket["rts"] += 1
            elif subtype == "CTS": bucket["cts"] += 1
            elif subtype == "Deauthentication": bucket["deauth"] += 1
            elif subtype == "Disassociation": bucket["disassoc"] += 1
            elif subtype == "Association Request": bucket["assoc"] += 1
            elif subtype == "Authentication": bucket["auth"] += 1
            elif subtype in {"Null Data", "QoS Null"}: bucket["null"] += 1
            if observation.retry:
                bucket["retry"] += 1
            if observation.signal_dbm is not None:
                bucket["rssi"].append(observation.signal_dbm)
            sequence_key = (observation.transmitter_mac or observation.source_mac, observation.bssid)
            if observation.sequence_number is not None and sequence_key[0]:
                prior = previous_sequences.get(sequence_key)
                if prior is not None:
                    delta = (observation.sequence_number - prior) % 4096
                    if 1 < delta < 2048:
                        bucket["gap"] += delta - 1
                previous_sequences[sequence_key] = observation.sequence_number
        ticks: List[ThreatTick] = []
        for (timestamp_sec, frequency, bssid), values in sorted(
            buckets.items(), key=lambda item: (item[0][0], item[0][1] or -1.0, item[0][2] or "")
        ):
            rssi = values["rssi"]
            identifier = f"{timestamp_sec}|{frequency}|{bssid or ''}"
            ticks.append(ThreatTick(
                threat_tick_id=hashlib.sha256(identifier.encode()).hexdigest()[:24],
                timestamp_sec=timestamp_sec, channel_frequency_mhz=frequency, bssid=bssid,
                rts_frame_count=values["rts"], cts_frame_count=values["cts"],
                deauth_frame_count=values["deauth"], disassoc_frame_count=values["disassoc"],
                assoc_req_count=values["assoc"], auth_req_count=values["auth"],
                null_data_frame_count=values["null"], retry_frame_count=values["retry"],
                sequence_gap_delta_sum=values["gap"], mean_rssi_dbm=_mean_or_none(rssi),
                rssi_std_dev=_std_or_none(rssi),
            ))
        return ticks


def _as_number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number != 0 else None


def to_fingerprint_observation(observation: StructuredObservation) -> Optional[FingerprintObservation]:
    """Project a structured observation onto the fingerprint-only contract."""
    if observation.frame_subtype not in FINGERPRINT_SUBTYPES:
        return None
    return FingerprintObservation(
        observation_id=observation.observation_id,
        timestamp_epoch_ms=observation.timestamp_epoch_ms,
        source_mac=observation.source_mac,
        is_randomized_mac=is_randomized_mac(observation.source_mac),
        frame_subtype=observation.frame_subtype,
        sequence_number=observation.sequence_number,
        signal_dbm=observation.signal_dbm,
        frequency_mhz=observation.frequency_mhz,
        ie_tag_sequence=observation.ie_tag_sequence,
        ie_vendor_ouis=observation.ie_vendor_ouis,
        ht_capabilities_hex=observation.ht_capabilities_hex,
        vht_capabilities_hex=observation.vht_capabilities_hex,
        he_capabilities_hex=observation.he_capabilities_hex,
        wmm_capabilities_present=observation.wmm_capabilities_present,
        capture_file=observation.capture_file,
    )


def _as_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _mean_or_none(values: Sequence[float]) -> Optional[float]:
    return statistics.fmean(values) if values else None


def _std_or_none(values: Sequence[float]) -> Optional[float]:
    return statistics.pstdev(values) if len(values) > 1 else (0.0 if values else None)


def _direction_for_client(observation: StructuredObservation, client_mac: str) -> Optional[str]:
    """Use To-DS/From-DS only for unambiguous infrastructure-mode traffic."""
    if observation.to_ds is True and observation.from_ds is False:
        if client_mac in {observation.source_mac, observation.transmitter_mac}:
            return "uplink"
    elif observation.from_ds is True and observation.to_ds is False:
        if client_mac == observation.destination_mac:
            return "downlink"
    return None


def _periodicity_score(timestamps_ms: Sequence[int], config: WindowConfig) -> Optional[float]:
    """Maximum positive normalized autocorrelation over a bounded lag range."""
    if len(timestamps_ms) < config.periodicity_min_samples:
        return None
    bin_ms = config.periodicity_bin_seconds * 1000
    first_bin = min(timestamps_ms) // bin_ms
    last_bin = max(timestamps_ms) // bin_ms
    counts = [0] * (last_bin - first_bin + 1)
    for timestamp in timestamps_ms:
        counts[timestamp // bin_ms - first_bin] += 1
    if len(counts) < config.periodicity_min_samples:
        return None
    mean = statistics.fmean(counts)
    denominator = sum((value - mean) ** 2 for value in counts)
    if denominator == 0:
        return 0.0
    upper_lag = min(config.periodicity_max_lag, len(counts) - 1)
    if upper_lag < 1:
        return None
    scores = []
    for lag in range(1, upper_lag + 1):
        numerator = sum((counts[i] - mean) * (counts[i + lag] - mean) for i in range(len(counts) - lag))
        scores.append(numerator / denominator)
    return max(0.0, max(scores)) if scores else None


def _burst_metrics(timestamps_ms: Sequence[int], config: WindowConfig) -> Tuple[float, Optional[float]]:
    if len(timestamps_ms) < config.burst_min_consecutive:
        return 0.0, None
    threshold = config.burst_iat_ms
    burst_durations: List[float] = []
    run_start: Optional[int] = None
    run_iats = 0
    for previous, current in zip(timestamps_ms, timestamps_ms[1:]):
        if current - previous <= threshold:
            if run_start is None:
                run_start = previous
            run_iats += 1
        else:
            if run_start is not None and run_iats + 1 >= config.burst_min_consecutive:
                burst_durations.append(float(previous - run_start))
            run_start, run_iats = None, 0
    if run_start is not None and run_iats + 1 >= config.burst_min_consecutive:
        burst_durations.append(float(timestamps_ms[-1] - run_start))
    return float(len(burst_durations)), _mean_or_none(burst_durations)


def build_traffic_windows(
    observations: Iterable[StructuredObservation], *, config: WindowConfig = WindowConfig(),
    client_macs: Optional[Iterable[str]] = None,
) -> List[TrafficWindow]:
    """Build overlapping, leakage-aware traffic windows from stable observations."""
    all_observations = sorted(observations, key=lambda item: item.timestamp_epoch_ms)
    requested = {normalized for raw in (client_macs or []) if (normalized := normalize_mac(raw))}
    discovered = {
        mac for item in all_observations
        for mac in (item.source_mac, item.destination_mac, item.transmitter_mac) if mac
    }
    clients = sorted(requested or discovered)
    windows: List[TrafficWindow] = []
    duration_ms, hop_ms = config.length_seconds * 1000, config.hop_seconds * 1000
    for client in clients:
        client_observations = [item for item in all_observations if client in {
            item.source_mac, item.destination_mac, item.transmitter_mac,
        }]
        if not client_observations:
            continue
        start = (client_observations[0].timestamp_epoch_ms // hop_ms) * hop_ms
        last = client_observations[-1].timestamp_epoch_ms
        while start <= last:
            end = start + duration_ms
            members = [item for item in client_observations if start <= item.timestamp_epoch_ms < end]
            if members:
                windows.append(_make_traffic_window(client, start, end, members, config))
            start += hop_ms
    return windows


def _make_traffic_window(
    client_mac: str, start_ms: int, end_ms: int, members: Sequence[StructuredObservation],
    config: WindowConfig,
) -> TrafficWindow:
    lengths = [item.frame_length for item in members if item.frame_length is not None]
    timestamps = [item.timestamp_epoch_ms for item in members]
    iats = [current - prior for prior, current in zip(timestamps, timestamps[1:])]
    uplink = [item for item in members if _direction_for_client(item, client_mac) == "uplink"]
    downlink = [item for item in members if _direction_for_client(item, client_mac) == "downlink"]
    total_bytes = sum(lengths)
    uplink_bytes = sum(item.frame_length or 0 for item in uplink)
    downlink_bytes = sum(item.frame_length or 0 for item in downlink)
    burst_count, burst_duration = _burst_metrics(timestamps, config)
    duration_seconds = (end_ms - start_ms) / 1000.0
    prefix = FEATURE_SCHEMA_VERSION
    features: Dict[str, Optional[float]] = {
        f"{prefix}.packet_rate": len(members) / duration_seconds,
        f"{prefix}.byte_rate": total_bytes / duration_seconds,
        f"{prefix}.mean_packet_size": _mean_or_none(lengths),
        f"{prefix}.median_packet_size": statistics.median(lengths) if lengths else None,
        f"{prefix}.packet_size_std": _std_or_none(lengths),
        f"{prefix}.mean_interarrival_ms": _mean_or_none(iats),
        f"{prefix}.median_interarrival_ms": statistics.median(iats) if iats else None,
        f"{prefix}.interarrival_std_ms": _std_or_none(iats),
        f"{prefix}.uplink_ratio": uplink_bytes / total_bytes if total_bytes else None,
        f"{prefix}.downlink_ratio": downlink_bytes / total_bytes if total_bytes else None,
        f"{prefix}.burst_rate": burst_count / duration_seconds,
        f"{prefix}.burst_duration_ms": burst_duration,
        f"{prefix}.periodicity_score": _periodicity_score(timestamps, config),
    }
    identity = f"{client_mac}|{start_ms}|{end_ms}|{FEATURE_SCHEMA_VERSION}"
    return TrafficWindow(
        window_id=hashlib.sha256(identity.encode()).hexdigest()[:24], client_mac=client_mac,
        window_start_ms=start_ms, window_end_ms=end_ms, total_frame_count=len(members),
        total_byte_count=total_bytes, uplink_frame_count=len(uplink), downlink_frame_count=len(downlink),
        uplink_byte_count=uplink_bytes, downlink_byte_count=downlink_bytes,
        retry_frame_count=sum(1 for item in members if item.retry),
        data_frame_count=sum(1 for item in members if item.frame_type == "Data"),
        mgmt_frame_count=sum(1 for item in members if item.frame_type == "Management"),
        ctrl_frame_count=sum(1 for item in members if item.frame_type == "Control"),
        derived_features_json=features,
    )


LABEL_PROVENANCE = {"ground_truth", "weak_label", "derived_label", "manually_reviewed"}
ACTIVITY_LABELS = {"idle", "browsing", "streaming", "file_transfer", "chat", "voip", "p2p", "other"}
THREAT_LABELS = {"normal", "deauth_flood", "disassoc_flood", "scanning", "rogue_ap", "power_save_injection", "anomaly"}
MINING_LABELS = {"mining", "non_mining"}


@dataclass(frozen=True)
class LabelRecord:
    """Versioned label metadata; activity may retain its complete probability vector."""

    target_id: str
    label_family: str
    provenance: str
    label: Optional[str] = None
    probabilities: Mapping[str, float] = field(default_factory=dict)
    physical_device_guid: Optional[str] = None
    vendor: Optional[str] = None
    os_family: Optional[str] = None
    label_schema_version: str = LABEL_SCHEMA_VERSION
    label_id: str = field(init=False)

    def __post_init__(self) -> None:
        if self.provenance not in LABEL_PROVENANCE:
            raise ValueError("unknown label provenance")
        if self.label_schema_version != LABEL_SCHEMA_VERSION:
            raise ValueError("label schema version is incompatible")
        allowed = {
            "fingerprint": None, "activity": ACTIVITY_LABELS,
            "threat": THREAT_LABELS, "mining": MINING_LABELS,
        }.get(self.label_family)
        if self.label_family not in {"fingerprint", "activity", "threat", "mining"}:
            raise ValueError("unknown label family")
        if self.label_family == "fingerprint" and not self.physical_device_guid:
            raise ValueError("fingerprint labels require physical_device_guid")
        if allowed is not None and self.label is not None and self.label not in allowed:
            raise ValueError("label is invalid for its family")
        if self.probabilities:
            if self.label_family != "activity":
                raise ValueError("probability vectors are supported for activity labels only")
            if set(self.probabilities) - ACTIVITY_LABELS:
                raise ValueError("activity probability vector has an unknown label")
            if any(not 0.0 <= float(value) <= 1.0 for value in self.probabilities.values()):
                raise ValueError("label probabilities must be between zero and one")
            if not math.isclose(sum(float(value) for value in self.probabilities.values()), 1.0, abs_tol=1e-6):
                raise ValueError("activity probability vector must sum to one")
        object.__setattr__(
            self, "label_id",
            hashlib.sha256(f"{self.label_family}|{self.target_id}".encode("utf-8")).hexdigest()[:24],
        )


@dataclass(frozen=True)
class DatasetManifest:
    dataset_version: str
    feature_schema_version: str
    source_dataset: str
    capture_period_start: Optional[str]
    capture_period_end: Optional[str]
    capture_environment: str
    label_source_type: str
    split_strategy: str
    generated_at: str
    capture_files: Tuple[str, ...]
    schema_reports: Tuple[Dict[str, Any], ...]

    def __post_init__(self) -> None:
        if self.label_source_type not in LABEL_PROVENANCE:
            raise ValueError("unknown label provenance")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def make_dataset_manifest(
    *, dataset_version: str, source_dataset: str, capture_environment: str,
    label_source_type: str, split_strategy: str, schema_reports: Sequence[KismetSchemaReport],
    capture_period_start: Optional[str] = None, capture_period_end: Optional[str] = None,
) -> DatasetManifest:
    return DatasetManifest(
        dataset_version=dataset_version, feature_schema_version=FEATURE_SCHEMA_VERSION,
        source_dataset=source_dataset, capture_period_start=capture_period_start,
        capture_period_end=capture_period_end, capture_environment=capture_environment,
        label_source_type=label_source_type, split_strategy=split_strategy,
        generated_at=datetime.now(timezone.utc).isoformat(),
        capture_files=tuple(report.capture_file for report in schema_reports),
        schema_reports=tuple(asdict(report) for report in schema_reports),
    )


def group_aware_split(
    records: Sequence[Mapping[str, Any]], *, group_field: str, validation_fraction: float = 0.2,
    test_fraction: float = 0.2,
) -> Tuple[Dict[str, List[Mapping[str, Any]]], Dict[str, Any]]:
    """Split complete groups deterministically, never individual overlapping windows.

    Callers select the required group field: physical-device/session for
    fingerprinting and client/session/day for activity or mining.
    """
    if not 0 <= validation_fraction < 1 or not 0 <= test_fraction < 1 or validation_fraction + test_fraction >= 1:
        raise ValueError("split fractions must be non-negative and total less than one")
    grouped: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        group = record.get(group_field)
        if group in (None, ""):
            raise ValueError(f"record missing required group field '{group_field}'")
        grouped[str(group)].append(record)
    split_records: Dict[str, List[Mapping[str, Any]]] = {"train": [], "validation": [], "test": []}
    # A stable digest makes the split reproducible without randomly separating a group.
    for group, members in grouped.items():
        bucket = int(hashlib.sha256(group.encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF
        split = "test" if bucket < test_fraction else "validation" if bucket < test_fraction + validation_fraction else "train"
        split_records[split].extend(members)
    return split_records, {
        "strategy": "group_aware_hash", "group_field": group_field,
        "validation_fraction": validation_fraction, "test_fraction": test_fraction,
        "group_count": len(grouped),
    }


def time_block_split(
    records: Sequence[Mapping[str, Any]], *, block_field: str,
    validation_fraction: float = 0.2, test_fraction: float = 0.2,
) -> Tuple[Dict[str, List[Mapping[str, Any]]], Dict[str, Any]]:
    """Chronologically split entire capture-day/session blocks for threat data."""
    if not records:
        return {"train": [], "validation": [], "test": []}, {"strategy": "time_block", "block_field": block_field, "block_count": 0}
    blocks: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        block = record.get(block_field)
        if block in (None, ""):
            raise ValueError(f"record missing required block field '{block_field}'")
        blocks[str(block)].append(record)
    ordered = sorted(blocks)
    test_count = math.ceil(len(ordered) * test_fraction)
    validation_count = math.ceil(len(ordered) * validation_fraction)
    test_blocks = set(ordered[-test_count:]) if test_count else set()
    validation_end = len(ordered) - test_count
    validation_blocks = set(ordered[max(0, validation_end - validation_count):validation_end])
    result = {"train": [], "validation": [], "test": []}
    for block, members in blocks.items():
        result["test" if block in test_blocks else "validation" if block in validation_blocks else "train"].extend(members)
    return result, {"strategy": "time_block", "block_field": block_field, "block_count": len(blocks)}


@dataclass(frozen=True)
class ModelArtifactMetadata:
    model_id: str
    feature_schema_version: str
    dataset_version: str
    feature_columns: Tuple[str, ...]
    label_schema: Tuple[str, ...]
    aggregation_window_seconds: int
    prediction_output_shape: Tuple[int, ...]


class ModelCompatibilityError(ValueError):
    """Raised when a model cannot safely consume the current ML foundation."""


class ModelSchemaRegistry:
    """Minimal in-process registry gate used before a model artifact is accepted."""

    def __init__(self) -> None:
        self._models: Dict[str, ModelArtifactMetadata] = {}

    def register(
        self, artifact: ModelArtifactMetadata, *, expected_dataset_version: str,
        expected_feature_columns: Sequence[str], expected_label_schema: Sequence[str],
        expected_window_seconds: int, expected_prediction_output_shape: Sequence[int],
    ) -> None:
        if artifact.feature_schema_version != FEATURE_SCHEMA_VERSION:
            raise ModelCompatibilityError("feature schema version is incompatible")
        if artifact.dataset_version != expected_dataset_version:
            raise ModelCompatibilityError("dataset version is incompatible")
        if tuple(artifact.feature_columns) != tuple(expected_feature_columns):
            raise ModelCompatibilityError("feature columns are incompatible")
        if tuple(artifact.label_schema) != tuple(expected_label_schema):
            raise ModelCompatibilityError("label schema is incompatible")
        if artifact.aggregation_window_seconds != expected_window_seconds:
            raise ModelCompatibilityError("aggregation window is incompatible")
        if tuple(artifact.prediction_output_shape) != tuple(expected_prediction_output_shape):
            raise ModelCompatibilityError("prediction output shape is incompatible")
        self._models[artifact.model_id] = artifact

    def get(self, model_id: str) -> ModelArtifactMetadata:
        return self._models[model_id]


@dataclass(frozen=True)
class ProcessingCheckpoint:
    """Only derived cursor state; raw Kismet captures remain the source of truth."""

    feature_schema_version: str
    capture_offsets: Dict[str, int]
    emitted_observation_ids: Tuple[str, ...] = ()


class CheckpointStore:
    """Atomic JSON checkpoint storage for restart/capture-rotation resilience."""

    def __init__(self, path: Path | str):
        self.path = Path(path)

    def load(self) -> ProcessingCheckpoint:
        if not self.path.exists():
            return ProcessingCheckpoint(FEATURE_SCHEMA_VERSION, {})
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if payload.get("feature_schema_version") != FEATURE_SCHEMA_VERSION:
            raise ModelCompatibilityError("checkpoint feature schema version is incompatible")
        return ProcessingCheckpoint(
            feature_schema_version=payload["feature_schema_version"],
            capture_offsets={str(key): int(value) for key, value in payload.get("capture_offsets", {}).items()},
            emitted_observation_ids=tuple(str(item) for item in payload.get("emitted_observation_ids", ())),
        )

    def save(self, checkpoint: ProcessingCheckpoint) -> None:
        if checkpoint.feature_schema_version != FEATURE_SCHEMA_VERSION:
            raise ModelCompatibilityError("refusing to persist an incompatible checkpoint")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(asdict(checkpoint), sort_keys=True), encoding="utf-8")
        temporary.replace(self.path)


def resume_from_checkpoint(
    extractor: KismetMLExtractor, checkpoint: ProcessingCheckpoint,
) -> Tuple[List[StructuredObservation], ProcessingCheckpoint]:
    """Produce only unseen derived observations and an atomic-save-ready cursor.

    Capture filenames are intentionally part of the state: when Kismet rotates
    to a new file it is read as a separate source, while already emitted IDs
    protect a restarted job from duplicating observations in either file.
    """
    if checkpoint.feature_schema_version != FEATURE_SCHEMA_VERSION:
        raise ModelCompatibilityError("checkpoint feature schema version is incompatible")
    seen = set(checkpoint.emitted_observation_ids)
    unseen: List[StructuredObservation] = []
    offsets = dict(checkpoint.capture_offsets)
    for observation in extractor.iter_structured_observations():
        if observation.observation_id in seen:
            continue
        unseen.append(observation)
        offsets[observation.capture_file] = max(offsets.get(observation.capture_file, -1), observation.timestamp_epoch_ms)
    # IDs are bounded to the IDs that can overlap the latest known cursor per
    # capture.  This preserves restart de-duplication without storing payloads.
    retained_ids = tuple(sorted((seen | {item.observation_id for item in unseen})))
    return unseen, ProcessingCheckpoint(FEATURE_SCHEMA_VERSION, offsets, retained_ids)
