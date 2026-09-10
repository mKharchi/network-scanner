"""Phase 1 unit tests for the packet filter policy.

Covers every frame class described in the plan:
  - unicast data frames          → KEEP
  - broadcast data frames        → DROP
  - multicast data frames        → DROP
  - broadcast Probe Requests     → KEEP
  - directed Probe Requests      → KEEP
  - non-probe management frames  → DROP
  - control-frame noise          → DROP
  - malformed/empty packets      → DROP
  - randomized MACs              → KEEP (MAC kind does not change the policy)
  - missing optional fields      → handled gracefully
"""

from __future__ import annotations

import struct
import sys
import os
import unittest
from pathlib import Path

# Make server/ and repo-root importable so filter.py can find its dependencies.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_SERVER_DIR = _REPO_ROOT / "server"
for _extra in (_REPO_ROOT, _SERVER_DIR):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

from tools.kismet_probe_scanner.filter import Decision, classify_packet  # noqa: E402


# ---------------------------------------------------------------------------
# Packet builders (mirror the fixture helpers in test_kismet_probe_service.py)
# ---------------------------------------------------------------------------

AP = "AA:BB:CC:DD:EE:FF"
UNICAST_STA = "10:11:22:33:44:55"
RANDOMIZED_STA = "02:11:22:33:44:55"          # LAA bit set
BROADCAST = "FF:FF:FF:FF:FF:FF"
MULTICAST = "01:00:5E:00:00:01"               # IPv4 multicast


def _mac(value: str) -> bytes:
    return bytes.fromhex(value.replace(":", ""))


def _radiotap() -> bytes:
    return struct.pack("<BBHI", 0, 0, 8, 0)


def _probe_request(source: str, *, destination: str = BROADCAST, ies: bytes = b"") -> bytes:
    """Build a minimal Probe Request (management, subtype 4)."""
    fc = struct.pack("<H", (4 << 4))           # type=0 (mgmt), subtype=4
    header = fc + b"\x00\x00" + _mac(destination) + _mac(source) + _mac(AP) + struct.pack("<H", 4 << 4)
    return _radiotap() + header + ies


def _beacon(source: str = AP, *, ies: bytes = b"") -> bytes:
    """Build a minimal Beacon (management, subtype 8)."""
    fc = struct.pack("<H", (8 << 4))
    header = fc + b"\x00\x00" + _mac(BROADCAST) + _mac(source) + _mac(AP) + struct.pack("<H", 8 << 4)
    fixed = b"\x00" * 12
    return _radiotap() + header + fixed + ies


def _data_frame(source: str, destination: str, *, qos: bool = True) -> bytes:
    """Build a minimal Data (QoS or plain) frame."""
    subtype = 8 if qos else 0              # 8 = QoS Data, 0 = plain Data
    fc = struct.pack("<H", (2 << 2) | (subtype << 4))  # type=2 (data)
    header = fc + b"\x00\x00" + _mac(destination) + _mac(source) + _mac(AP) + struct.pack("<H", 0)
    return _radiotap() + header


def _ack_frame(receiver: str) -> bytes:
    """Build a minimal ACK control frame (type=1, subtype=13)."""
    fc = struct.pack("<H", (1 << 2) | (13 << 4))
    return _radiotap() + fc + b"\x00\x00" + _mac(receiver)


def _rts_frame(receiver: str, transmitter: str) -> bytes:
    fc = struct.pack("<H", (1 << 2) | (11 << 4))
    return _radiotap() + fc + b"\x00\x00" + _mac(receiver) + _mac(transmitter)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class FilterPolicyTests(unittest.TestCase):

    # ---- Probe Requests (management) ----------------------------------------

    def test_broadcast_probe_request_is_kept(self) -> None:
        pkt = _probe_request(RANDOMIZED_STA, destination=BROADCAST)
        result = classify_packet(pkt, dlt=127, source_mac=RANDOMIZED_STA, destination_mac=BROADCAST)
        self.assertEqual(result.decision, Decision.KEEP)
        self.assertIn("Probe Request", result.reason)
        self.assertEqual(result.frame_type, "Management")
        self.assertEqual(result.frame_subtype, "Probe Request")

    def test_directed_probe_request_is_kept(self) -> None:
        """Directed probe requests (to an AP) must also be retained."""
        pkt = _probe_request(UNICAST_STA, destination=AP)
        result = classify_packet(pkt, dlt=127, source_mac=UNICAST_STA, destination_mac=AP)
        self.assertEqual(result.decision, Decision.KEEP)
        self.assertEqual(result.frame_subtype, "Probe Request")

    def test_randomized_mac_probe_request_is_kept(self) -> None:
        pkt = _probe_request(RANDOMIZED_STA)
        result = classify_packet(pkt, dlt=127, source_mac=RANDOMIZED_STA, destination_mac=BROADCAST)
        self.assertEqual(result.decision, Decision.KEEP)

    # ---- Non-probe management frames ----------------------------------------

    def test_beacon_is_dropped(self) -> None:
        pkt = _beacon()
        result = classify_packet(pkt, dlt=127, source_mac=AP, destination_mac=BROADCAST)
        self.assertEqual(result.decision, Decision.DROP)
        self.assertIn("Beacon", result.reason)

    def test_non_probe_management_subtype_is_dropped(self) -> None:
        """Association Request (subtype 0) should be dropped."""
        fc = struct.pack("<H", (0 << 4))      # mgmt, subtype=0 (Assoc Req)
        header = fc + b"\x00\x00" + _mac(AP) + _mac(UNICAST_STA) + _mac(AP) + struct.pack("<H", 0)
        pkt = _radiotap() + header
        result = classify_packet(pkt, dlt=127, source_mac=UNICAST_STA, destination_mac=AP)
        self.assertEqual(result.decision, Decision.DROP)

    # ---- Data frames --------------------------------------------------------

    def test_unicast_data_frame_is_kept(self) -> None:
        pkt = _data_frame(UNICAST_STA, AP)
        result = classify_packet(pkt, dlt=127, source_mac=UNICAST_STA, destination_mac=AP)
        self.assertEqual(result.decision, Decision.KEEP)
        self.assertIn("unicast", result.reason)

    def test_broadcast_data_frame_is_dropped(self) -> None:
        pkt = _data_frame(UNICAST_STA, BROADCAST)
        result = classify_packet(pkt, dlt=127, source_mac=UNICAST_STA, destination_mac=BROADCAST)
        self.assertEqual(result.decision, Decision.DROP)
        self.assertIn("broadcast", result.reason)

    def test_multicast_data_frame_is_dropped(self) -> None:
        pkt = _data_frame(UNICAST_STA, MULTICAST)
        result = classify_packet(pkt, dlt=127, source_mac=UNICAST_STA, destination_mac=MULTICAST)
        self.assertEqual(result.decision, Decision.DROP)
        self.assertIn("multicast", result.reason)

    def test_unicast_data_from_randomized_mac_is_kept(self) -> None:
        """Randomized source MAC does not change the data-frame policy."""
        pkt = _data_frame(RANDOMIZED_STA, AP)
        result = classify_packet(pkt, dlt=127, source_mac=RANDOMIZED_STA, destination_mac=AP)
        self.assertEqual(result.decision, Decision.KEEP)

    # ---- Control frames -----------------------------------------------------

    def test_ack_frame_is_dropped(self) -> None:
        pkt = _ack_frame(UNICAST_STA)
        result = classify_packet(pkt, dlt=127, destination_mac=UNICAST_STA)
        self.assertEqual(result.decision, Decision.DROP)
        self.assertIn("control", result.reason.lower())

    def test_rts_frame_is_dropped(self) -> None:
        pkt = _rts_frame(AP, UNICAST_STA)
        result = classify_packet(pkt, dlt=127, source_mac=UNICAST_STA, destination_mac=AP)
        self.assertEqual(result.decision, Decision.DROP)

    # ---- Malformed / missing optional fields ---------------------------------

    def test_none_packet_is_dropped(self) -> None:
        result = classify_packet(None, dlt=127)
        self.assertEqual(result.decision, Decision.DROP)
        self.assertIn("malformed", result.reason)
        self.assertIsNone(result.frame_type)

    def test_empty_bytes_is_dropped(self) -> None:
        result = classify_packet(b"", dlt=127)
        self.assertEqual(result.decision, Decision.DROP)

    def test_truncated_packet_is_dropped(self) -> None:
        result = classify_packet(b"\x00\x00", dlt=127)
        self.assertEqual(result.decision, Decision.DROP)

    def test_random_noise_bytes_are_dropped(self) -> None:
        result = classify_packet(b"\xDE\xAD\xBE\xEF" * 10, dlt=127)
        self.assertEqual(result.decision, Decision.DROP)

    def test_missing_optional_source_mac_does_not_raise(self) -> None:
        """Classify a probe request without providing the source_mac kwarg."""
        pkt = _probe_request(RANDOMIZED_STA, destination=BROADCAST)
        # parse_80211_packet falls back to addr2 from the frame
        result = classify_packet(pkt, dlt=127)
        self.assertEqual(result.decision, Decision.KEEP)

    # ---- Output completeness -----------------------------------------------

    def test_result_contains_destination_kind(self) -> None:
        pkt = _probe_request(RANDOMIZED_STA, destination=BROADCAST)
        result = classify_packet(pkt, dlt=127, source_mac=RANDOMIZED_STA, destination_mac=BROADCAST)
        self.assertEqual(result.destination_kind, "broadcast")

    def test_unicast_data_result_has_unicast_destination_kind(self) -> None:
        pkt = _data_frame(UNICAST_STA, AP)
        result = classify_packet(pkt, dlt=127, source_mac=UNICAST_STA, destination_mac=AP)
        self.assertEqual(result.destination_kind, "unicast")

    def test_drop_reason_is_never_empty(self) -> None:
        """Every DROP result must supply a non-empty reason string."""
        cases = [
            _beacon(),
            _ack_frame(UNICAST_STA),
            _data_frame(UNICAST_STA, BROADCAST),
            b"bad",
        ]
        for pkt in cases:
            result = classify_packet(pkt, dlt=127)
            if result.decision == Decision.DROP:
                self.assertTrue(result.reason, f"empty reason for packet {pkt!r}")


if __name__ == "__main__":
    unittest.main()
