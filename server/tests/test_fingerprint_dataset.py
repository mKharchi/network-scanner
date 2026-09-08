"""Streaming PCAP and dataset-layout adapter tests."""

from __future__ import annotations

import struct
import sys
import tempfile
import unittest
from pathlib import Path

SERVER_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIRECTORY))

from server_components.fingerprint_dataset import iter_probe_observations


def _probe_packet() -> bytes:
    radiotap = struct.pack("<BBHI", 0, 0, 8, 0)
    header = (
        b"\x40\x00\x00\x00"
        + bytes.fromhex("FFFFFFFFFFFF")
        + bytes.fromhex("021122334455")
        + bytes.fromhex("FFFFFFFFFFFF")
        + struct.pack("<H", 9 << 4)
    )
    ies = b"\x00\x03abc\x2d\x02\x11\x22\xdd\x04\x00\x50\xf2\x02"
    return radiotap + header + ies


class FingerprintDatasetTests(unittest.TestCase):
    def test_classic_pcap_is_streamed_without_scapy_or_payload_persistence(self):
        packet = _probe_packet()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "probe.pcap"
            with path.open("wb") as stream:
                stream.write(struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 127))
                stream.write(struct.pack("<IIII", 1_700_000_000, 123_000, len(packet), len(packet)))
                stream.write(packet)
            observations = list(iter_probe_observations(path))
        self.assertEqual(len(observations), 1)
        observation = observations[0]
        self.assertEqual(observation.frame_subtype, "Probe Request")
        self.assertEqual(observation.source_mac, "02:11:22:33:44:55")
        self.assertTrue(observation.is_randomized_mac)
        self.assertEqual(observation.sequence_number, 9)
        self.assertEqual(observation.ie_tag_sequence, (0, 45, 221))
        self.assertEqual(observation.ie_vendor_ouis, ("0050F2",))
        self.assertEqual(observation.ht_capabilities_hex, "1122")
        self.assertTrue(observation.wmm_capabilities_present)


if __name__ == "__main__":
    unittest.main()
