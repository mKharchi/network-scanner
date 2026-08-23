"""Unit tests for multi-protocol fingerprinting and device classification."""

import sys
import unittest
from pathlib import Path

CLIENT_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLIENT_DIRECTORY))

from device_model import DeviceRecord
from fingerprinting import (
    apply_classification_to_device,
    classify_dhcp_evidence,
    classify_mdns_evidence,
    classify_ssdp_evidence,
    evaluate_hostname_heuristics,
)


class FingerprintingTests(unittest.TestCase):
    def test_dhcp_windows_fingerprint(self):
        eval_res = classify_dhcp_evidence(
            vendor_class="MSFT 5.0",
            parameter_request_list=[1, 3, 6, 15, 31, 33, 43, 44, 46, 47],
            hostname="DESKTOP-DJP05CM",
        )
        self.assertEqual(eval_res["os_hint"], "Windows")
        self.assertEqual(eval_res["device_type"], "Workstation")
        self.assertGreaterEqual(eval_res["confidence"], 0.95)
        self.assertTrue(any("microsoft" in ev for ev in eval_res["evidence"]))

    def test_dhcp_android_fingerprint(self):
        eval_res = classify_dhcp_evidence(
            vendor_class="android-dhcp-12",
            parameter_request_list=[1, 3, 6, 15, 26, 28, 51, 58, 59, 43],
        )
        self.assertEqual(eval_res["os_hint"], "Android")
        self.assertEqual(eval_res["device_type"], "Mobile Device")
        self.assertGreaterEqual(eval_res["confidence"], 0.95)

    def test_mdns_apple_device_info_fingerprint(self):
        eval_res = classify_mdns_evidence(
            service_type="_device-info._tcp.local",
            txt_records={"model": "MacBookPro16,2", "osxvers": "25"},
        )
        self.assertEqual(eval_res["os_hint"], "macOS")
        self.assertEqual(eval_res["device_type"], "MacBook")
        self.assertEqual(eval_res["model_hint"], "MacBookPro16,2")
        self.assertGreaterEqual(eval_res["confidence"], 0.90)

    def test_mdns_printer_fingerprint(self):
        eval_res = classify_mdns_evidence(
            service_type="_ipp._tcp.local",
            service_name="EPSON ET-4750",
        )
        self.assertEqual(eval_res["device_type"], "Printer")
        self.assertGreaterEqual(eval_res["confidence"], 0.90)

    def test_ssdp_server_fingerprint(self):
        eval_res = classify_ssdp_evidence(
            server_header="Windows/10.0 UPnP/1.1 uTorrent/3.5.5",
            device_type_urn="urn:schemas-upnp-org:device:MediaRenderer:1",
        )
        self.assertEqual(eval_res["os_hint"], "Windows")
        self.assertGreaterEqual(eval_res["confidence"], 0.85)

    def test_hostname_heuristics(self):
        eval_res = evaluate_hostname_heuristics("DESKTOP-ABC1234")
        self.assertEqual(eval_res["os_hint"], "Windows")
        self.assertEqual(eval_res["device_type"], "Workstation")

        eval_iphone = evaluate_hostname_heuristics("Johns-iPhone.local")
        self.assertEqual(eval_iphone["os_hint"], "iOS")
        self.assertEqual(eval_iphone["model_hint"], "iPhone")

    def test_multi_source_synergy(self):
        dev = DeviceRecord(mac_address="AA:BB:CC:DD:EE:FF")
        dev.add_protocol("dhcp")
        dev.add_protocol("llmnr")
        dev.add_service("_dosvc._tcp.local")
        dev.add_evidence("os_hint", "dhcp.vendor_class.microsoft")
        dev.add_evidence("os_hint", "llmnr")
        dev.add_evidence("os_hint", "mdns.dosvc")

        apply_classification_to_device(dev)
        self.assertEqual(dev.os_hint, "Windows")
        self.assertGreaterEqual(dev.os_classification.confidence, 0.95)


if __name__ == "__main__":
    unittest.main()
