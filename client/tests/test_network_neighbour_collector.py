"""Unit tests for local neighbour-table collection.

Run from repository root:
    python3 client/tests/test_network_neighbour_collector.py
"""

import json
import platform
import socket
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


CLIENT_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLIENT_DIRECTORY))

from network_neighbour_collector import (  # noqa: E402
    NetworkNeighbourCollector,
    discover_active_arp,
    get_local_network,
    merge_neighbours_by_mac,
    parse_arp_output,
    parse_linux_neighbours,
)


class NetworkNeighbourCollectorTests(unittest.TestCase):
    def test_linux_parser_normalizes_dynamic_and_static_entries(self):
        neighbours = parse_linux_neighbours(
            json.dumps(
                [
                    {
                        "dst": "172.16.0.102",
                        "lladdr": "aa-bb-cc-dd-ee-ff",
                        "state": ["STALE"],
                        "dev": "eth0",
                    },
                    {
                        "dst": "172.16.0.1",
                        "lladdr": "12:22:33:44:55:66",
                        "state": "PERMANENT",
                        "dev": "eth0",
                    },
                ]
            )
        )

        self.assertEqual(
            neighbours,
            [
                {
                    "ip_address": "172.16.0.102",
                    "mac_address": "AA:BB:CC:DD:EE:FF",
                    "entry_type": "dynamic",
                    "interface": "eth0",
                },
                {
                    "ip_address": "172.16.0.1",
                    "mac_address": "12:22:33:44:55:66",
                    "entry_type": "static",
                    "interface": "eth0",
                },
            ],
        )

    def test_linux_parser_ignores_malformed_incomplete_and_multicast_entries(self):
        neighbours = parse_linux_neighbours(
            json.dumps(
                [
                    {"dst": "172.16.0.3", "state": "INCOMPLETE", "dev": "eth0"},
                    {"dst": "not-an-ip", "lladdr": "aa:bb:cc:dd:ee:ff", "state": "STALE"},
                    {"dst": "224.0.0.1", "lladdr": "01:00:5e:00:00:01", "state": "STALE"},
                    {"dst": "172.16.0.4", "lladdr": "ff:ff:ff:ff:ff:ff", "state": "STALE"},
                ]
            )
        )
        self.assertEqual(neighbours, [])

    def test_empty_or_invalid_linux_output_is_safe(self):
        self.assertEqual(parse_linux_neighbours("[]"), [])
        self.assertEqual(parse_linux_neighbours("not-json"), [])

    def test_windows_arp_output_keeps_dynamic_and_static_entries(self):
        neighbours = parse_arp_output(
            "  172.16.0.12          aa-bb-cc-dd-ee-ff     dynamic\n"
            "  172.16.0.13          12-22-33-44-55-66     static\n"
        )
        self.assertEqual([entry["entry_type"] for entry in neighbours], ["dynamic", "static"])
        self.assertEqual(neighbours[0]["mac_address"], "AA:BB:CC:DD:EE:FF")

    def test_collector_returns_empty_when_platform_command_fails(self):
        collector = NetworkNeighbourCollector(
            system_name="Linux",
            command_runner=lambda _: SimpleNamespace(returncode=1, stdout=""),
        )
        self.assertEqual(collector.collect(), [])

    def test_collector_returns_normalized_neighbourhood_observations(self):
        collector = NetworkNeighbourCollector(
            system_name="Linux",
            command_runner=lambda _: SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    [
                        {
                            "dst": "172.16.0.102",
                            "lladdr": "aa-bb-cc-dd-ee-ff",
                            "state": "REACHABLE",
                            "dev": "eth0",
                        }
                    ]
                ),
            ),
        )

        observations = collector.collect()

        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0]["source"], "arp")
        self.assertEqual(observations[0]["sources"], ["arp"])
        self.assertIn("observed_at", observations[0])

    def test_get_local_network_parses_linux_ip_routes_and_addrs(self):
        def fake_runner(cmd, **kwargs):
            if "route" in cmd:
                return SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps([{"dst": "default", "dev": "eth0", "gateway": "172.16.0.1"}]),
                )
            if "addr" in cmd:
                return SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps([
                        {
                            "addr_info": [
                                {
                                    "family": "inet",
                                    "local": "172.16.0.102",
                                    "prefixlen": 20,
                                    "scope": "global",
                                }
                            ]
                        }
                    ]),
                )
            return SimpleNamespace(returncode=1, stdout="")

        net = get_local_network(command_runner=fake_runner)
        self.assertIsNotNone(net)
        self.assertEqual(net["interface"], "eth0")
        self.assertEqual(net["local_ip"], "172.16.0.102")
        self.assertEqual(net["network"], "172.16.0.0/20")
        self.assertEqual(net["gateway"], "172.16.0.1")

    def test_get_local_network_skips_apipa_adapter_on_windows(self):
        fake_psutil = SimpleNamespace(
            net_if_addrs=lambda: {
                "Ethernet 3": [
                    SimpleNamespace(
                        family=socket.AF_INET,
                        address="169.254.10.20",
                        netmask="255.255.0.0",
                    )
                ],
                "Wi-Fi": [
                    SimpleNamespace(
                        family=socket.AF_INET,
                        address="192.168.50.25",
                        netmask="255.255.255.0",
                    )
                ],
            },
            net_if_stats=lambda: {
                "Ethernet 3": SimpleNamespace(isup=True),
                "Wi-Fi": SimpleNamespace(isup=True),
            },
        )
        with patch.object(platform, "system", return_value="Windows"), patch.dict(
            sys.modules, {"psutil": fake_psutil}
        ), patch(
            "network_neighbour_collector._default_route_source_ip",
            return_value="192.168.50.25",
        ):
            network = get_local_network()

        self.assertEqual(network["interface"], "Wi-Fi")
        self.assertEqual(network["local_ip"], "192.168.50.25")
        self.assertEqual(network["network"], "192.168.50.0/24")

    def test_discover_active_arp_normalizes_scapy_responses(self):
        fake_context = {"interface": "eth0", "network": "172.16.0.0/24"}
        fake_responses = [
            SimpleNamespace(psrc="172.16.0.50", hwsrc="aa:bb:cc:dd:ee:50"),
            SimpleNamespace(psrc="172.16.0.51", hwsrc="aa:bb:cc:dd:ee:51"),
        ]
        devices = discover_active_arp(fake_context, arp_runner=lambda net, iface, to: fake_responses)
        self.assertEqual(len(devices), 2)
        self.assertEqual(devices[0]["ip_address"], "172.16.0.50")
        self.assertEqual(devices[0]["mac_address"], "AA:BB:CC:DD:EE:50")
        self.assertEqual(devices[1]["ip_address"], "172.16.0.51")
        self.assertEqual(devices[1]["mac_address"], "AA:BB:CC:DD:EE:51")

    def test_merge_neighbours_by_mac_deduplicates_and_preserves_details(self):
        passive = [
            {
                "ip_address": "172.16.0.102",
                "mac_address": "AA:BB:CC:DD:EE:FF",
                "entry_type": "dynamic",
                "interface": "eth0",
                "hostname": "workstation-01",
            }
        ]
        active = [
            {
                "ip_address": "172.16.0.102",
                "mac_address": "AA:BB:CC:DD:EE:FF",
                "entry_type": "dynamic",
                "interface": "eth0",
            },
            {
                "ip_address": "172.16.0.105",
                "mac_address": "12:22:33:44:55:66",
                "entry_type": "dynamic",
                "interface": "eth0",
            },
        ]
        merged = merge_neighbours_by_mac(passive, active)
        self.assertEqual(len(merged), 2)
        dev1 = next(d for d in merged if d["mac_address"] == "AA:BB:CC:DD:EE:FF")
        self.assertEqual(dev1["hostname"], "workstation-01")
        dev2 = next(d for d in merged if d["mac_address"] == "12:22:33:44:55:66")
        self.assertEqual(dev2["ip_address"], "172.16.0.105")

    def test_collector_runs_active_scan_and_merges_when_requested(self):
        def fake_cmd(cmd, **kwargs):
            if "neigh" in cmd:
                return SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps([
                        {"dst": "172.16.0.1", "lladdr": "12:22:33:44:55:66", "state": "REACHABLE", "dev": "eth0"}
                    ]),
                )
            if "route" in cmd:
                return SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps([{"dst": "default", "dev": "eth0", "gateway": "172.16.0.1"}]),
                )
            if "addr" in cmd:
                return SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps([
                        {
                            "addr_info": [
                                {
                                    "family": "inet",
                                    "local": "172.16.0.102",
                                    "prefixlen": 24,
                                    "scope": "global",
                                }
                            ]
                        }
                    ]),
                )
            return SimpleNamespace(returncode=1, stdout="")

        fake_arp_responses = [
            SimpleNamespace(psrc="172.16.0.200", hwsrc="ee:ee:ee:ee:ee:ee")
        ]

        collector = NetworkNeighbourCollector(
            system_name="Linux",
            command_runner=fake_cmd,
            arp_runner=lambda net, iface, to: fake_arp_responses,
        )
        results = collector.collect(enrich=False, active_scan=True)
        self.assertEqual(len(results), 2)
        macs = {r["mac_address"] for r in results}
        self.assertIn("12:22:33:44:55:66", macs)
        self.assertIn("EE:EE:EE:EE:EE:EE", macs)


if __name__ == "__main__":
    unittest.main()
