"""Network-discovery helpers and client-report aggregation.

The legacy server-local ARP and OS-discovery helpers remain available for
compatibility, but the running server does not invoke them.  Network presence
is discovered by monitoring clients and this module aggregates their reports.
"""

import ipaddress
import json
import logging
import os
import re
import socket
import subprocess
import xml.etree.ElementTree as element_tree
from datetime import datetime, timezone

from server_components.network_scan_storage import load_latest_network_scan, store_network_scan
from server_components.network_device_classification import classify_devices
from server_components.network_device_storage import (
    get_recent_client_neighbour_observations,
)


LOGGER = logging.getLogger(__name__)
DEFAULT_OUI_DATABASE = "/usr/share/arp-scan/ieee-oui.txt"
DEFAULT_ARP_TIMEOUT_SECONDS = 3.0
DEFAULT_NMAP_TIMEOUT_SECONDS = 20
DEFAULT_OS_TARGET_LIMIT = 3


class NetworkDiscoveryError(RuntimeError):
    """Raised when the server cannot safely perform LAN discovery."""


def configure_logging():
    """Make discovery logs visible in both server and standalone execution."""
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="[%(levelname)s] %(asctime)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger().setLevel(level)


def _read_timeout():
    value = os.getenv("NETWORK_SCAN_TIMEOUT_SECONDS", str(DEFAULT_ARP_TIMEOUT_SECONDS))
    try:
        return max(0.1, float(value))
    except ValueError:
        LOGGER.warning(
            "Invalid NETWORK_SCAN_TIMEOUT_SECONDS=%r; using %s.",
            value,
            DEFAULT_ARP_TIMEOUT_SECONDS,
        )
        return DEFAULT_ARP_TIMEOUT_SECONDS


def _run_ip_command(arguments):
    try:
        LOGGER.debug("Running command: ip -j %s", " ".join(arguments))
        result = subprocess.run(
            ["ip", "-j", *arguments],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except FileNotFoundError as error:
        raise NetworkDiscoveryError("The Linux 'ip' command is not available.") from error
    except subprocess.TimeoutExpired as error:
        raise NetworkDiscoveryError(
            "Timed out while reading the local network configuration."
        ) from error

    if result.returncode != 0:
        message = result.stderr.strip() or "unknown error"
        raise NetworkDiscoveryError(
            f"Unable to read the local network configuration: {message}"
        )

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise NetworkDiscoveryError(
            "The local network configuration returned invalid JSON."
        ) from error


def get_local_network():
    """Return the active IPv4 interface, address, subnet, and default gateway.

    ``NETWORK_SCAN_INTERFACE`` and ``NETWORK_SCAN_SUBNET`` can be used for a
    deliberate server-side override. The subnet is validated before it is
    passed to the ARP scanner.
    """
    interface_override = os.getenv("NETWORK_SCAN_INTERFACE")
    subnet_override = os.getenv("NETWORK_SCAN_SUBNET")
    LOGGER.info("Determining the local IPv4 network configuration.")
    routes = _run_ip_command(["route", "show", "default"])
    if not isinstance(routes, list):
        raise NetworkDiscoveryError("The local route configuration is malformed.")

    default_route = next(
        (
            route
            for route in routes
            if isinstance(route, dict)
            and route.get("dst") == "default"
            and route.get("dev")
        ),
        None,
    )
    if not default_route and not interface_override:
        raise NetworkDiscoveryError("No active default IPv4 route was found.")

    interface = interface_override or default_route["dev"]
    addresses = _run_ip_command(["-4", "addr", "show", "dev", interface])
    if not isinstance(addresses, list):
        raise NetworkDiscoveryError("The local address configuration is malformed.")
    interface_data = next(
        (entry for entry in addresses if isinstance(entry, dict)),
        None,
    )
    address_info = interface_data.get("addr_info", []) if interface_data else []
    ipv4_address = next(
        (
            address
            for address in address_info
            if isinstance(address, dict)
            and address.get("family") == "inet"
            and address.get("scope") != "host"
        ),
        None,
    )
    if not ipv4_address:
        raise NetworkDiscoveryError(
            f"Interface {interface!r} has no usable IPv4 address."
        )

    local_ip = ipv4_address.get("local")
    prefix_length = ipv4_address.get("prefixlen")
    try:
        detected_network = ipaddress.ip_interface(
            f"{local_ip}/{prefix_length}"
        ).network
    except ValueError as error:
        raise NetworkDiscoveryError(
            f"Interface {interface!r} has an invalid IPv4 configuration."
        ) from error

    if subnet_override:
        try:
            network = ipaddress.ip_network(subnet_override, strict=False)
        except ValueError as error:
            raise NetworkDiscoveryError(
                "NETWORK_SCAN_SUBNET must be a valid IPv4 CIDR."
            ) from error
        if network.version != 4:
            raise NetworkDiscoveryError("NETWORK_SCAN_SUBNET must be an IPv4 CIDR.")
    else:
        network = detected_network
    context = {
        "interface": interface,
        "local_ip": str(local_ip),
        "network": str(network),
        "gateway": (default_route or {}).get("gateway"),
    }
    LOGGER.info(
        "Local network detected: interface=%s local_ip=%s network=%s gateway=%s",
        context["interface"],
        context["local_ip"],
        context["network"],
        context["gateway"] or "unknown",
    )
    return context


def get_mdns_hostname(ip_address):
    """Return an mDNS hostname when Avahi is available, otherwise ``None``."""
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
    return _normalise_hostname(parts[1]) if len(parts) >= 2 else None


def _normalise_hostname(hostname):
    """Decode Avahi octal escapes and reject empty/control-character names."""
    if not isinstance(hostname, str):
        return None

    hostname = re.sub(
        r"\\([0-7]{3})",
        lambda match: chr(int(match.group(1), 8)),
        hostname,
    ).strip()
    if not hostname or any(character in "\r\n\x00" for character in hostname):
        return None
    return hostname


def get_hostname(ip_address):
    """Use reverse DNS first, then mDNS. Hostname discovery is optional."""
    try:
        hostname, _, _ = socket.gethostbyaddr(ip_address)
        return _normalise_hostname(hostname)
    except (socket.herror, socket.gaierror, OSError):
        return get_mdns_hostname(ip_address)


def load_oui_database(path=None):
    """Load locally available 24-bit OUI entries without making them required."""
    vendors = {}
    path = path or os.getenv("NETWORK_SCAN_OUI_DATABASE", DEFAULT_OUI_DATABASE)
    try:
        with open(path, "r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(maxsplit=1)
                if len(parts) == 2 and len(parts[0]) == 6:
                    vendors[parts[0].upper()] = parts[1].strip()
    except (FileNotFoundError, PermissionError, OSError, UnicodeDecodeError) as error:
        LOGGER.info("OUI vendor lookup is unavailable: %s", error)
    return vendors


def get_vendor(mac_address, vendors):
    if not isinstance(mac_address, str):
        return None
    prefix = mac_address.replace(":", "").upper()[:6]
    return vendors.get(prefix)


def _normalise_mac_address(mac_address):
    if not isinstance(mac_address, str):
        return None
    compact = mac_address.replace(":", "").replace("-", "").upper()
    if len(compact) != 12 or any(char not in "0123456789ABCDEF" for char in compact):
        return None
    return ":".join(compact[index:index + 2] for index in range(0, 12, 2))


def _arp_discover(network, interface, timeout_seconds):
    """Return Scapy ARP response packets, loading the dependency on demand."""
    try:
        from scapy.all import ARP, Ether, srp
    except ImportError as error:
        raise NetworkDiscoveryError(
            "ARP discovery requires the 'scapy' server dependency."
        ) from error

    try:
        LOGGER.info(
            "Starting ARP discovery: interface=%s network=%s timeout=%ss",
            interface,
            network,
            timeout_seconds,
        )
        answered, _ = srp(
            Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(pdst=network),
            iface=interface,
            timeout=timeout_seconds,
            verbose=False,
        )
        responses = [received for _, received in answered]
        LOGGER.info("ARP discovery received %d response(s).", len(responses))
        return responses
    except PermissionError as error:
        raise NetworkDiscoveryError(
            "ARP discovery requires permission to send raw packets."
        ) from error
    except OSError as error:
        raise NetworkDiscoveryError(
            f"ARP discovery failed on {interface!r}: {error}"
        ) from error


def discover_arp_devices(context=None, *, arp_discoverer=None):
    """Return normalized IP/MAC records from ARP responses, without enrichment."""
    context = context or get_local_network()
    arp_discoverer = arp_discoverer or _arp_discover

    responses = arp_discoverer(
        context["network"], context["interface"], _read_timeout()
    )
    LOGGER.info("Normalizing %d ARP response(s).", len(responses))
    devices = []
    seen_macs = set()
    for response in responses:
        try:
            ip_address = str(ipaddress.ip_address(response.psrc))
            mac_address = _normalise_mac_address(response.hwsrc)
        except (AttributeError, ValueError):
            LOGGER.warning("Ignoring malformed ARP response: %r", response)
            continue
        if not mac_address or mac_address in seen_macs:
            continue
        seen_macs.add(mac_address)

        devices.append(
            {
                "ip_address": ip_address,
                "mac_address": mac_address,
                "hostname": None,
                "vendor": None,
                "os_name": None,
                "os_family": None,
                "os_confidence": None,
            }
        )
    LOGGER.info("ARP discovery produced %d unique device(s).", len(devices))
    return devices


def _read_os_target_limit():
    value = os.getenv("NETWORK_SCAN_OS_TARGET_LIMIT", str(DEFAULT_OS_TARGET_LIMIT))
    try:
        return max(1, int(value))
    except ValueError:
        LOGGER.warning(
            "Invalid NETWORK_SCAN_OS_TARGET_LIMIT=%r; using %s.",
            value,
            DEFAULT_OS_TARGET_LIMIT,
        )
        return DEFAULT_OS_TARGET_LIMIT


def get_os_detection_targets():
    """Return explicitly configured IPv4 targets, capped for safe execution."""
    targets = []
    for value in os.getenv("NETWORK_SCAN_OS_TARGETS", "").split(","):
        value = value.strip()
        if not value:
            continue
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            LOGGER.warning("Ignoring invalid NETWORK_SCAN_OS_TARGETS entry: %r", value)
            continue
        if address.version == 4 and str(address) not in targets:
            targets.append(str(address))
    return targets[:_read_os_target_limit()]


def _empty_os_result():
    return {"os_name": None, "os_family": None, "os_confidence": None}


def detect_os(ip_address):
    """Return the best Nmap OS match for one explicit IPv4 target.

    Nmap is optional. A missing executable, lack of privileges, timeout, or an
    uncertain fingerprint returns an unknown OS instead of failing the scan.
    """
    try:
        address = ipaddress.ip_address(ip_address)
    except ValueError:
        LOGGER.warning("Skipping OS detection for invalid IP address %r", ip_address)
        return _empty_os_result()
    if address.version != 4:
        return _empty_os_result()

    try:
        LOGGER.info("Starting opt-in OS detection for %s.", address)
        result = subprocess.run(
            [
                "nmap",
                "-O",
                "--osscan-guess",
                "-PE",
                "-PS443",
                "--host-timeout",
                "15s",
                "-oX",
                "-",
                str(address),
            ],
            capture_output=True,
            text=True,
            timeout=DEFAULT_NMAP_TIMEOUT_SECONDS,
            check=False,
        )
    except (FileNotFoundError, PermissionError, OSError) as error:
        LOGGER.info("OS detection is unavailable for %s: %s", address, error)
        return _empty_os_result()
    except subprocess.TimeoutExpired:
        LOGGER.info("OS detection timed out for %s.", address)
        return _empty_os_result()

    if result.returncode != 0:
        LOGGER.info("OS detection failed for %s: %s", address, result.stderr.strip())
        return _empty_os_result()

    try:
        matches = element_tree.fromstring(result.stdout).findall("./host/os/osmatch")
    except element_tree.ParseError:
        LOGGER.info("OS detection returned malformed XML for %s.", address)
        return _empty_os_result()
    if not matches:
        LOGGER.info("OS detection found no fingerprint for %s.", address)
        return _empty_os_result()

    def accuracy(match):
        try:
            return int(match.get("accuracy", "0"))
        except ValueError:
            return 0

    best_match = max(matches, key=accuracy)
    os_class = best_match.find("osclass")
    confidence = min(100, max(0, accuracy(best_match))) / 100
    result = {
        "os_name": best_match.get("name") or None,
        "os_family": os_class.get("osfamily") if os_class is not None else None,
        "os_confidence": confidence,
    }
    LOGGER.info(
        "OS detection completed for %s: name=%s confidence=%s",
        address,
        result["os_name"] or "unknown",
        result["os_confidence"],
    )
    return result


def enrich_devices(
    devices,
    *,
    hostname_resolver=None,
    vendor_resolver=None,
    os_detector=None,
    os_detection_targets=None,
):
    """Add optional hostname, vendor, and explicitly requested OS information."""
    hostname_resolver = hostname_resolver or get_hostname
    if vendor_resolver is None:
        vendors = load_oui_database()
        vendor_resolver = lambda mac_address: get_vendor(mac_address, vendors)
    os_detector = os_detector or detect_os
    os_detection_targets = set(
        os_detection_targets
        if os_detection_targets is not None
        else get_os_detection_targets()
    )
    discovered_ips = {device.get("ip_address") for device in devices}
    unavailable_targets = os_detection_targets - discovered_ips
    for target in sorted(unavailable_targets):
        LOGGER.warning("Skipping OS detection target not found by ARP: %s", target)

    enriched_devices = []
    for device in devices:
        enriched_device = dict(device)
        ip_address = enriched_device.get("ip_address")
        mac_address = enriched_device.get("mac_address")
        if not enriched_device.get("hostname"):
            try:
                enriched_device["hostname"] = hostname_resolver(ip_address) or None
            except Exception as error:
                LOGGER.info("Hostname lookup failed for %s: %s", ip_address, error)
                enriched_device["hostname"] = None
        try:
            enriched_device["vendor"] = vendor_resolver(mac_address) or None
        except Exception as error:
            LOGGER.info("Vendor lookup failed for %s: %s", mac_address, error)
            enriched_device["vendor"] = None

        if enriched_device.get("os_name"):
            # The registered client agent is the preferred OS source.
            pass
        elif ip_address in os_detection_targets:
            try:
                enriched_device.update(os_detector(ip_address))
            except Exception as error:
                LOGGER.info("OS detection failed for %s: %s", ip_address, error)
                enriched_device.update(_empty_os_result())
        else:
            enriched_device.update(_empty_os_result())
        enriched_devices.append(enriched_device)

    LOGGER.info("Device enrichment completed for %d device(s).", len(enriched_devices))
    return enriched_devices


def discover_devices(
    context=None,
    *,
    arp_discoverer=None,
    hostname_resolver=None,
    vendor_resolver=None,
):
    """Compatibility helper that runs discovery and non-OS enrichment together."""
    return enrich_devices(
        discover_arp_devices(context, arp_discoverer=arp_discoverer),
        hostname_resolver=hostname_resolver,
        vendor_resolver=vendor_resolver,
        os_detection_targets=[],
    )


def _merge_missing_device_details(target, candidate):
    """Fill absent device details without replacing a direct observation."""
    for field in (
        "hostname",
        "vendor",
        "os_name",
        "os_family",
        "os_confidence",
        "classification",
        "is_managed",
        "managed_client",
    ):
        if target.get(field) is None and candidate.get(field) is not None:
            target[field] = candidate[field]


def _append_observation_sources(target, sources):
    for source in sources:
        if isinstance(source, dict) and source not in target["observation_sources"]:
            target["observation_sources"].append(source)


def _append_observed_ip(target, ip_address):
    """Preserve every valid address observed for one MAC-deduplicated device."""
    if not isinstance(ip_address, str) or not ip_address:
        return
    observed_ips = target.setdefault("ip_addresses", [])
    if ip_address not in observed_ips:
        observed_ips.append(ip_address)


def merge_discovery_sources(
    server_devices, client_observations, *, previous_devices=None, observed_at=None
):
    """Aggregate server ARP and fresh client ARP observations by MAC address.

    The server's direct ARP response is the preferred current IP when both
    sources see a device. Client-only devices remain in the result and retain
    the reporting client and observation time for later inspection.
    """
    observed_at = observed_at or datetime.now(timezone.utc).isoformat()
    devices_by_mac = {}

    # Retain the prior aggregate so a report-only merge cannot hide devices
    # discovered by the immediately preceding ARP scan.
    for device in previous_devices or []:
        mac_address = _normalise_mac_address(device.get("mac_address"))
        if not mac_address:
            continue
        merged_device = dict(device)
        merged_device["mac_address"] = mac_address
        merged_device["observation_sources"] = []
        merged_device["ip_addresses"] = list(device.get("ip_addresses") or [])
        _append_observed_ip(merged_device, merged_device.get("ip_address"))
        _append_observation_sources(
            merged_device,
            device.get("observation_sources")
            or [{"source_type": "PREVIOUS_SCAN", "observed_at": observed_at}],
        )
        existing = devices_by_mac.get(mac_address)
        if existing is None:
            devices_by_mac[mac_address] = merged_device
        else:
            _merge_missing_device_details(existing, merged_device)
            _append_observation_sources(existing, merged_device["observation_sources"])

    for device in server_devices:
        mac_address = _normalise_mac_address(device.get("mac_address"))
        if not mac_address:
            continue
        source = {
            "source_type": "SERVER_SCAN",
            "ip_address": device.get("ip_address"),
            "observed_at": observed_at,
        }
        merged_device = devices_by_mac.get(mac_address)
        if merged_device is None:
            merged_device = dict(device)
            merged_device["mac_address"] = mac_address
            merged_device["observation_sources"] = []
            merged_device["ip_addresses"] = []
            devices_by_mac[mac_address] = merged_device
        else:
            # A direct ARP response is the newest authoritative IP address.
            merged_device["ip_address"] = device.get("ip_address")
            _merge_missing_device_details(merged_device, device)
        _append_observed_ip(merged_device, device.get("ip_address"))
        _append_observation_sources(merged_device, [source])

    for observation in client_observations:
        mac_address = _normalise_mac_address(observation.get("mac_address"))
        if not mac_address:
            continue
        source = {
            "source_type": observation.get("source_type", "CLIENT_ARP"),
            "source_client_database_id": observation.get("source_client_database_id"),
            "source_client_id": observation.get("source_client_id"),
            "source_client_hostname": observation.get("source_client_hostname"),
            "ip_address": observation.get("ip_address"),
            "interface": observation.get("interface"),
            "entry_type": observation.get("entry_type"),
            "hostname": observation.get("hostname"),
            "vendor": observation.get("vendor"),
            "observed_at": observation.get("observed_at"),
        }
        merged_device = devices_by_mac.get(mac_address)
        if merged_device is None:
            merged_device = {
                "ip_address": observation.get("ip_address"),
                "mac_address": mac_address,
                "hostname": observation.get("hostname"),
                "vendor": observation.get("vendor"),
                "os_name": None,
                "os_family": None,
                "os_confidence": None,
                "observation_sources": [],
                "ip_addresses": [],
            }
            devices_by_mac[mac_address] = merged_device
        else:
            if not merged_device.get("ip_address") and observation.get("ip_address"):
                merged_device["ip_address"] = observation["ip_address"]
            if not merged_device.get("hostname") and observation.get("hostname"):
                merged_device["hostname"] = observation["hostname"]
            if not merged_device.get("vendor") and observation.get("vendor"):
                merged_device["vendor"] = observation["vendor"]
        _append_observed_ip(merged_device, observation.get("ip_address"))
        _append_observation_sources(merged_device, [source])

    return list(devices_by_mac.values())



def merge_and_persist_client_neighbourhood(*, context_overrides=None):
    """Merge fresh client neighbourhood reports by MAC and persist one snapshot.

    Server-local ARP discovery, hostname lookup, and OS detection are
    intentionally not called here.  Those helper functions are retained for
    backwards compatibility only; clients are the sole discovery agents.
    """
    context = {
        "interface": "client-reported",
        "local_ip": None,
        "network": "client-reported",
        "gateway": None,
    }
    if context_overrides:
        context.update(context_overrides)
    LOGGER.info("Network aggregation started from client neighbour reports.")
    scan_started_at = datetime.now(timezone.utc)

    try:
        client_observations = get_recent_client_neighbour_observations(
            now=scan_started_at.replace(tzinfo=None)
        )
    except Exception as error:
        LOGGER.warning("Could not load recent client ARP observations: %s", error)
        client_observations = []

    previous_scan = load_latest_network_scan()
    previous_devices = previous_scan.get("devices", []) if previous_scan else []
    discovered_devices = merge_discovery_sources(
        [],
        client_observations,
        previous_devices=previous_devices,
        observed_at=scan_started_at.isoformat(),
    )
    LOGGER.info(
        "Client discovery reports merged with %d previous device(s): %d observation(s), %d unique device(s).",
        len(previous_devices),
        len(client_observations),
        len(discovered_devices),
    )
    classified_devices = classify_devices(discovered_devices)
    devices = classified_devices
    LOGGER.info("Network aggregation completed: %d devices discovered", len(devices))
    result_path = store_network_scan(context, devices)
    LOGGER.info("Network scan result saved to %s", result_path)
    return context, devices, result_path


def run_manual_scan(*, context_overrides=None):
    """Compatibility alias for client-neighbourhood merge and persistence."""
    return merge_and_persist_client_neighbourhood(
        context_overrides=context_overrides
    )


def run_active_scan():
    """Run a real server-side ARP scan, merge with client reports, classify, and persist.

    Unlike run_manual_scan(), this function actively discovers devices on the
    local network using ARP (requires root/sudo) and enriches them with
    hostnames and vendor information.  Client-observed devices are then merged
    on top so that client-only devices are not lost.
    """
    LOGGER.info("Active server ARP scan started.")
    scan_started_at = datetime.now(timezone.utc)

    # 1. Active ARP discovery from the server
    try:
        server_devices = discover_devices()
    except Exception as error:
        LOGGER.warning("Server ARP discovery failed, proceeding with empty server list: %s", error)
        server_devices = []

    # 2. Merge with recent client neighbour observations
    try:
        client_observations = get_recent_client_neighbour_observations(
            now=scan_started_at.replace(tzinfo=None)
        )
    except Exception as error:
        LOGGER.warning("Could not load recent client ARP observations: %s", error)
        client_observations = []

    previous_scan = load_latest_network_scan()
    previous_devices = previous_scan.get("devices", []) if previous_scan else []
    merged = merge_discovery_sources(
        server_devices,
        client_observations,
        previous_devices=previous_devices,
        observed_at=scan_started_at.isoformat(),
    )
    LOGGER.info(
        "Active scan merged: %d previous device(s) + %d server device(s) + %d client observation(s) = %d unique device(s).",
        len(previous_devices),
        len(server_devices),
        len(client_observations),
        len(merged),
    )

    # 3. Classify (managed vs unmanaged) and persist
    classified_devices = classify_devices(merged)
    context = {
        "interface": "server-arp",
        "scan_type": "ACTIVE",
        "local_ip": None,
        "network": "auto-detected",
        "gateway": None,
    }
    result_path = store_network_scan(context, classified_devices)
    LOGGER.info(
        "Active scan completed: %d devices found. Saved to %s",
        len(classified_devices),
        result_path,
    )
    return context, classified_devices, result_path


def run_global_active_scan():
    """Start a non-blocking, bounded client-based active scan job.

    The job reserves no more than the configured number of client scan slots
    at a time.  Slots are released only by a correlated report or scan timeout,
    rather than by the quick command acknowledgement.
    """
    from server_components import server_lib
    from server_components.global_network_scan import global_network_scan_manager

    with server_lib.clients_lock:
        online_clients = list(server_lib.clients.values())
    print(
        "[GLOBAL NETWORK SCAN] Online-client snapshot captured: "
        f"eligible_clients={len(online_clients)} "
        f"client_ids={[client.get('client_id', 'unknown') for client in online_clients]}.",
        flush=True,
    )
    return global_network_scan_manager.start(online_clients)


def run_global_neighbourhood_collection():
    """Start a bucketed passive collection from the current online clients.

    The collection requests only each client's already-stored daily
    neighbourhood; it does not trigger active ARP discovery.
    """
    from server_components import server_lib
    from server_components.global_network_scan import (
        global_neighbourhood_collection_manager,
    )

    with server_lib.clients_lock:
        online_clients = list(server_lib.clients.values())
    return global_neighbourhood_collection_manager.start(online_clients)
