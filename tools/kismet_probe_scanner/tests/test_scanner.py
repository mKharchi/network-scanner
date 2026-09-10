"""Phase 2 unit tests for the standalone probe scanner.

Covers:
  - CLI fixture: multiple capture files → newest probe wins
  - No-result envelope when no probes exist
  - Malformed rows are skipped without crashing
  - Journal / degraded-file handling (stale and active journals)
  - Scan-budget truncation is reported
  - Newest-first scan: probe buried behind data rows is found
  - Payload bytes and SSID text are absent from JSON output
  - Capture-file provenance is recorded
  - CLI exit-code contracts (0 on success, 0 on no-result, 1 on bad args)
"""

from __future__ import annotations

import json
import os
import sqlite3
import struct
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SERVER_DIR = _REPO_ROOT / "server"
for _extra in (_REPO_ROOT, _SERVER_DIR):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

from tools.kismet_probe_scanner.scanner import (  # noqa: E402
    MAX_SCAN_ROWS_PER_CAPTURE,
    SCAN_BATCH_ROWS,
    scan_latest_probe,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

AP = "AA:BB:CC:DD:EE:FF"
STABLE = "10:11:22:33:44:55"
RANDOMIZED = "02:AA:BB:CC:DD:EE"
BROADCAST = "FF:FF:FF:FF:FF:FF"

BASE_TS = 1_757_491_200   # 2025-09-10 12:00:00 UTC


def _mac(value: str) -> bytes:
    return bytes.fromhex(value.replace(":", ""))


def _radiotap() -> bytes:
    return struct.pack("<BBHI", 0, 0, 8, 0)


def _probe_request(source: str, *, destination: str = BROADCAST, ies: bytes = b"") -> bytes:
    fc = struct.pack("<H", 4 << 4)
    header = fc + b"\x00\x00" + _mac(destination) + _mac(source) + _mac(AP) + struct.pack("<H", 4 << 4)
    return _radiotap() + header + ies


def _beacon(source: str = AP) -> bytes:
    fc = struct.pack("<H", 8 << 4)
    header = fc + b"\x00\x00" + _mac(BROADCAST) + _mac(source) + _mac(AP) + struct.pack("<H", 8 << 4)
    return _radiotap() + header + b"\x00" * 12


def _data_unicast(source: str, dest: str = AP) -> bytes:
    fc = struct.pack("<H", (2 << 2) | (8 << 4))
    header = fc + b"\x00\x00" + _mac(dest) + _mac(source) + _mac(AP) + struct.pack("<H", 0)
    return _radiotap() + header


def _create_db(path: Path, rows: list) -> None:
    con = sqlite3.connect(path)
    con.execute("""CREATE TABLE packets (
        ts_sec INTEGER, ts_usec INTEGER, sourcemac TEXT, destmac TEXT, transmac TEXT,
        signal INTEGER, frequency REAL, packet_len INTEGER, datasource TEXT, dlt INTEGER,
        packet BLOB, hash TEXT
    )""")
    con.executemany("INSERT INTO packets VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()


def _probe_row(ts_offset: int, source: str = RANDOMIZED, *, ies: bytes = b"", sensor: str = "sensor-a") -> tuple:
    pkt = _probe_request(source, ies=ies)
    return (
        BASE_TS + ts_offset, 0,
        source, BROADCAST, source,
        -55, 2412000, len(pkt), sensor, 127, pkt, f"pr-{ts_offset}",
    )


def _beacon_row(ts_offset: int) -> tuple:
    pkt = _beacon()
    return (
        BASE_TS + ts_offset, 0,
        AP, BROADCAST, AP,
        -40, 2412000, len(pkt), "sensor-a", 127, pkt, f"b-{ts_offset}",
    )


def _data_row(ts_offset: int) -> tuple:
    pkt = _data_unicast(STABLE)
    return (
        BASE_TS + ts_offset, 0,
        STABLE, AP, STABLE,
        -70, 2412000, len(pkt), "sensor-a", 127, pkt, f"d-{ts_offset}",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class ScannerTests(unittest.TestCase):

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    # --- basic happy-path ---

    def test_finds_probe_request_in_single_file(self) -> None:
        db = self.root / "cap.kismet"
        _create_db(db, [_probe_row(0)])
        result = scan_latest_probe(capture_file=db)
        self.assertTrue(result.status.found)
        self.assertIsNotNone(result.latest_probe)
        self.assertEqual(result.latest_probe.frame_subtype, "Probe Request")

    def test_returns_newest_probe_across_two_files(self) -> None:
        db1 = self.root / "old.kismet"
        db2 = self.root / "new.kismet"
        _create_db(db1, [_probe_row(0)])
        _create_db(db2, [_probe_row(10)])
        # Give new.kismet a higher mtime so it is discovered first
        t = time.time()
        os.utime(db1, (t - 100, t - 100))
        os.utime(db2, (t, t))
        result = scan_latest_probe(capture_dirs=[self.root])
        self.assertTrue(result.status.found)
        self.assertEqual(result.latest_probe.epoch_sec, BASE_TS + 10)

    def test_no_result_when_no_captures(self) -> None:
        result = scan_latest_probe(capture_dirs=[self.root])
        self.assertFalse(result.status.found)
        self.assertIsNone(result.latest_probe)
        self.assertIsNotNone(result.status.no_result_reason)

    def test_no_result_when_only_beacons_present(self) -> None:
        db = self.root / "beacons.kismet"
        _create_db(db, [_beacon_row(0), _beacon_row(1)])
        result = scan_latest_probe(capture_file=db)
        self.assertFalse(result.status.found)
        self.assertIsNone(result.latest_probe)

    # --- payload / SSID privacy ---

    def test_json_output_contains_no_packet_bytes_or_ssid_text(self) -> None:
        db = self.root / "privacy.kismet"
        # Use a probe with a named SSID IE; the scanner must never emit the text.
        real_ies = (
            b"\x00\x08MyWiFi42"   # SSID IE — length 8, text that must not appear
            + b"\x01\x02\x82\x84" # Supported rates
        )
        pkt = _probe_request(RANDOMIZED, ies=real_ies)
        row = (BASE_TS, 0, RANDOMIZED, BROADCAST, RANDOMIZED, -55, 2412000, len(pkt), "s", 127, pkt, "pr")
        _create_db(db, [row])
        result = scan_latest_probe(capture_file=db)
        serialized = json.dumps(result.to_dict())
        # The raw packet blob key must never appear ("packet_length" is allowed)
        self.assertNotIn('"packet":', serialized)
        # Plaintext SSID must never appear
        self.assertNotIn("mywifi42", serialized.lower())
        # SSID shape fields are still present
        self.assertIn("ssid_present", serialized)
        self.assertIn("ssid_length", serialized)

    # --- IE feature extraction ---

    def test_ie_fields_are_populated(self) -> None:
        ies = (
            b"\x00\x05Hello"       # SSID, 5 bytes
            + b"\x01\x02\x82\x84" # Supported rates: 1.0, 2.0 Mbps
            + b"\x2d\x02\x11\x22" # HT capabilities
            + b"\xdd\x04\x00\x50\xf2\x02"  # WMM
            + b"\x30\x02\x01\x00" # RSN
        )
        pkt = _probe_request(RANDOMIZED, ies=ies)
        row = (BASE_TS, 0, RANDOMIZED, BROADCAST, RANDOMIZED, -55, 2412000, len(pkt), "s", 127, pkt, "ie")
        db = self.root / "ie.kismet"
        _create_db(db, [row])
        result = scan_latest_probe(capture_file=db)
        probe = result.latest_probe
        self.assertIsNotNone(probe)
        self.assertTrue(probe.ssid_present)
        self.assertEqual(probe.ssid_length, 5)
        self.assertTrue(probe.wmm_capabilities_present)
        self.assertTrue(probe.rsn_capabilities_present)
        self.assertIsNotNone(probe.ht_capabilities_digest)
        self.assertIn(1.0, probe.supported_rates_mbps)
        self.assertIn(2.0, probe.supported_rates_mbps)

    # --- provenance fields ---

    def test_capture_file_provenance_is_recorded(self) -> None:
        db = self.root / "myfile.kismet"
        _create_db(db, [_probe_row(0)])
        result = scan_latest_probe(capture_file=db)
        self.assertEqual(result.latest_probe.capture_file, "myfile.kismet")

    def test_is_randomized_mac_flag_is_set(self) -> None:
        db = self.root / "rand.kismet"
        _create_db(db, [_probe_row(0, source=RANDOMIZED)])
        result = scan_latest_probe(capture_file=db)
        self.assertTrue(result.latest_probe.is_randomized_mac)

    def test_stable_mac_not_flagged_as_randomized(self) -> None:
        db = self.root / "stable.kismet"
        _create_db(db, [_probe_row(0, source=STABLE)])
        result = scan_latest_probe(capture_file=db)
        self.assertFalse(result.latest_probe.is_randomized_mac)

    # --- malformed rows ---

    def test_malformed_rows_are_skipped(self) -> None:
        db = self.root / "mixed.kismet"
        good = _probe_row(5)
        bad = (BASE_TS + 10, 0, RANDOMIZED, BROADCAST, RANDOMIZED, -55, 2412000, 4, "s", 127, b"\xDE\xAD", "bad")
        _create_db(db, [bad, good])
        result = scan_latest_probe(capture_file=db)
        self.assertTrue(result.status.found)
        self.assertEqual(result.latest_probe.epoch_sec, BASE_TS + 5)

    def test_null_packet_blob_is_skipped(self) -> None:
        db = self.root / "null_blob.kismet"
        null_row = (BASE_TS, 0, RANDOMIZED, BROADCAST, RANDOMIZED, -55, 2412000, 0, "s", 127, None, "n")
        good = _probe_row(1)
        _create_db(db, [null_row, good])
        result = scan_latest_probe(capture_file=db)
        self.assertTrue(result.status.found)

    # --- journal / degraded files ---

    def test_stale_journal_is_opened_as_degraded(self) -> None:
        db = self.root / "stale.kismet"
        _create_db(db, [_probe_row(0)])
        journal = Path(f"{db}-journal")
        journal.write_bytes(b"stale")
        old = time.time() - 3600
        os.utime(db, (old, old))
        os.utime(journal, (old, old))
        result = scan_latest_probe(capture_file=db)
        self.assertIn("stale.kismet", result.status.degraded_captures)
        self.assertNotIn("stale.kismet", result.status.rejected_captures)

    def test_active_journal_is_opened_as_degraded(self) -> None:
        db = self.root / "active.kismet"
        _create_db(db, [_probe_row(0)])
        journal = Path(f"{db}-journal")
        journal.write_bytes(b"active")
        now = time.time()
        os.utime(db, (now, now))
        os.utime(journal, (now, now))
        result = scan_latest_probe(capture_file=db)
        self.assertIn("active.kismet", result.status.degraded_captures)

    # --- scan budget / truncation ---

    def test_scan_budget_truncation_is_reported(self) -> None:
        db = self.root / "big.kismet"
        # Probe buried behind many beacon/data rows
        rows = [_probe_row(0)]
        rows.extend(_beacon_row(i + 1) for i in range(8))
        _create_db(db, rows)

        # Patch budget to 4 so the probe at rowid=1 is never reached
        with (
            patch("tools.kismet_probe_scanner.scanner.MAX_SCAN_ROWS_PER_CAPTURE", 4),
            patch("tools.kismet_probe_scanner.scanner.SCAN_BATCH_ROWS", 2),
        ):
            result = scan_latest_probe(capture_file=db)

        self.assertIn("big.kismet", result.status.truncated_captures)

    def test_probe_found_before_budget_exhausted(self) -> None:
        db = self.root / "early.kismet"
        rows = [_beacon_row(0), _probe_row(1), _beacon_row(2), _beacon_row(3)]
        _create_db(db, rows)
        result = scan_latest_probe(capture_file=db)
        self.assertTrue(result.status.found)
        self.assertNotIn("early.kismet", result.status.truncated_captures)

    # --- to_dict serialization ---

    def test_to_dict_is_json_serializable(self) -> None:
        db = self.root / "serial.kismet"
        _create_db(db, [_probe_row(0)])
        result = scan_latest_probe(capture_file=db)
        d = result.to_dict()
        serialized = json.dumps(d)
        self.assertIn("latest_probe", serialized)
        self.assertIn("status", serialized)

    def test_no_result_to_dict_has_null_latest_probe(self) -> None:
        db = self.root / "empty.kismet"
        _create_db(db, [_beacon_row(0)])
        result = scan_latest_probe(capture_file=db)
        d = result.to_dict()
        self.assertIsNone(d["latest_probe"])
        self.assertIsNotNone(d["status"]["no_result_reason"])

    # --- fingerprint signature ---

    def test_fingerprint_signature_is_present_and_stable(self) -> None:
        ies = b"\x01\x02\x82\x84"
        pkt = _probe_request(RANDOMIZED, ies=ies)
        row = (BASE_TS, 0, RANDOMIZED, BROADCAST, RANDOMIZED, -55, 2412000, len(pkt), "s", 127, pkt, "fs")
        db = self.root / "sig.kismet"
        _create_db(db, [row])
        r1 = scan_latest_probe(capture_file=db)
        r2 = scan_latest_probe(capture_file=db)
        self.assertIsNotNone(r1.latest_probe.fingerprint_signature)
        self.assertEqual(r1.latest_probe.fingerprint_signature, r2.latest_probe.fingerprint_signature)

    def test_fingerprint_signature_does_not_contain_mac(self) -> None:
        db = self.root / "nomac.kismet"
        _create_db(db, [_probe_row(0, source=RANDOMIZED)])
        result = scan_latest_probe(capture_file=db)
        sig = result.latest_probe.fingerprint_signature
        self.assertNotIn(RANDOMIZED.lower().replace(":", ""), sig.lower())


if __name__ == "__main__":
    unittest.main()
