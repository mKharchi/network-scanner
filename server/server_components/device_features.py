"""Device Observation Feature Extractor for ML Device Classification.

Extracts normalized, leakage-free numeric and categorical feature vectors
from raw device records, observations, and protocol signatures according to
docs/ml/plan.md (Phase 5).
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# Supported Canonical Device Classification Categories (v1)
CLASSIFICATION_CLASSES: Tuple[str, ...] = (
    "WINDOWS_WORKSTATION",
    "APPLE_WORKSTATION",
    "ANDROID_MOBILE",
    "APPLE_MOBILE",
    "SMART_TV_MEDIA",
    "PRINTER",
    "NETWORK_DEVICE",
    "IOT_DEVICE",
    "UNKNOWN",
)

# Known Vendor Families Mapping
VENDOR_FAMILY_MAP: Dict[str, Sequence[str]] = {
    "apple": ("apple", "aapl"),
    "microsoft": ("microsoft", "msft"),
    "google": ("google", "nest", "alphabet"),
    "samsung": ("samsung", "sec"),
    "xiaomi": ("xiaomi", "redmi", "poco", "chongqing"),
    "huawei": ("huawei", "honor"),
    "hp": ("hp", "hewlett", "hewlett-packard", "hp-jetdirect"),
    "canon": ("canon",),
    "epson": ("epson", "seiko"),
    "brother": ("brother",),
    "xerox": ("xerox",),
    "cisco": ("cisco", "linksys", "meraki"),
    "tp_link": ("tp-link", "tplink"),
    "netgear": ("netgear",),
    "ubiquiti": ("ubiquiti", "unifi"),
    "synology": ("synology",),
    "qnap": ("qnap",),
    "espressif": ("espressif", "esp32", "esp8266"),
    "raspberry_pi": ("raspberry", "raspberry pi"),
    "sony": ("sony",),
    "lg": ("lg", "lg electronics"),
    "roku": ("roku",),
    "amazon": ("amazon", "lab126"),
    "sonos": ("sonos",),
    "tuya": ("tuya",),
    "philips": ("philips", "signify"),
    "dell": ("dell",),
    "lenovo": ("lenovo", "motorola"),
    "intel": ("intel",),
    "asus": ("asus", "asustek"),
    "acer": ("acer",),
}

# Hostname Pattern Rules: (Regex Pattern, Category Hint, Subtype)
HOSTNAME_RULES: List[Tuple[re.Pattern, str, str]] = [
    (re.compile(r"^DESKTOP-[A-Z0-9]{4,10}$", re.IGNORECASE), "desktop_win", "workstation"),
    (re.compile(r"^LAPTOP-[A-Z0-9]{4,10}$", re.IGNORECASE), "laptop_win", "laptop"),
    (re.compile(r"^WIN-[A-Z0-9]{4,12}$", re.IGNORECASE), "win_generic", "workstation"),
    (re.compile(r"^(PC|WS|WORKSTATION)[-_][A-Z0-9]+$", re.IGNORECASE), "pc_generic", "workstation"),
    (re.compile(r"^(SRV|SERVER)[-_][A-Z0-9]+$", re.IGNORECASE), "server_generic", "server"),
    (re.compile(r"iphone", re.IGNORECASE), "iphone", "mobile"),
    (re.compile(r"ipad", re.IGNORECASE), "ipad", "tablet"),
    (re.compile(r"macbook[-_ ]?(pro|air)?", re.IGNORECASE), "macbook", "laptop"),
    (re.compile(r"(imac|mac[-_ ]?mini|mac[-_ ]?studio|mac[-_ ]?pro)", re.IGNORECASE), "mac_desktop", "workstation"),
    (re.compile(r"(galaxy[-_ ]?(s\d+|note|a\d+|tab|z|flip|fold)|samsung[-_ ]?sm)", re.IGNORECASE), "android_galaxy", "mobile"),
    (re.compile(r"pixel[-_ ]?\d+", re.IGNORECASE), "android_pixel", "mobile"),
    (re.compile(r"(redmi|xiaomi|poco|mi[-_ ]?\d+)", re.IGNORECASE), "android_xiaomi", "mobile"),
    (re.compile(r"(huawei|honor)[-_ ]?[a-z0-9]+", re.IGNORECASE), "android_huawei", "mobile"),
    (re.compile(r"(android|oneplus|oppo|vivo|realme)", re.IGNORECASE), "android_generic", "mobile"),
    (re.compile(r"(direct-.*[a-z0-9]|hp[-_ ]?print|epson|brother|canon|xerox|kyocera|laserjet|deskjet|officejet|printer)", re.IGNORECASE), "printer", "printer"),
    (re.compile(r"(bravia|samsung[-_ ]?tv|lg[-_ ]?tv|roku|firetv|appletv|chromecast|vizio|tcl[-_ ]?tv|smarttv|smart-tv|shield)", re.IGNORECASE), "smart_tv", "media"),
    (re.compile(r"(sonos|echo[-_ ]?dot|echo[-_ ]?show|homepod|soundbar|bose|jbl)", re.IGNORECASE), "audio", "media"),
    (re.compile(r"(esp[-_ ]?[0-9a-f]+|tasmota|shelly|hue[-_ ]?bridge|camera|cam[-_ ]\d+|ring[-_ ]?doorbell|nest[-_ ]?cam|matter|wemo)", re.IGNORECASE), "iot", "iot"),
    (re.compile(r"(router|gateway|switch|accesspoint|ap[-_ ]\d+|unifi|cisco|mikrotik|openwrt|pfsense)", re.IGNORECASE), "network_dev", "network"),
]

# DHCP Option 55 Signature Subsets
DHCP_OPT55_SIGNATURES: Dict[str, set[int]] = {
    "windows": {1, 3, 6, 15, 31, 43},
    "apple": {1, 3, 6, 15, 119, 252},
    "android": {1, 3, 6, 15, 26, 28, 51, 58, 59, 43},
    "printer": {1, 3, 6, 15, 43, 66, 67},
    "linux_generic": {1, 28, 2, 3, 15, 6, 119, 12, 44, 47, 26, 121, 42},
}


def normalize_vendor(vendor_name: Optional[str]) -> str:
    """Normalize vendor string into a clean lowercase vendor token."""
    if not vendor_name or not isinstance(vendor_name, str):
        return "unknown"
    cleaned = vendor_name.strip().lower()
    cleaned = re.sub(r"[,\.\(\)\'\"]", " ", cleaned)
    cleaned = re.sub(r"\b(inc|corp|corporation|ltd|limited|co|llc|gmbh|technologies|technology|systems|electronics)\b", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or "unknown"


def extract_vendor_family(vendor_name: Optional[str]) -> str:
    """Map vendor string to high-level vendor family."""
    normalized = normalize_vendor(vendor_name)
    if normalized in ("unknown", "none", "") or normalized.startswith("unknown") or "unknown" in normalized:
        return "unknown"

    for family, keywords in VENDOR_FAMILY_MAP.items():
        if any(keyword in normalized for keyword in keywords):
            return family
    return "other"


def extract_hostname_feature(hostname: Optional[str]) -> str:
    """Extract structural hostname class without memorizing specific device IDs."""
    if not hostname or not isinstance(hostname, str):
        return "unknown"
    clean_host = hostname.strip()
    if not clean_host:
        return "unknown"

    for pattern, feature_name, _ in HOSTNAME_RULES:
        if pattern.search(clean_host):
            return feature_name

    # Check generic characteristics
    if re.match(r"^[a-zA-Z0-9_-]+$", clean_host):
        if any(w in clean_host.lower() for w in ("phone", "mobile", "cel")):
            return "mobile_keyword"
        if any(w in clean_host.lower() for w in ("desk", "workstation", "station")):
            return "workstation_keyword"
        if any(w in clean_host.lower() for w in ("print", "scan", "plot")):
            return "printer_keyword"
        if any(w in clean_host.lower() for w in ("tab", "pad")):
            return "tablet_keyword"
        if any(w in clean_host.lower() for w in ("tv", "cast", "box", "media", "stick")):
            return "media_keyword"
        return "generic_alphanumeric"

    return "unknown"


def extract_dhcp_features(observations: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Extract normalized DHCP option fingerprints from observations."""
    dhcp_present = 0
    opt55_signature = "none"
    opt60_family = "none"
    has_dhcp_hostname = 0

    for obs in observations:
        raw_text = obs.get("raw_data") or ""
        protocol = str(obs.get("source_type") or obs.get("entry_type") or "").lower()

        is_dhcp = "dhcp" in protocol or "dhcp" in raw_text.lower()
        if not is_dhcp:
            continue

        dhcp_present = 1
        raw_dict = {}
        if isinstance(raw_text, str) and raw_text.startswith("{") and raw_text.endswith("}"):
            try:
                raw_dict = json.loads(raw_text)
            except Exception:
                raw_dict = {}
        elif isinstance(raw_text, dict):
            raw_dict = raw_text

        # Option 60: Vendor Class
        vc = str(raw_dict.get("vendor_class") or raw_dict.get("option_60") or "").lower()
        if vc:
            if "msft" in vc or "microsoft" in vc:
                opt60_family = "msft"
            elif "android" in vc:
                opt60_family = "android"
            elif "aapl" in vc or "apple" in vc:
                opt60_family = "apple"
            elif "cisco" in vc:
                opt60_family = "cisco"
            elif "hp" in vc or "jetdirect" in vc or "printer" in vc:
                opt60_family = "hp_printer"
            elif "roku" in vc:
                opt60_family = "roku"
            elif "espressif" in vc:
                opt60_family = "espressif"
            else:
                opt60_family = "other"

        # Option 55: Parameter Request List
        prl = raw_dict.get("parameter_request_list") or raw_dict.get("option_55") or []
        if isinstance(prl, list) and prl:
            prl_set = set(int(x) for x in prl if isinstance(x, (int, float, str)) and str(x).isdigit())
            for sig_name, required_opts in DHCP_OPT55_SIGNATURES.items():
                if required_opts.issubset(prl_set):
                    opt55_signature = sig_name
                    break

        if raw_dict.get("hostname") or raw_dict.get("option_12"):
            has_dhcp_hostname = 1

    return {
        "dhcp_present": dhcp_present,
        "dhcp_opt55_sig": opt55_signature,
        "dhcp_opt60_family": opt60_family,
        "dhcp_has_hostname": has_dhcp_hostname,
    }


def extract_mdns_features(observations: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Extract mDNS advertised service presence."""
    mdns_present = 0
    has_airplay = 0
    has_googlecast = 0
    has_printer = 0
    has_smb = 0
    has_apple_companion = 0
    has_spotify = 0
    has_iot = 0
    service_count = 0

    for obs in observations:
        raw_text = obs.get("raw_data") or ""
        protocol = str(obs.get("source_type") or obs.get("entry_type") or "").lower()

        is_mdns = "mdns" in protocol or "bonjour" in protocol or "mdns" in str(raw_text).lower()
        if not is_mdns:
            continue

        mdns_present = 1
        raw_str = str(raw_text).lower()

        if "_airplay._tcp" in raw_str or "_raop._tcp" in raw_str:
            has_airplay = 1
            service_count += 1
        if "_googlecast._tcp" in raw_str or "_googlerpc._tcp" in raw_str:
            has_googlecast = 1
            service_count += 1
        if any(p in raw_str for p in ("_printer._tcp", "_ipp._tcp", "_ipps._tcp", "_pdl-datastream._tcp", "_scanner._tcp")):
            has_printer = 1
            service_count += 1
        if "_smb._tcp" in raw_str or "_netbios._tcp" in raw_str:
            has_smb = 1
            service_count += 1
        if any(a in raw_str for a in ("_companion-link._tcp", "_apple-mobdev2._tcp", "_sleep-proxy._udp", "_rdlink._tcp")):
            has_apple_companion = 1
            service_count += 1
        if "_spotify-connect._tcp" in raw_str:
            has_spotify = 1
            service_count += 1
        if any(i in raw_str for i in ("_hap._tcp", "_hue._tcp", "_matter._tcp", "_mqtt._tcp", "_esphome._tcp", "_shelly._tcp")):
            has_iot = 1
            service_count += 1

    return {
        "mdns_present": mdns_present,
        "mdns_service_count": min(service_count, 10),
        "mdns_has_airplay": has_airplay,
        "mdns_has_googlecast": has_googlecast,
        "mdns_has_printer": has_printer,
        "mdns_has_smb": has_smb,
        "mdns_has_apple_companion": has_apple_companion,
        "mdns_has_spotify": has_spotify,
        "mdns_has_iot": has_iot,
    }


def extract_ssdp_features(observations: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Extract SSDP (UPnP) advertised server & device features."""
    ssdp_present = 0
    ssdp_is_media = 0
    ssdp_is_printer = 0
    ssdp_is_gateway = 0
    ssdp_is_smart_speaker = 0

    for obs in observations:
        raw_text = obs.get("raw_data") or ""
        protocol = str(obs.get("source_type") or obs.get("entry_type") or "").lower()

        is_ssdp = "ssdp" in protocol or "upnp" in protocol or "ssdp" in str(raw_text).lower()
        if not is_ssdp:
            continue

        ssdp_present = 1
        raw_str = str(raw_text).lower()

        if any(m in raw_str for m in ("mediarenderer", "mediaserver", "dial-multiscreen", "roku", "bravia", "vizio", "smarttv")):
            ssdp_is_media = 1
        if "printer" in raw_str or "printbasic" in raw_str:
            ssdp_is_printer = 1
        if any(g in raw_str for g in ("internetgatewaydevice", "landevice", "wfa-device", "wanipconnection")):
            ssdp_is_gateway = 1
        if any(s in raw_str for s in ("sonos", "soundtouch", "heos", "echo")):
            ssdp_is_smart_speaker = 1

    return {
        "ssdp_present": ssdp_present,
        "ssdp_is_media": ssdp_is_media,
        "ssdp_is_printer": ssdp_is_printer,
        "ssdp_is_gateway": ssdp_is_gateway,
        "ssdp_is_smart_speaker": ssdp_is_smart_speaker,
    }


def extract_llmnr_nbns_features(observations: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Extract LLMNR & NBNS presence features."""
    llmnr_present = 0
    nbns_present = 0

    for obs in observations:
        raw_text = str(obs.get("raw_data") or "").lower()
        protocol = str(obs.get("source_type") or obs.get("entry_type") or "").lower()

        if "llmnr" in protocol or "llmnr" in raw_text:
            llmnr_present = 1
        if "nbns" in protocol or "netbios" in protocol or "nbns" in raw_text:
            nbns_present = 1

    return {
        "llmnr_present": llmnr_present,
        "nbns_present": nbns_present,
    }


def extract_device_features(
    device_data: Mapping[str, Any],
    observations: Optional[Sequence[Mapping[str, Any]]] = None,
    client_metadata: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Extract a complete, normalized feature dictionary for a network device.

    Guarantees strict privacy / anti-leakage:
    - Strips MAC, IP, DB ID, and unique hardware serials.
    - Yields clean numerical & categorical properties.
    """
    obs_list = list(observations or [])
    vendor = normalize_vendor(device_data.get("vendor"))
    vendor_family = extract_vendor_family(device_data.get("vendor"))
    hostname_feature = extract_hostname_feature(device_data.get("hostname"))

    dhcp_feats = extract_dhcp_features(obs_list)
    mdns_feats = extract_mdns_features(obs_list)
    ssdp_feats = extract_ssdp_features(obs_list)
    llmnr_nbns_feats = extract_llmnr_nbns_features(obs_list)

    # Observed protocols set
    protocols_seen = set()
    for obs in obs_list:
        st = obs.get("source_type")
        if st:
            protocols_seen.add(str(st).lower())
    if dhcp_feats["dhcp_present"]:
        protocols_seen.add("dhcp")
    if mdns_feats["mdns_present"]:
        protocols_seen.add("mdns")
    if ssdp_feats["ssdp_present"]:
        protocols_seen.add("ssdp")
    if llmnr_nbns_feats["llmnr_present"]:
        protocols_seen.add("llmnr")
    if llmnr_nbns_feats["nbns_present"]:
        protocols_seen.add("nbns")

    # Managed Client OS check (if device is a registered managed client)
    is_managed_client = 1 if client_metadata else (1 if device_data.get("is_managed") else 0)
    client_os_family = "none"
    if client_metadata:
        os_sys = str(client_metadata.get("os_system") or "").lower()
        if "windows" in os_sys:
            client_os_family = "windows"
        elif "darwin" in os_sys or "macos" in os_sys or "mac" in os_sys:
            client_os_family = "macos"
        elif "linux" in os_sys:
            client_os_family = "linux"

    observation_count = len(obs_list)

    return {
        "features_version": "v1",
        "vendor": vendor,
        "vendor_family": vendor_family,
        "hostname_pattern": hostname_feature,
        "dhcp_present": dhcp_feats["dhcp_present"],
        "dhcp_opt55_sig": dhcp_feats["dhcp_opt55_sig"],
        "dhcp_opt60_family": dhcp_feats["dhcp_opt60_family"],
        "dhcp_has_hostname": dhcp_feats["dhcp_has_hostname"],
        "mdns_present": mdns_feats["mdns_present"],
        "mdns_service_count": mdns_feats["mdns_service_count"],
        "mdns_has_airplay": mdns_feats["mdns_has_airplay"],
        "mdns_has_googlecast": mdns_feats["mdns_has_googlecast"],
        "mdns_has_printer": mdns_feats["mdns_has_printer"],
        "mdns_has_smb": mdns_feats["mdns_has_smb"],
        "mdns_has_apple_companion": mdns_feats["mdns_has_apple_companion"],
        "mdns_has_spotify": mdns_feats["mdns_has_spotify"],
        "mdns_has_iot": mdns_feats["mdns_has_iot"],
        "ssdp_present": ssdp_feats["ssdp_present"],
        "ssdp_is_media": ssdp_feats["ssdp_is_media"],
        "ssdp_is_printer": ssdp_feats["ssdp_is_printer"],
        "ssdp_is_gateway": ssdp_feats["ssdp_is_gateway"],
        "ssdp_is_smart_speaker": ssdp_feats["ssdp_is_smart_speaker"],
        "llmnr_present": llmnr_nbns_feats["llmnr_present"],
        "nbns_present": llmnr_nbns_feats["nbns_present"],
        "protocol_count": len(protocols_seen),
        "observation_count": min(observation_count, 100),
        "is_managed_client": is_managed_client,
        "client_os_family": client_os_family,
    }
