"""Unified Passive Protocol Discovery Scanner for the Windows Client.

Captures traffic passively visible on the selected interface across DHCP,
mDNS, SSDP, LLMNR, and NBNS. Unifies observations into a single device
enrichment engine with evidence tracking, temporal metrics, and classification.
"""

from __future__ import annotations

import copy
import ipaddress
import json
import logging
import re
import struct
import threading
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Callable

from device_model import (
    DeviceCorrelator,
    DeviceRecord,
    normalise_ip_address,
    normalise_mac_address,
    normalise_timestamp,
    utc_now,
)
from fingerprinting import (
    apply_classification_to_device,
    classify_dhcp_evidence,
    classify_mdns_evidence,
    classify_ssdp_evidence,
    evaluate_hostname_heuristics,
)
from dhcp_listener import parse_dhcp_packet

LOG = logging.getLogger("passive_protocol_listener")

SUPPORTED_PROTOCOLS = frozenset({"dhcp", "mdns", "llmnr", "nbns", "ssdp"})
PROTOCOL_LABELS = {
    "dhcp": "DHCP",
    "mdns": "mDNS",
    "llmnr": "LLMNR",
    "nbns": "NBNS",
    "ssdp": "SSDP",
}
PASSIVE_PROTOCOL_BPF_FILTER = "udp and (port 67 or port 68 or port 137 or port 1900 or port 5353 or port 5355)"
MAX_OBSERVATIONS = 512
MAX_RAW_FIELDS = 16
MAX_RAW_FIELD_SIZE = 512
MAX_RAW_SERIALIZED_SIZE = 4096
MAX_TEXT_SIZE = 255
MAC_ADDRESS_PATTERN = re.compile(r"^[0-9A-F]{2}(?::[0-9A-F]{2}){5}$")


def _normalise_text(value: Any, *, limit: int = MAX_TEXT_SIZE) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > limit or any(char in value for char in "\r\n\x00"):
        return None
    return value


def _normalise_port(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        port = int(value)
    except (TypeError, ValueError):
        return None
    return port if 1 <= port <= 65535 else None


def _normalise_raw_fields(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}

    result: dict[str, Any] = {}
    for key, item in value.items():
        clean_key = _normalise_text(key, limit=64)
        if clean_key is None or len(result) >= MAX_RAW_FIELDS:
            continue
        if isinstance(item, Mapping):
            nested = {}
            for nested_key, nested_value in item.items():
                clean_nested_key = _normalise_text(nested_key, limit=64)
                clean_nested_value = _normalise_text(
                    nested_value, limit=MAX_RAW_FIELD_SIZE
                )
                if (
                    clean_nested_key is not None
                    and clean_nested_value is not None
                    and len(nested) < MAX_RAW_FIELDS
                ):
                    nested[clean_nested_key] = clean_nested_value
            if nested:
                result[clean_key] = nested
        elif isinstance(item, list):
            clean_list = [
                _normalise_text(str(elem), limit=MAX_RAW_FIELD_SIZE)
                if isinstance(elem, str) else elem
                for elem in item[:MAX_RAW_FIELDS]
            ]
            result[clean_key] = clean_list
        else:
            clean_value = _normalise_text(str(item), limit=MAX_RAW_FIELD_SIZE)
            if clean_value is not None:
                result[clean_key] = item if isinstance(item, (int, float, bool)) else clean_value

    while result:
        try:
            if len(json.dumps(result, sort_keys=True).encode("utf-8")) <= MAX_RAW_SERIALIZED_SIZE:
                break
        except (TypeError, ValueError):
            return {}
        result.pop(next(reversed(result)))
    return result


def normalise_passive_observation(
    observation: Mapping[str, Any], *, observed_at: str | None = None
) -> dict[str, Any] | None:
    """Validate one passive observation without inferring device identity."""
    if not isinstance(observation, Mapping):
        return None

    protocol = observation.get("protocol")
    if protocol not in SUPPORTED_PROTOCOLS:
        return None

    timestamp = normalise_timestamp(
        observed_at or observation.get("observed_at"), default=utc_now()
    )
    first_observed_at = normalise_timestamp(
        observation.get("first_observed_at"), default=timestamp
    )
    if timestamp is None or first_observed_at is None:
        return None

    kind = observation.get("observation_kind")
    if kind not in {None, "query", "response", "announcement", "search", "advertisement", "request", "discover", "ack"}:
        return None

    normalized: dict[str, Any] = {
        "protocol": protocol,
        "observed_at": timestamp,
        "first_observed_at": first_observed_at,
        "seen_count": 1,
    }
    optional_fields = {
        "observation_kind": _normalise_text(kind, limit=32),
        "ip_address": normalise_ip_address(observation.get("ip_address")),
        "mac_address": normalise_mac_address(observation.get("mac_address")),
        "hostname": _normalise_text(observation.get("hostname")),
        "device_name": _normalise_text(observation.get("device_name")),
        "service_type": _normalise_text(observation.get("service_type")),
        "service_name": _normalise_text(observation.get("service_name")),
        "service_port": _normalise_port(observation.get("service_port")),
        "device_type": _normalise_text(observation.get("device_type")),
        "vendor": _normalise_text(observation.get("vendor")),
        "model": _normalise_text(observation.get("model")),
        "server": _normalise_text(observation.get("server"), limit=512),
        "location": _normalise_text(observation.get("location"), limit=2048),
    }
    normalized.update(
        {key: value for key, value in optional_fields.items() if value is not None}
    )

    raw_fields = _normalise_raw_fields(observation.get("raw_fields"))
    if raw_fields:
        normalized["raw_fields"] = raw_fields

    if not any(
        normalized.get(field)
        for field in ("hostname", "service_name", "device_type", "ip_address", "mac_address")
    ) and not raw_fields.get("usn"):
        return None
    return normalized


def passive_observation_key(observation: Mapping[str, Any]) -> tuple[Any, ...] | None:
    """Return the protocol-specific key for a normalized observation."""
    protocol = observation.get("protocol")
    raw_fields = observation.get("raw_fields") or {}
    if protocol == "dhcp":
        return (
            protocol,
            observation.get("mac_address") or "",
            observation.get("ip_address") or "",
            observation.get("hostname") or "",
        )
    if protocol == "mdns":
        return (
            protocol,
            observation.get("service_name") or observation.get("hostname") or "",
            observation.get("service_type") or "",
            observation.get("ip_address") or "",
            observation.get("service_port") or "",
        )
    if protocol in {"llmnr", "nbns"}:
        return (
            protocol,
            observation.get("observation_kind") or "",
            observation.get("hostname") or "",
            observation.get("ip_address") or "",
        )
    if protocol == "ssdp":
        return (
            protocol,
            observation.get("observation_kind") or "",
            raw_fields.get("usn", "") if isinstance(raw_fields, Mapping) else "",
            observation.get("device_type") or "",
            observation.get("location") or "",
            observation.get("ip_address") or "",
        )
    return None


class PassiveObservationBuffer:
    """Thread-safe, bounded, protocol-aware observation storage."""

    def __init__(self, max_observations: int = MAX_OBSERVATIONS):
        if not isinstance(max_observations, int) or max_observations < 1:
            raise ValueError("max_observations must be a positive integer")
        self._max_observations = max_observations
        self._observations: dict[tuple[Any, ...], dict[str, Any]] = {}
        self._lock = threading.RLock()

    def add(self, observation: Mapping[str, Any], *, observed_at: str | None = None) -> bool:
        normalized = normalise_passive_observation(observation, observed_at=observed_at)
        if normalized is None:
            return False
        key = passive_observation_key(normalized)
        if key is None:
            return False

        with self._lock:
            existing = self._observations.get(key)
            if existing is not None:
                existing["observed_at"] = normalized["observed_at"]
                existing["seen_count"] = min(
                    2_147_483_647, existing["seen_count"] + 1
                )
                for field, value in normalized.items():
                    if field not in {"observed_at", "first_observed_at", "seen_count"} and (
                        field not in existing or not existing[field]
                    ):
                        existing[field] = copy.deepcopy(value)
                return True

            if len(self._observations) >= self._max_observations:
                oldest_key = min(
                    self._observations,
                    key=lambda item: self._observations[item]["observed_at"],
                )
                del self._observations[oldest_key]
            self._observations[key] = normalized
        return True

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            observations = copy.deepcopy(list(self._observations.values()))
        return sorted(observations, key=lambda item: item["observed_at"], reverse=True)

    def __len__(self) -> int:
        with self._lock:
            return len(self._observations)


def _read_dns_name(data: bytes, offset: int, *, depth: int = 0) -> tuple[str, int]:
    if depth > 12 or offset >= len(data):
        raise ValueError("invalid DNS name")

    labels = []
    cursor = offset
    next_offset = None
    while cursor < len(data):
        length = data[cursor]
        if length == 0:
            cursor += 1
            return ".".join(labels), next_offset or cursor
        if length & 0xC0 == 0xC0:
            if cursor + 1 >= len(data):
                raise ValueError("truncated DNS pointer")
            pointer = ((length & 0x3F) << 8) | data[cursor + 1]
            pointed_name, _ = _read_dns_name(data, pointer, depth=depth + 1)
            labels.append(pointed_name)
            return ".".join(label for label in labels if label), next_offset or cursor + 2
        if length & 0xC0 or length > 63 or cursor + 1 + length > len(data):
            raise ValueError("invalid DNS label")
        label = data[cursor + 1 : cursor + 1 + length].decode("utf-8", errors="replace")
        labels.append(label)
        cursor += 1 + length
    raise ValueError("truncated DNS name")


def _parse_dns_message(data: bytes) -> tuple[bool, list[tuple[str, int]], list[dict[str, Any]]]:
    if len(data) < 12:
        return False, [], []

    _transaction_id, flags, question_count, answer_count, authority_count, additional_count = struct.unpack_from(
        "!HHHHHH", data
    )
    offset = 12
    questions = []
    records = []

    try:
        for _ in range(question_count):
            name, offset = _read_dns_name(data, offset)
            record_type, _record_class = struct.unpack_from("!HH", data, offset)
            offset += 4
            questions.append((name, record_type))

        for _ in range(answer_count + authority_count + additional_count):
            name, offset = _read_dns_name(data, offset)
            record_type, record_class, _ttl, rdlength = struct.unpack_from(
                "!HHIH", data, offset
            )
            offset += 10
            rdata_offset = offset
            offset += rdlength
            if offset > len(data):
                raise ValueError("truncated DNS record")
            records.append(
                {
                    "name": name,
                    "record_type": record_type,
                    "record_class": record_class,
                    "rdata": data[rdata_offset:offset],
                    "rdata_offset": rdata_offset,
                }
            )
    except (UnicodeError, ValueError, struct.error):
        return False, [], []
    return bool(flags & 0x8000), questions, records


def _parse_dns_txt(data: bytes) -> dict[str, str]:
    result = {}
    offset = 0
    while offset < len(data) and len(result) < MAX_RAW_FIELDS:
        length = data[offset]
        offset += 1
        if offset + length > len(data):
            return {}
        value = data[offset : offset + length].decode("utf-8", errors="replace").strip()
        offset += length
        if "=" in value:
            key, item = value.split("=", 1)
        else:
            key, item = value, ""
        key = _normalise_text(key, limit=64)
        item = _normalise_text(item, limit=MAX_RAW_FIELD_SIZE)
        if key and item is not None:
            result[key] = item
    return result


def _dns_observations(
    protocol: str, payload: bytes, source: Mapping[str, Any]
) -> list[dict[str, Any]]:
    is_response, questions, records = _parse_dns_message(payload)
    observations = []
    source_data = {
        key: value
        for key, value in source.items()
        if key in {"ip_address", "mac_address"} and value is not None
    }

    if not is_response:
        for name, _record_type in questions:
            observations.append(
                {
                    "protocol": protocol,
                    "observation_kind": "query",
                    "hostname": name,
                    **source_data,
                }
            )
        return observations

    for record in records:
        record_type = record["record_type"]
        name = record["name"]
        base = {
            "protocol": protocol,
            "observation_kind": "response",
            **source_data,
        }
        try:
            if record_type == 1 and len(record["rdata"]) == 4:
                base.update({"hostname": name, "ip_address": str(ipaddress.IPv4Address(record["rdata"]))})
            elif record_type == 28 and len(record["rdata"]) == 16:
                base.update({"hostname": name, "ip_address": str(ipaddress.IPv6Address(record["rdata"]))})
            elif protocol == "mdns" and record_type == 12:
                service_name, _ = _read_dns_name(payload, record["rdata_offset"])
                base.update({"service_type": name, "service_name": service_name})
            elif protocol == "mdns" and record_type == 33 and len(record["rdata"]) >= 6:
                _priority, _weight, port = struct.unpack_from("!HHH", record["rdata"])
                target, _ = _read_dns_name(payload, record["rdata_offset"] + 6)
                base.update({"service_name": name, "hostname": target, "service_port": port})
            elif protocol == "mdns" and record_type == 16:
                txt = _parse_dns_txt(record["rdata"])
                base.update({"service_name": name, "raw_fields": {"txt": txt}})
            else:
                continue
        except (ValueError, struct.error):
            continue
        observations.append(base)
    return observations


def _decode_nbns_name(data: bytes, offset: int) -> tuple[str, int]:
    if offset >= len(data) or data[offset] != 32 or offset + 33 > len(data):
        raise ValueError("invalid NBNS name")
    encoded = data[offset + 1 : offset + 33]
    if any(value < ord("A") or value > ord("P") for value in encoded):
        raise ValueError("invalid NBNS encoded name")
    decoded = bytes(
        ((encoded[index] - ord("A")) << 4) | (encoded[index + 1] - ord("A"))
        for index in range(0, 32, 2)
    )
    name = decoded[:15].decode("ascii", errors="replace").rstrip()
    cursor = offset + 33
    while cursor < len(data):
        length = data[cursor]
        cursor += 1
        if length == 0:
            return name, cursor
        if length & 0xC0 or cursor + length > len(data):
            raise ValueError("invalid NBNS scope")
        cursor += length
    raise ValueError("truncated NBNS name")


def parse_nbns_payload(payload: bytes, source: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Parse query/response names from an NBNS UDP payload."""
    if len(payload) < 12:
        return []
    try:
        _tid, flags, question_count, answer_count, authority_count, additional_count = struct.unpack_from(
            "!HHHHHH", payload
        )
        offset = 12
        kind = "response" if flags & 0x8000 else "query"
        observations = []
        source_data = {
            key: value
            for key, value in source.items()
            if key in {"ip_address", "mac_address"} and value is not None
        }
        for _ in range(question_count):
            name, offset = _decode_nbns_name(payload, offset)
            _question_type, _question_class = struct.unpack_from("!HH", payload, offset)
            offset += 4
            observations.append(
                {"protocol": "nbns", "observation_kind": kind, "hostname": name, **source_data}
            )

        for _ in range(answer_count + authority_count + additional_count):
            name, offset = _decode_nbns_name(payload, offset)
            record_type, _record_class, _ttl, rdlength = struct.unpack_from(
                "!HHIH", payload, offset
            )
            offset += 10
            rdata = payload[offset : offset + rdlength]
            offset += rdlength
            if len(rdata) != rdlength:
                return observations
            observation = {
                "protocol": "nbns",
                "observation_kind": kind,
                "hostname": name,
                **source_data,
            }
            if record_type == 0x20 and len(rdata) >= 6:
                observation["ip_address"] = str(ipaddress.IPv4Address(rdata[-4:]))
                observation["raw_fields"] = {"name_type": "netbios"}
            observations.append(observation)
        return observations
    except (UnicodeError, ValueError, struct.error):
        return []


def parse_ssdp_payload(payload: bytes, source: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Parse one safe SSDP advertisement, search, or response."""
    try:
        text = payload[:8192].decode("utf-8", errors="replace")
        lines = text.replace("\r\n", "\n").split("\n")
        if not lines or not lines[0]:
            return []
        start_line = lines[0].strip().upper()
        if start_line.startswith("NOTIFY "):
            kind = "advertisement"
        elif start_line.startswith("M-SEARCH "):
            kind = "search"
        elif start_line.startswith("HTTP/1."):
            kind = "response"
        else:
            return []

        headers = {}
        for line in lines[1:]:
            if not line:
                break
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip().lower()
            value = _normalise_text(value, limit=2048)
            if key in {"nt", "st", "usn", "server", "location", "cache-control", "host", "man"} and value:
                headers[key] = value

        raw_fields = {
            output_key: headers[input_key]
            for input_key, output_key in (
                ("usn", "usn"),
                ("cache-control", "cache_control"),
                ("host", "host"),
                ("man", "man"),
            )
            if input_key in headers
        }
        observation = {
            "protocol": "ssdp",
            "observation_kind": kind,
            "ip_address": source.get("ip_address"),
            "mac_address": source.get("mac_address"),
            "device_type": headers.get("nt") or headers.get("st"),
            "server": headers.get("server"),
            "location": headers.get("location"),
            "raw_fields": raw_fields,
        }
        return [observation]
    except (UnicodeError, ValueError):
        return []


class PassiveProtocolListener:
    """Unified passive discovery scanner across DHCP, mDNS, SSDP, LLMNR, and NBNS."""

    def __init__(
        self,
        interface: str | None = None,
        *,
        max_observations: int = MAX_OBSERVATIONS,
        status_callback: Callable[[str], None] | None = None,
        dhcp_callback: Callable[[dict[str, Any]], None] | None = None,
    ):
        self.interface = interface
        self.observations = PassiveObservationBuffer(max_observations)
        self.correlator = DeviceCorrelator(max_devices=max_observations)
        self._status_callback = status_callback
        self._dhcp_callback = dhcp_callback
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._status_lock = threading.RLock()
        self._protocol_status = {protocol: "UNAVAILABLE" for protocol in PROTOCOL_LABELS}
        self._capture_error: str | None = None
        self._vendors_db: Any = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def availability(self) -> str:
        with self._status_lock:
            statuses = set(self._protocol_status.values())
        if not statuses or statuses == {"UNAVAILABLE"}:
            return "UNAVAILABLE"
        if statuses == {"AVAILABLE"}:
            return "AVAILABLE"
        return "PARTIALLY_AVAILABLE"

    @property
    def protocol_status(self) -> dict[str, str]:
        with self._status_lock:
            return dict(self._protocol_status)

    def _emit_status(self, message: str, *, level: int = logging.INFO) -> None:
        LOG.log(level, message)
        if self._status_callback is not None:
            try:
                self._status_callback(message)
                return
            except Exception:
                LOG.exception("[PASSIVE LISTENER] Status callback failed")
        print(message, flush=True)

    def _mark_protocol_unavailable(self, protocol: str, reason: str) -> None:
        if protocol not in PROTOCOL_LABELS:
            return
        with self._status_lock:
            if self._protocol_status[protocol] == "UNAVAILABLE":
                return
            self._protocol_status[protocol] = "UNAVAILABLE"
        self._emit_status(
            f"[PASSIVE LISTENER] {PROTOCOL_LABELS[protocol]} unavailable: {reason}",
            level=logging.WARNING,
        )

    def _mark_capture_unavailable(self, reason: str) -> None:
        for protocol in PROTOCOL_LABELS:
            self._mark_protocol_unavailable(protocol, reason)
        self._emit_status(
            f"[PASSIVE LISTENER] Listener unavailable ({self.availability})",
            level=logging.WARNING,
        )

    def start(self) -> bool:
        if self.running:
            return False
        self._stop.clear()
        self._capture_error = None

        # Preload OUI vendor database
        try:
            import oui
            self._vendors_db = oui.load_oui_database()
        except Exception:
            self._vendors_db = None

        with self._status_lock:
            for protocol in self._protocol_status:
                self._protocol_status[protocol] = "AVAILABLE"
        self._emit_status("[PASSIVE LISTENER] Starting unified discovery scanner...")
        for protocol, label in PROTOCOL_LABELS.items():
            self._emit_status(f"[PASSIVE LISTENER] {label} listener active")
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="passive-protocol-listener",
        )
        self._thread.start()
        self._emit_status(f"[PASSIVE LISTENER] Unified listener ready ({self.availability})")
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def snapshot(self) -> list[dict[str, Any]]:
        """Return raw observation buffer snapshot."""
        return self.observations.snapshot()

    def snapshot_devices(self) -> list[dict[str, Any]]:
        """Return unified, enriched device records."""
        return self.correlator.snapshot()

    def _correlate_observation(self, obs: dict[str, Any]) -> None:
        """Enrich and correlate one observation into the DeviceCorrelator."""
        protocol = obs.get("protocol")
        mac = obs.get("mac_address")
        ip = obs.get("ip_address")

        if not mac and not ip:
            return

        device = self.correlator.get_or_create_device(mac, ip, observed_at=obs.get("observed_at"))
        device.record_activity(obs.get("observed_at"), protocol)

        if mac and not device.mac_address:
            device.mac_address = mac
        if ip:
            device.add_ip_address(ip, source=protocol)

        # Merge protocol-specific details
        if protocol == "dhcp":
            raw_fields = obs.get("raw_fields") or {}
            hostname = obs.get("hostname")
            vendor_class = obs.get("vendor_class")
            prl = obs.get("parameter_request_list")

            if hostname:
                device.set_hostname(hostname, source="dhcp", priority=40)
            if raw_fields:
                device.raw_fields.setdefault("dhcp", {}).update(raw_fields)

            if vendor_class:
                device.add_evidence("os_hint", "dhcp.vendor_class")
            if prl:
                device.add_evidence("os_hint", "dhcp.parameter_request_list")

            dhcp_eval = classify_dhcp_evidence(
                vendor_class=vendor_class,
                parameter_request_list=prl,
                hostname=hostname,
                client_id=obs.get("client_id"),
            )
            if dhcp_eval.get("os_hint"):
                device.os_classification.update_if_better(dhcp_eval["os_hint"], dhcp_eval["confidence"], "dhcp.vendor_class")
                device.os_hint = device.os_classification.value
                for ev in dhcp_eval.get("evidence", []):
                    device.add_evidence("os_hint", ev)
            if dhcp_eval.get("device_type"):
                device.device_type_classification.update_if_better(dhcp_eval["device_type"], dhcp_eval["confidence"], "dhcp.device_type")
                device.device_type = device.device_type_classification.value
                for ev in dhcp_eval.get("evidence", []):
                    device.add_evidence("device_type", ev)

        elif protocol == "mdns":
            service_type = obs.get("service_type")
            service_name = obs.get("service_name")
            hostname = obs.get("hostname")
            txt_dict = (obs.get("raw_fields") or {}).get("txt") if isinstance(obs.get("raw_fields"), dict) else None

            if service_type:
                device.add_service(service_type)
            if hostname:
                device.set_hostname(hostname, source="mdns", priority=30)
            if txt_dict:
                device.raw_fields.setdefault("mdns_txt", {}).update(txt_dict)

            mdns_eval = classify_mdns_evidence(
                service_type=service_type,
                service_name=service_name,
                txt_records=txt_dict,
                hostname=hostname,
            )
            if mdns_eval.get("os_hint"):
                device.os_classification.update_if_better(mdns_eval["os_hint"], mdns_eval["confidence"], "mdns")
                device.os_hint = device.os_classification.value
                for ev in mdns_eval.get("evidence", []):
                    device.add_evidence("os_hint", ev)
            if mdns_eval.get("device_type"):
                device.device_type_classification.update_if_better(mdns_eval["device_type"], mdns_eval["confidence"], "mdns")
                device.device_type = device.device_type_classification.value
                for ev in mdns_eval.get("evidence", []):
                    device.add_evidence("device_type", ev)
            if mdns_eval.get("model_hint"):
                device.model_classification.update_if_better(mdns_eval["model_hint"], mdns_eval["confidence"], "mdns.txt.model")
                device.model_hint = device.model_classification.value
                for ev in mdns_eval.get("evidence", []):
                    device.add_evidence("model_hint", ev)
            for hint in mdns_eval.get("software_hints", []):
                device.add_software_hint(hint)

        elif protocol in {"llmnr", "nbns"}:
            hostname = obs.get("hostname")
            if hostname:
                priority = 20 if protocol == "llmnr" else 10
                device.set_hostname(hostname, source=protocol, priority=priority)
            if protocol == "nbns":
                device.add_evidence("os_hint", "nbns")
            elif protocol == "llmnr":
                device.add_evidence("os_hint", "llmnr")

        elif protocol == "ssdp":
            server_header = obs.get("server")
            dev_type = obs.get("device_type")
            loc = obs.get("location")
            if server_header:
                device.software_hint = server_header
            ssdp_eval = classify_ssdp_evidence(server_header, dev_type, loc)
            if ssdp_eval.get("os_hint"):
                device.os_classification.update_if_better(ssdp_eval["os_hint"], ssdp_eval["confidence"], "ssdp.server")
                device.os_hint = device.os_classification.value
                for ev in ssdp_eval.get("evidence", []):
                    device.add_evidence("os_hint", ev)
            if ssdp_eval.get("device_type"):
                device.device_type_classification.update_if_better(ssdp_eval["device_type"], ssdp_eval["confidence"], "ssdp.device_type")
                device.device_type = device.device_type_classification.value
                for ev in ssdp_eval.get("evidence", []):
                    device.add_evidence("device_type", ev)
            for hint in ssdp_eval.get("software_hints", []):
                device.add_software_hint(hint)

        # Apply multi-source synergistic classification
        apply_classification_to_device(device, self._vendors_db)

    def process_packet(self, packet: Any) -> int:
        """Parse one Scapy packet synchronously; intended for capture worker/tests."""
        try:
            from scapy.layers.inet import IP, UDP  # type: ignore
            from scapy.layers.inet6 import IPv6  # type: ignore
            from scapy.layers.l2 import Ether  # type: ignore

            if not packet.haslayer(UDP):
                return 0
            udp = packet[UDP]
            port = udp.sport if udp.sport in {67, 68, 137, 1900, 5353, 5355} else udp.dport
            if port not in {67, 68, 137, 1900, 5353, 5355}:
                return 0

            source: dict[str, Any] = {}
            if packet.haslayer(IP):
                source["ip_address"] = packet[IP].src
            elif packet.haslayer(IPv6):
                source["ip_address"] = packet[IPv6].src
            if packet.haslayer(Ether):
                source["mac_address"] = packet[Ether].src
            payload = bytes(udp.payload)

            parsed: list[dict[str, Any]] = []

            if port in {67, 68}:
                dhcp_parsed = parse_dhcp_packet(payload)
                if dhcp_parsed and dhcp_parsed.get("mac_address"):
                    parsed = [dhcp_parsed]
                    if self._dhcp_callback:
                        try:
                            self._dhcp_callback(dhcp_parsed)
                        except Exception:
                            LOG.exception("[PASSIVE LISTENER] DHCP callback failed")
            elif port == 5353:
                parsed = _dns_observations("mdns", payload, source)
            elif port == 5355:
                parsed = _dns_observations("llmnr", payload, source)
            elif port == 137:
                parsed = parse_nbns_payload(payload, source)
            else:
                parsed = parse_ssdp_payload(payload, source)

            added_count = 0
            for item in parsed:
                if self.observations.add(item):
                    added_count += 1
                self._correlate_observation(item)

            return added_count
        except Exception:
            LOG.exception("[PASSIVE LISTENER] Packet parser failed")
            return 0

    def _handle_scapy_packet(self, packet: Any) -> None:
        """Buffer a captured packet without letting Scapy print a numeric result."""
        self.process_packet(packet)

    @staticmethod
    def _is_supported_packet(packet: Any) -> bool:
        try:
            from scapy.layers.inet import UDP  # type: ignore

            return packet.haslayer(UDP) and (
                packet[UDP].sport in {67, 68, 137, 1900, 5353, 5355}
                or packet[UDP].dport in {67, 68, 137, 1900, 5353, 5355}
            )
        except Exception:
            return False

    def _capture_with_scapy(self) -> bool:
        try:
            from scapy.all import sniff  # type: ignore
        except ImportError:
            self._capture_error = "Scapy is not installed"
            return False

        kwargs = {"prn": self._handle_scapy_packet, "store": False, "timeout": 1}
        if self.interface:
            kwargs["iface"] = self.interface
        try:
            while not self._stop.is_set():
                sniff(filter=PASSIVE_PROTOCOL_BPF_FILTER, **kwargs)
            return True
        except Exception as error:
            self._emit_status(
                f"[PASSIVE LISTENER] BPF capture unavailable ({error}); "
                "retrying with a packet predicate",
                level=logging.WARNING,
            )
            try:
                while not self._stop.is_set():
                    sniff(lfilter=self._is_supported_packet, **kwargs)
                return True
            except Exception as fallback_error:
                self._capture_error = str(fallback_error)
                return False

    def _run(self) -> None:
        try:
            if not self._capture_with_scapy() and not self._stop.is_set():
                self._mark_capture_unavailable(
                    self._capture_error or "packet capture could not be started"
                )
        finally:
            self._emit_status("[PASSIVE LISTENER] Capture worker stopped")
