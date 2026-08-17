"""Passive DHCP observation for the client agent.

DHCP broadcasts from *other* devices are visible through packet capture, not
by binding a normal UDP socket to port 68. ``DHCPListener`` therefore uses
Scapy/libpcap as its primary capture mechanism and keeps a UDP socket only as
a limited fallback for locally delivered test traffic.
"""

import ipaddress
import logging
import socket
import struct
import threading
from typing import Optional


LOG = logging.getLogger("dhcp")
DHCP_BPF_FILTER = "udp and (port 67 or port 68)"
DHCP_REQUEST = 3


def _format_mac(bytes6: bytes) -> Optional[str]:
    if not isinstance(bytes6, (bytes, bytearray)) or len(bytes6) < 6:
        return None
    return ":".join(f"{byte:02X}" for byte in bytes6[:6])


def _parse_options(options: bytes) -> dict:
    index = 0
    result = {}
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


def _decode_str(value: bytes) -> Optional[str]:
    try:
        return value.decode("utf-8", errors="ignore").strip("\x00") or None
    except (AttributeError, UnicodeError):
        return None


def _decode_ipv4(value: bytes) -> Optional[str]:
    if len(value) != 4:
        return None
    try:
        return str(ipaddress.IPv4Address(value))
    except ipaddress.AddressValueError:
        return None


def parse_dhcp_packet(data: bytes) -> Optional[dict]:
    """Parse a BOOTP/DHCP UDP payload into a safe observation dictionary."""
    try:
        if not isinstance(data, (bytes, bytearray)) or len(data) < 240:
            return None

        header = struct.unpack_from("!BBBBIHHIIII16s", data, 0)
        hlen = header[2]
        ciaddr = header[7]
        yiaddr = header[8]
        chaddr = header[11]
        mac = _format_mac(chaddr[:hlen])

        if data[236:240] != b"\x63\x82\x53\x63":
            return None
        options = _parse_options(data[240:])

        message_type = options.get(53, b"")
        message_type = message_type[0] if message_type else None
        # A renewing client normally puts its existing address in ciaddr and
        # omits option 50. Option 50 is preferred for selecting/rebinding.
        requested_ip = _decode_ipv4(options.get(50, b""))
        if requested_ip is None and ciaddr:
            requested_ip = str(ipaddress.IPv4Address(ciaddr))
        if requested_ip is None and yiaddr:
            requested_ip = str(ipaddress.IPv4Address(yiaddr))

        if not mac:
            return None
        first_octet = int(mac[:2], 16)
        if mac == "FF:FF:FF:FF:FF:FF" or first_octet & 1:
            return None

        client_id = options.get(61)
        if client_id:
            client_id = ":".join(f"{byte:02X}" for byte in client_id)
        else:
            client_id = None

        return {
            "mac_address": mac,
            "dhcp_message_type": message_type,
            "requested_ip": requested_ip,
            "hostname": _decode_str(options.get(12, b"")),
            "vendor_class": _decode_str(options.get(60, b"")),
            "client_id": client_id,
        }
    except (IndexError, struct.error, ValueError, ipaddress.AddressValueError):
        return None


class DHCPListener:
    """Observe DHCPREQUEST packets without sending or modifying traffic.

    Packet capture is used first because a UDP socket only receives datagrams
    delivered to this host; it cannot passively observe peers' broadcasts.
    ``interface`` may be set for multi-homed hosts.
    """

    def __init__(self, on_observation, interface: Optional[str] = None):
        self.on_observation = on_observation
        self.interface = interface
        self._thread = None
        self._stop = threading.Event()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        LOG.info("[DHCP] Listener started")

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _handle_payload(self, payload: bytes):
        parsed = parse_dhcp_packet(payload)
        if not parsed or parsed.get("dhcp_message_type") != DHCP_REQUEST:
            return
        LOG.info("[DHCP] Request observed: %s", parsed["mac_address"])
        try:
            self.on_observation(parsed)
        except Exception:
            LOG.exception("[DHCP] on_observation handler failed")

    @staticmethod
    def _is_dhcp_packet(packet) -> bool:
        try:
            from scapy.layers.inet import UDP  # type: ignore

            return packet.haslayer(UDP) and (
                packet[UDP].sport in (67, 68) or packet[UDP].dport in (67, 68)
            )
        except Exception:
            return False

    def _handle_scapy_packet(self, packet):
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
            LOG.warning("[DHCP] Scapy is not installed; packet capture is unavailable")
            return False

        sniff_kwargs = {"prn": self._handle_scapy_packet, "store": False, "timeout": 1}
        if self.interface:
            sniff_kwargs["iface"] = self.interface
        try:
            LOG.info(
                "[DHCP] Capturing DHCP traffic on %s",
                self.interface or "the default interface",
            )
            while not self._stop.is_set():
                sniff(filter=DHCP_BPF_FILTER, **sniff_kwargs)
            return True
        except Exception as error:
            # Some Scapy installations do not have libpcap for BPF filters.
            # Retrying without BPF keeps real packet capture available.
            LOG.warning("[DHCP] BPF capture unavailable: %s", error)
            try:
                while not self._stop.is_set():
                    sniff(lfilter=self._is_dhcp_packet, **sniff_kwargs)
                return True
            except Exception as fallback_error:
                # Npcap/libpcap availability is a normal deployment concern,
                # particularly on Windows. Do not flood the client console
                # with a traceback while the limited UDP fallback is tried.
                LOG.warning(
                    "[DHCP] Packet capture unavailable: %s. "
                    "Install Npcap (Windows) or grant packet-capture permission.",
                    fallback_error,
                )
                return False

    def _capture_with_udp_socket(self):
        """Limited fallback for packets the OS explicitly delivers to this host."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(0.5)
            sock.bind(("", 68))
        except OSError as error:
            LOG.warning("[DHCP] UDP fallback unavailable: %s", error)
            return

        LOG.warning("[DHCP] Using limited UDP fallback; peer DHCP broadcasts will not be observed")
        try:
            while not self._stop.is_set():
                try:
                    payload, _ = sock.recvfrom(4096)
                except socket.timeout:
                    continue
                self._handle_payload(payload)
        finally:
            sock.close()

    def _run(self):
        try:
            if not self._capture_with_scapy() and not self._stop.is_set():
                self._capture_with_udp_socket()
        finally:
            LOG.info("[DHCP] Listener stopped")
