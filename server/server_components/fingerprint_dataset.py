"""Streaming adapters for labelled probe-request PCAP datasets.

Public and local benchmark files are converted into the Phase 0
``FingerprintObservation`` contract. The adapter does not retain packet
payloads and uses a small standard-library PCAP/XLSX reader, so the
production Kismet service does not gain a capture-decoding dependency at
startup.
"""

from __future__ import annotations

import hashlib
import re
import struct
import xml.etree.ElementTree as element_tree
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple
from zipfile import ZipFile

from .device_fingerprinting import LabeledFingerprintExample, fingerprint_feature_vector
from .kismet_ml_foundation import FingerprintObservation, is_randomized_mac, normalize_mac, parse_80211_packet

MGMT_SUBTYPES = {
    4: "Probe Request", 5: "Probe Response", 0: "Association Request",
    1: "Association Response", 2: "Reassociation Request",
}
XLSX_NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
CHANNEL_SUFFIX = re.compile(r"-ch-[^-]+(?=-th-|\.pcap$)", re.IGNORECASE)


@dataclass(frozen=True)
class MendeleyDeviceMetadata:
    device_guid: str
    os: Optional[str]
    os_version: Optional[str]
    vendor: Optional[str]
    model: Optional[str]
    mac_randomization: Optional[bool]
    device_type: Optional[str]


def _xlsx_rows(path: Path) -> Iterator[List[Optional[str]]]:
    """Read the small metadata workbooks without adding an openpyxl runtime dependency."""
    with ZipFile(path) as archive:
        shared: List[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = element_tree.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall("x:si", XLSX_NS):
                shared.append("".join(text.text or "" for text in item.findall(".//x:t", XLSX_NS)))
        sheet = element_tree.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        for row in sheet.findall(".//x:row", XLSX_NS):
            values: Dict[int, Optional[str]] = {}
            for cell in row.findall("x:c", XLSX_NS):
                reference = cell.get("r", "A1")
                column = 0
                for character in re.match(r"[A-Z]+", reference).group(0):
                    column = column * 26 + ord(character) - ord("A") + 1
                value = cell.find("x:v", XLSX_NS)
                resolved: Optional[str] = None if value is None else value.text
                if cell.get("t") == "s" and resolved is not None:
                    resolved = shared[int(resolved)]
                values[column - 1] = resolved.strip() if isinstance(resolved, str) else resolved
            if values:
                yield [values.get(index) for index in range(max(values) + 1)]


def load_mendeley_metadata(dataset_root: Path | str) -> Dict[str, MendeleyDeviceMetadata]:
    """Load the labelled ``Individual devices - info.xlsx`` sidecar."""
    root = Path(dataset_root)
    workbook = next(root.glob("*Individual devices - info.xlsx"), None)
    if workbook is None:
        raise FileNotFoundError("Individual devices - info.xlsx not found")
    rows = _xlsx_rows(workbook)
    next(rows, None)  # header
    metadata: Dict[str, MendeleyDeviceMetadata] = {}
    for row in rows:
        if not row or not row[0]:
            continue
        values = list(row) + [None] * 7
        randomization = values[5].lower() if isinstance(values[5], str) else ""
        metadata[str(values[0])] = MendeleyDeviceMetadata(
            device_guid=f"mendeley-2024-{values[0]}", os=values[1], os_version=values[2],
            vendor=values[3], model=values[4],
            mac_randomization=True if randomization == "yes" else False if randomization == "no" else None,
            device_type=values[6],
        )
    return metadata


def discover_mendeley_sessions(dataset_root: Path | str) -> Dict[Tuple[str, str], Tuple[Path, ...]]:
    """Group each device's three channel PCAPs into labelled capture sessions."""
    root = Path(dataset_root) / "Individual devices"
    grouped: Dict[Tuple[str, str], List[Path]] = {}
    for path in sorted(root.glob("*/*.pcap")):
        device = path.parent.name
        session = CHANNEL_SUFFIX.sub("", path.stem)
        grouped.setdefault((device, session), []).append(path)
    return {key: tuple(paths) for key, paths in grouped.items()}


def _pcap_records(path: Path) -> Iterator[Tuple[int, int, int, bytes, int]]:
    """Yield classic PCAP records without importing a packet-capture runtime."""
    with path.open("rb") as stream:
        header = stream.read(24)
        if len(header) != 24:
            return
        formats = {
            b"\xd4\xc3\xb2\xa1": ("<", 1_000_000),
            b"\xa1\xb2\xc3\xd4": (">", 1_000_000),
            b"\x4d\x3c\xb2\xa1": ("<", 1_000_000_000),
            b"\xa1\xb2\x3c\x4d": (">", 1_000_000_000),
        }
        if header[:4] not in formats:
            raise ValueError(f"unsupported PCAP magic in {path.name}")
        byte_order, timestamp_scale = formats[header[:4]]
        link_type = struct.unpack_from(byte_order + "I", header, 20)[0]
        packet_header = struct.Struct(byte_order + "IIII")
        while True:
            raw_header = stream.read(packet_header.size)
            if not raw_header:
                return
            if len(raw_header) != packet_header.size:
                raise ValueError(f"truncated PCAP header in {path.name}")
            seconds, fraction, included_length, _original_length = packet_header.unpack(raw_header)
            payload = stream.read(included_length)
            if len(payload) != included_length:
                raise ValueError(f"truncated PCAP payload in {path.name}")
            yield seconds, fraction, timestamp_scale, payload, link_type


def _radiotap_metadata(packet: bytes) -> Tuple[Optional[float], Optional[float]]:
    """Extract only channel frequency and signal from a radiotap header."""
    if len(packet) < 8 or packet[:2] != b"\x00\x00":
        return None, None
    length = int.from_bytes(packet[2:4], "little")
    if length < 8 or length > len(packet):
        return None, None
    words: List[int] = []
    cursor = 4
    while True:
        if cursor + 4 > length:
            return None, None
        word = int.from_bytes(packet[cursor:cursor + 4], "little")
        words.append(word)
        cursor += 4
        if not word & (1 << 31):
            break
    field_sizes = {
        0: (8, 8), 1: (1, 1), 2: (1, 1), 3: (2, 4), 4: (2, 2),
        5: (1, 1), 6: (1, 1), 7: (2, 2), 8: (2, 2), 9: (2, 2),
        10: (1, 1), 11: (2, 2), 12: (1, 1), 13: (1, 1),
    }
    frequency = signal = None
    field_offset = cursor
    for word_index, word in enumerate(words):
        for bit in range(31):
            if not word & (1 << bit):
                continue
            field_index = word_index * 32 + bit
            alignment, size = field_sizes.get(field_index, (1, 0))
            if size == 0:
                continue
            field_offset = (field_offset + alignment - 1) // alignment * alignment
            if field_offset + size > length:
                return frequency, signal
            field = packet[field_offset:field_offset + size]
            if field_index == 3:
                frequency = float(int.from_bytes(field[:2], "little"))
            elif field_index == 5:
                signal = float(struct.unpack("b", field[:1])[0])
            field_offset += size
    return frequency, signal


def iter_probe_observations(pcap_file: Path | str) -> Iterator[FingerprintObservation]:
    """Stream management observations from a PCAP without loading it wholesale."""
    path = Path(pcap_file)
    for seconds, fraction, timestamp_scale, packet, link_type in _pcap_records(path):
        parsed = parse_80211_packet(packet, dlt=link_type)
        if not parsed or parsed["frame_type"] != "Management" or parsed["frame_subtype"] not in MGMT_SUBTYPES.values():
            continue
        source_mac = parsed["source_mac"]
        if not source_mac:
            continue
        timestamp = seconds + fraction / timestamp_scale
        frequency, signal_dbm = _radiotap_metadata(packet) if link_type == 127 else (None, None)
        raw_identity = f"{path.name}|{timestamp:.6f}|{source_mac}|{parsed['sequence_number']}|{len(parsed['tags'])}"
        yield FingerprintObservation(
            observation_id=hashlib.sha256(raw_identity.encode()).hexdigest()[:24],
            timestamp_epoch_ms=int(timestamp * 1000), source_mac=source_mac,
            is_randomized_mac=is_randomized_mac(source_mac), frame_subtype=parsed["frame_subtype"],
            sequence_number=parsed["sequence_number"], signal_dbm=signal_dbm,
            frequency_mhz=frequency, ie_tag_sequence=tuple(parsed["tags"]),
            ie_vendor_ouis=tuple(parsed["vendor_ouis"]), ht_capabilities_hex=parsed["ht"],
            vht_capabilities_hex=parsed["vht"], he_capabilities_hex=parsed["he"],
            wmm_capabilities_present=parsed["wmm"], capture_file=path.name,
        )


def load_labeled_pcap_profiles(
    captures: Mapping[Path | str, str], *, sessions: Optional[Mapping[Path | str, str]] = None,
) -> Iterator[LabeledFingerprintExample]:
    """Convert ``capture -> physical_device_guid`` mappings into profiles.

    Organizing one controlled capture per device/session keeps labels explicit
    and avoids guessing identity from a filename or MAC address.
    """
    sessions = sessions or {}
    for capture, physical_device_guid in captures.items():
        path = Path(capture)
        observations = list(iter_probe_observations(path))
        if not observations:
            continue
        profile_id = hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:24]
        yield LabeledFingerprintExample(
            profile_id=profile_id,
            physical_device_guid=str(physical_device_guid),
            capture_session=str(sessions.get(capture, sessions.get(path, path.stem))),
            feature_vector=fingerprint_feature_vector(observations),
        )


def load_mendeley_profiles(dataset_root: Path | str) -> Iterator[Tuple[LabeledFingerprintExample, MendeleyDeviceMetadata]]:
    """Create one profile per device/session, combining its captured channels."""
    root = Path(dataset_root)
    metadata = load_mendeley_metadata(root)
    for (device, session), captures in discover_mendeley_sessions(root).items():
        device_metadata = metadata.get(device)
        if device_metadata is None:
            continue
        observations = [observation for capture in captures for observation in iter_probe_observations(capture)]
        if not observations:
            continue
        profile_id = hashlib.sha256(f"{device}|{session}".encode()).hexdigest()[:24]
        yield LabeledFingerprintExample(
            profile_id=profile_id,
            physical_device_guid=device_metadata.device_guid,
            capture_session=session,
            feature_vector=fingerprint_feature_vector(observations),
        ), device_metadata
