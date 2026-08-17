#!/usr/bin/env python3
"""Send a synthetic DHCPREQUEST UDP packet to localhost:68 for testing the passive listener.

Usage: python3 tools/send_fake_dhcp.py
"""

import socket


def ip_to_bytes(ip: str) -> bytes:
    return bytes(int(x) for x in ip.split("."))


def build_dhcp_request(
    mac=b"\xe4\xfd\x45\xba\x8b\x96",
    requested_ip="172.16.0.102",
    hostname=b"TEST-CLIENT",
    vendor=b"TEST-VENDOR",
    client_id=b"\x01\xe4\xfd\x45\xba\x8b\x96",
):
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

    fixed = (
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
    # DHCP Message Type (53) = 3 (REQUEST)
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


def main():
    import os

    target_port = int(os.environ.get("TARGET_PORT", "1068"))
    pkt = build_dhcp_request()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(pkt, ("127.0.0.1", target_port))
        print(f"Sent synthetic DHCPREQUEST to 127.0.0.1:{target_port}")
    finally:
        s.close()


if __name__ == "__main__":
    main()
