"""Unit tests for the independent passive protocol listener."""

import struct
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


CLIENT_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLIENT_DIRECTORY))

from passive_protocol_listener import (  # noqa: E402
    PassiveObservationBuffer,
    PassiveProtocolListener,
    _dns_observations,
    normalise_passive_observation,
    parse_nbns_payload,
    parse_ssdp_payload,
)


class PassiveProtocolListenerTests(unittest.TestCase):
    @staticmethod
    def _dns_name(name):
        return b"".join(
            bytes([len(label)]) + label.encode("utf-8")
            for label in name.split(".")
        ) + b"\x00"

    @staticmethod
    def _nbns_name(name, suffix=0x20):
        raw_name = name.upper().encode("ascii")[:15].ljust(15, b" ") + bytes([suffix])
        encoded = b"".join(
            bytes([ord("A") + (byte >> 4), ord("A") + (byte & 0x0F)])
            for byte in raw_name
        )
        return b"\x20" + encoded + b"\x00"

    def test_normalisation_omits_invalid_optional_fields(self):
        normalized = normalise_passive_observation(
            {
                "protocol": "mdns",
                "ip_address": "224.0.0.251",
                "hostname": "printer.local",
            }
        )
        self.assertIsNotNone(normalized)
        self.assertNotIn("ip_address", normalized)

        normalized = normalise_passive_observation(
            {
                "protocol": "llmnr",
                "ip_address": "172.16.0.20",
                "hostname": "bad\nname",
            }
        )
        self.assertIsNotNone(normalized)
        self.assertNotIn("hostname", normalized)

    def test_buffer_deduplicates_and_preserves_first_observation(self):
        buffer = PassiveObservationBuffer()
        observation = {
            "protocol": "mdns",
            "hostname": "printer.local",
            "service_type": "_ipp._tcp.local",
            "ip_address": "172.16.0.20",
        }

        self.assertTrue(buffer.add(observation, observed_at="2026-08-22T10:00:00+00:00"))
        self.assertTrue(buffer.add(observation, observed_at="2026-08-22T10:05:00+00:00"))

        snapshot = buffer.snapshot()
        self.assertEqual(len(snapshot), 1)
        self.assertEqual(snapshot[0]["seen_count"], 2)
        self.assertEqual(snapshot[0]["first_observed_at"], "2026-08-22T10:00:00+00:00")
        self.assertEqual(snapshot[0]["observed_at"], "2026-08-22T10:05:00+00:00")

    def test_buffer_evicts_oldest_observation_at_capacity(self):
        buffer = PassiveObservationBuffer(max_observations=2)
        for name, timestamp in (
            ("one.local", "2026-08-22T10:00:00+00:00"),
            ("two.local", "2026-08-22T10:01:00+00:00"),
            ("three.local", "2026-08-22T10:02:00+00:00"),
        ):
            self.assertTrue(
                buffer.add(
                    {"protocol": "llmnr", "hostname": name, "ip_address": "172.16.0.20"},
                    observed_at=timestamp,
                )
            )

        self.assertEqual(
            [item["hostname"] for item in buffer.snapshot()],
            ["three.local", "two.local"],
        )

    def test_duplicate_refresh_prevents_a_recent_observation_from_being_evicted(self):
        buffer = PassiveObservationBuffer(max_observations=2)
        one = {"protocol": "llmnr", "hostname": "one.local", "ip_address": "172.16.0.20"}
        two = {"protocol": "llmnr", "hostname": "two.local", "ip_address": "172.16.0.21"}
        three = {"protocol": "llmnr", "hostname": "three.local", "ip_address": "172.16.0.22"}

        buffer.add(one, observed_at="2026-08-22T10:00:00+00:00")
        buffer.add(two, observed_at="2026-08-22T10:01:00+00:00")
        buffer.add(one, observed_at="2026-08-22T10:02:00+00:00")
        buffer.add(three, observed_at="2026-08-22T10:03:00+00:00")

        snapshot = buffer.snapshot()
        self.assertEqual([item["hostname"] for item in snapshot], ["three.local", "one.local"])
        self.assertEqual(snapshot[1]["seen_count"], 2)

    def test_snapshot_is_a_defensive_copy_of_memory_only_observations(self):
        buffer = PassiveObservationBuffer()
        buffer.add(
            {
                "protocol": "ssdp",
                "ip_address": "172.16.0.30",
                "device_type": "urn:example:device:1",
                "raw_fields": {"usn": "uuid:device-1"},
            },
            observed_at="2026-08-22T10:00:00+00:00",
        )

        first_snapshot = buffer.snapshot()
        first_snapshot[0]["raw_fields"]["usn"] = "changed-by-caller"

        second_snapshot = buffer.snapshot()
        self.assertEqual(second_snapshot[0]["raw_fields"]["usn"], "uuid:device-1")
        self.assertEqual(len(buffer), 1)

    def test_parses_mdns_address_response(self):
        name = b"\x07printer\x05local\x00"
        payload = (
            struct.pack("!HHHHHH", 0, 0x8400, 0, 1, 0, 0)
            + name
            + struct.pack("!HHIH", 1, 1, 120, 4)
            + bytes([172, 16, 0, 20])
        )

        observations = _dns_observations(
            "mdns", payload, {"ip_address": "172.16.0.20", "mac_address": "AA:BB:CC:DD:EE:FF"}
        )

        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0]["hostname"], "printer.local")
        self.assertEqual(observations[0]["ip_address"], "172.16.0.20")

    def test_parses_mdns_service_records(self):
        service_type = "_ipp._tcp.local"
        service_name = "Office Printer._ipp._tcp.local"
        hostname = "printer.local"
        ptr_rdata = self._dns_name(service_name)
        srv_rdata = struct.pack("!HHH", 0, 0, 631) + self._dns_name(hostname)
        payload = (
            struct.pack("!HHHHHH", 0, 0x8400, 0, 2, 0, 0)
            + self._dns_name(service_type)
            + struct.pack("!HHIH", 12, 1, 120, len(ptr_rdata))
            + ptr_rdata
            + self._dns_name(service_name)
            + struct.pack("!HHIH", 33, 1, 120, len(srv_rdata))
            + srv_rdata
        )

        observations = _dns_observations("mdns", payload, {})

        self.assertEqual(observations[0]["service_type"], service_type)
        self.assertEqual(observations[0]["service_name"], service_name)
        self.assertEqual(observations[1]["hostname"], hostname)
        self.assertEqual(observations[1]["service_port"], 631)

    def test_parses_llmnr_query_and_response(self):
        hostname = "workstation"
        query = (
            struct.pack("!HHHHHH", 1, 0, 1, 0, 0, 0)
            + self._dns_name(hostname)
            + struct.pack("!HH", 1, 1)
        )
        response = (
            struct.pack("!HHHHHH", 1, 0x8000, 0, 1, 0, 0)
            + self._dns_name(hostname)
            + struct.pack("!HHIH", 1, 1, 30, 4)
            + bytes([172, 16, 0, 44])
        )

        query_observations = _dns_observations(
            "llmnr", query, {"ip_address": "172.16.0.10"}
        )
        response_observations = _dns_observations("llmnr", response, {})

        self.assertEqual(query_observations[0]["observation_kind"], "query")
        self.assertEqual(query_observations[0]["hostname"], hostname)
        self.assertEqual(response_observations[0]["observation_kind"], "response")
        self.assertEqual(response_observations[0]["hostname"], hostname)
        self.assertEqual(response_observations[0]["ip_address"], "172.16.0.44")

    def test_parses_nbns_query_and_response(self):
        name = self._nbns_name("OFFICE-PC")
        query = struct.pack("!HHHHHH", 1, 0, 1, 0, 0, 0) + name + struct.pack("!HH", 0x20, 1)
        response = (
            struct.pack("!HHHHHH", 1, 0x8500, 0, 1, 0, 0)
            + name
            + struct.pack("!HHIH", 0x20, 1, 30, 6)
            + b"\x00\x00\xac\x10\x00\x32"
        )

        query_observations = parse_nbns_payload(query, {"ip_address": "172.16.0.10"})
        response_observations = parse_nbns_payload(response, {})

        self.assertEqual(query_observations[0]["observation_kind"], "query")
        self.assertEqual(query_observations[0]["hostname"], "OFFICE-PC")
        self.assertEqual(response_observations[0]["observation_kind"], "response")
        self.assertEqual(response_observations[0]["hostname"], "OFFICE-PC")
        self.assertEqual(response_observations[0]["ip_address"], "172.16.0.50")

    def test_parses_ssdp_without_fetching_location(self):
        payload = (
            b"NOTIFY * HTTP/1.1\r\n"
            b"NT: urn:schemas-upnp-org:device:MediaServer:1\r\n"
            b"USN: uuid:device-1::upnp:rootdevice\r\n"
            b"LOCATION: http://172.16.0.30:8200/description.xml\r\n"
            b"SERVER: Example/1.0 UPnP/1.1\r\n\r\n"
        )
        observations = parse_ssdp_payload(payload, {"ip_address": "172.16.0.30"})

        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0]["observation_kind"], "advertisement")
        self.assertEqual(observations[0]["device_type"], "urn:schemas-upnp-org:device:MediaServer:1")
        self.assertEqual(
            observations[0]["location"], "http://172.16.0.30:8200/description.xml"
        )
        self.assertEqual(observations[0]["raw_fields"]["usn"], "uuid:device-1::upnp:rootdevice")

    def test_parses_ssdp_search_response(self):
        payload = (
            b"HTTP/1.1 200 OK\r\n"
            b"ST: urn:schemas-upnp-org:service:ContentDirectory:1\r\n"
            b"USN: uuid:device-2::urn:schemas-upnp-org:service:ContentDirectory:1\r\n"
            b"LOCATION: http://172.16.0.31:8200/description.xml\r\n\r\n"
        )

        observations = parse_ssdp_payload(payload, {"ip_address": "172.16.0.31"})

        self.assertEqual(observations[0]["observation_kind"], "response")
        self.assertEqual(
            observations[0]["device_type"],
            "urn:schemas-upnp-org:service:ContentDirectory:1",
        )
        self.assertEqual(observations[0]["raw_fields"]["usn"].split("::")[0], "uuid:device-2")

    def test_scapy_callback_discards_the_internal_observation_count(self):
        listener = PassiveProtocolListener()
        packet = object()

        with patch.object(listener, "process_packet", return_value=3) as process_packet:
            self.assertIsNone(listener._handle_scapy_packet(packet))

        process_packet.assert_called_once_with(packet)

    def test_listener_start_is_idempotent_and_stop_joins_worker(self):
        listener = PassiveProtocolListener()
        with patch.object(
            listener,
            "_capture_with_scapy",
            side_effect=lambda: listener._stop.wait(1),
        ):
            self.assertTrue(listener.start())
            self.assertFalse(listener.start())
            listener.stop()

        self.assertFalse(listener.running)

    def test_listener_reports_protocol_readiness_and_partial_availability(self):
        messages = []
        listener = PassiveProtocolListener(status_callback=messages.append)
        with patch.object(
            listener,
            "_capture_with_scapy",
            side_effect=lambda: listener._stop.wait(1),
        ):
            self.assertTrue(listener.start())
            self.assertEqual(listener.availability, "AVAILABLE")
            listener._mark_protocol_unavailable("ssdp", "test capture failure")
            self.assertEqual(listener.availability, "PARTIALLY_AVAILABLE")
            listener.stop()

        self.assertIn("[PASSIVE LISTENER] Starting unified discovery scanner...", messages)
        self.assertIn("[PASSIVE LISTENER] DHCP listener active", messages)
        self.assertIn("[PASSIVE LISTENER] mDNS listener active", messages)
        self.assertIn("[PASSIVE LISTENER] LLMNR listener active", messages)
        self.assertIn("[PASSIVE LISTENER] NBNS listener active", messages)
        self.assertIn("[PASSIVE LISTENER] SSDP listener active", messages)
        self.assertIn("[PASSIVE LISTENER] Unified listener ready (AVAILABLE)", messages)
        self.assertIn(
            "[PASSIVE LISTENER] SSDP unavailable: test capture failure", messages
        )

    def test_listener_reports_capture_unavailable_without_leaking_a_worker(self):
        messages = []
        listener = PassiveProtocolListener(status_callback=messages.append)
        listener._capture_error = "Npcap unavailable"
        with listener._status_lock:
            for protocol in listener._protocol_status:
                listener._protocol_status[protocol] = "AVAILABLE"
        with patch.object(listener, "_capture_with_scapy", return_value=False):
            listener._run()

        self.assertEqual(listener.availability, "UNAVAILABLE")
        self.assertIn("[PASSIVE LISTENER] Listener unavailable (UNAVAILABLE)", messages)
        self.assertIn("[PASSIVE LISTENER] Capture worker stopped", messages)

    def test_unified_listener_correlates_dhcp_and_mdns_into_one_device_record(self):
        listener = PassiveProtocolListener()
        
        # Simulate DHCP observation
        dhcp_obs = {
            "protocol": "dhcp",
            "mac_address": "E4:FD:45:BA:8B:96",
            "ip_address": "172.16.2.50",
            "hostname": "DESKTOP-ABC",
            "vendor_class": "MSFT 5.0",
            "parameter_request_list": [1, 3, 6, 15, 31, 33, 43, 44, 46, 47],
        }
        listener._correlate_observation(dhcp_obs)

        # Simulate mDNS observation on same MAC
        mdns_obs = {
            "protocol": "mdns",
            "mac_address": "E4:FD:45:BA:8B:96",
            "ip_address": "172.16.2.50",
            "hostname": "DESKTOP-ABC.local",
            "service_type": "_dosvc._tcp.local",
        }
        listener._correlate_observation(mdns_obs)

        devices = listener.snapshot_devices()
        self.assertEqual(len(devices), 1)
        device = devices[0]
        self.assertEqual(device["mac_address"], "E4:FD:45:BA:8B:96")
        self.assertEqual(device["hostname"], "DESKTOP-ABC")
        self.assertEqual(device["os_hint"], "Windows")
        self.assertIn("dhcp", device["protocols_seen"])
        self.assertIn("mdns", device["protocols_seen"])
        self.assertIn("_dosvc._tcp.local", device["services"])
        self.assertIn("dhcp.vendor_class", device["evidence"]["os_hint"])


if __name__ == "__main__":
    unittest.main()
