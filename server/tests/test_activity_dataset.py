"""Tests for the streaming VNAT PCAP adapter."""

from __future__ import annotations

import json
import socket
import struct
import tempfile
import unittest
from pathlib import Path

from server_components.activity_dataset import (
    PcapRecord,
    capture_inventory,
    classify_capture,
    iter_pcap_records,
    iter_capture_windows,
    parse_packet_metadata,
    window_record,
)


def _ipv4_packet(source: str, destination: str, *, sport: int = 443, dport: int = 50000, body: bytes = b"payload") -> bytes:
    tcp = struct.pack("!HH", sport, dport) + b"\x00" * 18 + body
    total_length = 20 + len(tcp)
    header = struct.pack(
        "!BBHHHBBH4s4s",
        0x45, 0, total_length, 1, 0, 64, 6, 0,
        socket.inet_aton(source), socket.inet_aton(destination),
    )
    return header + tcp


def _ethernet(ip_payload: bytes, *, vlan: bool = False) -> bytes:
    macs = b"\x00\x11\x22\x33\x44\x55\x66\x77\x88\x99\xaa\xbb"
    if vlan:
        return macs + struct.pack("!H", 0x8100) + struct.pack("!HH", 7, 0x0800) + ip_payload
    return macs + struct.pack("!H", 0x0800) + ip_payload


def _write_pcap(path: Path, payloads: list[tuple[int, int, bytes]], *, link_type: int = 101, endian: str = "<", nano: bool = False) -> None:
    if endian == "<":
        magic = b"\x4d\x3c\xb2\xa1" if nano else b"\xd4\xc3\xb2\xa1"
    else:
        magic = b"\xa1\xb2\x3c\x4d" if nano else b"\xa1\xb2\xc3\xd4"
    header = magic + struct.pack(endian + "HHIIII", 2, 4, 0, 0, 65535, link_type)
    with path.open("wb") as stream:
        stream.write(header)
        for seconds, fraction, payload in payloads:
            stream.write(struct.pack(endian + "IIII", seconds, fraction, len(payload), len(payload)))
            stream.write(payload)


class ActivityDatasetTests(unittest.TestCase):
    def test_ethernet_vlan_and_raw_metadata(self) -> None:
        raw = _ipv4_packet("10.0.0.2", "10.0.0.1", sport=1234, dport=443)
        ethernet = PcapRecord(1000, len(_ethernet(raw, vlan=True)), 1, _ethernet(raw, vlan=True))
        parsed = parse_packet_metadata(ethernet)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual((parsed.source, parsed.destination), ("10.0.0.2", "10.0.0.1"))
        self.assertEqual((parsed.source_port, parsed.destination_port), (1234, 443))
        raw_record = PcapRecord(1000, len(raw), 101, raw)
        raw_parsed = parse_packet_metadata(raw_record)
        self.assertIsNotNone(raw_parsed)
        assert raw_parsed is not None
        self.assertEqual((raw_parsed.source, raw_parsed.destination, raw_parsed.protocol), (parsed.source, parsed.destination, parsed.protocol))
        self.assertEqual((raw_parsed.source_port, raw_parsed.destination_port), (parsed.source_port, parsed.destination_port))

    def test_endian_and_nanosecond_headers_stream(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nonvpn_netflix_nano.pcap"
            payload = _ipv4_packet("10.0.0.2", "10.0.0.1")
            _write_pcap(path, [(12, 500_000_000, payload)], endian=">", nano=True)
            records = list(iter_pcap_records(path))
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].timestamp_epoch_ms, 12500)
            self.assertEqual(classify_capture(path), ("streaming", False))

    def test_malformed_records_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vpn_voip.pcap"
            _write_pcap(path, [])
            with path.open("ab") as stream:
                stream.write(b"\x00" * 8)
            with self.assertRaises(ValueError):
                list(iter_pcap_records(path))

    def test_session_and_windows_are_deterministic_and_payload_free(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "nonvpn_skype-chat.pcap"
            first = _ipv4_packet("10.0.0.2", "10.0.0.1", body=b"SENSITIVE_PAYLOAD")
            second = _ipv4_packet("10.0.0.1", "10.0.0.2", sport=443, dport=1234)
            _write_pcap(path, [(100, 0, first), (110, 0, second)])
            inventory_a = capture_inventory(path, root)
            inventory_b = capture_inventory(path, root)
            self.assertEqual(inventory_a.capture_session, inventory_b.capture_session)
            windows, client, _stats = iter_capture_windows(path, session_id=inventory_a.capture_session)
            rows = [window_record(window, capture_session=inventory_a.capture_session, label="chat", vpn=False, source_file=path.name) for window in windows]
            self.assertTrue(rows)
            self.assertEqual(client, f"vnat:{inventory_a.capture_session}:client")
            encoded = json.dumps(rows)
            self.assertNotIn("SENSITIVE_PAYLOAD", encoded)
            self.assertNotIn("10.0.0.2", encoded)


if __name__ == "__main__":
    unittest.main()
