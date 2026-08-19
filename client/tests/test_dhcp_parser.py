import json
import sys
import unittest
from pathlib import Path

CLIENT_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLIENT_DIRECTORY))

from dhcp_listener import parse_dhcp_packet


def _build_dhcp_request(
    mac=b"\xe4\xfd\x45\xba\x8b\x96",
    requested_ip="172.16.0.102",
    hostname=b"DESKTOP-DJP05CM",
    vendor=b"MSFT 5.0",
    client_id=b"\x01\xe4\xfd\x45\xba\x8b\x96",
):
    # Build a minimal DHCPREQUEST UDP payload: fixed header + magic cookie + options
    op = 1
    htype = 1
    hlen = 6
    hops = 0
    xid = 0x3904A3B2
    secs = 0
    flags = 0
    ciaddr = b"\x00\x00\x00\x00"
    yiaddr = b"\x00\x00\x00\x00"
    siaddr = b"\x00\x00\x00\x00"
    giaddr = b"\x00\x00\x00\x00"
    chaddr = mac + b"\x00" * (16 - len(mac))
    sname = b"\x00" * 64
    file = b"\x00" * 128

    fixed = struct_pack = (
        bytes([op, htype, hlen, hops])
        + xid.to_bytes(4, "big")
        + secs.to_bytes(2, "big")
        + flags.to_bytes(2, "big")
        + ciaddr
        + yiaddr
        + siaddr
        + giaddr
        + chaddr
        + sname
        + file
    )

    cookie = b"\x63\x82\x53\x63"
    opts = b""
    # DHCP Message Type (53) = 3
    opts += bytes([53, 1, 3])
    # Requested IP (50)
    opts += bytes([50, 4]) + ip_to_bytes(requested_ip)
    # Hostname (12)
    if hostname:
        opts += bytes([12, len(hostname)]) + hostname
    # Vendor class (60)
    if vendor:
        opts += bytes([60, len(vendor)]) + vendor
    # Client ID (61)
    if client_id:
        opts += bytes([61, len(client_id)]) + client_id
    # End
    opts += bytes([255])

    return fixed + cookie + opts


def ip_to_bytes(ip: str) -> bytes:
    parts = [int(x) for x in ip.split(".")]
    return bytes(parts)


import struct


class DHCPParserTests(unittest.TestCase):
    def test_parse_valid_request(self):
        pkt = _build_dhcp_request()
        parsed = parse_dhcp_packet(pkt)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.get("mac_address"), "E4:FD:45:BA:8B:96")
        self.assertEqual(parsed.get("dhcp_message_type"), 3)
        self.assertEqual(parsed.get("requested_ip"), "172.16.0.102")
        self.assertEqual(parsed.get("hostname"), "DESKTOP-DJP05CM")
        self.assertEqual(parsed.get("vendor_class"), "MSFT 5.0")
        self.assertTrue(parsed.get("client_id") is not None)

    def test_missing_hostname(self):
        pkt = _build_dhcp_request(hostname=b"")
        parsed = parse_dhcp_packet(pkt)
        self.assertIsNotNone(parsed)
        self.assertIsNone(parsed.get("hostname"))

    def test_parse_dhcp_discover_and_ack(self):
        # Test DHCPDISCOVER (type 1)
        pkt_discover = _build_dhcp_request(requested_ip="0.0.0.0", hostname=b"DISCOVER-HOST")
        # Replace message type 3 with 1
        pkt_discover = pkt_discover[:242] + bytes([1]) + pkt_discover[243:]
        parsed_discover = parse_dhcp_packet(pkt_discover)
        self.assertIsNotNone(parsed_discover)
        self.assertEqual(parsed_discover.get("dhcp_message_type"), 1)
        self.assertEqual(parsed_discover.get("hostname"), "DISCOVER-HOST")

        # Test DHCPACK (type 5)
        pkt_ack = _build_dhcp_request(requested_ip="192.168.1.55", hostname=b"ACK-HOST")
        pkt_ack = pkt_ack[:242] + bytes([5]) + pkt_ack[243:]
        parsed_ack = parse_dhcp_packet(pkt_ack)
        self.assertIsNotNone(parsed_ack)
        self.assertEqual(parsed_ack.get("dhcp_message_type"), 5)
        self.assertEqual(parsed_ack.get("requested_ip"), "192.168.1.55")
        self.assertEqual(parsed_ack.get("hostname"), "ACK-HOST")


if __name__ == "__main__":
    unittest.main()
