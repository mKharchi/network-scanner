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
import time
from datetime import datetime, timezone
import oui
from neighbourhood import merge_neighbourhood_observations, normalise_neighbourhood_observation

MAC_ADDRESS_PATTERN = re.compile(r"^[0-9A-F]{2}(?::[0-9A-F]{2}){5}$")
LINUX_DYNAMIC_STATES = {"REACHABLE", "STALE", "DELAY", "PROBE"}
LINUX_STATIC_STATES = {"PERMANENT", "NOARP"}
DEFAULT_OUI_DATABASE_PATHS = (
    "/usr/share/arp-scan/ieee-oui.txt",
    "/usr/share/ieee-data/oui.txt",
)
DEFAULT_HOSTNAME_LOOKUP_LIMIT = 64


def _scan_log(message):
    """Print concise client-side scan lifecycle telemetry."""
    print(f"[NETWORK SCAN] {message}", flush=True)


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


def normalise_neighbour(ip_value, mac_value, entry_type, interface=None, *, rssi=None, switch_port=None):
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
    if rssi is not None:
        try:
            record["rssi"] = int(rssi)
        except (TypeError, ValueError):
            pass
    if isinstance(switch_port, str) and switch_port.strip():
        record["switch_port"] = switch_port.strip()
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
        r"^\s*(\d{1,3}(?:\.\d{1,3}){3})\s+([0-9a-f:-]{17})\s+" r"(dynamic|static)\b",
        re.IGNORECASE,
    )
    darwin_pattern = re.compile(
        r"\((\d{1,3}(?:\.\d{1,3}){3})\)\s+at\s+([0-9a-f:]{17})" r"(?:\s+on\s+(\S+))?",
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
                normalise_neighbour(
                    match.group(1), match.group(2), "dynamic", match.group(3)
                )
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
    if (
        not value
        or len(value) > 255
        or any(character in "\r\n\x00" for character in value)
    ):
        return None
    return value


def get_mdns_hostname(ip_address):
    """Return a local mDNS hostname when Avahi is available."""
    try:
        result = subprocess.run(
            ["avahi-resolve-address", ip_address],
            capture_output=True,
            text=True,
            timeout=0.5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    parts = result.stdout.strip().split()
    return _normalise_metadata(parts[1]) if len(parts) >= 2 else None


def get_hostname(ip_address, timeout=0.5):
    """Resolve a neighbour from the reporting client's DNS, then local mDNS."""
    orig_timeout = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(timeout)
        hostname, _, _ = socket.gethostbyaddr(ip_address)
        return _normalise_metadata(hostname)
    except (socket.herror, socket.gaierror, socket.timeout, OSError):
        return get_mdns_hostname(ip_address)
    finally:
        socket.setdefaulttimeout(orig_timeout)


def load_oui_database_linux(path=None):
    """Load the OUI database on Linux."""
    paths = []

    if path:
        paths.append(path)

    env_path = os.getenv("NETWORK_OUI_DATABASE")
    if env_path:
        paths.append(env_path)

    paths.extend(
        [
            "/usr/share/arp-scan/ieee-oui.txt",
            "/usr/share/ieee-data/oui.txt",
            "/usr/share/wireshark/manuf",
            "/usr/share/wireshark/manuf.txt",
        ]
    )

    return _load_oui_database_from_paths(paths)


def load_oui_database_windows(path=None):
    """Load the OUI database on Windows."""
    paths = []

    if path:
        paths.append(path)

    env_path = os.getenv("NETWORK_OUI_DATABASE")
    if env_path:
        paths.append(env_path)

    # Common locations where an OUI/manufacturer database
    # may exist if installed with a networking tool.
    paths.extend(
        [
            r"C:\Program Files\Wireshark\manuf",
            r"C:\Program Files\Wireshark\manuf.txt",
            r"C:\Program Files (x86)\Wireshark\manuf",
            r"C:\Program Files (x86)\Wireshark\manuf.txt",
        ]
    )

    return _load_oui_database_from_paths(paths)


def _load_oui_database_from_paths(paths):
    """Load an OUI database from the first usable database file."""
    for candidate in paths:
        if not candidate:
            continue

        print(f"[OUI] Checking: {candidate}")

        if not os.path.isfile(candidate):
            print("[OUI] File not found")
            continue

        print("[OUI] File found!")

        vendors = {}

        try:
            with open(candidate, "r", encoding="utf-8", errors="ignore") as file:
                for line in file:
                    line = line.strip()

                    if not line or line.startswith(("#", ";")):
                        continue

                    # arp-scan / IEEE style:
                    #
                    # 001122    (hex)    Example Corporation
                    #
                    # 00:11:22    Example Corporation
                    #
                    # Wireshark manuf style:
                    #
                    # 001122    Example_Corp    Example Corporation
                    #

                    match = re.match(
                        r"^([0-9A-Fa-f]{2}(?::|-)?"
                        r"[0-9A-Fa-f]{2}(?::|-)?"
                        r"[0-9A-Fa-f]{2})"
                        r"(?:\s+\(hex\))?"
                        r"\s+(.+)$",
                        line,
                    )

                    if not match:
                        continue

                    prefix = re.sub(r"[^0-9A-Fa-f]", "", match.group(1)).upper()

                    vendor = _normalise_metadata(match.group(2))

                    if len(prefix) == 6 and vendor:
                        vendors.setdefault(prefix, vendor)

            print(f"[OUI] Loaded {len(vendors)} entries")

            if vendors:
                print(f"[OUI] Using database: {candidate}")
                return vendors

            print("[OUI] File was found but no entries were parsed")

        except (PermissionError, OSError, UnicodeDecodeError) as exc:
            print(f"[OUI] Could not read file: {exc}")

    print("[OUI] No usable OUI database found")
    return {}


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


def _is_usable_scan_address(value):
    """Return whether an IPv4 address can identify a LAN worth scanning."""
    try:
        address = ipaddress.ip_address(str(value).strip())
    except (ValueError, AttributeError):
        return False

    return (
        address.version == 4
        and not address.is_loopback
        and not address.is_link_local
        and not address.is_multicast
        and not address.is_unspecified
        and not address.is_reserved
    )


def _default_route_source_ip():
    """Return the IPv4 source selected by the operating system's default route."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # UDP connect does not transmit traffic; it only asks the OS to select
        # the local source address for the default route.
        probe.connect(("8.8.8.8", 80))
        source_ip = probe.getsockname()[0]
        return source_ip if _is_usable_scan_address(source_ip) else None
    except OSError:
        return None
    finally:
        probe.close()


def _select_interface_address(
    addrs_by_iface, *, preferred_ip=None, interface_name=None, interface_stats=None
):
    """Choose a usable IPv4 interface, favouring the active default route."""
    candidates = []
    for iface_name, addresses in addrs_by_iface.items():
        if interface_name and iface_name != interface_name:
            continue
        for address in addresses:
            if getattr(address, "family", None) != socket.AF_INET:
                continue
            local_ip = getattr(address, "address", None)
            netmask = getattr(address, "netmask", None)
            if not _is_usable_scan_address(local_ip) or not netmask:
                continue
            try:
                network = ipaddress.IPv4Network(f"{local_ip}/{netmask}", strict=False)
            except ValueError:
                continue
            stats = (interface_stats or {}).get(iface_name)
            is_up = bool(getattr(stats, "isup", True))
            ip_address = ipaddress.ip_address(local_ip)
            score = (
                int(local_ip == preferred_ip),
                int(is_up),
                int(ip_address.is_private),
            )
            candidates.append((score, iface_name, local_ip, network))

    if not candidates:
        return None
    _, iface_name, local_ip, network = max(candidates, key=lambda candidate: candidate[0])
    return iface_name, local_ip, network


def get_local_network(command_runner=None):
    """Determine the active local IPv4 interface, address, and subnet CIDR dynamically."""
    interface_override = os.getenv("NETWORK_SCAN_INTERFACE")
    subnet_override = os.getenv("NETWORK_SCAN_SUBNET")
    command_runner = command_runner or subprocess.run

    interface = interface_override
    local_ip = None
    prefix_length = None
    detected_network = None
    gateway = None

    if platform.system() == "Linux":
        try:
            res = command_runner(
                ["ip", "-j", "route", "show", "default"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            if res.returncode == 0 and res.stdout:
                routes = json.loads(res.stdout)
                default_route = next(
                    (r for r in routes if isinstance(r, dict) and r.get("dst") == "default" and r.get("dev")),
                    None,
                )
                if default_route:
                    if not interface:
                        interface = default_route["dev"]
                    gateway = default_route.get("gateway")
        except Exception:
            pass

        if interface:
            try:
                res = command_runner(
                    ["ip", "-j", "-4", "addr", "show", "dev", interface],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    check=False,
                )
                if res.returncode == 0 and res.stdout:
                    addrs = json.loads(res.stdout)
                    interface_data = next((e for e in addrs if isinstance(e, dict)), None)
                    address_info = interface_data.get("addr_info", []) if interface_data else []
                    ipv4_address = next(
                        (
                            a for a in address_info
                            if isinstance(a, dict)
                            and a.get("family") == "inet"
                            and _is_usable_scan_address(a.get("local"))
                        ),
                        None,
                    )
                    if ipv4_address:
                        local_ip = ipv4_address.get("local")
                        prefix_length = ipv4_address.get("prefixlen")
                        if local_ip and prefix_length:
                            detected_network = ipaddress.ip_interface(f"{local_ip}/{prefix_length}").network
            except Exception:
                pass

        # A default route can point to a disconnected adapter with only an
        # APIPA address. Let the cross-platform fallback choose a real LAN
        # interface instead of scanning 169.254.0.0/16.
        if not detected_network and not interface_override:
            interface = None

    # Fallback using psutil / socket if Linux ip command was not used or on other platforms
    if not detected_network:
        try:
            import psutil
            addrs_by_iface = psutil.net_if_addrs()
            selected = _select_interface_address(
                addrs_by_iface,
                preferred_ip=_default_route_source_ip(),
                interface_name=interface,
                interface_stats=psutil.net_if_stats(),
            )
            if selected:
                interface, local_ip, detected_network = selected
        except Exception:
            pass

    if subnet_override:
        try:
            network = ipaddress.ip_network(subnet_override, strict=False)
            if network.version != 4:
                network = detected_network
        except Exception:
            network = detected_network
    else:
        network = detected_network

    if not interface or not local_ip or not network:
        _scan_log("No usable IPv4 network was detected; active ARP scan skipped.")
        return None

    context = {
        "interface": interface,
        "local_ip": str(local_ip) if local_ip else None,
        "network": str(network),
        "gateway": gateway,
    }
    _scan_log(
        "Network detected: "
        f"interface={context['interface']} local_ip={context['local_ip']} "
        f"network={context['network']} gateway={context['gateway'] or 'unknown'}."
    )
    return context


def _default_arp_runner(network_cidr, iface, timeout_sec):
    """Execute Scapy ARP broadcast scan if raw packet capture/send is permitted."""
    try:
        from scapy.all import ARP, Ether, srp
        answered, _ = srp(
            Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(pdst=network_cidr),
            iface=iface,
            timeout=timeout_sec,
            verbose=False,
        )
        return [received for _, received in answered]
    except (ImportError, PermissionError, OSError):
        return []


def discover_active_arp(context=None, *, command_runner=None, arp_runner=None, timeout_seconds=2.5):
    """Perform an active ARP scan of the dynamically discovered local subnet."""
    context = context or get_local_network(command_runner=command_runner)
    if not context or not context.get("network") or not context.get("interface"):
        return []

    runner = arp_runner or _default_arp_runner
    started_at = time.monotonic()
    _scan_log(
        f"Starting active ARP scan: network={context['network']} "
        f"interface={context['interface']} response_timeout={timeout_seconds}s."
    )
    try:
        responses = runner(context["network"], context["interface"], timeout_seconds)
    except Exception as error:
        _scan_log(f"Active ARP scan failed: {error}")
        return []

    devices = []
    seen_macs = set()
    for response in responses or []:
        try:
            ip_val = getattr(response, "psrc", None) or (response.get("psrc") if isinstance(response, dict) else None)
            mac_val = getattr(response, "hwsrc", None) or (response.get("hwsrc") if isinstance(response, dict) else None)
        except Exception:
            continue

        neighbour = normalise_neighbour(ip_val, mac_val, "dynamic", context["interface"])
        if not neighbour:
            continue
        if neighbour["mac_address"] in seen_macs:
            continue
        seen_macs.add(neighbour["mac_address"])
        devices.append(neighbour)

    _scan_log(
        f"Active ARP scan completed: responses={len(responses or [])} "
        f"unique_devices={len(devices)} elapsed={time.monotonic() - started_at:.1f}s."
    )
    return devices


def get_wifi_rssi_map(command_runner=None):
    """Attempt to collect MAC-to-RSSI mappings from wireless interfaces where available."""
    runner = command_runner or subprocess.run
    rssi_map = {}
    system = platform.system()
    try:
        if system == "Linux":
            try:
                res = runner(["iw", "dev"], capture_output=True, text=True, timeout=2, check=False)
                if res.returncode == 0 and res.stdout:
                    ifaces = re.findall(r"Interface\s+([a-zA-Z0-9_-]+)", res.stdout)
                    for iface in ifaces:
                        dump_res = runner(["iw", "dev", iface, "station", "dump"], capture_output=True, text=True, timeout=2, check=False)
                        if dump_res.returncode == 0 and dump_res.stdout:
                            curr_mac = None
                            for line in dump_res.stdout.splitlines():
                                st_match = re.match(r"Station\s+([0-9a-fA-F:]{17})", line)
                                if st_match:
                                    curr_mac = normalise_mac_address(st_match.group(1))
                                elif curr_mac and "signal:" in line:
                                    sig_match = re.search(r"signal:\s*(-?\d+)", line)
                                    if sig_match:
                                        rssi_map[curr_mac] = int(sig_match.group(1))
                                elif curr_mac and "signal avg:" in line and curr_mac not in rssi_map:
                                    sig_match = re.search(r"signal avg:\s*(-?\d+)", line)
                                    if sig_match:
                                        rssi_map[curr_mac] = int(sig_match.group(1))
                        link_res = runner(["iw", "dev", iface, "link"], capture_output=True, text=True, timeout=2, check=False)
                        if link_res.returncode == 0 and link_res.stdout:
                            bssid_match = re.search(r"Connected to\s+([0-9a-fA-F:]{17})", link_res.stdout)
                            sig_match = re.search(r"signal:\s*(-?\d+)", link_res.stdout)
                            if bssid_match and sig_match:
                                bssid = normalise_mac_address(bssid_match.group(1))
                                if bssid:
                                    rssi_map[bssid] = int(sig_match.group(1))
            except Exception:
                pass
        elif system == "Windows":
            try:
                res = runner(["netsh", "wlan", "show", "interfaces"], capture_output=True, text=True, timeout=3, check=False)
                if res.returncode == 0 and res.stdout:
                    bssid = None
                    signal_pct = None
                    for line in res.stdout.splitlines():
                        if "BSSID" in line:
                            parts = line.split(":", 1)
                            if len(parts) > 1:
                                bssid = normalise_mac_address(parts[1].strip())
                        elif "Signal" in line:
                            parts = line.split(":", 1)
                            if len(parts) > 1:
                                match = re.search(r"(\d+)%", parts[1])
                                if match:
                                    signal_pct = int(match.group(1))
                    if bssid and signal_pct is not None:
                        rssi_map[bssid] = int((signal_pct / 2.0) - 100)
            except Exception:
                pass
    except Exception:
        pass
    return rssi_map


def merge_neighbours_by_mac(passive_neighbours, active_neighbours):
    """Merge passive kernel neighbour entries and active ARP scan results by MAC address."""
    by_mac = {}

    for entry in passive_neighbours or []:
        mac = normalise_mac_address(entry.get("mac_address"))
        if not mac:
            continue
        by_mac[mac] = dict(entry)
        by_mac[mac]["mac_address"] = mac

    for entry in active_neighbours or []:
        mac = normalise_mac_address(entry.get("mac_address"))
        if not mac:
            continue
        existing = by_mac.get(mac)
        if existing is None:
            by_mac[mac] = dict(entry)
            by_mac[mac]["mac_address"] = mac
        else:
            if entry.get("ip_address"):
                existing["ip_address"] = entry["ip_address"]
            if entry.get("interface") and not existing.get("interface"):
                existing["interface"] = entry["interface"]
            if entry.get("hostname") and not existing.get("hostname"):
                existing["hostname"] = entry["hostname"]
            if entry.get("vendor") and not existing.get("vendor"):
                existing["vendor"] = entry["vendor"]
            if entry.get("rssi") is not None:
                existing["rssi"] = entry["rssi"]
            if entry.get("switch_port") and not existing.get("switch_port"):
                existing["switch_port"] = entry["switch_port"]

    return list(by_mac.values())


class NetworkNeighbourCollector:
    """Collect the local ARP/neighbour cache and active ARP scan for the client platform."""

    def __init__(
        self,
        system_name=None,
        command_runner=None,
        hostname_resolver=None,
        vendor_resolver=None,
        arp_runner=None,
        wifi_rssi_fetcher=None,
    ):
        self.system_name = system_name or platform.system()
        self.command_runner = command_runner or self._run_command
        self.hostname_resolver = hostname_resolver or get_hostname
        self.vendor_resolver = vendor_resolver
        self.arp_runner = arp_runner
        self.wifi_rssi_fetcher = wifi_rssi_fetcher or get_wifi_rssi_map

    @staticmethod
    def _run_command(command):
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

    def collect(self, *, enrich=False, active_scan=False):
        """Return normalized entries, optionally merging active ARP scan and enriching."""
        started_at = time.monotonic()
        _scan_log(
            f"Collection started: platform={self.system_name} active_scan={active_scan} "
            f"enrich={enrich}."
        )
        neighbours = []
        try:
            if self.system_name == "Linux":
                result = self.command_runner(["ip", "-j", "neigh", "show"])
                neighbours = (
                    parse_linux_neighbours(result.stdout)
                    if result.returncode == 0
                    else []
                )
            elif self.system_name == "Windows":
                result = self.command_runner(["arp", "-a"])
                neighbours = (
                    parse_arp_output(result.stdout) if result.returncode == 0 else []
                )
            elif self.system_name == "Darwin":
                result = self.command_runner(["arp", "-an"])
                neighbours = (
                    parse_arp_output(result.stdout) if result.returncode == 0 else []
                )
        except (OSError, subprocess.TimeoutExpired, AttributeError) as error:
            _scan_log(f"Could not read the local neighbour cache: {error}")
            neighbours = []

        _scan_log(f"Passive neighbour cache collected: entries={len(neighbours)}.")

        if active_scan:
            try:
                active_entries = discover_active_arp(
                    command_runner=self.command_runner,
                    arp_runner=self.arp_runner,
                )
                neighbours = merge_neighbours_by_mac(neighbours, active_entries)
                _scan_log(
                    f"Merged active ARP results: active_entries={len(active_entries)} "
                    f"combined_entries={len(neighbours)}."
                )
            except Exception as error:
                _scan_log(f"Active ARP collection step failed: {error}")

        result = self.enrich(neighbours) if enrich else neighbours
        observed_at = datetime.now(timezone.utc).isoformat()
        result = merge_neighbourhood_observations(
            normalise_neighbourhood_observation(
                neighbour, source="arp", observed_at=observed_at
            )
            for neighbour in result
        )
        _scan_log(
            f"Collection completed: devices={len(result)} "
            f"elapsed={time.monotonic() - started_at:.1f}s."
        )
        return result

    def enrich(self, neighbours):
        """Resolve metadata locally before the report leaves this client."""
        if not neighbours:
            return []
        started_at = time.monotonic()
        # Prefer a user-provided resolver; otherwise use the bundled IEEE CSVs.
        vendor_resolver = self.vendor_resolver
        if vendor_resolver is None:
            try:
                database = oui.load_oui_database()
                vendor_resolver = lambda mac_address: oui.get_vendor(
                    mac_address, database
                )
            except Exception:
                vendor_resolver = lambda mac_address: None
        hostname_lookup_limit = _read_hostname_lookup_limit()
        wifi_rssi_map = {}
        if self.wifi_rssi_fetcher:
            try:
                wifi_rssi_map = self.wifi_rssi_fetcher(self.command_runner) or {}
            except Exception:
                wifi_rssi_map = {}
        _scan_log(
            f"Enrichment started: devices={len(neighbours)} "
            f"hostname_lookup_limit={hostname_lookup_limit}."
        )
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
            mac = neighbour.get("mac_address")
            if mac and mac in wifi_rssi_map and neighbour.get("rssi") is None:
                enriched["rssi"] = wifi_rssi_map[mac]
            enriched_neighbours.append(enriched)
        _scan_log(
            f"Enrichment completed: devices={len(enriched_neighbours)} "
            f"elapsed={time.monotonic() - started_at:.1f}s."
        )
        return enriched_neighbours
