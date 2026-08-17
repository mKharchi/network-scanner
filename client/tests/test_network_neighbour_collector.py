"""Unit tests for local neighbour-table collection.

Run from repository root:
    python3 client/tests/test_network_neighbour_collector.py
"""

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


CLIENT_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLIENT_DIRECTORY))

from network_neighbour_collector import (  # noqa: E402
    NetworkNeighbourCollector,
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


if __name__ == "__main__":
    unittest.main()
