"""Unit tests for DeviceRecord, DeviceCorrelator, and presence states."""

import sys
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

CLIENT_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLIENT_DIRECTORY))

from device_model import (
    DeviceCorrelator,
    DeviceRecord,
    calculate_presence_state,
    normalise_ip_address,
    normalise_mac_address,
)


class DeviceModelTests(unittest.TestCase):
    def test_mac_and_ip_normalisation(self):
        self.assertEqual(normalise_mac_address("aa-bb-cc-dd-ee-ff"), "AA:BB:CC:DD:EE:FF")
        self.assertEqual(normalise_mac_address("AA:BB:CC:DD:EE:FF"), "AA:BB:CC:DD:EE:FF")
        self.assertIsNone(normalise_mac_address("FF:FF:FF:FF:FF:FF"))  # Broadcast
        self.assertIsNone(normalise_mac_address("01:00:5E:00:00:01"))  # Multicast
        self.assertIsNone(normalise_mac_address("invalid-mac"))

        self.assertEqual(normalise_ip_address("192.168.1.50"), "192.168.1.50")
        self.assertEqual(normalise_ip_address("fe80::1"), "fe80::1")
        self.assertIsNone(normalise_ip_address("224.0.0.1"))  # Multicast
        self.assertIsNone(normalise_ip_address("127.0.0.1"))  # Loopback
        self.assertIsNone(normalise_ip_address("0.0.0.0"))  # Unspecified

    def test_presence_states(self):
        now = datetime.now(timezone.utc)
        ts_active = (now - timedelta(minutes=5)).isoformat()
        ts_idle = (now - timedelta(minutes=30)).isoformat()
        ts_stale = (now - timedelta(hours=6)).isoformat()
        ts_old = (now - timedelta(hours=30)).isoformat()

        self.assertEqual(calculate_presence_state(ts_active, now), "PASSIVELY_ACTIVE")
        self.assertEqual(calculate_presence_state(ts_idle, now), "PASSIVELY_IDLE")
        self.assertEqual(calculate_presence_state(ts_stale, now), "PASSIVELY_STALE")
        self.assertEqual(calculate_presence_state(ts_old, now), "NOT_RECENTLY_OBSERVED")

    def test_device_record_temporal_tracking(self):
        t1 = "2026-08-22T10:00:00+00:00"
        t2 = "2026-08-22T10:15:00+00:00"
        t3 = "2026-08-22T10:30:00+00:00"

        dev = DeviceRecord(mac_address="AA:BB:CC:DD:EE:FF", first_seen=t1)
        self.assertEqual(dev.first_seen, t1)
        self.assertEqual(dev.last_seen, t1)
        self.assertEqual(dev.seen_count, 1)

        dev.record_activity(t2, protocol="dhcp")
        self.assertEqual(dev.first_seen, t1)  # Immutable
        self.assertEqual(dev.last_seen, t2)
        self.assertEqual(dev.seen_count, 2)
        self.assertIn("dhcp", dev.protocols_seen)

        dev.record_activity(t3, protocol="mdns")
        self.assertEqual(dev.first_seen, t1)
        self.assertEqual(dev.last_seen, t3)
        self.assertEqual(dev.seen_count, 3)
        self.assertEqual(dev.protocols_seen, ["dhcp", "mdns"])

    def test_protocol_last_seen_tracks_exact_per_protocol_timestamps(self):
        t1 = "2026-08-22T10:00:00+00:00"
        t2 = "2026-08-22T10:15:00+00:00"
        t0 = "2026-08-22T09:00:00+00:00"  # earlier than t1, same protocol as t1

        dev = DeviceRecord(mac_address="AA:BB:CC:DD:EE:FF", first_seen=t1)
        dev.record_activity(t1, protocol="dhcp")
        dev.record_activity(t2, protocol="mdns")
        self.assertEqual(dev.protocol_last_seen["dhcp"], t1)
        self.assertEqual(dev.protocol_last_seen["mdns"], t2)

        # An out-of-order (earlier) observation for an already-seen protocol
        # must not regress its recorded last_seen.
        dev.record_activity(t0, protocol="dhcp")
        self.assertEqual(dev.protocol_last_seen["dhcp"], t1)
        self.assertEqual(dev.to_dict()["protocol_last_seen"], {"dhcp": t1, "mdns": t2})

    def test_device_correlator_merges_multi_protocol_evidence(self):
        correlator = DeviceCorrelator()

        # DHCP observation
        dev = correlator.get_or_create_device("AA:BB:CC:DD:EE:FF", "192.168.1.100")
        dev.set_hostname("DESKTOP-ABC", source="dhcp", priority=40)
        dev.add_protocol("dhcp")

        # Subsequent mDNS observation with same MAC
        dev2 = correlator.get_or_create_device("AA:BB:CC:DD:EE:FF", "192.168.1.100")
        self.assertIs(dev, dev2)
        dev2.set_hostname("DESKTOP-ABC.local", source="mdns", priority=30)
        dev2.add_protocol("mdns")
        dev2.add_service("_dosvc._tcp.local")

        # Hostname should retain clean DHCP hostname
        self.assertEqual(dev2.hostname, "DESKTOP-ABC")
        self.assertIn("dhcp", dev2.protocols_seen)
        self.assertIn("mdns", dev2.protocols_seen)
        self.assertIn("_dosvc._tcp.local", dev2.services)
        self.assertIn("dhcp", dev2.evidence["hostname"])
        self.assertIn("mdns", dev2.evidence["hostname"])

    def test_device_correlator_secondary_ip_correlation(self):
        correlator = DeviceCorrelator()

        # Observation without MAC (e.g. SSDP)
        dev_ssdp = correlator.get_or_create_device(None, "192.168.1.150")
        dev_ssdp.software_hint = "Windows/10.0 UPnP/1.1"
        dev_ssdp.add_protocol("ssdp")

        # Later DHCP observation with MAC on same IP
        dev_dhcp = correlator.get_or_create_device("12:22:33:44:55:66", "192.168.1.150")
        self.assertIs(dev_ssdp, dev_dhcp)
        self.assertEqual(dev_dhcp.mac_address, "12:22:33:44:55:66")
        self.assertEqual(dev_dhcp.software_hint, "Windows/10.0 UPnP/1.1")
        self.assertIn("ssdp", dev_dhcp.protocols_seen)


if __name__ == "__main__":
    unittest.main()
