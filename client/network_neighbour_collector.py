"""Collect and locally enrich useful network-neighbour entries.

The collector deliberately has no knowledge of sockets, server messages, or
database storage.  Each supported platform adapter produces the same small
record format so that reporting code stays platform-independent.
"""

import ipaddress
import json
import os
import platform
import re
import socket
import subprocess


MAC_ADDRESS_PATTERN = re.compile(r"^[0-9A-F]{2}(?::[0-9A-F]{2}){5}$")
LINUX_DYNAMIC_STATES = {"REACHABLE", "STALE", "DELAY", "PROBE"}
LINUX_STATIC_STATES = {"PERMANENT", "NOARP"}
DEFAULT_OUI_DATABASE_PATHS = (
    "/usr/share/arp-scan/ieee-oui.txt",
    "/usr/share/ieee-data/oui.txt",
)
DEFAULT_HOSTNAME_LOOKUP_LIMIT = 64


def normalise_mac_address(value):
    """Return an uppercase colon-delimited unicast MAC address, or ``None``."""
    if not isinstance(value, str):
        return None
    mac_address = value.strip().replace("-", ":").upper()
    if not MAC_ADDRESS_PATTERN.fullmatch(mac_address):
        return None

    first_octet = int(mac_address[:2], 16)
    if mac_address == "FF:FF:FF:FF:FF:FF" or first_octet & 1:
        return None
    return mac_address


def normalise_neighbour(ip_value, mac_value, entry_type, interface=None):
    """Return one safe normalized record, or ``None`` for irrelevant input."""
    try:
        ip_address = ipaddress.ip_address(str(ip_value).strip())
    except (ValueError, AttributeError):
        return None

    if (
        ip_address.version != 4
        or ip_address.is_multicast
        or ip_address.is_unspecified
        or ip_address.is_loopback
        or ip_address.is_reserved
    ):
        return None

    mac_address = normalise_mac_address(mac_value)
    if not mac_address or entry_type not in {"dynamic", "static"}:
        return None

    record = {
        "ip_address": str(ip_address),
        "mac_address": mac_address,
        "entry_type": entry_type,
    }
    if isinstance(interface, str) and interface.strip():
        record["interface"] = interface.strip()
    return record


def parse_linux_neighbours(output):
    """Parse ``ip -j neigh show`` JSON without raising on malformed rows."""
    try:
        entries = json.loads(output)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(entries, list):
        return []

    neighbours = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        raw_state = entry.get("state", "")
        states = (
            {str(state).upper() for state in raw_state}
            if isinstance(raw_state, list)
            else {str(raw_state).upper()}
        )
        if states & LINUX_DYNAMIC_STATES:
            entry_type = "dynamic"
        elif states & LINUX_STATIC_STATES:
            entry_type = "static"
        else:
            continue
        neighbour = normalise_neighbour(
            entry.get("dst"), entry.get("lladdr"), entry_type, entry.get("dev")
        )
        if neighbour:
            neighbours.append(neighbour)
    return _deduplicate(neighbours)


def parse_arp_output(output):
    """Parse common Windows/macOS ``arp`` formats, ignoring unknown lines."""
    if not isinstance(output, str):
        return []

    neighbours = []
    # Windows:  192.168.1.10  aa-bb-cc-dd-ee-ff  dynamic
    # macOS:    ? (192.168.1.10) at aa:bb:cc:dd:ee:ff on en0 ifscope [ethernet]
    windows_pattern = re.compile(
        r"^\s*(\d{1,3}(?:\.\d{1,3}){3})\s+([0-9a-f:-]{17})\s+"
        r"(dynamic|static)\b",
        re.IGNORECASE,
    )
    darwin_pattern = re.compile(
        r"\((\d{1,3}(?:\.\d{1,3}){3})\)\s+at\s+([0-9a-f:]{17})"
        r"(?:\s+on\s+(\S+))?",
        re.IGNORECASE,
    )
    for line in output.splitlines():
        match = windows_pattern.match(line)
        if match:
            neighbour = normalise_neighbour(
                match.group(1), match.group(2), match.group(3).lower()
            )
        else:
            match = darwin_pattern.search(line)
            neighbour = (
                normalise_neighbour(match.group(1), match.group(2), "dynamic", match.group(3))
                if match
                else None
            )
        if neighbour:
            neighbours.append(neighbour)
    return _deduplicate(neighbours)


def _deduplicate(neighbours):
    """Keep one entry per MAC/IP/interface tuple while preserving order."""
    unique_neighbours = []
    seen = set()
    for neighbour in neighbours:
        key = (
            neighbour["mac_address"],
            neighbour["ip_address"],
            neighbour.get("interface"),
        )
        if key not in seen:
            seen.add(key)
            unique_neighbours.append(neighbour)
    return unique_neighbours


def _normalise_metadata(value):
    """Return a bounded, display-safe metadata value or ``None``."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > 255 or any(character in "\r\n\x00" for character in value):
        return None
    return value


def get_mdns_hostname(ip_address):
    """Return a local mDNS hostname when Avahi is available."""
    try:
        result = subprocess.run(
            ["avahi-resolve-address", ip_address],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    parts = result.stdout.strip().split()
    return _normalise_metadata(parts[1]) if len(parts) >= 2 else None


def get_hostname(ip_address):
    """Resolve a neighbour from the reporting client's DNS, then local mDNS."""
    try:
        hostname, _, _ = socket.gethostbyaddr(ip_address)
        return _normalise_metadata(hostname)
    except (socket.herror, socket.gaierror, OSError):
        return get_mdns_hostname(ip_address)


def load_oui_database(path=None):
    """Load a client-local OUI database without making it a dependency.

    The parser accepts common arp-scan, IEEE, and Wireshark-manuf-style
    prefix lines. ``NETWORK_OUI_DATABASE`` may select a client-specific file.
    """
    paths = [path] if path else [
        os.getenv("NETWORK_OUI_DATABASE"),
        *DEFAULT_OUI_DATABASE_PATHS,
    ]
    vendors = {}
    for candidate in paths:
        if not candidate:
            continue
        try:
            with open(candidate, "r", encoding="utf-8") as file:
                for line in file:
                    line = line.strip()
                    if not line or line.startswith(("#", ";")):
                        continue
                    match = re.match(
                        r"^([0-9A-Fa-f]{2}(?::|-)?[0-9A-Fa-f]{2}(?::|-)?[0-9A-Fa-f]{2})"
                        r"(?:\s+\(hex\))?\s+(.+)$",
                        line,
                    )
                    if not match:
                        continue
                    prefix = re.sub(r"[^0-9A-Fa-f]", "", match.group(1)).upper()
                    vendor = _normalise_metadata(match.group(2))
                    if len(prefix) == 6 and vendor and prefix not in vendors:
                        vendors[prefix] = vendor
        except (FileNotFoundError, PermissionError, OSError, UnicodeDecodeError):
            continue
        if vendors:
            break
    return vendors


def get_vendor(mac_address, vendors):
    """Return the 24-bit-OUI vendor for a normalized MAC address."""
    if not isinstance(mac_address, str):
        return None
    return vendors.get(mac_address.replace(":", "").upper()[:6])


def _read_hostname_lookup_limit():
    value = os.getenv(
        "NETWORK_NEIGHBOUR_HOSTNAME_LOOKUP_LIMIT",
        str(DEFAULT_HOSTNAME_LOOKUP_LIMIT),
    )
    try:
        return max(0, int(value))
    except ValueError:
        return DEFAULT_HOSTNAME_LOOKUP_LIMIT


class NetworkNeighbourCollector:
    """Collect the local ARP/neighbour cache for the current client platform."""

    def __init__(
        self,
        system_name=None,
        command_runner=None,
        hostname_resolver=None,
        vendor_resolver=None,
    ):
        self.system_name = system_name or platform.system()
        self.command_runner = command_runner or self._run_command
        self.hostname_resolver = hostname_resolver or get_hostname
        self.vendor_resolver = vendor_resolver

    @staticmethod
    def _run_command(command):
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

    def collect(self, *, enrich=False):
        """Return normalized entries, optionally enriched on this client."""
        neighbours = []
        try:
            if self.system_name == "Linux":
                result = self.command_runner(["ip", "-j", "neigh", "show"])
                neighbours = parse_linux_neighbours(result.stdout) if result.returncode == 0 else []
            elif self.system_name == "Windows":
                result = self.command_runner(["arp", "-a"])
                neighbours = parse_arp_output(result.stdout) if result.returncode == 0 else []
            elif self.system_name == "Darwin":
                result = self.command_runner(["arp", "-an"])
                neighbours = parse_arp_output(result.stdout) if result.returncode == 0 else []
        except (OSError, subprocess.TimeoutExpired, AttributeError):
            return []
        return self.enrich(neighbours) if enrich else neighbours

    def enrich(self, neighbours):
        """Resolve metadata locally before the report leaves this client."""
        if not neighbours:
            return []
        vendors = load_oui_database()
        vendor_resolver = self.vendor_resolver or (
            lambda mac_address: get_vendor(mac_address, vendors)
        )
        hostname_lookup_limit = _read_hostname_lookup_limit()
        enriched_neighbours = []
        for index, neighbour in enumerate(neighbours):
            enriched = dict(neighbour)
            if index < hostname_lookup_limit:
                try:
                    hostname = _normalise_metadata(
                        self.hostname_resolver(neighbour["ip_address"])
                    )
                except (OSError, ValueError):
                    hostname = None
                if hostname:
                    enriched["hostname"] = hostname
            try:
                vendor = _normalise_metadata(vendor_resolver(neighbour["mac_address"]))
            except (OSError, ValueError):
                vendor = None
            if vendor:
                enriched["vendor"] = vendor
            enriched_neighbours.append(enriched)
        return enriched_neighbours
