"""Unit tests for LAN discovery that do not send packets or access MySQL.

Run from the repository root:
    python3 server/tests/test_network_discovery.py
"""

import json
import sys
import threading
import time
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from tempfile import TemporaryDirectory


SERVER_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIRECTORY))

try:
    import mysql.connector  # noqa: F401
except ModuleNotFoundError:
    mysql_module = types.ModuleType("mysql")
    mysql_module.connector = types.ModuleType("mysql.connector")
    sys.modules["mysql"] = mysql_module
    sys.modules["mysql.connector"] = mysql_module.connector

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

    def test_merge_discovery_sources_enriches_arp_device_with_dhcp_hostname(self):
        server_devices = [
            {
                "ip_address": "172.16.0.102",
                "mac_address": "E4:FD:45:BA:8B:96",
                "hostname": None,
                "vendor": "Dell Inc.",
                "os_name": None,
                "os_family": None,
                "os_confidence": None,
            }
        ]
        client_observations = [
            {
                "source_type": "CLIENT_DHCP",
                "source_client_database_id": 1,
                "source_client_id": "client-1",
                "source_client_hostname": "agent-host",
                "ip_address": "172.16.0.102",
                "mac_address": "E4:FD:45:BA:8B:96",
                "entry_type": "dynamic",
                "interface": None,
                "hostname": "DESKTOP-DJP05CM",
                "vendor": "Dell Inc.",
                "observed_at": "2026-08-19T10:00:00+00:00",
            }
        ]
        merged = network_discovery.merge_discovery_sources(
            server_devices, client_observations
        )
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["mac_address"], "E4:FD:45:BA:8B:96")
        self.assertEqual(merged[0]["hostname"], "DESKTOP-DJP05CM")
        self.assertEqual(
            [s["source_type"] for s in merged[0]["observation_sources"]],
            ["SERVER_SCAN", "CLIENT_DHCP"],
        )

    def test_merge_discovery_sources_keeps_multiple_ips_for_one_mac(self):
        merged = network_discovery.merge_discovery_sources(
            [],
            [
                {
                    "source_type": "CLIENT_ARP",
                    "source_client_id": "client-a",
                    "ip_address": "172.16.0.102",
                    "mac_address": "E4:FD:45:BA:8B:96",
                    "entry_type": "dynamic",
                    "hostname": "desktop",
                    "vendor": "Example Vendor",
                    "observed_at": "2026-08-20T10:00:00+00:00",
                },
                {
                    "source_type": "CLIENT_DHCP",
                    "source_client_id": "client-b",
                    "ip_address": "172.16.0.150",
                    "mac_address": "E4:FD:45:BA:8B:96",
                    "entry_type": "dynamic",
                    "hostname": "desktop",
                    "vendor": "Example Vendor",
                    "observed_at": "2026-08-20T10:01:00+00:00",
                },
            ],
        )

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["mac_address"], "E4:FD:45:BA:8B:96")
        self.assertEqual(merged[0]["ip_addresses"], ["172.16.0.102", "172.16.0.150"])
        self.assertEqual(
            [source["source_type"] for source in merged[0]["observation_sources"]],
            ["CLIENT_ARP", "CLIENT_DHCP"],
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

    def test_store_network_scan_updates_one_daily_json_file(self):
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
            second_path = network_scan_storage.store_network_scan(
                {"interface": "wlan0", "network": "192.168.20.0/24"},
                [],
                completed_at.replace(hour=13),
            )
            with open(file_path, encoding="utf-8") as file:
                stored_scan = json.load(file)

        self.assertEqual(file_path, second_path)
        self.assertTrue(file_path.endswith("network_scan_2026-08-16.json"))
        self.assertEqual(stored_scan["devices_found"], 0)
        self.assertEqual(stored_scan["devices"], [])
        self.assertEqual(stored_scan["completed_at"], "2026-08-16T13:00:00+00:00")

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
            scan_path = network_scan_storage.store_network_scan(
                {"interface": "eth0", "network": "192.168.10.0/24"},
                neighbours,
                observed_at,
            )
            with open(file_path, encoding="utf-8") as file:
                daily_log = json.load(file)

        self.assertEqual(file_path, second_path)
        self.assertEqual(file_path, snapshot_path)
        self.assertEqual(file_path, duplicate_path)
        self.assertEqual(file_path, scan_path)
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
        self.assertEqual(daily_log["devices"], neighbours)

    def test_vendor_lookup_failure_returns_empty_database(self):
        with patch("builtins.open", side_effect=FileNotFoundError):
            self.assertEqual(
                network_discovery.load_oui_database("/missing/oui.txt"),
                {},
            )

    def test_global_active_scan_uses_bounded_async_dispatch(self):
        from server_components import server_lib
        from server_components.global_network_scan import GlobalNetworkScanManager

        clients = {
            "AA:AA:AA:AA:AA:AA": {
                "client_id": "client-a",
                "mac": "AA:AA:AA:AA:AA:AA",
            },
            "BB:BB:BB:BB:BB:BB": {
                "client_id": "client-b",
                "mac": "BB:BB:BB:BB:BB:BB",
            },
        }
        responses = {
            "client-a": {
                "status": "ok",
                "data": {"status": "started"},
            },
            "client-b": {"status": "ok", "data": {"status": "started"}},
        }

        with patch.object(server_lib, "clients", clients), patch.object(
            server_lib, "clients_lock", threading.Lock()
        ), patch.object(
            server_lib,
            "execute_client_command",
            side_effect=lambda client_id, command, **kwargs: responses[client_id],
        ) as execute:
            manager = GlobalNetworkScanManager()
            result, created = manager.start(list(clients.values()))
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                if execute.call_count == 2:
                    break
                time.sleep(0.01)
            manager.record_report(result["id"], "AA:AA:AA:AA:AA:AA", [])
            manager.record_report(result["id"], "BB:BB:BB:BB:BB:BB", [])

        self.assertTrue(created)
        self.assertEqual(result["total_clients"], 2)
        self.assertEqual(execute.call_count, 2)
        for call in execute.call_args_list:
            self.assertEqual(call.args[1], "SCAN_NETWORK")
            self.assertEqual(call.kwargs["timeout"], 10.0)
            self.assertFalse(call.kwargs["process_network_scan"])
            self.assertEqual(call.kwargs["args"]["global_scan_id"], result["id"])

    def test_global_neighbourhood_collection_finishes_each_bucket_before_next(self):
        from server_components import server_lib
        from server_components.global_network_scan import (
            GlobalNeighbourhoodCollectionManager,
        )

        clients = [
            {"client_id": "client-a", "mac": "AA:AA:AA:AA:AA:AA"},
            {"client_id": "client-b", "mac": "BB:BB:BB:BB:BB:BB"},
            {"client_id": "client-c", "mac": "CC:CC:CC:CC:CC:CC"},
        ]
        first_bucket_entered = threading.Event()
        release_first_bucket = threading.Event()
        call_lock = threading.Lock()
        calls = []

        def request_neighbourhood(client_id, *, timeout):
            with call_lock:
                calls.append(client_id)
                if {"client-a", "client-b"}.issubset(calls):
                    first_bucket_entered.set()
            if client_id in {"client-a", "client-b"}:
                release_first_bucket.wait(1)
            return {
                "status": "completed",
                "client_id": client_id,
                "observations_sent": 1,
            }

        with patch.dict(
            "os.environ", {"GLOBAL_NEIGHBOURHOOD_COLLECTION_BUCKET_SIZE": "2"}
        ), patch.object(
            server_lib,
            "request_client_network_neighbourhood",
            side_effect=request_neighbourhood,
        ):
            manager = GlobalNeighbourhoodCollectionManager()
            result, created = manager.start(clients)
            self.assertTrue(first_bucket_entered.wait(1))
            with call_lock:
                self.assertEqual(set(calls), {"client-a", "client-b"})
            release_first_bucket.set()

            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                completed = manager.get(result["id"])
                if completed and completed["status"] == "completed":
                    break
                time.sleep(0.01)

        self.assertTrue(created)
        self.assertEqual(completed["total_clients"], 3)
        self.assertEqual(completed["completed"], 3)
        self.assertEqual(completed["buckets_total"], 2)
        self.assertEqual(completed["buckets_completed"], 2)
        self.assertEqual(calls[2], "client-c")

    def test_global_neighbourhood_collection_isolates_client_timeout(self):
        from server_components import server_lib
        from server_components.global_network_scan import (
            GlobalNeighbourhoodCollectionManager,
        )

        clients = [
            {"client_id": "client-a", "mac": "AA:AA:AA:AA:AA:AA"},
            {"client_id": "client-b", "mac": "BB:BB:BB:BB:BB:BB"},
            {"client_id": "client-c", "mac": "CC:CC:CC:CC:CC:CC"},
        ]
        calls = []

        def request_neighbourhood(client_id, *, timeout):
            calls.append((client_id, timeout))
            if client_id == "client-a":
                return {
                    "status": "client_timeout",
                    "client_id": client_id,
                    "timeout_seconds": timeout,
                    "message": "Command timed out.",
                }
            return {
                "status": "completed",
                "client_id": client_id,
                "observations_sent": 2,
                "timeout_seconds": timeout,
            }

        with patch.dict(
            "os.environ",
            {
                "GLOBAL_NEIGHBOURHOOD_COLLECTION_BUCKET_SIZE": "2",
                "GLOBAL_NEIGHBOURHOOD_COLLECTION_CLIENT_TIMEOUT": "4.5",
            },
        ), patch.object(
            server_lib,
            "request_client_network_neighbourhood",
            side_effect=request_neighbourhood,
        ):
            manager = GlobalNeighbourhoodCollectionManager()
            result, created = manager.start(clients)
            deadline = time.monotonic() + 1
            completed = None
            while time.monotonic() < deadline:
                completed = manager.get(result["id"])
                if completed and completed["status"] == "partial":
                    break
                time.sleep(0.01)

        self.assertTrue(created)
        self.assertEqual(completed["completed"], 2)
        self.assertEqual(completed["timed_out"], 1)
        self.assertEqual(completed["buckets_completed"], 2)
        self.assertEqual(completed["request_timeout"], 4.5)
        self.assertEqual({client_id for client_id, _ in calls[:2]}, {"client-a", "client-b"})
        self.assertEqual(calls[2][0], "client-c")
        self.assertTrue(all(timeout == 4.5 for _, timeout in calls))

    def test_global_neighbourhood_collection_reports_partial_success_result(self):
        from server_components import server_lib
        from server_components.global_network_scan import (
            GlobalNeighbourhoodCollectionManager,
        )

        clients = [
            {"client_id": "client-a", "mac": "AA:AA:AA:AA:AA:AA"},
            {"client_id": "client-b", "mac": "BB:BB:BB:BB:BB:BB"},
            {"client_id": "client-c", "mac": "CC:CC:CC:CC:CC:CC"},
        ]
        responses = {
            "client-a": {"status": "completed", "observations_sent": 2},
            "client-b": {"status": "client_timeout", "message": "Timed out."},
            "client-c": {"status": "client_unavailable", "message": "Offline."},
        }

        with patch.dict(
            "os.environ", {"GLOBAL_NEIGHBOURHOOD_COLLECTION_BUCKET_SIZE": "2"}
        ), patch.object(
            server_lib,
            "request_client_network_neighbourhood",
            side_effect=lambda client_id, **_: responses[client_id],
        ), patch.object(
            server_lib,
            "merge_and_broadcast_neighbourhood",
            return_value=([{"mac_address": "11:22:33:44:55:66"}], "/tmp/scan.json"),
        ) as merge:
            manager = GlobalNeighbourhoodCollectionManager()
            result, created = manager.start(clients)
            deadline = time.monotonic() + 1
            completed = None
            while time.monotonic() < deadline:
                completed = manager.get(result["id"])
                if completed and completed["status"] == "partial":
                    break
                time.sleep(0.01)

        self.assertTrue(created)
        self.assertEqual(completed["clients_requested"], 3)
        self.assertEqual(completed["clients_succeeded"], 1)
        self.assertEqual(completed["clients_failed"], 1)
        self.assertEqual(completed["clients_timed_out"], 1)
        self.assertEqual(completed["devices_discovered"], 1)
        self.assertEqual(completed["buckets_completed"], 2)
        self.assertIsNone(completed["merge_error"])
        merge.assert_called_once()

    def test_global_neighbourhood_collection_logs_lifecycle(self):
        from server_components import global_network_scan, server_lib
        from server_components.global_network_scan import (
            GlobalNeighbourhoodCollectionManager,
        )

        with patch.object(
            server_lib,
            "request_client_network_neighbourhood",
            return_value={"status": "completed", "observations_sent": 3},
        ), patch.object(
            server_lib,
            "merge_and_broadcast_neighbourhood",
            return_value=([{"mac_address": "11:22:33:44:55:66"}], "/tmp/scan.json"),
        ), patch.object(global_network_scan, "_collection_log") as collection_log:
            manager = GlobalNeighbourhoodCollectionManager()
            result, _ = manager.start([
                {"client_id": "client-a", "mac": "AA:AA:AA:AA:AA:AA"}
            ])
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                completed = manager.get(result["id"])
                if completed and completed["status"] == "completed":
                    break
                time.sleep(0.01)

        messages = [call.args[0] for call in collection_log.call_args_list]
        self.assertTrue(any("started: eligible_clients" in message for message in messages))
        self.assertTrue(any("bucket %d/%d started" in message for message in messages))
        self.assertTrue(any("responded: observations" in message for message in messages))
        self.assertTrue(any("bucket %d/%d completed" in message for message in messages))
        self.assertTrue(any("completed: status" in message for message in messages))


if __name__ == "__main__":
    unittest.main()
