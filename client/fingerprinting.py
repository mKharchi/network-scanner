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
    """Extract OS, Model, Service, and Software hints from mDNS announcements."""
    result: dict[str, Any] = {
        "os_hint": None,
        "device_type": None,
        "model_hint": None,
        "confidence": 0.0,
        "evidence": [],
        "software_hints": [],
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
            result["software_hints"].append("Windows Delivery Optimization")
        elif "_airplay._tcp" in st or "_raop._tcp" in st:
            result["evidence"].append("mdns.service.airplay")
            result["software_hints"].append("AirPlay")
            if not result["os_hint"]:
                result["os_hint"] = "Apple OS"
                result["confidence"] = max(result["confidence"], 0.85)
        elif "_googlecast._tcp" in st:
            result["device_type"] = "Cast Device"
            result["evidence"].append("mdns.service.googlecast")
            result["confidence"] = max(result["confidence"], 0.88)
            result["software_hints"].append("Google Cast")
        elif "_ipp._tcp" in st or "_printer._tcp" in st or "_pdl-datastream._tcp" in st:
            result["device_type"] = "Printer"
            result["evidence"].append("mdns.service.printer")
            result["confidence"] = max(result["confidence"], 0.92)
            result["software_hints"].append("IPP / Network Print Service")
        elif "_adb._tcp" in st:
            result["os_hint"] = "Android"
            result["device_type"] = "Android Device"
            result["evidence"].append("mdns.service.adb")
            result["confidence"] = max(result["confidence"], 0.95)
            result["software_hints"].append("Android Debug Bridge (ADB)")
        elif "_spotify-connect._tcp" in st:
            result["evidence"].append("mdns.service.spotify_connect")
            result["software_hints"].append("Spotify Connect")
        elif "_smb._tcp" in st:
            result["software_hints"].append("SMB File Sharing")
        elif "_ssh._tcp" in st:
            result["software_hints"].append("SSH Server")
        elif "_http._tcp" in st or "_https._tcp" in st:
            result["software_hints"].append("Web Server")

    return result


def classify_ssdp_evidence(
    server_header: str | None = None,
    device_type_urn: str | None = None,
    location: str | None = None,
) -> dict[str, Any]:
    """Extract OS, Device Type, and Software hints from SSDP/UPnP advertisements."""
    result: dict[str, Any] = {
        "os_hint": None,
        "device_type": None,
        "model_hint": None,
        "confidence": 0.0,
        "evidence": [],
        "software_hints": [],
    }

    if server_header:
        srv = server_header.strip()
        srv_lower = srv.lower()
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
            result["software_hints"].append("Roku OS")
        elif "Sonos" in srv:
            result["device_type"] = "Sonos Speaker"
            result["confidence"] = 0.95
            result["evidence"].append("ssdp.server.sonos")
            result["software_hints"].append("Sonos")

        if "utorrent" in srv_lower:
            result["software_hints"].append("uTorrent")
        elif "bittorrent" in srv_lower:
            result["software_hints"].append("BitTorrent")
        elif "plex" in srv_lower:
            result["software_hints"].append("Plex Media Server")
        elif "kodi" in srv_lower:
            result["software_hints"].append("Kodi")

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


# Known SNI Domain Classification Rules
SNI_DOMAIN_RULES: list[dict[str, Any]] = [
    {
        "pattern": re.compile(r"(apple\.com|icloud\.com|aaplimg\.com|apple-cloudkit\.com|push\.apple\.com|itunes\.apple\.com|me\.com)$", re.IGNORECASE),
        "os_hint": "Apple OS",
        "device_type": "Apple Device",
        "confidence": 0.92,
        "evidence": "sni.apple_services",
    },
    {
        "pattern": re.compile(r"(windowsupdate\.com|update\.microsoft\.com|msftncsi\.com|telemetry\.microsoft\.com|live\.com|office\.com|office365\.com|azure\.com|microsoft\.com|xboxlive\.com)$", re.IGNORECASE),
        "os_hint": "Windows",
        "device_type": "Workstation",
        "confidence": 0.90,
        "evidence": "sni.microsoft_services",
    },
    {
        "pattern": re.compile(r"(android\.com|googleapis\.com|googleplay\.com|gvt1\.com|ggpht\.com|gstatic\.com|googleusercontent\.com)$", re.IGNORECASE),
        "os_hint": "Android",
        "device_type": "Mobile Device",
        "confidence": 0.88,
        "evidence": "sni.google_android_services",
    },
    {
        "pattern": re.compile(r"(samsungcloud\.com|samsungqbe\.com|samsungosp\.com|samsung\.com)$", re.IGNORECASE),
        "os_hint": "Android",
        "device_type": "Samsung Device",
        "confidence": 0.90,
        "evidence": "sni.samsung_services",
    },
    {
        "pattern": re.compile(r"(netflix\.com|nflxvideo\.net|nflxext\.com|roku\.com|hulu\.com|disneyplus\.com|spotify\.com|lgtvcommon\.com|bravia\.sony|tivo\.com|smarttv)$", re.IGNORECASE),
        "device_type": "Smart TV / Media",
        "confidence": 0.92,
        "evidence": "sni.streaming_media",
    },
    {
        "pattern": re.compile(r"(tuya\.com|tuyaeu\.com|smartthings\.com|tplinkcloud\.com|ring\.com|nest\.com|philips-hue\.com|espressif\.com|wyze\.com|arlo\.com|blink\.com|mi-cloud\.com|yeelight\.com)$", re.IGNORECASE),
        "os_hint": "Embedded",
        "device_type": "IoT Device",
        "confidence": 0.95,
        "evidence": "sni.iot_cloud",
    },
    {
        "pattern": re.compile(r"(playstation\.net|playstation\.com|nintendo\.net|nintendo\.com|steamcommunity\.com|steampowered\.com)$", re.IGNORECASE),
        "device_type": "Gaming Console",
        "confidence": 0.92,
        "evidence": "sni.gaming_services",
    },
    {
        "pattern": re.compile(r"(hpconnected\.com|hpsmart\.com|epsonconnect\.com|canon-c-asdp\.com|brother\.com)$", re.IGNORECASE),
        "os_hint": "Embedded",
        "device_type": "Printer",
        "confidence": 0.95,
        "evidence": "sni.printer_cloud",
    },
]

# Known JA3 Hashes Fingerprint Map
JA3_FINGERPRINT_MAP: dict[str, dict[str, Any]] = {
    # Windows Chrome / Edge
    "b32309a26951912be7dba376398abc3b": {"os_hint": "Windows", "device_type": "Workstation", "client_stack": "Chrome/Edge on Windows", "confidence": 0.90},
    "66918128f1b9b03303d77c6f2eefd128": {"os_hint": "Windows", "device_type": "Workstation", "client_stack": "Chrome on Windows", "confidence": 0.90},
    "cd08e31494f9531f560d64c695473da9": {"os_hint": "Windows", "device_type": "Workstation", "client_stack": "Edge on Windows", "confidence": 0.90},
    # iOS Safari
    "51c64c77e60f39ac303c1b303e0e54b8": {"os_hint": "iOS", "device_type": "Mobile Device", "client_stack": "Safari on iOS", "confidence": 0.92},
    "b845089720b0339b3346ff1755a90714": {"os_hint": "iOS", "device_type": "iPhone", "client_stack": "iOS MobileSafari", "confidence": 0.92},
    "161b45ecdd3a32f6a7ae8991206cc4c6": {"os_hint": "iOS", "device_type": "Apple Device", "client_stack": "iOS Background TLS", "confidence": 0.90},
    # macOS Safari
    "773906b0efdefa24a7f2b8eb69858561": {"os_hint": "macOS", "device_type": "Mac Desktop/Laptop", "client_stack": "Safari on macOS", "confidence": 0.92},
    "21c5798da20c0f997dbba7cb0f19ae39": {"os_hint": "macOS", "device_type": "Apple Device", "client_stack": "macOS System TLS", "confidence": 0.90},
    # Android Chrome / OkHttp
    "15af977ce251252b42433092782e407e": {"os_hint": "Android", "device_type": "Mobile Device", "client_stack": "OkHttp / Android App", "confidence": 0.92},
    "8d70923055490717277e9caad8097b69": {"os_hint": "Android", "device_type": "Mobile Device", "client_stack": "Chrome on Android", "confidence": 0.90},
    "a0e9f5d64349fb13191bc781f81f42e1": {"os_hint": "Android", "device_type": "Mobile Device", "client_stack": "Android System Webview", "confidence": 0.88},
    # Linux / Python / Tools
    "0cce74b019b7d90e0c8ff0f81d11ff31": {"os_hint": "Linux", "device_type": "Workstation/Server", "client_stack": "Python requests / urllib", "confidence": 0.85},
    "71b78292c730823296dd5f311c107127": {"os_hint": "Linux", "device_type": "Workstation", "client_stack": "curl / libcurl", "confidence": 0.85},
    # IoT / Embedded
    "714e8679d67bf3c0beff3253b26639fc": {"os_hint": "Embedded", "device_type": "IoT Device", "client_stack": "ESP32 / mbedTLS", "confidence": 0.94},
    "ade138fba3302132b2fa141fad3a94f3": {"os_hint": "Embedded", "device_type": "IoT Device", "client_stack": "wolfSSL Embedded", "confidence": 0.94},
}


def classify_sni_evidence(sni_host: str | None) -> dict[str, Any]:
    """Extract OS, device type, and application hints from observed TLS SNI hostname."""
    result: dict[str, Any] = {
        "os_hint": None,
        "device_type": None,
        "model_hint": None,
        "confidence": 0.0,
        "evidence": [],
    }
    if not sni_host:
        return result

    clean_sni = sni_host.strip().lower()
    for rule in SNI_DOMAIN_RULES:
        if rule["pattern"].search(clean_sni):
            result["os_hint"] = rule.get("os_hint")
            result["device_type"] = rule.get("device_type")
            result["confidence"] = rule.get("confidence", 0.85)
            result["evidence"].append(f"{rule['evidence']}:{clean_sni}")
            break

    return result


def classify_ja3_evidence(ja3_hash: str | None, ja3_string: str | None = None) -> dict[str, Any]:
    """Extract OS and device hints from TLS JA3 fingerprint hash and parameter structure."""
    result: dict[str, Any] = {
        "os_hint": None,
        "device_type": None,
        "client_stack": None,
        "confidence": 0.0,
        "evidence": [],
    }
    if not ja3_hash:
        return result

    clean_hash = ja3_hash.strip().lower()
    match = JA3_FINGERPRINT_MAP.get(clean_hash)
    if match:
        result["os_hint"] = match.get("os_hint")
        result["device_type"] = match.get("device_type")
        result["client_stack"] = match.get("client_stack")
        result["confidence"] = match.get("confidence", 0.85)
        result["evidence"].append(f"ja3.matched:{clean_hash}")
    elif ja3_string:
        # Heuristic inspection of JA3 parameter string
        # e.g., TLS 1.3 only with minimal extensions -> embedded/IoT
        parts = ja3_string.split(",")
        if len(parts) >= 3:
            ciphers = parts[1].split("-") if parts[1] else []
            extensions = parts[2].split("-") if parts[2] else []
            if len(ciphers) <= 4 and len(extensions) <= 5:
                result["os_hint"] = "Embedded"
                result["device_type"] = "IoT Device"
                result["confidence"] = 0.75
                result["evidence"].append(f"ja3.heuristic.minimal_tls:{clean_hash}")

    return result


def classify_dns_evidence(domain: str | None) -> dict[str, Any]:
    """Extract OS and device hints from passive DNS queries."""
    if not domain:
        return {"os_hint": None, "device_type": None, "confidence": 0.0, "evidence": []}
    return classify_sni_evidence(domain)


def classify_traffic_evidence(traffic_profile: Mapping[str, Any] | None) -> dict[str, Any]:
    """Infer device behavioral characteristics from traffic profile metrics."""
    result: dict[str, Any] = {
        "behavioral_pattern": None,
        "device_type_hint": None,
        "confidence": 0.0,
        "evidence": [],
    }
    if not traffic_profile or not isinstance(traffic_profile, Mapping):
        return result

    pattern = traffic_profile.get("behavioral_pattern")
    if pattern:
        result["behavioral_pattern"] = pattern
        result["evidence"].append(f"traffic.pattern:{pattern}")

        if pattern == "HEAVY_STREAMING_TRANSFER":
            result["device_type_hint"] = "Smart TV / Workstation"
            result["confidence"] = 0.70
        elif pattern == "BURST_TELEMETRY":
            result["device_type_hint"] = "IoT Device / Mobile"
            result["confidence"] = 0.75

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

    # SNI domain classification
    if hasattr(device, "sni_domains") and device.sni_domains:
        for sni in device.sni_domains:
            sni_eval = classify_sni_evidence(sni)
            if sni_eval.get("os_hint"):
                device.os_classification.update_if_better(sni_eval["os_hint"], sni_eval["confidence"], f"sni.{sni}")
                device.os_hint = device.os_classification.value
            if sni_eval.get("device_type"):
                device.device_type_classification.update_if_better(sni_eval["device_type"], sni_eval["confidence"], f"sni.{sni}")
                device.device_type = device.device_type_classification.value

    # JA3 fingerprint classification
    if hasattr(device, "ja3_hashes") and device.ja3_hashes:
        for ja3 in device.ja3_hashes:
            ja3_eval = classify_ja3_evidence(ja3)
            if ja3_eval.get("os_hint"):
                device.os_classification.update_if_better(ja3_eval["os_hint"], ja3_eval["confidence"], f"ja3.{ja3[:8]}")
                device.os_hint = device.os_classification.value
            if ja3_eval.get("device_type"):
                device.device_type_classification.update_if_better(ja3_eval["device_type"], ja3_eval["confidence"], f"ja3.{ja3[:8]}")
                device.device_type = device.device_type_classification.value
            if ja3_eval.get("client_stack"):
                device.add_software_hint(ja3_eval["client_stack"])

    # Passive DNS queries classification
    if hasattr(device, "dns_queries") and device.dns_queries and not device.os_hint:
        for domain in device.dns_queries:
            dns_eval = classify_dns_evidence(domain)
            if dns_eval.get("os_hint"):
                device.os_classification.update_if_better(dns_eval["os_hint"], dns_eval["confidence"], f"dns.{domain}")
                device.os_hint = device.os_classification.value
            if dns_eval.get("device_type") and not device.device_type:
                device.device_type_classification.update_if_better(dns_eval["device_type"], dns_eval["confidence"], f"dns.{domain}")
                device.device_type = device.device_type_classification.value

    # Traffic profile heuristic
    if hasattr(device, "traffic_profile") and device.traffic_profile and not device.device_type:
        tf_eval = classify_traffic_evidence(device.traffic_profile)
        if tf_eval.get("device_type_hint"):
            device.device_type_classification.update_if_better(tf_eval["device_type_hint"], tf_eval["confidence"], "traffic.behavior")
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
