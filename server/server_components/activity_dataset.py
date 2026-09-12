"""Streaming adapters for the VNAT activity-classification dataset.

The VNAT release contains classic PCAP files with either Ethernet or raw-IP
link types.  This module reads them a record at a time, extracts only packet
metadata, and emits bounded :class:`TrafficWindow` records.  Packet payloads
and endpoint addresses are never written to the derived dataset.
"""

from __future__ import annotations

import hashlib
import socket
import struct
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

from .kismet_ml_foundation import (
    StructuredObservation,
    TrafficWindow,
    WindowConfig,
    _make_traffic_window,
)


DATASET_VERSION = "vnat-v1"
PARSER_VERSION = "vnat-pcap-parser-v1"
SUPPORTED_LINK_TYPES = {1: "ethernet", 101: "raw-ip"}
_ETHERNET = 1
_RAW_IP = 101
_VLAN_TYPES = {0x8100, 0x88A8, 0x9100}
_IPV4 = 0x0800
_IPV6 = 0x86DD
_KNOWN_LABELS = (
    ("skype-chat", "chat"),
    ("netflix", "streaming"),
    ("youtube", "streaming"),
    ("vimeo", "streaming"),
    ("rsync", "file_transfer"),
    ("scp", "file_transfer"),
    ("sftp", "file_transfer"),
    ("voip", "voip"),
    ("ssh", "other"),
    ("rdp", "other"),
)


@dataclass(frozen=True)
class PcapRecord:
    timestamp_epoch_ms: int
    captured_length: int
    link_type: int
    payload: bytes


@dataclass(frozen=True)
class PacketMeta:
    timestamp_epoch_ms: int
    captured_length: int
    source: str
    destination: str
    protocol: int
    source_port: Optional[int]
    destination_port: Optional[int]


@dataclass(frozen=True)
class CaptureInventory:
    path: str
    relative_path: str
    capture_session: str
    sha256: str
    size_bytes: int
    link_type: Optional[int]
    packet_count: int
    byte_count: int
    activity_label: Optional[str]
    vpn: Optional[bool]
    status: str
    reason: Optional[str] = None


def classify_capture(path: Path) -> Tuple[Optional[str], Optional[bool]]:
    """Map a VNAT filename to a proxy activity label and VPN domain."""
    name = path.stem.lower()
    vpn: Optional[bool]
    if name.startswith("nonvpn_"):
        vpn = False
        remainder = name[len("nonvpn_"):]
    elif name.startswith("vpn_"):
        vpn = True
        remainder = name[len("vpn_"):]
    else:
        return None, None
    for prefix, label in _KNOWN_LABELS:
        if remainder == prefix or remainder.startswith(prefix + "_"):
            return label, vpn
    # VNAT may add a new/ambiguous application prefix in a future release.
    # Keep the capture usable as an explicit negative/other proxy rather than
    # silently fabricating a more specific activity class.
    return "other", vpn


def _pcap_header(path: Path) -> Tuple[str, int, int]:
    with path.open("rb") as stream:
        header = stream.read(24)
    if len(header) != 24:
        raise ValueError("truncated PCAP global header")
    formats = {
        b"\xd4\xc3\xb2\xa1": ("<", 1_000_000),
        b"\xa1\xb2\xc3\xd4": (">", 1_000_000),
        b"\x4d\x3c\xb2\xa1": ("<", 1_000_000_000),
        b"\xa1\xb2\x3c\x4d": (">", 1_000_000_000),
    }
    if header[:4] not in formats:
        raise ValueError(f"unsupported PCAP magic {header[:4].hex()}")
    byte_order, timestamp_scale = formats[header[:4]]
    link_type = struct.unpack_from(byte_order + "I", header, 20)[0]
    if link_type not in SUPPORTED_LINK_TYPES:
        raise ValueError(f"unsupported link type {link_type}")
    return byte_order, timestamp_scale, link_type


def iter_pcap_records(path: Path | str) -> Iterator[PcapRecord]:
    """Stream classic PCAP records and reject malformed/truncated input."""
    capture = Path(path)
    byte_order, timestamp_scale, link_type = _pcap_header(capture)
    packet_header = struct.Struct(byte_order + "IIII")
    with capture.open("rb") as stream:
        stream.read(24)
        while True:
            raw_header = stream.read(packet_header.size)
            if not raw_header:
                return
            if len(raw_header) != packet_header.size:
                raise ValueError("truncated PCAP packet header")
            seconds, fraction, included_length, _original_length = packet_header.unpack(raw_header)
            payload = stream.read(included_length)
            if len(payload) != included_length:
                raise ValueError("truncated PCAP packet payload")
            timestamp = seconds + fraction / timestamp_scale
            yield PcapRecord(
                timestamp_epoch_ms=int(timestamp * 1000),
                captured_length=included_length,
                link_type=link_type,
                payload=payload,
            )


def _ip_header(payload: bytes, link_type: int) -> Optional[Tuple[int, int]]:
    """Return (network offset, IP version) for supported link encodings."""
    offset = 0
    if link_type == _ETHERNET:
        if len(payload) < 14:
            return None
        ether_type = int.from_bytes(payload[12:14], "big")
        offset = 14
        while ether_type in _VLAN_TYPES:
            if len(payload) < offset + 4:
                return None
            ether_type = int.from_bytes(payload[offset + 2:offset + 4], "big")
            offset += 4
        if ether_type == _IPV4:
            return offset, 4
        if ether_type == _IPV6:
            return offset, 6
        return None
    if link_type == _RAW_IP and payload:
        version = payload[0] >> 4
        return (0, version) if version in {4, 6} else None
    return None


def _transport_ports(payload: bytes, offset: int, protocol: int, header_end: int) -> Tuple[Optional[int], Optional[int]]:
    if protocol not in {6, 17, 132} or len(payload) < header_end + 4:
        return None, None
    return int.from_bytes(payload[header_end:header_end + 2], "big"), int.from_bytes(payload[header_end + 2:header_end + 4], "big")


def parse_packet_metadata(record: PcapRecord) -> Optional[PacketMeta]:
    location = _ip_header(record.payload, record.link_type)
    if location is None:
        return None
    offset, version = location
    payload = record.payload
    if version == 4:
        if len(payload) < offset + 20:
            return None
        first = payload[offset]
        header_length = (first & 0x0F) * 4
        if first >> 4 != 4 or header_length < 20 or len(payload) < offset + header_length:
            return None
        protocol = payload[offset + 9]
        source = socket.inet_ntop(socket.AF_INET, payload[offset + 12:offset + 16])
        destination = socket.inet_ntop(socket.AF_INET, payload[offset + 16:offset + 20])
        return PacketMeta(
            record.timestamp_epoch_ms, record.captured_length, source, destination,
            protocol, *_transport_ports(payload, offset, protocol, offset + header_length),
        )
    if len(payload) < offset + 40:
        return None
    if payload[offset] >> 4 != 6:
        return None
    protocol = payload[offset + 6]
    source = socket.inet_ntop(socket.AF_INET6, payload[offset + 8:offset + 24])
    destination = socket.inet_ntop(socket.AF_INET6, payload[offset + 24:offset + 40])
    return PacketMeta(
        record.timestamp_epoch_ms, record.captured_length, source, destination,
        protocol, *_transport_ports(payload, offset, protocol, offset + 40),
    )


def _capture_digest_and_stats(path: Path) -> Tuple[str, int, int, int]:
    digest = hashlib.sha256()
    packet_count = 0
    byte_count = 0
    link_type: Optional[int] = None
    byte_order, _scale, link_type = _pcap_header(path)
    packet_header = struct.Struct(byte_order + "IIII")
    with path.open("rb") as stream:
        global_header = stream.read(24)
        digest.update(global_header)
        while True:
            raw_header = stream.read(packet_header.size)
            if not raw_header:
                break
            if len(raw_header) != packet_header.size:
                raise ValueError("truncated PCAP packet header")
            digest.update(raw_header)
            _sec, _fraction, included_length, _original = packet_header.unpack(raw_header)
            payload = stream.read(included_length)
            if len(payload) != included_length:
                raise ValueError("truncated PCAP packet payload")
            digest.update(payload)
            packet_count += 1
            byte_count += included_length
    return digest.hexdigest(), packet_count, byte_count, link_type


def _endpoint_stats(path: Path) -> Tuple[Dict[str, Tuple[int, int]], int]:
    stats: Dict[str, Tuple[int, int]] = defaultdict(lambda: (0, 0))
    link_type: Optional[int] = None
    for record in iter_pcap_records(path):
        link_type = record.link_type
        packet = parse_packet_metadata(record)
        if packet is None:
            continue
        for endpoint in (packet.source, packet.destination):
            count, total = stats[endpoint]
            stats[endpoint] = (count + 1, total + packet.captured_length)
    if link_type is None:
        _pcap_header(path)
    return dict(stats), int(link_type or 0)


def _choose_client(stats: Dict[str, Tuple[int, int]]) -> Optional[str]:
    if not stats:
        return None
    return min(stats, key=lambda endpoint: (-stats[endpoint][1], -stats[endpoint][0], endpoint))


def _opaque_endpoint(session_id: str, role: str) -> str:
    return f"vnat:{session_id}:{role}"


def iter_capture_windows(
    path: Path | str,
    *,
    session_id: str,
    config: WindowConfig = WindowConfig(length_seconds=30, hop_seconds=30),
) -> Tuple[Iterator[TrafficWindow], Optional[str], Dict[str, int]]:
    """Return a bounded window iterator, selected client endpoint, and stats."""
    capture = Path(path)
    endpoint_stats, _link_type = _endpoint_stats(capture)
    client_ip = _choose_client(endpoint_stats)
    stats = {"endpoint_count": len(endpoint_stats), "parsed_packet_count": sum(item[0] for item in endpoint_stats.values()) // 2}
    if client_ip is None:
        return iter(()), None, stats
    client_id = _opaque_endpoint(session_id, "client")
    peer_id = _opaque_endpoint(session_id, "peer")

    def windows() -> Iterator[TrafficWindow]:
        current_start: Optional[int] = None
        members: List[StructuredObservation] = []
        for record in iter_pcap_records(capture):
            packet = parse_packet_metadata(record)
            if packet is None or client_ip not in {packet.source, packet.destination}:
                continue
            if packet.source == client_ip and packet.destination != client_ip:
                source, destination, to_ds, from_ds = client_id, peer_id, True, False
            elif packet.destination == client_ip and packet.source != client_ip:
                source, destination, to_ds, from_ds = peer_id, client_id, False, True
            else:
                continue
            start = (packet.timestamp_epoch_ms // (config.hop_seconds * 1000)) * (config.hop_seconds * 1000)
            if current_start is not None and start != current_start:
                if members:
                    yield _make_traffic_window(client_id, current_start, current_start + config.length_seconds * 1000, members, config)
                members = []
            current_start = start
            members.append(StructuredObservation(
                observation_id=hashlib.sha256(f"{session_id}|{packet.timestamp_epoch_ms}|{len(members)}".encode()).hexdigest()[:24],
                timestamp_epoch_ms=packet.timestamp_epoch_ms,
                source_mac=source, destination_mac=destination, transmitter_mac=source, bssid=None,
                frame_type="Data", frame_subtype="IP", frame_length=packet.captured_length,
                signal_dbm=None, frequency_mhz=None, sequence_number=None,
                to_ds=to_ds, from_ds=from_ds, retry=False, power_management=False,
                capture_file=capture.name,
            ))
        if current_start is not None and members:
            yield _make_traffic_window(client_id, current_start, current_start + config.length_seconds * 1000, members, config)

    return windows(), client_id, stats


def discover_vnat_captures(root: Path | str) -> List[Path]:
    return sorted(Path(root).glob("*.pcap"))


def capture_inventory(path: Path, dataset_root: Path) -> CaptureInventory:
    label, vpn = classify_capture(path)
    relative = str(path.relative_to(dataset_root))
    try:
        digest, packets, bytes_count, link_type = _capture_digest_and_stats(path)
        session_id = hashlib.sha256(f"{relative}|{digest}".encode()).hexdigest()[:24]
        return CaptureInventory(str(path), relative, session_id, digest, path.stat().st_size, link_type, packets, bytes_count, label, vpn, "ok")
    except (OSError, ValueError) as error:
        digest = hashlib.sha256(relative.encode()).hexdigest()
        session_id = hashlib.sha256(f"{relative}|{digest}".encode()).hexdigest()[:24]
        return CaptureInventory(str(path), relative, session_id, digest, path.stat().st_size if path.exists() else 0, None, 0, 0, label, vpn, "rejected", str(error))


def window_record(window: TrafficWindow, *, capture_session: str, label: str, vpn: Optional[bool], source_file: str) -> Dict[str, object]:
    return {
        **asdict(window),
        "capture_session": capture_session,
        "source_file": source_file,
        "vpn": vpn,
        "dataset_version": DATASET_VERSION,
        "parser_version": PARSER_VERSION,
    }


def label_record(window: TrafficWindow, *, capture_session: str, label: str, vpn: Optional[bool], source_file: str) -> Dict[str, object]:
    return {
        "target_id": window.window_id,
        "label_family": "activity",
        "label": label,
        "provenance": "ground_truth",
        "capture_session": capture_session,
        "source_file": source_file,
        "vpn": vpn,
        "dataset_version": DATASET_VERSION,
    }
