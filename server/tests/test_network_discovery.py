"""Unit tests for LAN discovery that do not send packets or access MySQL.

Run from the repository root:
    python3 server/tests/test_network_discovery.py
"""

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from tempfile import TemporaryDirectory


SERVER_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIRECTORY))

from server_components import (
    network_device_classification,
    network_discovery,
    network_scan_storage,
)


class NetworkDiscoveryTests(unittest.TestCase):
    def test_get_local_network_uses_default_route_and_interface_address(self):
        route_result = SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                [{"dst": "default", "gateway": "192.168.10.1", "dev": "eth0"}]
            ),
            stderr="",
        )
        address_result = SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                [{
                    "addr_info": [{
                        "family": "inet",
                        "local": "192.168.10.25",
                        "prefixlen": 24,
                        "scope": "global",
                    }]
                }]
            ),
            stderr="",
        )
        with patch.object(
            network_discovery.subprocess,
            "run",
            side_effect=[route_result, address_result],
        ):
            context = network_discovery.get_local_network()

        self.assertEqual(
            context,
            {
                "interface": "eth0",
                "local_ip": "192.168.10.25",
                "network": "192.168.10.0/24",
                "gateway": "192.168.10.1",
            },
        )

    def test_get_local_network_rejects_invalid_subnet_override(self):
        route_result = SimpleNamespace(
            returncode=0,
            stdout=json.dumps([{"dst": "default", "dev": "eth0"}]),
            stderr="",
        )
        address_result = SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                [{
                    "addr_info": [{
                        "family": "inet",
                        "local": "192.168.10.25",
                        "prefixlen": 24,
                        "scope": "global",
                    }]
                }]
            ),
            stderr="",
        )
        with patch.dict("os.environ", {"NETWORK_SCAN_SUBNET": "not-a-network"}), patch.object(
            network_discovery.subprocess,
            "run",
            side_effect=[route_result, address_result],
        ):
            with self.assertRaisesRegex(
                network_discovery.NetworkDiscoveryError,
                "valid IPv4 CIDR",
            ):
                network_discovery.get_local_network()

    def test_get_local_network_rejects_malformed_route_data(self):
        route_result = SimpleNamespace(returncode=0, stdout=json.dumps({}), stderr="")
        with patch.object(
            network_discovery.subprocess,
            "run",
            return_value=route_result,
        ):
            with self.assertRaisesRegex(
                network_discovery.NetworkDiscoveryError,
                "route configuration is malformed",
            ):
                network_discovery.get_local_network()

    def test_discover_devices_normalizes_and_deduplicates_responses(self):
        context = {"interface": "eth0", "network": "192.168.10.0/24"}
        responses = [
            SimpleNamespace(psrc="192.168.10.25", hwsrc="aa-bb-cc-dd-ee-ff"),
            SimpleNamespace(psrc="192.168.10.30", hwsrc="AA:BB:CC:DD:EE:FF"),
            SimpleNamespace(psrc="not-an-ip", hwsrc="11:22:33:44:55:66"),
        ]
        devices = network_discovery.discover_devices(
            context,
            arp_discoverer=lambda *_: responses,
            hostname_resolver=lambda _: "laptop.local",
            vendor_resolver=lambda _: "Example Vendor",
        )

        self.assertEqual(
            devices,
            [{
                "ip_address": "192.168.10.25",
                "mac_address": "AA:BB:CC:DD:EE:FF",
                "hostname": "laptop.local",
                "vendor": "Example Vendor",
                "os_name": None,
                "os_family": None,
                "os_confidence": None,
            }],
        )

    def test_discover_devices_keeps_scan_successful_when_enrichment_fails(self):
        context = {"interface": "eth0", "network": "192.168.10.0/24"}
        devices = network_discovery.discover_devices(
            context,
            arp_discoverer=lambda *_: [
                SimpleNamespace(psrc="192.168.10.25", hwsrc="AA:BB:CC:DD:EE:FF")
            ],
            hostname_resolver=lambda _: (_ for _ in ()).throw(OSError("DNS unavailable")),
            vendor_resolver=lambda _: (_ for _ in ()).throw(OSError("OUI unavailable")),
        )

        self.assertIsNone(devices[0]["hostname"])
        self.assertIsNone(devices[0]["vendor"])
        self.assertIsNone(devices[0]["os_name"])

    def test_discover_devices_returns_empty_list_for_empty_arp_responses(self):
        devices = network_discovery.discover_devices(
            {"interface": "eth0", "network": "192.168.10.0/24"},
            arp_discoverer=lambda *_: [],
        )
        self.assertEqual(devices, [])

    def test_discover_arp_devices_does_not_enrich_the_response(self):
        devices = network_discovery.discover_arp_devices(
            {"interface": "eth0", "network": "192.168.10.0/24"},
            arp_discoverer=lambda *_: [
                SimpleNamespace(psrc="192.168.10.25", hwsrc="AA:BB:CC:DD:EE:FF")
            ],
        )

        self.assertEqual(devices[0]["hostname"], None)
        self.assertEqual(devices[0]["vendor"], None)
        self.assertEqual(devices[0]["os_name"], None)

    def test_merge_discovery_sources_correlates_by_mac_and_preserves_sources(self):
        merged_devices = network_discovery.merge_discovery_sources(
            [
                {
                    "ip_address": "172.16.0.102",
                    "mac_address": "AA:BB:CC:DD:EE:FF",
                    "hostname": None,
                    "vendor": None,
                    "os_name": None,
                    "os_family": None,
                    "os_confidence": None,
                }
            ],
            [
                {
                    "ip_address": "172.16.0.99",
                    "mac_address": "aa:bb:cc:dd:ee:ff",
                    "entry_type": "dynamic",
                    "interface": "eth0",
                    "observed_at": "2026-08-17T10:00:00+00:00",
                    "source_client_database_id": 7,
                    "source_client_id": "client-reporter-a",
                    "source_client_hostname": "reporter-a",
                },
                {
                    "ip_address": "172.16.0.103",
                    "mac_address": "12:22:33:44:55:66",
                    "entry_type": "static",
                    "interface": "wlan0",
                    "observed_at": "2026-08-17T10:01:00+00:00",
                    "source_client_database_id": 8,
                    "source_client_id": "client-reporter-b",
                    "source_client_hostname": "reporter-b",
                },
            ],
            observed_at="2026-08-17T10:02:00+00:00",
        )

        self.assertEqual(len(merged_devices), 2)
        scanned_device = next(
            device for device in merged_devices if device["mac_address"] == "AA:BB:CC:DD:EE:FF"
        )
        self.assertEqual(scanned_device["ip_address"], "172.16.0.102")
        self.assertEqual(
            [source["source_type"] for source in scanned_device["observation_sources"]],
            ["SERVER_SCAN", "CLIENT_ARP"],
        )
        client_only_device = next(
            device for device in merged_devices if device["mac_address"] == "12:22:33:44:55:66"
        )
        self.assertEqual(client_only_device["ip_address"], "172.16.0.103")
        self.assertEqual(
            client_only_device["observation_sources"][0]["source_client_id"],
            "client-reporter-b",
        )

    def test_merge_discovery_sources_retains_prior_scan_devices_and_fills_details(self):
        merged_devices = network_discovery.merge_discovery_sources(
            [],
            [{
                "ip_address": "172.16.0.102",
                "mac_address": "AA:BB:CC:DD:EE:FF",
                "hostname": "workstation-01",
                "vendor": None,
                "entry_type": "dynamic",
                "interface": "eth0",
                "observed_at": "2026-08-18T10:00:00+00:00",
            }],
            previous_devices=[
                {
                    "ip_address": "172.16.0.102",
                    "mac_address": "AA:BB:CC:DD:EE:FF",
                    "hostname": None,
                    "vendor": "Example Vendor",
                    "observation_sources": [{"source_type": "SERVER_SCAN"}],
                },
                {
                    "ip_address": "172.16.0.103",
                    "mac_address": "12:22:33:44:55:66",
                    "hostname": "printer",
                    "vendor": "Printer Vendor",
                    "observation_sources": [{"source_type": "SERVER_SCAN"}],
                },
            ],
        )

        self.assertEqual(len(merged_devices), 2)
        workstation = next(
            device for device in merged_devices if device["mac_address"] == "AA:BB:CC:DD:EE:FF"
        )
        self.assertEqual(workstation["hostname"], "workstation-01")
        self.assertEqual(workstation["vendor"], "Example Vendor")
        self.assertEqual(
            [source["source_type"] for source in workstation["observation_sources"]],
            ["SERVER_SCAN", "CLIENT_ARP"],
        )

    def test_hostname_normalisation_decodes_avahi_octal_escapes(self):
        self.assertEqual(
            network_discovery._normalise_hostname(r"\040none\041.local"),
            "none!.local",
        )

    def test_enrichment_only_detects_os_for_explicit_discovered_targets(self):
        devices = [
            {
                "ip_address": "192.168.10.25",
                "mac_address": "AA:BB:CC:DD:EE:FF",
                "hostname": None,
                "vendor": None,
                "os_name": None,
                "os_family": None,
                "os_confidence": None,
            },
            {
                "ip_address": "192.168.10.26",
                "mac_address": "11:22:33:44:55:66",
                "hostname": None,
                "vendor": None,
                "os_name": None,
                "os_family": None,
                "os_confidence": None,
            },
        ]
        detected_ips = []
        enriched_devices = network_discovery.enrich_devices(
            devices,
            hostname_resolver=lambda ip_address: f"host-{ip_address}",
            vendor_resolver=lambda _: "Example Vendor",
            os_detector=lambda ip_address: (
                detected_ips.append(ip_address)
                or {
                    "os_name": "Linux",
                    "os_family": "Linux",
                    "os_confidence": 0.9,
                }
            ),
            os_detection_targets=["192.168.10.26", "192.168.10.99"],
        )

        self.assertEqual(detected_ips, ["192.168.10.26"])
        self.assertIsNone(enriched_devices[0]["os_name"])
        self.assertEqual(enriched_devices[1]["os_name"], "Linux")
        self.assertEqual(enriched_devices[1]["hostname"], "host-192.168.10.26")

    def test_classification_marks_registered_mac_as_managed(self):
        devices = [{
            "ip_address": "192.168.10.25",
            "mac_address": "AA:BB:CC:DD:EE:FF",
            "hostname": None,
            "vendor": None,
            "os_name": None,
            "os_family": None,
            "os_confidence": None,
        }, {
            "ip_address": "192.168.10.26",
            "mac_address": "11:22:33:44:55:66",
            "hostname": None,
            "vendor": None,
            "os_name": None,
            "os_family": None,
            "os_confidence": None,
        }]
        clients_by_mac = {
            "AA:BB:CC:DD:EE:FF": {
                "id": 7,
                "client_id": "client-7",
                "hostname": "workstation-07",
                "os_system": "Linux",
                "os_release": "6.8",
                "os_version": "Ubuntu",
                "os_machine": "x86_64",
            }
        }
        classified_devices = network_device_classification.classify_devices(
            devices,
            client_fetcher=lambda mac_addresses: clients_by_mac,
        )

        self.assertTrue(classified_devices[0]["is_managed"])
        self.assertEqual(classified_devices[0]["classification"], "MANAGED")
        self.assertEqual(classified_devices[0]["hostname"], "workstation-07")
        self.assertEqual(classified_devices[0]["os_name"], "Linux")
        self.assertEqual(
            classified_devices[0]["managed_client"]["client_id"],
            "client-7",
        )
        self.assertFalse(classified_devices[1]["is_managed"])
        self.assertEqual(classified_devices[1]["classification"], "UNMANAGED")

    def test_enrichment_reuses_managed_client_identity_before_dns_or_os_detection(self):
        devices = [{
            "ip_address": "192.168.10.25",
            "mac_address": "AA:BB:CC:DD:EE:FF",
            "hostname": "agent-host",
            "vendor": None,
            "os_name": "Windows",
            "os_family": "Windows",
            "os_confidence": 1.0,
            "classification": "MANAGED",
            "is_managed": True,
            "managed_client": {"client_id": "client-7"},
        }]
        enriched_devices = network_discovery.enrich_devices(
            devices,
            hostname_resolver=lambda _: self.fail("managed hostname should be reused"),
            vendor_resolver=lambda _: "Example Vendor",
            os_detector=lambda _: self.fail("managed OS should be reused"),
            os_detection_targets=["192.168.10.25"],
        )

        self.assertEqual(enriched_devices[0]["hostname"], "agent-host")
        self.assertEqual(enriched_devices[0]["os_name"], "Windows")
        self.assertEqual(enriched_devices[0]["vendor"], "Example Vendor")

    def test_classification_marks_results_unknown_when_client_lookup_fails(self):
        devices = [{"ip_address": "192.168.10.25", "mac_address": "AA:BB:CC:DD:EE:FF"}]
        classified_devices = network_device_classification.classify_devices(
            devices,
            client_fetcher=lambda _: None,
        )

        self.assertEqual(classified_devices[0]["classification"], "UNKNOWN")
        self.assertIsNone(classified_devices[0]["is_managed"])

    def test_detect_os_parses_the_highest_confidence_nmap_match(self):
        nmap_xml = """<?xml version='1.0'?>
        <nmaprun><host><os>
          <osmatch name='Generic Unix' accuracy='40'><osclass osfamily='Unix'/></osmatch>
          <osmatch name='Ubuntu Linux' accuracy='93'><osclass osfamily='Linux'/></osmatch>
        </os></host></nmaprun>"""
        completed = SimpleNamespace(returncode=0, stdout=nmap_xml, stderr="")
        with patch.object(
            network_discovery.subprocess,
            "run",
            return_value=completed,
        ) as run:
            result = network_discovery.detect_os("192.168.10.25")

        self.assertEqual(
            result,
            {
                "os_name": "Ubuntu Linux",
                "os_family": "Linux",
                "os_confidence": 0.93,
            },
        )
        command = run.call_args.args[0]
        self.assertIn("-PE", command)
        self.assertIn("-PS443", command)

    def test_manual_scan_merges_client_reports_without_server_discovery(self):
        client_observations = [
            {
                "ip_address": "192.168.10.26",
                "mac_address": "12:22:33:44:55:66",
                "entry_type": "dynamic",
                "interface": "eth0",
                "observed_at": "2026-08-17T10:00:00+00:00",
                "source_client_database_id": 7,
                "source_client_id": "client-reporter-a",
                "source_client_hostname": "reporter-a",
            }
        ]
        with patch.object(
            network_discovery, "get_local_network", side_effect=AssertionError("server scan called")
        ), patch.object(
            network_discovery, "discover_arp_devices", side_effect=AssertionError("server scan called")
        ), patch.object(
            network_discovery,
            "get_recent_client_neighbour_observations",
            return_value=client_observations,
        ), patch.object(
            network_discovery, "classify_devices", side_effect=lambda devices: devices
        ), patch.object(
            network_discovery, "enrich_devices", side_effect=AssertionError("server enrichment called")
        ), patch.object(
            network_discovery, "store_network_scan", return_value="/tmp/scan.json"
        ), patch.object(
            network_discovery, "load_latest_network_scan", return_value=None
        ):
            returned_context, devices, result_path = network_discovery.run_manual_scan()

        self.assertEqual(returned_context["network"], "client-reported")
        self.assertEqual(result_path, "/tmp/scan.json")
        self.assertEqual(len(devices), 1)
        client_only_device = devices[0]
        self.assertEqual(
            client_only_device["observation_sources"][0]["source_type"], "CLIENT_ARP"
        )

    def test_detect_os_returns_unknown_when_nmap_is_unavailable(self):
        with patch.object(
            network_discovery.subprocess,
            "run",
            side_effect=FileNotFoundError,
        ):
            self.assertEqual(
                network_discovery.detect_os("192.168.10.25"),
                {
                    "os_name": None,
                    "os_family": None,
                    "os_confidence": None,
                },
            )

    def test_store_network_scan_writes_a_timestamped_json_file(self):
        completed_at = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)
        devices = [{"ip_address": "192.168.10.25", "mac_address": "AA:BB:CC:DD:EE:FF"}]
        with TemporaryDirectory() as storage_dir, patch.dict(
            "os.environ",
            {"NETWORK_SCAN_STORAGE_DIR": storage_dir},
        ):
            file_path = network_scan_storage.store_network_scan(
                {"interface": "eth0", "network": "192.168.10.0/24"},
                devices,
                completed_at,
            )
            with open(file_path, encoding="utf-8") as file:
                stored_scan = json.load(file)

        self.assertTrue(file_path.endswith("2026-08-16_12-00-00_000000.json"))
        self.assertEqual(stored_scan["devices_found"], 1)
        self.assertEqual(stored_scan["devices"], devices)
        self.assertEqual(stored_scan["completed_at"], "2026-08-16T12:00:00+00:00")

    def test_daily_dhcp_log_uses_one_file_and_appends_observations(self):
        observed_at = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)
        neighbours = [
            {
                "ip_address": "192.168.10.25",
                "mac_address": "AA:BB:CC:DD:EE:FF",
                "entry_type": "dynamic",
                "hostname": "workstation",
                "vendor": None,
            }
        ]
        with TemporaryDirectory() as storage_dir, patch.dict(
            "os.environ", {"NETWORK_SCAN_STORAGE_DIR": storage_dir}
        ):
            file_path = network_scan_storage.append_daily_dhcp_observation(
                "11:22:33:44:55:66",
                neighbours,
                {"message_type": 3, "vendor_class": "MSFT 5.0"},
                observed_at,
            )
            second_path = network_scan_storage.append_daily_dhcp_observation(
                "11:22:33:44:55:66", neighbours, observed_at=observed_at
            )
            snapshot_path, created = network_scan_storage.record_daily_neighbour_snapshot(
                "11:22:33:44:55:66", neighbours, observed_at
            )
            duplicate_path, duplicate_created = (
                network_scan_storage.record_daily_neighbour_snapshot(
                    "11:22:33:44:55:66", neighbours, observed_at
                )
            )
            with open(file_path, encoding="utf-8") as file:
                daily_log = json.load(file)

        self.assertEqual(file_path, second_path)
        self.assertEqual(file_path, snapshot_path)
        self.assertEqual(file_path, duplicate_path)
        self.assertTrue(created)
        self.assertFalse(duplicate_created)
        self.assertTrue(file_path.endswith("network_scan_2026-08-16.json"))
        self.assertEqual(daily_log["date"], "2026-08-16")
        self.assertEqual(len(daily_log["dhcp_observations"]), 2)
        self.assertIn("11:22:33:44:55:66", daily_log["neighbour_snapshots"])
        self.assertEqual(
            daily_log["dhcp_observations"][0]["reporting_client_mac"],
            "11:22:33:44:55:66",
        )
        self.assertEqual(
            daily_log["dhcp_observations"][0]["dhcp"],
            {"message_type": 3, "vendor_class": "MSFT 5.0"},
        )

    def test_vendor_lookup_failure_returns_empty_database(self):
        with patch("builtins.open", side_effect=FileNotFoundError):
            self.assertEqual(
                network_discovery.load_oui_database("/missing/oui.txt"),
                {},
            )


if __name__ == "__main__":
    unittest.main()
