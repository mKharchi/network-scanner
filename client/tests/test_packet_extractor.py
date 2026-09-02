"""Unit tests for packet_extractor module."""

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

# Add client/app to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

from packet_extractor import (
    determine_direction,
    extract_metadata_from_scapy,
    extract_tcp_flags,
    format_timestamp,
    normalize_ip,
    normalize_mac,
)


class TestPacketExtractorHelpers(unittest.TestCase):
    """Test helper normalization and direction functions."""

    def test_normalize_mac(self):
        self.assertEqual(normalize_mac("aa:bb:cc:dd:ee:ff"), "AA:BB:CC:DD:EE:FF")
        self.assertEqual(normalize_mac("11-22-33-44-55-66"), "11:22:33:44:55:66")
        self.assertIsNone(normalize_mac("invalid-mac"))
        self.assertIsNone(normalize_mac(12345))

    def test_normalize_ip(self):
        self.assertEqual(normalize_ip("192.168.1.50"), "192.168.1.50")
        self.assertEqual(normalize_ip("  10.0.0.1 "), "10.0.0.1")
        self.assertEqual(normalize_ip("2001:db8::1"), "2001:db8::1")
        self.assertIsNone(normalize_ip("999.999.999.999"))
        self.assertIsNone(normalize_ip(None))

    def test_format_timestamp(self):
        dt = datetime(2026, 9, 2, 13, 42, 18, 381000, tzinfo=timezone.utc)
        ts = format_timestamp(dt)
        self.assertEqual(ts, "2026-09-02T13:42:18.381Z")

    def test_extract_tcp_flags(self):
        self.assertEqual(extract_tcp_flags("PA"), "PA")
        self.assertEqual(extract_tcp_flags("S"), "S")
        self.assertEqual(extract_tcp_flags(0x02), "S")
        self.assertEqual(extract_tcp_flags(0x12), "SA")
        self.assertEqual(extract_tcp_flags(0x18), "PA")

    def test_determine_direction_outbound(self):
        d = determine_direction(
            src_mac="AA:BB:CC:DD:EE:FF",
            dst_mac="11:22:33:44:55:66",
            src_ip="192.168.1.10",
            dst_ip="8.8.8.8",
            local_mac="AA:BB:CC:DD:EE:FF",
            local_ip="192.168.1.10",
        )
        self.assertEqual(d, "outbound")

    def test_determine_direction_inbound(self):
        d = determine_direction(
            src_mac="11:22:33:44:55:66",
            dst_mac="AA:BB:CC:DD:EE:FF",
            src_ip="8.8.8.8",
            dst_ip="192.168.1.10",
            local_mac="AA:BB:CC:DD:EE:FF",
            local_ip="192.168.1.10",
        )
        self.assertEqual(d, "inbound")

    def test_determine_direction_unknown(self):
        d = determine_direction(
            src_mac="11:22:33:44:55:66",
            dst_mac="22:33:44:55:66:77",
            src_ip="192.168.1.20",
            dst_ip="192.168.1.30",
            local_mac="AA:BB:CC:DD:EE:FF",
            local_ip="192.168.1.10",
        )
        self.assertEqual(d, "unknown")


class TestScapyPacketMetadataExtraction(unittest.TestCase):
    """Test packet metadata extraction from Scapy packet layers."""

    def test_tcp_packet_extraction(self):
        from scapy.layers.l2 import Ether
        from scapy.layers.inet import IP, TCP

        packet = (
            Ether(src="aa:bb:cc:dd:ee:01", dst="aa:bb:cc:dd:ee:02")
            / IP(src="192.168.1.5", dst="142.250.185.14")
            / TCP(sport=52341, dport=443, flags="PA")
            / b"GET / HTTP/1.1\r\nHost: example.com\r\n\r\n"
        )

        obs = extract_metadata_from_scapy(
            packet,
            interface="eth0",
            observer_client_id="client-test-1",
            local_mac="AA:BB:CC:DD:EE:01",
            local_ip="192.168.1.5",
        )

        self.assertEqual(obs["observer_client_id"], "client-test-1")
        self.assertEqual(obs["interface"], "eth0")
        self.assertEqual(obs["src_mac"], "AA:BB:CC:DD:EE:01")
        self.assertEqual(obs["dst_mac"], "AA:BB:CC:DD:EE:02")
        self.assertEqual(obs["src_ip"], "192.168.1.5")
        self.assertEqual(obs["dst_ip"], "142.250.185.14")
        self.assertEqual(obs["protocol"], "TCP")
        self.assertEqual(obs["src_port"], 52341)
        self.assertEqual(obs["dst_port"], 443)
        self.assertEqual(obs["tcp_flags"], "PA")
        self.assertEqual(obs["direction"], "outbound")
        self.assertGreater(obs["packet_length"], 0)

        # Ensure NO raw payload is stored
        self.assertNotIn("payload", obs)
        self.assertNotIn("raw", obs)
        self.assertNotIn("GET / HTTP/1.1", str(obs))

    def test_udp_packet_extraction(self):
        from scapy.layers.l2 import Ether
        from scapy.layers.inet import IP, UDP

        packet = (
            Ether(src="aa:bb:cc:dd:ee:02", dst="aa:bb:cc:dd:ee:01")
            / IP(src="192.168.1.1", dst="192.168.1.5")
            / UDP(sport=12345, dport=54321)
            / b"dummy UDP payload"
        )

        obs = extract_metadata_from_scapy(
            packet,
            interface="eth0",
            observer_client_id="client-test-1",
            local_mac="AA:BB:CC:DD:EE:01",
            local_ip="192.168.1.5",
        )

        self.assertEqual(obs["protocol"], "UDP")
        self.assertEqual(obs["src_port"], 12345)
        self.assertEqual(obs["dst_port"], 54321)
        self.assertEqual(obs["direction"], "inbound")
        self.assertNotIn("tcp_flags", obs)
        self.assertNotIn("dummy UDP payload", str(obs))

    def test_arp_packet_extraction(self):
        from scapy.layers.l2 import Ether, ARP

        packet = (
            Ether(src="aa:bb:cc:dd:ee:01", dst="ff:ff:ff:ff:ff:ff")
            / ARP(op=1, hwsrc="aa:bb:cc:dd:ee:01", psrc="192.168.1.5", hwdst="00:00:00:00:00:00", pdst="192.168.1.1")
        )

        obs = extract_metadata_from_scapy(
            packet,
            interface="eth0",
            observer_client_id="client-test-1",
        )

        self.assertEqual(obs["protocol"], "ARP")
        self.assertEqual(obs["src_mac"], "AA:BB:CC:DD:EE:01")
        self.assertEqual(obs["src_ip"], "192.168.1.5")
        self.assertEqual(obs["dst_ip"], "192.168.1.1")
        self.assertNotIn("src_port", obs)
        self.assertNotIn("dst_port", obs)
        self.assertEqual(obs["protocol_metadata"]["operation"], "who-has")

    def test_icmp_packet_extraction(self):
        from scapy.layers.l2 import Ether
        from scapy.layers.inet import IP, ICMP

        packet = (
            Ether(src="aa:bb:cc:dd:ee:01", dst="aa:bb:cc:dd:ee:02")
            / IP(src="192.168.1.5", dst="8.8.8.8")
            / ICMP(type=8, code=0)
        )

        obs = extract_metadata_from_scapy(packet)
        self.assertEqual(obs["protocol"], "ICMP")
        self.assertNotIn("src_port", obs)
        self.assertNotIn("dst_port", obs)
        self.assertEqual(obs["protocol_metadata"]["type"], 8)
        self.assertEqual(obs["protocol_metadata"]["type_name"], "echo-request")

    def test_dns_packet_extraction(self):
        from scapy.layers.l2 import Ether
        from scapy.layers.inet import IP, UDP
        from scapy.layers.dns import DNS, DNSQR

        packet = (
            Ether(src="aa:bb:cc:dd:ee:01", dst="aa:bb:cc:dd:ee:02")
            / IP(src="192.168.1.5", dst="192.168.1.1")
            / UDP(sport=51234, dport=53)
            / DNS(rd=1, qd=DNSQR(qname="example.com.", qtype=1))
        )

        obs = extract_metadata_from_scapy(packet)
        self.assertEqual(obs["protocol"], "DNS")
        self.assertEqual(obs["src_port"], 51234)
        self.assertEqual(obs["dst_port"], 53)
        self.assertIsNotNone(obs.get("protocol_metadata"))
        self.assertEqual(obs["protocol_metadata"]["message_type"], "query")
        self.assertEqual(obs["protocol_metadata"]["query_name"], "example.com")
        self.assertEqual(obs["protocol_metadata"]["query_type"], "A")


if __name__ == "__main__":
    unittest.main()
