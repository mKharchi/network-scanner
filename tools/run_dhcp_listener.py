#!/usr/bin/env python3
"""Run the passive DHCP listener and print observations to stdout.

For local testing this script binds to a non-privileged UDP port by default
so you don't need sudo. Set `LISTEN_PORT` env var to change it (e.g.
`LISTEN_PORT=68` to attempt the privileged bind).

Usage: python3 tools/run_dhcp_listener.py
       LISTEN_PORT=68 sudo python3 tools/run_dhcp_listener.py
"""

import logging
import sys
import time
import os
import socket
from pathlib import Path

CLIENT_DIR = Path(__file__).resolve().parents[1] / "client"
sys.path.insert(0, str(CLIENT_DIR))

from dhcp_listener import parse_dhcp_packet

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("run_dhcp_listener")


def on_observation(obs: dict):
    # Print a friendly block similar to the scapy-based test script
    print("\n========== DHCP REQUEST FOUND ==========")
    print(f"MAC:            {obs.get('mac_address')}")
    print(f"Message type:   {obs.get('dhcp_message_type')}")
    print(f"Requested IP:   {obs.get('requested_ip')}")
    print(f"Hostname:       {obs.get('hostname')}")
    print(f"Vendor class:   {obs.get('vendor_class')}")
    print(f"Client ID:      {obs.get('client_id')}")
    print("========================================\n")


def main():
    # For testing without sudo, allow overriding the listen port via env LISTEN_PORT
    force_pcap = os.environ.get("FORCE_PCAP", "0") == "1"
    iface = os.environ.get("LISTEN_IFACE")
    if force_pcap:
        # Use scapy sniff directly (requires root) so we can observe DHCP on the wire
        try:
            from scapy.all import sniff  # type: ignore

            def _scapy_prn(pkt):
                try:
                    if pkt.haslayer("UDP"):
                        data = bytes(pkt["UDP"].payload)
                    else:
                        return
                    parsed = parse_dhcp_packet(data)
                    if parsed:
                        on_observation(parsed)
                except Exception:
                    log.exception("scapy packet handler error")

            sniff_kwargs = dict(
                filter="udp and (port 67 or port 68)", prn=_scapy_prn, store=0
            )
            if iface:
                sniff_kwargs["iface"] = iface
            sniff_kwargs["stop_filter"] = lambda p: False
            log.info("Starting forced pcap sniff on iface=%s", iface or "<default>")
            try:
                sniff(**sniff_kwargs)
            except KeyboardInterrupt:
                log.info("Stopping forced pcap sniff")
            except Exception:
                log.exception("scapy sniff failed")
            return
        except Exception:
            log.exception(
                "scapy not available for forced pcap sniff; falling back to UDP bind"
            )

    port = int(os.environ.get("LISTEN_PORT", "1068"))
    log.info("Binding test UDP listener on 0.0.0.0:%d", port)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind(("", port))
    try:
        while True:
            data, addr = sock.recvfrom(4096)
            parsed = parse_dhcp_packet(data)
            if parsed:
                on_observation(parsed)
    except KeyboardInterrupt:
        log.info("Stopping listener")
    finally:
        sock.close()


if __name__ == "__main__":
    main()
