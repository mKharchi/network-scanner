"""Device Classification and Multi-Protocol Fingerprinting Engine.

Decouples protocol parsing from classification logic to infer:
- OS Hint (Windows, macOS, iOS, Android, Linux, Embedded)
- Device Type (Workstation, Laptop, Mobile Device, Smart TV, Printer, Router, IoT)
- Model Hint (e.g. MacBookPro16,2, iPhone14,2)
with calibrated confidence metrics and comprehensive evidence chains.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

# Known DHCP Parameter Request List (Option 55) Signatures
DHCP_PRL_SIGNATURES: list[dict[str, Any]] = [
    {
        "os_hint": "Windows",
        "device_type": "Workstation",
        "confidence": 0.85,
        "evidence": "dhcp.prl.windows",
        "match": lambda prl: isinstance(prl, list) and {1, 3, 6, 15, 31, 43}.issubset(set(prl)),
    },
    {
        "os_hint": "macOS / iOS",
        "device_type": "Apple Device",
        "confidence": 0.80,
        "evidence": "dhcp.prl.apple",
        "match": lambda prl: isinstance(prl, list) and {1, 3, 6, 15, 119, 252}.issubset(set(prl)),
    },
    {
        "os_hint": "Android",
        "device_type": "Mobile Device",
        "confidence": 0.80,
        "evidence": "dhcp.prl.android",
        "match": lambda prl: isinstance(prl, list) and {1, 3, 6, 15, 26, 28, 51, 58, 59, 43}.issubset(set(prl)),
    },
]

# Hostname Heuristic Patterns
HOSTNAME_PATTERNS: list[tuple[re.Pattern, str, str | None, str | None, float, str]] = [
    # (regex, os_hint, device_type, model_hint, confidence, evidence)
    (re.compile(r"^DESKTOP-[A-Z0-9]{5,8}$", re.IGNORECASE), "Windows", "Workstation", None, 0.88, "hostname.windows_desktop"),
    (re.compile(r"^LAPTOP-[A-Z0-9]{5,8}$", re.IGNORECASE), "Windows", "Laptop", None, 0.88, "hostname.windows_laptop"),
    (re.compile(r"^WIN-[A-Z0-9]{5,10}$", re.IGNORECASE), "Windows", "Workstation", None, 0.85, "hostname.windows_generic"),
    (re.compile(r"iphone", re.IGNORECASE), "iOS", "Mobile Device", "iPhone", 0.90, "hostname.iphone"),
    (re.compile(r"ipad", re.IGNORECASE), "iPadOS", "Tablet", "iPad", 0.90, "hostname.ipad"),
    (re.compile(r"macbook[ -]?pro", re.IGNORECASE), "macOS", "Laptop", "MacBook Pro", 0.92, "hostname.macbook_pro"),
    (re.compile(r"macbook[ -]?air", re.IGNORECASE), "macOS", "Laptop", "MacBook Air", 0.92, "hostname.macbook_air"),
    (re.compile(r"imac", re.IGNORECASE), "macOS", "Desktop", "iMac", 0.92, "hostname.imac"),
    (re.compile(r"mac[ -]?mini", re.IGNORECASE), "macOS", "Desktop", "Mac mini", 0.92, "hostname.mac_mini"),
    (re.compile(r"galaxy[ -]?(s\d+|note\d+|a\d+|tab|z)", re.IGNORECASE), "Android", "Mobile Device", None, 0.88, "hostname.samsung_galaxy"),
    (re.compile(r"pixel[ -]?\d+", re.IGNORECASE), "Android", "Mobile Device", "Google Pixel", 0.90, "hostname.google_pixel"),
    (re.compile(r"(direct-.*[a-z0-9]|hp-print|epson|brother|canon|xerox|kyocera)", re.IGNORECASE), "Embedded", "Printer", None, 0.90, "hostname.printer"),
    (re.compile(r"(bravia|samsung.*tv|lg.*tv|roku|firetv|appletv)", re.IGNORECASE), None, "Smart TV", None, 0.85, "hostname.smart_tv"),
    (re.compile(r"(sonos|echo|homepod|soundbar)", re.IGNORECASE), "Embedded", "Audio Device", None, 0.85, "hostname.audio"),
]


def classify_dhcp_evidence(
    vendor_class: str | None = None,
    parameter_request_list: list[int] | None = None,
    hostname: str | None = None,
    client_id: str | None = None,
) -> dict[str, Any]:
    """Infer OS, device type, and confidence from DHCP packet attributes."""
    result: dict[str, Any] = {
        "os_hint": None,
        "device_type": None,
        "model_hint": None,
        "confidence": 0.0,
        "evidence": [],
    }

    # 1. Vendor Class Identifier (Option 60)
    if vendor_class:
        clean_vc = vendor_class.strip()
        result["evidence"].append(f"dhcp.vendor_class:{clean_vc}")

        if clean_vc.startswith("MSFT 5.0") or clean_vc.startswith("MSFT 98") or clean_vc.startswith("MSFT"):
            result["os_hint"] = "Windows"
            result["device_type"] = "Workstation"
            result["confidence"] = 0.92
            result["evidence"].append("dhcp.vendor_class.microsoft")
        elif "android-dhcp" in clean_vc.lower():
            result["os_hint"] = "Android"
            result["device_type"] = "Mobile Device"
            result["confidence"] = 0.95
            result["evidence"].append("dhcp.vendor_class.android")
        elif "apple" in clean_vc.lower() or clean_vc.startswith("AAPL"):
            result["os_hint"] = "Apple OS"
            result["device_type"] = "Apple Device"
            result["confidence"] = 0.90
            result["evidence"].append("dhcp.vendor_class.apple")
        elif "cisco" in clean_vc.lower():
            result["device_type"] = "Network Device"
            result["confidence"] = 0.85
            result["evidence"].append("dhcp.vendor_class.cisco")
        elif "printer" in clean_vc.lower() or "hp-jetdirect" in clean_vc.lower():
            result["device_type"] = "Printer"
            result["os_hint"] = "Embedded"
            result["confidence"] = 0.95
            result["evidence"].append("dhcp.vendor_class.printer")

    # 2. Parameter Request List (Option 55)
    if parameter_request_list:
        for prl_sig in DHCP_PRL_SIGNATURES:
            try:
                if prl_sig["match"](parameter_request_list):
                    result["evidence"].append(prl_sig["evidence"])
                    if result["os_hint"] == prl_sig["os_hint"]:
                        # Multi-indicator synergy boosts confidence
                        result["confidence"] = min(0.99, result["confidence"] + 0.06)
                    elif not result["os_hint"]:
                        result["os_hint"] = prl_sig["os_hint"]
                        result["device_type"] = result["device_type"] or prl_sig.get("device_type")
                        result["confidence"] = max(result["confidence"], prl_sig["confidence"])
                    break
            except Exception:
                pass

    # 3. Hostname Heuristics
    if hostname:
        host_eval = evaluate_hostname_heuristics(hostname)
        if host_eval.get("os_hint"):
            result["evidence"].extend(host_eval["evidence"])
            if result["os_hint"] and result["os_hint"].lower() in host_eval["os_hint"].lower():
                result["confidence"] = min(0.99, result["confidence"] + 0.05)
            elif not result["os_hint"]:
                result["os_hint"] = host_eval["os_hint"]
                result["confidence"] = max(result["confidence"], host_eval["confidence"])
        if host_eval.get("device_type"):
            result["device_type"] = host_eval["device_type"]
        if host_eval.get("model_hint"):
            result["model_hint"] = host_eval["model_hint"]

    return result


def evaluate_hostname_heuristics(hostname: str) -> dict[str, Any]:
    """Evaluate hostname patterns for device and OS hints."""
    result: dict[str, Any] = {
        "os_hint": None,
        "device_type": None,
        "model_hint": None,
        "confidence": 0.0,
        "evidence": [],
    }
    if not hostname:
        return result

    clean_hostname = hostname.strip().rstrip(".local")
    for pattern, os_hint, device_type, model_hint, conf, evidence_tag in HOSTNAME_PATTERNS:
        if pattern.search(clean_hostname):
            result["os_hint"] = os_hint
            result["device_type"] = device_type
            result["model_hint"] = model_hint
            result["confidence"] = conf
            result["evidence"].append(evidence_tag)
            break
    return result


def classify_mdns_evidence(
    service_type: str | None = None,
    service_name: str | None = None,
    txt_records: Mapping[str, str] | None = None,
    hostname: str | None = None,
) -> dict[str, Any]:
    """Extract OS, Model, and Service hints from mDNS announcements."""
    result: dict[str, Any] = {
        "os_hint": None,
        "device_type": None,
        "model_hint": None,
        "confidence": 0.0,
        "evidence": [],
    }
    txt = txt_records or {}

    # Check for Apple Device Info model (e.g. model=MacBookPro16,2, osxvers=25)
    if "model" in txt:
        raw_model = txt["model"].strip()
        result["model_hint"] = raw_model
        result["evidence"].append(f"mdns.txt.model:{raw_model}")
        result["confidence"] = 0.95

        if raw_model.startswith("MacBook"):
            result["os_hint"] = "macOS"
            result["device_type"] = "MacBook"
        elif raw_model.startswith("Mac"):
            result["os_hint"] = "macOS"
            result["device_type"] = "Mac Desktop"
        elif raw_model.startswith("iPhone"):
            result["os_hint"] = "iOS"
            result["device_type"] = "iPhone"
        elif raw_model.startswith("iPad"):
            result["os_hint"] = "iPadOS"
            result["device_type"] = "iPad"
        elif raw_model.startswith("AppleTV"):
            result["os_hint"] = "tvOS"
            result["device_type"] = "Apple TV"

    if "osxvers" in txt:
        result["os_hint"] = "macOS"
        result["evidence"].append(f"mdns.txt.osxvers:{txt['osxvers']}")
        result["confidence"] = max(result["confidence"], 0.90)

    # Check service types
    if service_type:
        st = service_type.lower()
        if "_dosvc._tcp" in st:
            result["os_hint"] = "Windows"
            result["device_type"] = result["device_type"] or "Workstation"
            result["confidence"] = max(result["confidence"], 0.90)
            result["evidence"].append("mdns.service.dosvc")
        elif "_airplay._tcp" in st or "_raop._tcp" in st:
            result["evidence"].append("mdns.service.airplay")
            if not result["os_hint"]:
                result["os_hint"] = "Apple OS"
                result["confidence"] = max(result["confidence"], 0.85)
        elif "_googlecast._tcp" in st:
            result["device_type"] = "Cast Device"
            result["evidence"].append("mdns.service.googlecast")
            result["confidence"] = max(result["confidence"], 0.88)
        elif "_ipp._tcp" in st or "_printer._tcp" in st or "_pdl-datastream._tcp" in st:
            result["device_type"] = "Printer"
            result["evidence"].append("mdns.service.printer")
            result["confidence"] = max(result["confidence"], 0.92)
        elif "_adb._tcp" in st:
            result["os_hint"] = "Android"
            result["device_type"] = "Android Device"
            result["evidence"].append("mdns.service.adb")
            result["confidence"] = max(result["confidence"], 0.95)
        elif "_spotify-connect._tcp" in st:
            result["evidence"].append("mdns.service.spotify_connect")

    return result


def classify_ssdp_evidence(
    server_header: str | None = None,
    device_type_urn: str | None = None,
    location: str | None = None,
) -> dict[str, Any]:
    """Extract OS and Device Type hints from SSDP/UPnP advertisements."""
    result: dict[str, Any] = {
        "os_hint": None,
        "device_type": None,
        "model_hint": None,
        "confidence": 0.0,
        "evidence": [],
    }

    if server_header:
        srv = server_header.strip()
        result["evidence"].append(f"ssdp.server:{srv}")

        if "Windows" in srv or "Microsoft" in srv:
            result["os_hint"] = "Windows"
            result["confidence"] = 0.85
            result["evidence"].append("ssdp.server.windows")
        elif "Linux" in srv:
            result["os_hint"] = "Linux"
            result["confidence"] = 0.75
            result["evidence"].append("ssdp.server.linux")
        elif "Darwin" in srv or "Mac OS" in srv:
            result["os_hint"] = "macOS"
            result["confidence"] = 0.85
            result["evidence"].append("ssdp.server.darwin")
        elif "Roku" in srv:
            result["device_type"] = "Roku Streaming Device"
            result["confidence"] = 0.95
            result["evidence"].append("ssdp.server.roku")
        elif "Sonos" in srv:
            result["device_type"] = "Sonos Speaker"
            result["confidence"] = 0.95
            result["evidence"].append("ssdp.server.sonos")

    if device_type_urn:
        urn = device_type_urn.lower()
        if "printer" in urn:
            result["device_type"] = "Printer"
            result["confidence"] = max(result["confidence"], 0.90)
            result["evidence"].append("ssdp.urn.printer")
        elif "mediaserver" in urn or "mediarenderer" in urn:
            result["device_type"] = result["device_type"] or "Media Device"
            result["evidence"].append("ssdp.urn.media")
        elif "internetgatewaydevice" in urn or "router" in urn:
            result["device_type"] = "Router / Gateway"
            result["confidence"] = max(result["confidence"], 0.92)
            result["evidence"].append("ssdp.urn.router")

    return result


def apply_classification_to_device(device: Any, vendors_db: Any = None) -> None:
    """Evaluate multi-layer evidence and populate device classification fields."""
    # Check OUI vendor
    if not device.vendor and device.mac_address and vendors_db:
        try:
            import oui
            vendor = oui.get_vendor(device.mac_address, vendors_db)
            if vendor:
                device.set_vendor(vendor, source="oui")
        except Exception:
            pass

    # Synergy across layers
    # If DHCP said Windows, SSDP said Windows, and mDNS had dosvc -> high confidence
    ev = device.evidence
    os_ev = ev.get("os_hint", [])

    has_windows_dhcp = any("microsoft" in s.lower() or "msft" in s.lower() for s in os_ev)
    has_windows_llmnr = "llmnr" in device.protocols_seen or "nbns" in device.protocols_seen
    has_windows_mdns = any("dosvc" in s.lower() for s in os_ev)
    has_windows_ssdp = any("windows" in s.lower() for s in os_ev)

    if has_windows_dhcp or (has_windows_llmnr and (has_windows_mdns or has_windows_ssdp)):
        conf = 0.85
        if has_windows_dhcp and has_windows_llmnr:
            conf = 0.95
        if has_windows_dhcp and has_windows_llmnr and (has_windows_mdns or has_windows_ssdp):
            conf = 0.98
        device.os_classification.update_if_better("Windows", conf, "synergy.windows_multi_protocol")
        device.os_hint = device.os_classification.value
        if not device.device_type:
            device.device_type_classification.update_if_better("Windows Workstation", conf, "synergy.windows_workstation")
            device.device_type = device.device_type_classification.value

    # Hostname heuristics fallback if still unclassified
    if not device.os_hint and device.hostname:
        eval_host = evaluate_hostname_heuristics(device.hostname)
        if eval_host.get("os_hint"):
            device.os_classification.update_if_better(eval_host["os_hint"], eval_host["confidence"], "hostname_heuristics")
            device.os_hint = device.os_classification.value
        if eval_host.get("device_type") and not device.device_type:
            device.device_type_classification.update_if_better(eval_host["device_type"], eval_host["confidence"], "hostname_heuristics")
            device.device_type = device.device_type_classification.value
        if eval_host.get("model_hint") and not device.model_hint:
            device.model_classification.update_if_better(eval_host["model_hint"], eval_host["confidence"], "hostname_heuristics")
            device.model_hint = device.model_classification.value
