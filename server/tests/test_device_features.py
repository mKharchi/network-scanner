"""Unit tests for Device Feature Extraction and Normalization."""

import sys
import types
import unittest
from pathlib import Path

SERVER_DIRECTORY = Path(__file__).resolve().parents[1]
if str(SERVER_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SERVER_DIRECTORY))

try:
    import mysql.connector  # noqa: F401
except ModuleNotFoundError:
    mysql_module = types.ModuleType("mysql")
    mysql_module.connector = types.ModuleType("mysql.connector")
    sys.modules["mysql"] = mysql_module
    sys.modules["mysql.connector"] = mysql_module.connector

from server_components.device_features import (
    CLASSIFICATION_CLASSES,
    extract_device_features,
    extract_dhcp_features,
    extract_hostname_feature,
    extract_mdns_features,
    extract_ssdp_features,
    extract_vendor_family,
    normalize_vendor,
)


class DeviceFeaturesTests(unittest.TestCase):
    def test_canonical_classes_defined(self):
        self.assertIn("WINDOWS_WORKSTATION", CLASSIFICATION_CLASSES)
        self.assertIn("APPLE_WORKSTATION", CLASSIFICATION_CLASSES)
        self.assertIn("ANDROID_MOBILE", CLASSIFICATION_CLASSES)
        self.assertIn("APPLE_MOBILE", CLASSIFICATION_CLASSES)
        self.assertIn("SMART_TV_MEDIA", CLASSIFICATION_CLASSES)
        self.assertIn("PRINTER", CLASSIFICATION_CLASSES)
        self.assertIn("NETWORK_DEVICE", CLASSIFICATION_CLASSES)
        self.assertIn("IOT_DEVICE", CLASSIFICATION_CLASSES)
        self.assertIn("UNKNOWN", CLASSIFICATION_CLASSES)

    def test_vendor_normalization_and_family(self):
        self.assertEqual(normalize_vendor("Apple, Inc."), "apple")
        self.assertEqual(extract_vendor_family("Apple Inc."), "apple")
        self.assertEqual(extract_vendor_family("Microsoft Corporation"), "microsoft")
        self.assertEqual(extract_vendor_family("Samsung Electronics Co., Ltd."), "samsung")
        self.assertEqual(extract_vendor_family("Hewlett Packard Enterprise"), "hp")
        self.assertEqual(extract_vendor_family("Cisco Systems"), "cisco")
        self.assertEqual(extract_vendor_family("Espressif Inc"), "espressif")
        self.assertEqual(extract_vendor_family("Unknown Vendor"), "unknown")
        self.assertEqual(extract_vendor_family(None), "unknown")

    def test_hostname_pattern_extraction(self):
        self.assertEqual(extract_hostname_feature("DESKTOP-A1B2C3D"), "desktop_win")
        self.assertEqual(extract_hostname_feature("LAPTOP-9X8Y7Z"), "laptop_win")
        self.assertEqual(extract_hostname_feature("WIN-SERVER01"), "win_generic")
        self.assertEqual(extract_hostname_feature("iPhone-Adonis"), "iphone")
        self.assertEqual(extract_hostname_feature("Adonis-iPad-Pro"), "ipad")
        self.assertEqual(extract_hostname_feature("MacBook-Pro-16"), "macbook")
        self.assertEqual(extract_hostname_feature("Galaxy-S23-Ultra"), "android_galaxy")
        self.assertEqual(extract_hostname_feature("Pixel-7a"), "android_pixel")
        self.assertEqual(extract_hostname_feature("HP-LaserJet-M404"), "printer")
        self.assertEqual(extract_hostname_feature("LG-Smart-TV-4K"), "smart_tv")
        self.assertEqual(extract_hostname_feature("Sonos-LivingRoom"), "audio")
        self.assertEqual(extract_hostname_feature(None), "unknown")

    def test_dhcp_feature_extraction(self):
        raw_obs = [
            {
                "source_type": "CLIENT_DHCP",
                "raw_data": '{"vendor_class": "MSFT 5.0", "parameter_request_list": [1, 3, 6, 15, 31, 43]}',
            }
        ]
        feats = extract_dhcp_features(raw_obs)
        self.assertEqual(feats["dhcp_present"], 1)
        self.assertEqual(feats["dhcp_opt60_family"], "msft")
        self.assertEqual(feats["dhcp_opt55_sig"], "windows")

    def test_mdns_feature_extraction(self):
        raw_obs = [
            {
                "source_type": "CLIENT_MDNS",
                "raw_data": "_airplay._tcp.local, _companion-link._tcp.local",
            }
        ]
        feats = extract_mdns_features(raw_obs)
        self.assertEqual(feats["mdns_present"], 1)
        self.assertEqual(feats["mdns_has_airplay"], 1)
        self.assertEqual(feats["mdns_has_apple_companion"], 1)
        self.assertEqual(feats["mdns_has_printer"], 0)

    def test_ssdp_feature_extraction(self):
        raw_obs = [
            {
                "source_type": "CLIENT_SSDP",
                "raw_data": "urn:schemas-upnp-org:device:MediaRenderer:1",
            }
        ]
        feats = extract_ssdp_features(raw_obs)
        self.assertEqual(feats["ssdp_present"], 1)
        self.assertEqual(feats["ssdp_is_media"], 1)

    def test_anti_leakage_guarantee(self):
        device = {
            "id": 999,
            "mac_address": "AA:BB:CC:DD:EE:FF",
            "ip_address": "192.168.1.50",
            "hostname": "DESKTOP-9988A",
            "vendor": "Dell Inc.",
        }
        observations = [
            {
                "source_type": "CLIENT_DHCP",
                "ip_address": "192.168.1.50",
                "raw_data": '{"vendor_class": "MSFT 5.0"}',
            }
        ]
        feats = extract_device_features(device, observations)
        self.assertNotIn("AA:BB:CC:DD:EE:FF", str(feats))
        self.assertNotIn("192.168.1.50", str(feats))
        self.assertNotIn("999", str(feats))
        self.assertEqual(feats["vendor_family"], "dell")
        self.assertEqual(feats["hostname_pattern"], "desktop_win")


if __name__ == "__main__":
    unittest.main()
