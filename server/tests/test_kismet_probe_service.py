"""Tests for global, metadata-only Kismet Probe Request/Response browsing."""

from __future__ import annotations

import sqlite3
import struct
import json
import os
import time
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

SERVER_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIRECTORY))

from server_components.kismet_service import KismetInvestigationService


AP = "AA:BB:CC:DD:EE:FF"
STABLE = "10:11:22:33:44:55"
RANDOMIZED = "02:11:22:33:44:55"
BASE = int(datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc).timestamp())


def _mac(value: str) -> bytes:
    return bytes.fromhex(value.replace(":", ""))


def _probe(subtype: int, source: str, *, destination: str = "FF:FF:FF:FF:FF:FF", ies: bytes = b"") -> bytes:
    radiotap = struct.pack("<BBHI", 0, 0, 8, 0)
    header = struct.pack("<H", subtype << 4) + b"\x00\x00" + _mac(destination) + _mac(source) + _mac(AP) + struct.pack("<H", 4 << 4)
    fixed = b"\x00" * 12 if subtype == 5 else b""
    return radiotap + header + fixed + ies


def _create_db(path: Path, rows: list[tuple]) -> None:
    con = sqlite3.connect(path)
    con.execute("""CREATE TABLE packets (
        ts_sec INTEGER, ts_usec INTEGER, sourcemac TEXT, destmac TEXT, transmac TEXT,
        signal INTEGER, frequency REAL, packet_len INTEGER, datasource TEXT, dlt INTEGER,
        packet BLOB, hash TEXT
    )""")
    con.executemany("INSERT INTO packets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    con.commit()
    con.close()


class RecentProbeQueryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        ies = b"".join((
            b"\x00\x08MyWiFi42",  # must never appear in returned data
            b"\x01\x02\x82\x84",
            b"\x32\x01\x8b",
            b"\x2d\x02\x11\x22",
            b"\xdd\x04\x00\x50\xf2\x02",
            b"\x30\x02\x01\x00",
        ))
        request = _probe(4, RANDOMIZED, ies=ies)
        response = _probe(5, STABLE, destination=RANDOMIZED, ies=ies)
        request_2 = _probe(4, "06:11:22:33:44:56", ies=ies)
        _create_db(self.root / "first.kismet", [
            (BASE, 0, RANDOMIZED.lower(), "ff:ff:ff:ff:ff:ff", RANDOMIZED.lower(), -55, 2412000, len(request), "sensor-a", 127, request, "r1"),
            (BASE + 1, 0, STABLE.lower(), RANDOMIZED.lower(), STABLE.lower(), -68, 2412000, len(response), "sensor-a", 127, response, "p1"),
        ])
        _create_db(self.root / "second.kismet", [
            (BASE + 2, 0, "06:11:22:33:44:56", "ff:ff:ff:ff:ff:ff", "06:11:22:33:44:56", -72, 5180000, len(request_2), "sensor-b", 127, request_2, "r2"),
        ])
        self.service = KismetInvestigationService(capture_dirs=[self.root])

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_global_query_reads_all_files_and_returns_no_packet_blob_or_ssid_text(self) -> None:
        result = self.service.query_recent_probes(lookback_minutes="all")
        self.assertEqual(result["summary"]["observation_count"], 3)
        self.assertEqual({item["capture_file"] for item in result["observations"]}, {"first.kismet", "second.kismet"})
        self.assertEqual(result["observations"][0]["frame_subtype"], "Probe Request")
        self.assertEqual(result["summary"]["randomized_source_mac_count"], 2)
        serialized = json.dumps(result)
        self.assertNotIn('"packet":', serialized)
        self.assertNotIn("mywifi42", serialized.lower())

    def test_filters_and_metadata_are_decoded(self) -> None:
        randomized = self.service.query_recent_probes(lookback_minutes="all", randomized=True, channel=1)
        self.assertEqual(len(randomized["observations"]), 1)
        observation = randomized["observations"][0]
        self.assertTrue(observation["is_randomized_mac"])
        self.assertEqual(observation["destination_kind"], "broadcast")
        self.assertEqual(observation["supported_rates_mbps"], [1.0, 2.0, 5.5])
        self.assertEqual(observation["vendor_ouis"], ["0050F2"])
        self.assertTrue(observation["rsn_capabilities_present"])
        self.assertEqual(observation["ssid_length"], 8)
        self.assertTrue(observation["wmm_capabilities_present"])

    def test_candidate_groups_do_not_use_mac_address(self) -> None:
        result = self.service.query_recent_probes(lookback_minutes="all", subtype="request")
        self.assertEqual(len(result["candidate_groups"]), 1)
        group = result["candidate_groups"][0]
        self.assertEqual(group["unique_mac_count"], 2)
        self.assertEqual(group["probe_count"], 2)
        self.assertNotIn(RANDOMIZED, group["fingerprint_signature"])

    def test_invalid_filters_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.service.query_recent_probes(channel="bad")
        with self.assertRaises(ValueError):
            self.service.query_recent_probes(subtype="beacon")
        with self.assertRaises(ValueError):
            self.service.query_recent_probes(bssid="not-a-mac")

    def test_stale_rollback_journal_uses_committed_snapshot(self) -> None:
        db = self.root / "stale.kismet"
        _create_db(db, [])
        journal = Path(f"{db}-journal")
        journal.write_bytes(b"stale journal")
        old = time.time() - 3600
        os.utime(db, (old, old))
        os.utime(journal, (old, old))
        result = KismetInvestigationService(capture_dirs=[self.root]).query_recent_probes(
            lookback_minutes="all", capture_file=db.name,
        )
        self.assertEqual(len(result["observations"]), 0)
        self.assertNotIn(db.name, result["rejected_captures"])
        self.assertIn(db.name, result["degraded_captures"])

    def test_active_rollback_journal_uses_committed_snapshot(self) -> None:
        db = self.root / "active.kismet"
        request = _probe(4, RANDOMIZED)
        _create_db(db, [
            (BASE + 10, 0, RANDOMIZED, "FF:FF:FF:FF:FF:FF", RANDOMIZED, -50,
             2412000, len(request), "sensor-live", 127, request, "live-1"),
        ])
        journal = Path(f"{db}-journal")
        journal.write_bytes(b"active journal marker")
        now = time.time()
        os.utime(db, (now, now))
        os.utime(journal, (now, now))

        result = KismetInvestigationService(capture_dirs=[self.root]).query_recent_probes(
            lookback_minutes="all", capture_file=db.name,
        )
        self.assertEqual(len(result["observations"]), 1)
        self.assertNotIn(db.name, result["rejected_captures"])
        self.assertIn(db.name, result["degraded_captures"])

    def test_backward_scan_finds_probe_before_newer_data_rows(self) -> None:
        db = self.root / "burst-before-data.kismet"
        request = _probe(4, RANDOMIZED)
        non_probe = _probe(8, STABLE)
        rows = [
            (BASE, 0, RANDOMIZED, "FF:FF:FF:FF:FF:FF", RANDOMIZED, -48,
             2412000, len(request), "sensor-a", 127, request, "probe-first"),
        ]
        rows.extend(
            (BASE + offset, 0, STABLE, "FF:FF:FF:FF:FF:FF", STABLE, -60,
             2412000, len(non_probe), "sensor-a", 127, non_probe, f"newer-{offset}")
            for offset in range(1, 8)
        )
        _create_db(db, rows)

        with patch("server_components.kismet_service.MAX_PROBE_SCAN_ROWS_PER_CAPTURE", 8), \
                patch("server_components.kismet_service.PROBE_SCAN_BATCH_ROWS", 2):
            result = KismetInvestigationService(capture_dirs=[self.root]).query_recent_probes(
                lookback_minutes="all", capture_file=db.name, limit=1,
            )

        self.assertEqual(len(result["observations"]), 1)
        self.assertEqual(result["observations"][0]["source_mac"], RANDOMIZED)
        self.assertNotIn(db.name, result["truncated_captures"])

    def test_small_limit_still_scans_past_non_probe_burst(self) -> None:
        """Result limit must not shrink the per-capture scan budget."""
        db = self.root / "limit-vs-scan.kismet"
        request = _probe(4, RANDOMIZED)
        non_probe = _probe(8, STABLE)
        rows = [
            (BASE, 0, RANDOMIZED, "FF:FF:FF:FF:FF:FF", RANDOMIZED, -48,
             2412000, len(request), "sensor-a", 127, request, "probe-buried"),
        ]
        rows.extend(
            (BASE + offset, 0, STABLE, "FF:FF:FF:FF:FF:FF", STABLE, -60,
             2412000, len(non_probe), "sensor-a", 127, non_probe, f"newer-{offset}")
            for offset in range(1, 250)
        )
        _create_db(db, rows)

        result = KismetInvestigationService(capture_dirs=[self.root]).query_recent_probes(
            lookback_minutes="all", capture_file=db.name, limit=1,
        )
        self.assertEqual(len(result["observations"]), 1)
        self.assertEqual(result["observations"][0]["source_mac"], RANDOMIZED)

    def test_scan_safety_cap_is_reported(self) -> None:
        db = self.root / "truncated.kismet"
        request = _probe(4, RANDOMIZED)
        non_probe = _probe(8, STABLE)
        rows = [
            (BASE, 0, RANDOMIZED, "FF:FF:FF:FF:FF:FF", RANDOMIZED, -48,
             2412000, len(request), "sensor-a", 127, request, "too-old-probe"),
        ]
        rows.extend(
            (BASE + offset, 0, STABLE, "FF:FF:FF:FF:FF:FF", STABLE, -60,
             2412000, len(non_probe), "sensor-a", 127, non_probe, f"newer-{offset}")
            for offset in range(1, 6)
        )
        _create_db(db, rows)

        with patch("server_components.kismet_service.MAX_PROBE_SCAN_ROWS_PER_CAPTURE", 4), \
                patch("server_components.kismet_service.PROBE_SCAN_BATCH_ROWS", 2):
            result = KismetInvestigationService(capture_dirs=[self.root]).query_recent_probes(
                lookback_minutes="all", capture_file=db.name, limit=10,
            )

        self.assertEqual(result["observations"], [])
        self.assertIn(db.name, result["truncated_captures"])


if __name__ == "__main__":
    unittest.main()
