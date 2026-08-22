"""Passive DHCP observation for the client agent.

Extracts rich identity, network, and parameter request list (PRL) fields
from BOOTP/DHCP packets without sending or modifying traffic.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
import struct
import threading
from typing import Any, Callable, Optional


LOG = logging.getLogger("dhcp")
DHCP_BPF_FILTER = "udp and (port 67 or port 68)"
DHCP_REQUEST = 3


def _format_mac(bytes6: bytes) -> Optional[str]:
    if not isinstance(bytes6, (bytes, bytearray)) or len(bytes6) < 6:
        return None
    return ":".join(f"{byte:02X}" for byte in bytes6[:6])


def _parse_options(options: bytes) -> dict[int, bytes]:
    """Parse raw DHCP options into code -> bytes mapping."""
    index = 0
    result: dict[int, bytes] = {}
    while index < len(options):
        code = options[index]
        index += 1
        if code == 0:  # Pad
            continue
        if code == 255:  # End
            break
        if index >= len(options):
            break
        length = options[index]
        index += 1
        if index + length > len(options):
            break
        result[code] = options[index : index + length]
        index += length
    return result


def _decode_str(value: bytes | None) -> Optional[str]:
    if not value:
        return None
    try:
        clean = value.decode("utf-8", errors="ignore").strip("\x00").strip()
        return clean or None
    except (AttributeError, UnicodeError):
        return None


def _decode_ipv4(value: bytes | None) -> Optional[str]:
    if not value or len(value) < 4:
        return None
    try:
        return str(ipaddress.IPv4Address(value[:4]))
    except (ipaddress.AddressValueError, ValueError):
        return None


def _decode_ipv4_list(value: bytes | None) -> list[str]:
    if not value or len(value) % 4 != 0:
        return []
    ips = []
    for i in range(0, len(value), 4):
        ip = _decode_ipv4(value[i : i + 4])
        if ip:
            ips.append(ip)
    return ips


def _decode_int32(value: bytes | None) -> Optional[int]:
    if not value or len(value) < 4:
        return None
    try:
        return struct.unpack("!I", value[:4])[0]
    except struct.error:
        return None


def parse_dhcp_packet(data: bytes) -> Optional[dict[str, Any]]:
    """Parse a BOOTP/DHCP UDP payload into a rich, safe observation dictionary."""
    try:
        if not isinstance(data, (bytes, bytearray)) or len(data) < 240:
            return None

        header = struct.unpack_from("!BBBBIHHIIII16s", data, 0)
        _op = header[0]
        _htype = header[1]
        hlen = header[2]
        _xid = header[4]
        ciaddr = header[7]
        yiaddr = header[8]
        _siaddr = header[9]
        _giaddr = header[10]
        chaddr = header[11]
        mac = _format_mac(chaddr[:hlen])

        # Check DHCP Magic Cookie 0x63825363
        if data[236:240] != b"\x63\x82\x53\x63":
            return None
        options = _parse_options(data[240:])

        message_type_raw = options.get(53, b"")
        message_type = message_type_raw[0] if message_type_raw else None

        # Address resolution priority: Option 50 (Requested IP) -> ciaddr -> yiaddr
        requested_ip = _decode_ipv4(options.get(50))
        if requested_ip is None and ciaddr:
            requested_ip = str(ipaddress.IPv4Address(ciaddr))
        if requested_ip is None and yiaddr:
            requested_ip = str(ipaddress.IPv4Address(yiaddr))

        if not mac:
            return None
        first_octet = int(mac[:2], 16)
        if mac == "FF:FF:FF:FF:FF:FF" or first_octet & 1:
            return None

        # Option 61 Client Identifier
        client_id_raw = options.get(61)
        client_id = ":".join(f"{byte:02X}" for byte in client_id_raw) if client_id_raw else None

        # Option 55 Parameter Request List
        prl_raw = options.get(55)
        prl = list(prl_raw) if prl_raw else None

        # Option 12 Hostname & Option 60 Vendor Class
        hostname = _decode_str(options.get(12))
        vendor_class = _decode_str(options.get(60))

        # Additional standard network options
        subnet_mask = _decode_ipv4(options.get(1))
        routers = _decode_ipv4_list(options.get(3))
        dns_servers = _decode_ipv4_list(options.get(6))
        domain_name = _decode_str(options.get(15))
        broadcast_addr = _decode_ipv4(options.get(28))
        lease_time = _decode_int32(options.get(51))
        server_id = _decode_ipv4(options.get(54))

        raw_fields: dict[str, Any] = {
            "transaction_id": hex(_xid),
        }
        if vendor_class:
            raw_fields["vendor_class"] = vendor_class
        if prl:
            raw_fields["parameter_request_list"] = prl
        if subnet_mask:
            raw_fields["subnet_mask"] = subnet_mask
        if routers:
            raw_fields["routers"] = routers
        if dns_servers:
            raw_fields["dns_servers"] = dns_servers
        if domain_name:
            raw_fields["domain_name"] = domain_name
        if lease_time is not None:
            raw_fields["lease_time"] = lease_time
        if server_id:
            raw_fields["server_identifier"] = server_id
        if broadcast_addr:
            raw_fields["broadcast_address"] = broadcast_addr

        return {
            "protocol": "dhcp",
            "mac_address": mac,
            "dhcp_message_type": message_type,
            "requested_ip": requested_ip,
            "ip_address": requested_ip,
            "hostname": hostname,
            "vendor_class": vendor_class,
            "client_id": client_id,
            "parameter_request_list": prl,
            "raw_fields": raw_fields,
        }
    except (IndexError, struct.error, ValueError, ipaddress.AddressValueError):
        return None


class DHCPListener:
    """Observe DHCP packets without sending or modifying traffic."""

    def __init__(self, on_observation: Callable[[dict[str, Any]], None], interface: Optional[str] = None):
        self.on_observation = on_observation
        self.interface = interface
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="dhcp-listener")
        self._thread.start()
        LOG.info("[DHCP] Listener started")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _handle_payload(self, payload: bytes) -> None:
        parsed = parse_dhcp_packet(payload)
        if not parsed or not parsed.get("mac_address"):
            return
        msg_type = parsed.get("dhcp_message_type")
        if msg_type is not None and msg_type not in (1, 2, 3, 5, 8):
            return
        LOG.info(
            "[DHCP] Packet observed: %s (Type %s, IP: %s, Hostname: %s)",
            parsed["mac_address"],
            msg_type,
            parsed.get("requested_ip"),
            parsed.get("hostname"),
        )
        try:
            self.on_observation(parsed)
        except Exception:
            LOG.exception("[DHCP] on_observation handler failed")

    @staticmethod
    def _is_dhcp_packet(packet: Any) -> bool:
        try:
            from scapy.layers.inet import UDP  # type: ignore

            return packet.haslayer(UDP) and (
                packet[UDP].sport in (67, 68) or packet[UDP].dport in (67, 68)
            )
        except Exception:
            return False

    def _handle_scapy_packet(self, packet: Any) -> None:
        try:
            from scapy.layers.inet import UDP  # type: ignore

            if self._is_dhcp_packet(packet):
                self._handle_payload(bytes(packet[UDP].payload))
        except Exception:
            LOG.exception("[DHCP] Scapy packet handler failed")

    def _capture_with_scapy(self) -> bool:
        """Capture until stopped. Return False when capture cannot be started."""
        try:
            from scapy.all import sniff  # type: ignore
        except ImportError:
            print("[DHCP] Scapy is not installed; packet capture is unavailable", flush=True)
            return False

        sniff_kwargs = {"prn": self._handle_scapy_packet, "store": False, "timeout": 1}
        if self.interface:
            sniff_kwargs["iface"] = self.interface
        try:
            print(
                f"[DHCP] Capturing DHCP traffic on {self.interface or 'default interface'}...",
                flush=True,
            )
            while not self._stop.is_set():
                sniff(filter=DHCP_BPF_FILTER, **sniff_kwargs)
            return True
        except Exception as error:
            try:
                while not self._stop.is_set():
                    sniff(lfilter=self._is_dhcp_packet, **sniff_kwargs)
                return True
            except Exception as fallback_error:
                print(
                    f"[DHCP] Packet capture unavailable ({fallback_error}). "
                    "Running with root/sudo or installing Npcap is recommended for live packet capture.",
                    flush=True,
                )
                return False

    def _capture_with_udp_socket(self) -> None:
        """Limited fallback for packets the OS explicitly delivers to this host."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(0.5)
            sock.bind(("", 68))
        except OSError as error:
            print(f"[DHCP] UDP fallback unavailable on port 68: {error}", flush=True)
            return

        print("[DHCP] Using UDP socket fallback on port 68...", flush=True)
        try:
            while not self._stop.is_set():
                try:
                    payload, _ = sock.recvfrom(4096)
                except socket.timeout:
                    continue
                self._handle_payload(payload)
        finally:
            sock.close()

    def _run(self) -> None:
        try:
            if not self._capture_with_scapy() and not self._stop.is_set():
                self._capture_with_udp_socket()
        finally:
            print("[DHCP] Listener stopped", flush=True)
