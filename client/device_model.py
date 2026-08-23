"""Unified Observation and Device Correlation Model.

Provides normalized device identity, multi-protocol evidence tracking,
temporal metrics (first_seen, last_seen, seen_count), and presence states.
"""

from __future__ import annotations

import copy
import ipaddress
import json
import logging
import re
import threading
from datetime import datetime, timezone, timedelta
from typing import Any, Mapping, Sequence

LOG = logging.getLogger("device_model")

MAC_ADDRESS_PATTERN = re.compile(r"^[0-9A-F]{2}(?::[0-9A-F]{2}){5}$")
MAX_TEXT_SIZE = 255


def utc_now() -> str:
    """Return current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def normalise_timestamp(value: Any, *, default: str | None = None) -> str | None:
    """Normalise timestamp to ISO-8601 UTC string."""
    if value is None:
        return default
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def normalise_mac_address(value: Any) -> str | None:
    """Validate and normalise MAC address to uppercase colon-delimited format."""
    if not isinstance(value, str):
        return None
    mac = value.strip().replace("-", ":").upper()
    if not MAC_ADDRESS_PATTERN.fullmatch(mac):
        return None
    # Reject broadcast and multicast (odd first octet) MAC addresses
    if mac == "FF:FF:FF:FF:FF:FF" or int(mac[:2], 16) & 1:
        return None
    return mac


def normalise_ip_address(value: Any) -> str | None:
    """Validate and normalise IPv4/IPv6 address, rejecting multicast/loopback/unspecified."""
    if value is None:
        return None
    try:
        addr = ipaddress.ip_address(str(value).strip())
    except ValueError:
        return None
    if addr.is_unspecified or addr.is_loopback or addr.is_multicast or addr.is_reserved:
        return None
    return str(addr)


def calculate_presence_state(last_seen_iso: str, now: datetime | None = None) -> str:
    """Calculate presence state from last_seen timestamp:
    - PASSIVELY_ACTIVE: <= 15 minutes
    - PASSIVELY_IDLE: 15-60 minutes
    - PASSIVELY_STALE: 1-24 hours
    - NOT_RECENTLY_OBSERVED: > 24 hours
    """
    if not last_seen_iso:
        return "NOT_RECENTLY_OBSERVED"
    try:
        last_seen = datetime.fromisoformat(last_seen_iso.replace("Z", "+00:00"))
    except ValueError:
        return "NOT_RECENTLY_OBSERVED"

    now_dt = now or datetime.now(timezone.utc)
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)

    delta = now_dt - last_seen
    if delta < timedelta(minutes=15):
        return "PASSIVELY_ACTIVE"
    elif delta < timedelta(hours=1):
        return "PASSIVELY_IDLE"
    elif delta < timedelta(hours=24):
        return "PASSIVELY_STALE"
    return "NOT_RECENTLY_OBSERVED"


class EnrichedAttribute:
    """Attribute with associated confidence and supporting evidence."""

    def __init__(
        self,
        value: str | None = None,
        confidence: float = 0.0,
        evidence: Sequence[str] | None = None,
    ):
        self.value = value
        self.confidence = float(confidence)
        self.evidence: list[str] = list(evidence) if evidence else []

    def update_if_better(
        self,
        value: str | None,
        confidence: float,
        evidence_source: str | None = None,
    ) -> bool:
        """Update value if new confidence is higher, preserving evidence."""
        if not value:
            return False

        if evidence_source and evidence_source not in self.evidence:
            self.evidence.append(evidence_source)

        if self.value is None or confidence > self.confidence:
            self.value = value
            self.confidence = confidence
            return True
        elif confidence == self.confidence and self.value != value:
            return False
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "confidence": round(self.confidence, 2),
            "evidence": list(self.evidence),
        }


class DeviceRecord:
    """Unified device record aggregating multi-protocol discovery evidence."""

    def __init__(
        self,
        mac_address: str | None = None,
        *,
        first_seen: str | None = None,
    ):
        self.mac_address = normalise_mac_address(mac_address)
        self.ip_addresses: list[str] = []
        self.ipv6_addresses: list[str] = []
        self.hostname: str | None = None
        self._hostname_priority: int = 0
        self.vendor: str | None = None
        self.device_type: str | None = None
        self.model_hint: str | None = None
        self.os_hint: str | None = None
        self.software_hint: str | None = None
        self.software_hints: list[str] = []

        # Confidence attributes
        self.os_classification = EnrichedAttribute()
        self.device_type_classification = EnrichedAttribute()
        self.model_classification = EnrichedAttribute()

        # Evidence tracking maps
        self.evidence: dict[str, list[str]] = {
            "hostname": [],
            "vendor": [],
            "os_hint": [],
            "model_hint": [],
            "device_type": [],
        }

        # Protocol & service tracking
        self.protocols_seen: list[str] = []
        self.services: list[str] = []
        self.last_protocol: str | None = None

        # Temporal information
        now_ts = utc_now()
        self.first_seen: str = normalise_timestamp(first_seen, default=now_ts) or now_ts
        self.last_seen: str = self.first_seen
        self.seen_count: int = 1
        self.observation_count: int = 1

        # Protocol-specific / raw extracted fields
        self.raw_fields: dict[str, Any] = {}

    def add_ip_address(self, ip_str: str | None, source: str | None = None) -> bool:
        """Add an IPv4 or IPv6 address."""
        if not ip_str:
            return False
        clean_ip = normalise_ip_address(ip_str)
        if not clean_ip:
            return False

        try:
            addr = ipaddress.ip_address(clean_ip)
            if addr.version == 4:
                if clean_ip not in self.ip_addresses:
                    self.ip_addresses.append(clean_ip)
                    return True
            elif addr.version == 6:
                if clean_ip not in self.ipv6_addresses:
                    self.ipv6_addresses.append(clean_ip)
                    return True
        except ValueError:
            pass
        return False

    def add_protocol(self, protocol: str) -> None:
        """Record protocol observation."""
        if protocol and protocol not in self.protocols_seen:
            self.protocols_seen.append(protocol)
        self.last_protocol = protocol

    def add_service(self, service_type: str) -> None:
        """Record discovered service type."""
        if service_type and service_type not in self.services:
            self.services.append(service_type)

    def add_software_hint(self, hint: str) -> None:
        """Record discovered software hint."""
        if not hint:
            return
        clean_hint = hint.strip()
        if clean_hint and clean_hint not in self.software_hints:
            self.software_hints.append(clean_hint)
        if not self.software_hint:
            self.software_hint = clean_hint

    def add_evidence(self, category: str, source: str) -> None:
        """Track source attribution for an attribute."""
        if category not in self.evidence:
            self.evidence[category] = []
        if source and source not in self.evidence[category]:
            self.evidence[category].append(source)

    def set_hostname(self, hostname: str | None, source: str | None = None, priority: int = 0) -> bool:
        """Set hostname with priority and evidence tracking.
        Priority: DHCP (40) > mDNS (30) > LLMNR (20) > NBNS (10) > Reverse DNS (5)
        """
        if not hostname:
            return False
        clean_host = hostname.strip()
        if not clean_host or len(clean_host) > MAX_TEXT_SIZE:
            return False

        if source:
            self.add_evidence("hostname", source)

        if self.hostname is None:
            self.hostname = clean_host
            self._hostname_priority = priority
            return True
        elif priority > self._hostname_priority:
            self.hostname = clean_host
            self._hostname_priority = priority
            return True
        elif priority == self._hostname_priority:
            if self.hostname.endswith(".local") and not clean_host.endswith(".local"):
                self.hostname = clean_host
                return True
        return False

    def set_vendor(self, vendor: str | None, source: str = "oui") -> bool:
        """Set vendor with evidence tracking."""
        if not vendor:
            return False
        clean_vendor = vendor.strip()
        if not clean_vendor or len(clean_vendor) > MAX_TEXT_SIZE:
            return False
        self.add_evidence("vendor", source)
        if not self.vendor or len(clean_vendor) > len(self.vendor):
            self.vendor = clean_vendor
            return True
        return False

    def record_activity(self, timestamp: str | None = None, protocol: str | None = None) -> None:
        """Update last_seen and increment seen/observation counters."""
        ts = normalise_timestamp(timestamp, default=utc_now()) or utc_now()
        if ts > self.last_seen:
            self.last_seen = ts
        self.seen_count = min(2_147_483_647, self.seen_count + 1)
        self.observation_count = min(2_147_483_647, self.observation_count + 1)
        if protocol:
            self.add_protocol(protocol)

    @property
    def presence_state(self) -> str:
        """Compute current passive presence state."""
        return calculate_presence_state(self.last_seen)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to normalized JSON-friendly dictionary."""
        result: dict[str, Any] = {
            "mac_address": self.mac_address,
            "ip_addresses": list(self.ip_addresses),
            "ipv6_addresses": list(self.ipv6_addresses),
            "hostname": self.hostname,
            "vendor": self.vendor,
            "device_type": self.device_type,
            "model_hint": self.model_hint,
            "os_hint": self.os_hint,
            "software_hint": self.software_hint,
            "software_hints": list(self.software_hints),
            "protocols_seen": list(self.protocols_seen),
            "services": list(self.services),
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "seen_count": self.seen_count,
            "observation_count": self.observation_count,
            "presence_state": self.presence_state,
            "evidence": {k: list(v) for k, v in self.evidence.items() if v},
        }
        if self.os_classification.value:
            result["os_classification"] = self.os_classification.to_dict()
        if self.device_type_classification.value:
            result["device_type_classification"] = self.device_type_classification.to_dict()
        if self.model_classification.value:
            result["model_classification"] = self.model_classification.to_dict()
        if self.raw_fields:
            result["raw_fields"] = copy.deepcopy(self.raw_fields)
        return result


class DeviceCorrelator:
    """Thread-safe correlation engine that unifies multi-protocol observations."""

    def __init__(self, max_devices: int = 1024):
        self.max_devices = max_devices
        self._devices_by_mac: dict[str, DeviceRecord] = {}
        self._devices_by_ip: dict[str, DeviceRecord] = {}
        self._lock = threading.RLock()

    def get_or_create_device(
        self,
        mac_address: str | None,
        ip_address: str | None = None,
        *,
        observed_at: str | None = None,
    ) -> DeviceRecord:
        """Find existing device by MAC or IP, or create a new one."""
        with self._lock:
            clean_mac = normalise_mac_address(mac_address)
            clean_ip = normalise_ip_address(ip_address)

            # 1. Primary correlation key: MAC address
            if clean_mac and clean_mac in self._devices_by_mac:
                device = self._devices_by_mac[clean_mac]
                if clean_ip:
                    device.add_ip_address(clean_ip)
                    self._devices_by_ip[clean_ip] = device
                return device

            # 2. Secondary correlation key: IP address fallback
            if clean_ip and clean_ip in self._devices_by_ip:
                device = self._devices_by_ip[clean_ip]
                if clean_mac:
                    if not device.mac_address:
                        device.mac_address = clean_mac
                    self._devices_by_mac[clean_mac] = device
                return device

            # 3. Create new device record
            device = DeviceRecord(mac_address=clean_mac, first_seen=observed_at)
            if clean_ip:
                device.add_ip_address(clean_ip)

            # Enforce bounds
            if len(self._devices_by_mac) >= self.max_devices:
                oldest_mac = min(
                    self._devices_by_mac,
                    key=lambda m: self._devices_by_mac[m].last_seen,
                )
                old_dev = self._devices_by_mac.pop(oldest_mac)
                for ip in old_dev.ip_addresses:
                    self._devices_by_ip.pop(ip, None)

            if clean_mac:
                self._devices_by_mac[clean_mac] = device
            if clean_ip:
                self._devices_by_ip[clean_ip] = device

            return device

    def snapshot(self) -> list[dict[str, Any]]:
        """Return a sorted snapshot of all correlated device records."""
        with self._lock:
            unique_devices = list(dict.fromkeys(
                [*self._devices_by_mac.values(), *self._devices_by_ip.values()]
            ))
            devices = [dev.to_dict() for dev in unique_devices]
        return sorted(devices, key=lambda d: d["last_seen"], reverse=True)

    def get_device_by_mac(self, mac_address: str) -> DeviceRecord | None:
        """Lookup device by MAC address."""
        with self._lock:
            clean_mac = normalise_mac_address(mac_address)
            return self._devices_by_mac.get(clean_mac) if clean_mac else None

    def get_device_by_ip(self, ip_address: str) -> DeviceRecord | None:
        """Lookup device by IP address."""
        with self._lock:
            clean_ip = normalise_ip_address(ip_address)
            return self._devices_by_ip.get(clean_ip) if clean_ip else None

    def clear(self) -> None:
        """Clear all correlated devices."""
        with self._lock:
            self._devices_by_mac.clear()
            self._devices_by_ip.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(set(
                [*self._devices_by_mac.values(), *self._devices_by_ip.values()]
            ))
