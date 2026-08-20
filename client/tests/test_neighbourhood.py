"""Unit tests for the client-side normalized neighbourhood representation."""

import sys
import tempfile
import unittest
from pathlib import Path


CLIENT_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLIENT_DIRECTORY))

from neighbourhood import (  # noqa: E402
    merge_neighbourhood_observations,
    load_daily_neighbourhood,
    normalise_dhcp_observation,
    normalise_neighbourhood_observation,
    update_daily_neighbourhood,
)


class NeighbourhoodTests(unittest.TestCase):
    def test_normalises_passive_arp_record(self):
        observation = normalise_neighbourhood_observation(
            {
                "ip_address": "172.16.0.102",
                "mac_address": "e4-fd-45-ba-8b-96",
                "entry_type": "dynamic",
                "interface": "eth0",
                "hostname": "desktop.local",
                "vendor": "Example Vendor",
            },
            source="arp",
            observed_at="2026-08-20T10:00:00+00:00",
        )
        self.assertEqual(observation["mac_address"], "E4:FD:45:BA:8B:96")
        self.assertEqual(observation["source"], "arp")
        self.assertEqual(observation["sources"], ["arp"])
        self.assertIsNone(observation["os"])

    def test_adapts_dhcp_record_with_dhcp_metadata(self):
        observation = normalise_dhcp_observation(
            {
                "requested_ip": "172.16.0.102",
                "mac_address": "E4:FD:45:BA:8B:96",
                "hostname": "DESKTOP-DJP05CM",
                "vendor_class": "MSFT 5.0",
                "client_id": "01:E4:FD:45:BA:8B:96",
                "dhcp_message_type": 3,
            },
            vendor="Microsoft",
            observed_at="2026-08-20T10:00:00+00:00",
        )
        self.assertEqual(observation["source"], "dhcp")
        self.assertEqual(observation["dhcp_message_type"], 3)
        self.assertEqual(observation["dhcp_vendor_class"], "MSFT 5.0")
        self.assertEqual(observation["vendor"], "Microsoft")

    def test_merges_same_mac_and_ip_without_losing_source_metadata(self):
        arp = normalise_neighbourhood_observation(
            {
                "ip_address": "172.16.0.102",
                "mac_address": "E4:FD:45:BA:8B:96",
                "entry_type": "dynamic",
                "vendor": "Microsoft",
            },
            source="arp",
            observed_at="2026-08-20T10:00:00+00:00",
        )
        dhcp = normalise_dhcp_observation(
            {
                "requested_ip": "172.16.0.102",
                "mac_address": "E4:FD:45:BA:8B:96",
                "hostname": "DESKTOP-DJP05CM",
                "vendor_class": "MSFT 5.0",
                "dhcp_message_type": 3,
            },
            observed_at="2026-08-20T10:01:00+00:00",
        )
        merged = merge_neighbourhood_observations([arp, dhcp])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["sources"], ["arp", "dhcp"])
        self.assertEqual(merged[0]["hostname"], "DESKTOP-DJP05CM")
        self.assertEqual(merged[0]["vendor"], "Microsoft")
        self.assertEqual(merged[0]["dhcp_vendor_class"], "MSFT 5.0")

    def test_daily_file_merges_same_mac_and_ip_across_updates(self):
        arp = normalise_neighbourhood_observation(
            {
                "ip_address": "172.16.0.102",
                "mac_address": "E4:FD:45:BA:8B:96",
                "entry_type": "dynamic",
                "vendor": "Microsoft",
            },
            source="arp",
            observed_at="2026-08-20T10:00:00+00:00",
        )
        dhcp = normalise_dhcp_observation(
            {
                "requested_ip": "172.16.0.102",
                "mac_address": "E4:FD:45:BA:8B:96",
                "hostname": "DESKTOP-DJP05CM",
                "vendor_class": "MSFT 5.0",
                "dhcp_message_type": 3,
            },
            observed_at="2026-08-20T10:01:00+00:00",
        )
        with tempfile.TemporaryDirectory() as directory:
            file_path, _ = update_daily_neighbourhood(
                [arp], date="2026-08-20", storage_dir=directory
            )
            _, payload = update_daily_neighbourhood(
                [dhcp], date="2026-08-20", storage_dir=directory
            )
            loaded = load_daily_neighbourhood(
                date="2026-08-20", storage_dir=directory
            )

        self.assertEqual(file_path.name, "2026-08-20.json")
        self.assertEqual(payload, loaded)
        self.assertEqual(len(loaded["observations"]), 1)
        self.assertEqual(loaded["observations"][0]["sources"], ["arp", "dhcp"])
        self.assertEqual(loaded["observations"][0]["hostname"], "DESKTOP-DJP05CM")


if __name__ == "__main__":
    unittest.main()
