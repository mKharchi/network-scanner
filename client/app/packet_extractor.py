"""Passive packet metadata extraction and normalization.

Extracts structured, normalized behavioral metadata from observed network packets
without storing raw payloads, application message contents, or credentials.
"""

from __future__ import annotations

import datetime
import ipaddress
import re
from typing import Any, Dict, List, Optional

MAC_PATTERN = re.compile(r"^[0-9A-Fa-f]{2}(?:[:-][0-9A-Fa-f]{2}){5}$")

# Map standard ICMP types for IPv4
ICMP_TYPE_NAMES = {
    0: "echo-reply",
    3: "dest-unreachable",
    4: "source-quench",
    5: "redirect",
    8: "echo-request",
    11: "time-exceeded",
    12: "parameter-problem",
    13: "timestamp-request",
    14: "timestamp-reply",
}

# DHCP message types (Option 53)
DHCP_MESSAGE_TYPES = {
    1: "DISCOVER",
    2: "OFFER",
    3: "REQUEST",
    4: "DECLINE",
    5: "ACK",
    6: "NAK",
    7: "RELEASE",
    8: "INFORM",
}

DNS_QTYPES = {
    1: "A",
    2: "NS",
    5: "CNAME",
    6: "SOA",
    12: "PTR",
    15: "MX",
    16: "TXT",
    28: "AAAA",
    33: "SRV",
    255: "ANY",
}


def normalize_mac(value: Any) -> Optional[str]:
    """Normalize a MAC address to uppercase colon-separated format."""
    if not isinstance(value, str):
        return None
    val = value.strip().replace("-", ":").upper()
    if MAC_PATTERN.fullmatch(val):
        return val
    return None


def normalize_ip(value: Any) -> Optional[str]:
    """Validate and return normalized IP address string."""
    if not isinstance(value, str):
        return None
    val = value.strip()
    try:
        addr = ipaddress.ip_address(val)
        return str(addr)
    except (ValueError, AttributeError):
        return None


def format_timestamp(dt: Optional[datetime.datetime] = None) -> str:
    """Format UTC datetime as ISO 8601 string with millisecond precision."""
    if dt is None:
        dt = datetime.datetime.now(datetime.timezone.utc)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def extract_tcp_flags(flags_val: Any) -> Optional[str]:
    """Normalize TCP flags into standard string representation (e.g. 'S', 'PA', 'FA')."""
    if flags_val is None:
        return None
    if isinstance(flags_val, str):
        return flags_val.strip().upper() or None
    # If Scapy FlagValue / int
    try:
        val = int(flags_val)
        result = []
        if val & 0x01:
            result.append("F")
        if val & 0x02:
            result.append("S")
        if val & 0x04:
            result.append("R")
        if val & 0x08:
            result.append("P")
        if val & 0x10:
            result.append("A")
        if val & 0x20:
            result.append("U")
        if val & 0x40:
            result.append("E")
        if val & 0x80:
            result.append("C")
        return "".join(result) if result else None
    except (ValueError, TypeError):
        return str(flags_val)


def determine_direction(
    src_mac: Optional[str],
    dst_mac: Optional[str],
    src_ip: Optional[str],
    dst_ip: Optional[str],
    local_mac: Optional[str],
    local_ip: Optional[str],
) -> str:
    """Determine packet direction (inbound, outbound, unknown) relative to local client."""
    norm_local_mac = normalize_mac(local_mac) if local_mac else None
    norm_local_ip = normalize_ip(local_ip) if local_ip else None

    is_src_local = False
    is_dst_local = False

    if norm_local_mac:
        if src_mac and src_mac == norm_local_mac:
            is_src_local = True
        if dst_mac and dst_mac == norm_local_mac:
            is_dst_local = True

    if norm_local_ip:
        if src_ip and src_ip == norm_local_ip:
            is_src_local = True
        if dst_ip and dst_ip == norm_local_ip:
            is_dst_local = True

    if is_src_local and not is_dst_local:
        return "outbound"
    if is_dst_local and not is_src_local:
        return "inbound"
    return "unknown"


def _extract_dhcp_metadata(payload_bytes: bytes) -> Optional[Dict[str, Any]]:
    """Extract structured DHCP options without raw payload."""
    from dhcp_listener import parse_dhcp_packet

    parsed = parse_dhcp_packet(payload_bytes)
    if not parsed:
        return None

    msg_type_code = parsed.get("dhcp_message_type")
    msg_type_name = DHCP_MESSAGE_TYPES.get(msg_type_code, str(msg_type_code)) if msg_type_code else None

    meta: Dict[str, Any] = {}
    if msg_type_name:
        meta["message_type"] = msg_type_name
    if parsed.get("requested_ip"):
        meta["requested_ip"] = parsed["requested_ip"]
    if parsed.get("hostname"):
        meta["hostname"] = parsed["hostname"]
    if parsed.get("vendor_class"):
        meta["vendor_class"] = parsed["vendor_class"]
    if parsed.get("client_id"):
        meta["client_id"] = parsed["client_id"]
    if parsed.get("parameter_request_list"):
        meta["parameter_request_list"] = parsed["parameter_request_list"]

    raw = parsed.get("raw_fields", {})
    if raw.get("domain_name"):
        meta["domain_name"] = raw["domain_name"]
    if raw.get("server_identifier"):
        meta["server_identifier"] = raw["server_identifier"]
    if raw.get("lease_time") is not None:
        meta["lease_time"] = raw["lease_time"]

    return meta or None


def _extract_dns_metadata(dns_layer: Any) -> Optional[Dict[str, Any]]:
    """Extract DNS/mDNS/LLMNR query and response metadata."""
    try:
        qr = getattr(dns_layer, "qr", 0)
        opcode = getattr(dns_layer, "opcode", 0)
        rcode = getattr(dns_layer, "rcode", 0)
        qdcount = getattr(dns_layer, "qdcount", 0)
        ancount = getattr(dns_layer, "ancount", 0)

        is_response = bool(qr == 1)
        message_type = "response" if is_response else "query"

        meta: Dict[str, Any] = {
            "message_type": message_type,
            "query_count": qdcount,
            "answer_count": ancount,
        }
        if is_response:
            meta["rcode"] = rcode

        # Extract first question name & type
        qd = getattr(dns_layer, "qd", None)
        if qd:
            qname = getattr(qd, "qname", b"")
            if isinstance(qname, bytes):
                qname = qname.decode("utf-8", errors="ignore").rstrip(".")
            elif isinstance(qname, str):
                qname = qname.rstrip(".")
            if qname:
                meta["query_name"] = qname

            qtype_num = getattr(qd, "qtype", None)
            if qtype_num is not None:
                meta["query_type"] = DNS_QTYPES.get(qtype_num, str(qtype_num))

        return meta
    except Exception:
        return None


def _extract_ssdp_metadata(payload_bytes: bytes) -> Optional[Dict[str, Any]]:
    """Extract SSDP M-SEARCH / NOTIFY headers."""
    try:
        text = payload_bytes.decode("utf-8", errors="ignore")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return None

        first_line = lines[0]
        method = None
        if first_line.startswith("NOTIFY "):
            method = "NOTIFY"
        elif first_line.startswith("M-SEARCH "):
            method = "M-SEARCH"
        elif first_line.startswith("HTTP/1.1 200"):
            method = "200 OK"
        else:
            return None

        meta: Dict[str, Any] = {"method": method}
        for line in lines[1:]:
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            key_upper = key.strip().upper()
            val_clean = val.strip()
            if not val_clean:
                continue
            if key_upper == "ST":
                meta["st"] = val_clean
            elif key_upper == "NT":
                meta["nt"] = val_clean
            elif key_upper == "USN":
                meta["usn"] = val_clean
            elif key_upper == "SERVER":
                meta["server"] = val_clean
            elif key_upper == "LOCATION":
                meta["location"] = val_clean
            elif key_upper == "USER-AGENT":
                meta["user_agent"] = val_clean

        return meta
    except Exception:
        return None


def _extract_nbns_metadata(payload_bytes: bytes) -> Optional[Dict[str, Any]]:
    """Extract NetBIOS Name Service query metadata."""
    if len(payload_bytes) < 12:
        return None
    try:
        flags = int.from_bytes(payload_bytes[2:4], "big")
        is_response = bool((flags >> 15) & 1)
        qdcount = int.from_bytes(payload_bytes[4:6], "big")

        meta: Dict[str, Any] = {
            "message_type": "response" if is_response else "query",
        }

        # Parse encoded NetBIOS name if present
        if qdcount > 0 and len(payload_bytes) >= 13:
            name_len = payload_bytes[12]
            if name_len == 32 and len(payload_bytes) >= 13 + 32:
                encoded = payload_bytes[13:45]
                decoded = []
                for i in range(0, 32, 2):
                    c1 = encoded[i] - 0x41
                    c2 = encoded[i + 1] - 0x41
                    decoded.append(chr((c1 << 4) | c2))
                nb_name = "".join(decoded).strip()
                if nb_name:
                    meta["name"] = nb_name

        return meta
    except Exception:
        return None


def extract_metadata_from_scapy(
    packet: Any,
    *,
    interface: Optional[str] = None,
    observer_client_id: Optional[str] = None,
    local_mac: Optional[str] = None,
    local_ip: Optional[str] = None,
    observed_time: Optional[datetime.datetime] = None,
) -> Dict[str, Any]:
    """Extract normalized observation metadata from a live Scapy packet."""
    timestamp = format_timestamp(observed_time)
    packet_length = len(packet) if hasattr(packet, "__len__") else 0

    src_mac = None
    dst_mac = None
    src_ip = None
    dst_ip = None
    protocol = "UNKNOWN"
    src_port = None
    dst_port = None
    tcp_flags = None
    protocol_metadata: Optional[Dict[str, Any]] = None

    # L2 layer (Ethernet / ARP)
    try:
        from scapy.layers.l2 import Ether, ARP
        if packet.haslayer(Ether):
            eth = packet[Ether]
            src_mac = normalize_mac(getattr(eth, "src", None))
            dst_mac = normalize_mac(getattr(eth, "dst", None))

        if packet.haslayer(ARP):
            protocol = "ARP"
            arp = packet[ARP]
            if not src_mac:
                src_mac = normalize_mac(getattr(arp, "hwsrc", None))
            if not dst_mac:
                dst_mac = normalize_mac(getattr(arp, "hwdst", None))
            src_ip = normalize_ip(getattr(arp, "psrc", None))
            dst_ip = normalize_ip(getattr(arp, "pdst", None))
            op_code = getattr(arp, "op", 1)
            protocol_metadata = {
                "operation": "who-has" if op_code == 1 else "is-at" if op_code == 2 else str(op_code),
            }
    except Exception:
        pass

    # L3 layer (IPv4 / IPv6)
    try:
        from scapy.layers.inet import IP, TCP, UDP, ICMP
        from scapy.layers.inet6 import IPv6

        if packet.haslayer(IP):
            ip_layer = packet[IP]
            src_ip = normalize_ip(getattr(ip_layer, "src", None))
            dst_ip = normalize_ip(getattr(ip_layer, "dst", None))
            proto_num = getattr(ip_layer, "proto", None)
            if proto_num == 1:
                protocol = "ICMP"
            elif proto_num == 6:
                protocol = "TCP"
            elif proto_num == 17:
                protocol = "UDP"
            elif proto_num == 2:
                protocol = "IGMP"
            else:
                protocol = f"IP({proto_num})"
        elif packet.haslayer(IPv6):
            ip6 = packet[IPv6]
            src_ip = getattr(ip6, "src", None)
            dst_ip = getattr(ip6, "dst", None)
            protocol = "IPv6"

        # L4 layer
        if packet.haslayer(TCP):
            protocol = "TCP"
            tcp = packet[TCP]
            src_port = getattr(tcp, "sport", None)
            dst_port = getattr(tcp, "dport", None)
            tcp_flags = extract_tcp_flags(getattr(tcp, "flags", None))

            # TLS ClientHello SNI inspection on port 443
            if (src_port == 443 or dst_port == 443) and hasattr(tcp, "payload"):
                payload_bytes = bytes(tcp.payload)
                if len(payload_bytes) >= 6 and payload_bytes[0] == 0x16:
                    from passive_protocol_listener import parse_tls_client_hello
                    tls_parsed = parse_tls_client_hello(payload_bytes)
                    if tls_parsed:
                        protocol = "TLS"
                        protocol_metadata = {
                            k: v for k, v in tls_parsed.items()
                            if k in ("sni", "ja3_hash", "tls_version") and v is not None
                        }

        elif packet.haslayer(UDP):
            protocol = "UDP"
            udp = packet[UDP]
            src_port = getattr(udp, "sport", None)
            dst_port = getattr(udp, "dport", None)
            payload_bytes = bytes(udp.payload) if hasattr(udp, "payload") else b""

            # Inspect high-level protocols over UDP
            if src_port in (67, 68) or dst_port in (67, 68):
                protocol = "DHCP"
                protocol_metadata = _extract_dhcp_metadata(payload_bytes)
            elif src_port == 5353 or dst_port == 5353:
                protocol = "mDNS"
                if hasattr(packet, "getlayer"):
                    from scapy.layers.dns import DNS
                    if packet.haslayer(DNS):
                        protocol_metadata = _extract_dns_metadata(packet[DNS])
            elif src_port == 5355 or dst_port == 5355:
                protocol = "LLMNR"
                if hasattr(packet, "getlayer"):
                    from scapy.layers.dns import DNS
                    if packet.haslayer(DNS):
                        protocol_metadata = _extract_dns_metadata(packet[DNS])
            elif src_port == 137 or dst_port == 137:
                protocol = "NBNS"
                protocol_metadata = _extract_nbns_metadata(payload_bytes)
            elif src_port == 1900 or dst_port == 1900:
                protocol = "SSDP"
                protocol_metadata = _extract_ssdp_metadata(payload_bytes)
            elif src_port == 53 or dst_port == 53:
                protocol = "DNS"
                if hasattr(packet, "getlayer"):
                    from scapy.layers.dns import DNS
                    if packet.haslayer(DNS):
                        protocol_metadata = _extract_dns_metadata(packet[DNS])

        elif packet.haslayer(ICMP):
            protocol = "ICMP"
            icmp = packet[ICMP]
            itype = getattr(icmp, "type", None)
            icode = getattr(icmp, "code", None)
            protocol_metadata = {
                "type": itype,
                "code": icode,
                "type_name": ICMP_TYPE_NAMES.get(itype, str(itype)),
            }

    except Exception:
        pass

    direction = determine_direction(
        src_mac=src_mac,
        dst_mac=dst_mac,
        src_ip=src_ip,
        dst_ip=dst_ip,
        local_mac=local_mac,
        local_ip=local_ip,
    )

    record: Dict[str, Any] = {
        "timestamp": timestamp,
        "packet_length": packet_length,
        "protocol": protocol,
        "direction": direction,
    }

    if observer_client_id:
        record["observer_client_id"] = observer_client_id
    if interface:
        record["interface"] = interface
    if src_mac:
        record["src_mac"] = src_mac
    if dst_mac:
        record["dst_mac"] = dst_mac
    if src_ip:
        record["src_ip"] = src_ip
    if dst_ip:
        record["dst_ip"] = dst_ip
    if src_port is not None:
        record["src_port"] = src_port
    if dst_port is not None:
        record["dst_port"] = dst_port
    if tcp_flags:
        record["tcp_flags"] = tcp_flags
    if protocol_metadata:
        record["protocol_metadata"] = protocol_metadata

    return record
