"""
Phase 3 Contract Tests — KismetInvestigationService Source Adapter

These tests enforce the frozen invariants documented in:
  docs/integrating-kismet-and-backup/option-a-client-server/phase-3-contract.md

Each test class maps to a contract section (S, M, T, R, F, N, E).
Do NOT modify these tests to make failing code pass — fix the service instead.
"""

from __future__ import annotations

import sqlite3
import struct
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from server_components.kismet_service import (
    KismetInvestigationService,
    normalize_mac,
    frequency_to_channel,
)

# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------

def _make_beacon_blob() -> bytes:
    """Minimal radiotap + 802.11 Management Beacon (type=0, subtype=8 -> FC=0x80)."""
    rt = struct.pack("<BBHI", 0x00, 0x00, 8, 0x00000000)
    return rt + bytes([0x80, 0x00]) + b"\x00" * 22


def _make_data_blob() -> bytes:
    """Minimal radiotap + 802.11 Data QoS (type=2, subtype=8 -> FC=0x88)."""
    rt = struct.pack("<BBHI", 0x00, 0x00, 8, 0x00000000)
    return rt + bytes([0x88, 0x00]) + b"\x00" * 22


def _make_ack_blob() -> bytes:
    """Minimal radiotap + 802.11 Control ACK (type=1, subtype=13 -> FC=0xD4)."""
    rt = struct.pack("<BBHI", 0x00, 0x00, 8, 0x00000000)
    return rt + bytes([0xD4, 0x00]) + b"\x00" * 8


def _create_kismet_db(path: Path, rows: list) -> None:
    """Create a minimal .kismet SQLite DB with given packet rows.

    Each row: (ts_sec, ts_usec, sourcemac, destmac, transmac, signal,
               frequency, packet_len, datasource, dlt, packet_blob, hash)
    """
    con = sqlite3.connect(str(path))
    con.execute("""
        CREATE TABLE packets (
            ts_sec INTEGER, ts_usec INTEGER, phyname TEXT,
            sourcemac TEXT, destmac TEXT, transmac TEXT,
            signal INTEGER, frequency REAL, packet_len INTEGER,
            datasource TEXT, dlt INTEGER, packet BLOB, hash TEXT
        )
    """)
    for r in rows:
        ts_sec, ts_usec, src, dst, tx, sig, freq, plen, ds, dlt, blob, h = r
        con.execute(
            "INSERT INTO packets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (ts_sec, ts_usec, "IEEE802.11", src, dst, tx, sig, freq, plen, ds, dlt, blob, h),
        )
    con.commit()
    con.close()


def _fake_device(mac: str = "AA:BB:CC:DD:EE:FF") -> dict:
    return {"mac": mac, "ip_address": None, "hostname": None, "vendor": None}


def _make_svc(tmpdir: Path) -> KismetInvestigationService:
    svc = KismetInvestigationService(capture_dirs=[tmpdir])
    svc.resolve_device = lambda _: _fake_device()
    return svc


T_BASE = int(datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc).timestamp())
MAC = "AA:BB:CC:DD:EE:FF"
MAC_L = MAC.lower()

# ---------------------------------------------------------------------------
# S — Source Access Invariants
# ---------------------------------------------------------------------------

class SourceAccessContractTests(unittest.TestCase):
    """Contract section 2 — Source Access (S1, S3, S4)."""

    def test_S1_connections_use_read_only_uri(self):
        """S1: Every SQLite connection must open with ?mode=ro."""
        opened = []
        _orig = sqlite3.connect

        def capturing(database, **kw):
            opened.append(database)
            return _orig(database, **kw)

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "test.kismet"
            _create_kismet_db(db, [])
            svc = _make_svc(Path(tmp))
            with patch("server_components.kismet_service.sqlite3.connect", side_effect=capturing):
                svc.query_wireless_observations("any", lookback_minutes=10)

        for uri in opened:
            self.assertIn("mode=ro", uri, f"Missing mode=ro in URI: {uri}")

    def test_S3_corrupt_db_does_not_raise(self):
        """S3: A corrupt DB must not propagate an exception — returns empty result."""
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "corrupt.kismet"
            bad.write_bytes(b"NOT SQLITE")
            svc = _make_svc(Path(tmp))
            result = svc.query_wireless_observations("any", lookback_minutes=10)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["observations"], [])

    def test_S4_reads_from_all_files_not_just_newest(self):
        """S4: Observations from ALL .kismet files are included."""
        with tempfile.TemporaryDirectory() as tmp:
            db1 = Path(tmp) / "Kismet-A.kismet"
            db2 = Path(tmp) / "Kismet-B.kismet"
            _create_kismet_db(db1, [(T_BASE, 0, MAC_L, "ff:ff:ff:ff:ff:ff", MAC_L, -60, 2412000, 50, "ds1", 127, _make_beacon_blob(), "h1")])
            _create_kismet_db(db2, [(T_BASE + 3600, 0, MAC_L, "ff:ff:ff:ff:ff:ff", MAC_L, -65, 2412000, 50, "ds2", 127, _make_beacon_blob(), "h2")])
            svc = _make_svc(Path(tmp))
            result = svc.query_wireless_observations("any", lookback_minutes="all")
        files = {o["capture_file"] for o in result["observations"]}
        self.assertEqual(len(files), 2, "Both DB files must contribute observations")


# ---------------------------------------------------------------------------
# M — MAC Address Contract
# ---------------------------------------------------------------------------

class MacContractTests(unittest.TestCase):
    """Contract section 3 — MAC Address (M1–M4)."""

    def test_M2_normalize_returns_uppercase_colon(self):
        """M2: normalize_mac always returns uppercase colon-separated or None."""
        cases = [
            ("aa:bb:cc:dd:ee:ff", "AA:BB:CC:DD:EE:FF"),
            ("AA-BB-CC-DD-EE-FF", "AA:BB:CC:DD:EE:FF"),
            ("aabbccddeeff",      "AA:BB:CC:DD:EE:FF"),
            ("AA:BB:CC:DD:EE:FF", "AA:BB:CC:DD:EE:FF"),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(normalize_mac(raw), expected)

    def test_M2_normalize_invalid_returns_none(self):
        """M2: Invalid MACs return None."""
        for bad in ["not-a-mac", "00:11:22:33:44", "", None, 42]:
            with self.subTest(bad=bad):
                self.assertIsNone(normalize_mac(bad))

    def test_M3_kismet_lowercase_mac_matched(self):
        """M3: Uppercase target MAC must match Kismet's lowercase-stored MACs (COLLATE NOCASE)."""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "test.kismet"
            _create_kismet_db(db, [(T_BASE, 0, MAC_L, "ff:ff:ff:ff:ff:ff", MAC_L, -55, 5180000, 50, "ds", 127, _make_beacon_blob(), "h")])
            svc = KismetInvestigationService(capture_dirs=[Path(tmp)])
            svc.resolve_device = lambda _: _fake_device(MAC)  # uppercase target
            result = svc.query_wireless_observations("any", lookback_minutes="all")
        self.assertGreater(len(result["observations"]), 0)

    def test_M4_randomised_mac_not_excluded(self):
        """M4: Locally administered MACs (LAA bit set) are matched like any other."""
        laa_mac = "02:AB:CD:EF:01:23"
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "test.kismet"
            _create_kismet_db(db, [(T_BASE, 0, laa_mac.lower(), "ff:ff:ff:ff:ff:ff", laa_mac.lower(), -70, 2412000, 50, "ds", 127, _make_beacon_blob(), "h")])
            svc = KismetInvestigationService(capture_dirs=[Path(tmp)])
            svc.resolve_device = lambda _: _fake_device(laa_mac)
            result = svc.query_wireless_observations("any", lookback_minutes="all")
        self.assertGreater(len(result["observations"]), 0)


# ---------------------------------------------------------------------------
# T — Time Window Contract
# ---------------------------------------------------------------------------

class TimeWindowContractTests(unittest.TestCase):
    """Contract section 4 — Time Window (T1–T8)."""

    def test_T1_reversed_range_raises(self):
        """T1: start > end raises ValueError with correct message."""
        svc = KismetInvestigationService(capture_dirs=[])
        svc.resolve_device = lambda _: _fake_device()
        with self.assertRaises(ValueError) as ctx:
            svc.query_wireless_observations("any",
                start_time="2026-09-05T15:00:00Z",
                end_time="2026-09-05T12:00:00Z")
        self.assertIn("start_time must be earlier than end_time", str(ctx.exception))

    def test_T2_packet_at_exact_boundary_included(self):
        """T2: Packet exactly at start_ts is included; 1µs before is excluded."""
        window_start = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)
        window_end   = datetime(2026, 9, 5, 12, 10, 0, tzinfo=timezone.utc)
        ts_sec = int(window_start.timestamp())
        inside  = (ts_sec,     0,       MAC_L, "ff:ff:ff:ff:ff:ff", MAC_L, -60, 2412000, 50, "ds", 127, _make_beacon_blob(), "in")
        outside = (ts_sec - 1, 999_999, MAC_L, "ff:ff:ff:ff:ff:ff", MAC_L, -60, 2412000, 50, "ds", 127, _make_beacon_blob(), "out")
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "test.kismet"
            _create_kismet_db(db, [inside, outside])
            svc = _make_svc(Path(tmp))
            result = svc.query_wireless_observations("any",
                start_time=window_start.isoformat(),
                end_time=window_end.isoformat())
        hashes = {o["packet_hash"] for o in result["observations"]}
        self.assertIn("in",  hashes, "Packet at exact start boundary must be included")
        self.assertNotIn("out", hashes, "Packet 1µs before start must be excluded")

    def test_T4_all_lookback_disables_filter(self):
        """T4: lookback='all' returns packets from any era; query_window.start='unbounded'."""
        old_ts = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp())
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "test.kismet"
            _create_kismet_db(db, [(old_ts, 0, MAC_L, "ff:ff:ff:ff:ff:ff", MAC_L, -70, 2412000, 50, "ds", 127, _make_beacon_blob(), "old")])
            svc = _make_svc(Path(tmp))
            result = svc.query_wireless_observations("any", lookback_minutes="all")
        self.assertGreater(len(result["observations"]), 0)
        self.assertEqual(result["query_window"]["start"], "unbounded")
        self.assertIsNone(result["query_window"]["lookback_minutes"])

    def test_T4_none_lookback_disables_filter(self):
        """T4: lookback='none' also disables time filter."""
        svc = KismetInvestigationService(capture_dirs=[])
        svc.resolve_device = lambda _: _fake_device()
        result = svc.query_wireless_observations("any", lookback_minutes="none")
        self.assertEqual(result["query_window"]["start"], "unbounded")

    def test_T5_default_lookback_is_30_minutes(self):
        """T5: No time args -> 30-minute lookback_minutes in query_window."""
        svc = KismetInvestigationService(capture_dirs=[])
        svc.resolve_device = lambda _: _fake_device()
        result = svc.query_wireless_observations("any")
        self.assertAlmostEqual(result["query_window"]["lookback_minutes"], 30.0, delta=0.1)

    def test_T7_unbounded_start_label(self):
        """T7: query_window.start is 'unbounded' when no filter."""
        svc = KismetInvestigationService(capture_dirs=[])
        svc.resolve_device = lambda _: _fake_device()
        result = svc.query_wireless_observations("any", lookback_minutes="all")
        self.assertEqual(result["query_window"]["start"], "unbounded")

    def test_T8_lookback_minutes_none_when_unbounded(self):
        """T8: query_window.lookback_minutes is None when unbounded."""
        svc = KismetInvestigationService(capture_dirs=[])
        svc.resolve_device = lambda _: _fake_device()
        result = svc.query_wireless_observations("any", lookback_minutes="all")
        self.assertIsNone(result["query_window"]["lookback_minutes"])


# ---------------------------------------------------------------------------
# R — Result Ordering and Limit Contract
# ---------------------------------------------------------------------------

class ResultOrderingContractTests(unittest.TestCase):
    """Contract section 5 — Ordering and Limit (R1–R4)."""

    def test_R1_newest_first(self):
        """R1: Observations are ordered newest-first (epoch_sec descending)."""
        rows = [(T_BASE + i * 60, 0, MAC_L, "ff:ff:ff:ff:ff:ff", MAC_L, -60, 2412000, 50, "ds", 127, _make_data_blob(), f"h{i}") for i in range(5)]
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "test.kismet"
            _create_kismet_db(db, rows)
            svc = _make_svc(Path(tmp))
            result = svc.query_wireless_observations("any", lookback_minutes="all")
        secs = [o["epoch_sec"] for o in result["observations"]]
        self.assertEqual(secs, sorted(secs, reverse=True))

    def test_R2_limit_clamped_to_2000(self):
        """R2: limit > 2000 is silently clamped; observation_count <= 2000."""
        svc = KismetInvestigationService(capture_dirs=[])
        svc.resolve_device = lambda _: _fake_device()
        result = svc.query_wireless_observations("any", limit=99999)
        self.assertLessEqual(result["summary"]["observation_count"], 2000)

    def test_R3_observation_count_equals_len(self):
        """R3: summary.observation_count must always equal len(observations)."""
        rows = [(T_BASE + i, 0, MAC_L, "ff:ff:ff:ff:ff:ff", MAC_L, -60, 2412000, 50, "ds", 127, _make_data_blob(), f"h{i}") for i in range(10)]
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "test.kismet"
            _create_kismet_db(db, rows)
            svc = _make_svc(Path(tmp))
            result = svc.query_wireless_observations("any", lookback_minutes="all")
        self.assertEqual(result["summary"]["observation_count"], len(result["observations"]))


# ---------------------------------------------------------------------------
# F — Frame Role Assignment Contract
# ---------------------------------------------------------------------------

class FrameRoleContractTests(unittest.TestCase):
    """Contract section 6 — Frame Role (F1–F4)."""

    def _role(self, src, dst, tx, target=MAC):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "test.kismet"
            _create_kismet_db(db, [(T_BASE, 0, src, dst, tx, -60, 2412000, 50, "ds", 127, _make_data_blob(), "h")])
            svc = KismetInvestigationService(capture_dirs=[Path(tmp)])
            svc.resolve_device = lambda _: _fake_device(target)
            result = svc.query_wireless_observations("any", lookback_minutes="all")
        self.assertEqual(len(result["observations"]), 1)
        return result["observations"][0]["role"]

    def test_F1_role_always_valid(self):
        """F1: role is always one of the four valid values."""
        valid = {"SOURCE", "TRANSMITTER", "DESTINATION", "OBSERVED"}
        rows = [(T_BASE, 0, MAC_L, "ff:ff:ff:ff:ff:ff", "00:00:00:00:00:00", -60, 2412000, 50, "ds", 127, _make_data_blob(), "h")]
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "test.kismet"
            _create_kismet_db(db, rows)
            svc = _make_svc(Path(tmp))
            result = svc.query_wireless_observations("any", lookback_minutes="all")
        for obs in result["observations"]:
            self.assertIn(obs["role"], valid)

    def test_F2_source_wins_over_transmitter(self):
        """F2: SOURCE takes priority even when transmac also matches."""
        role = self._role(src=MAC_L, dst="ff:ff:ff:ff:ff:ff", tx=MAC_L)
        self.assertEqual(role, "SOURCE")

    def test_F3_transmitter_role(self):
        """F3: transmac matches + sourcemac does not -> TRANSMITTER."""
        role = self._role(src="11:22:33:44:55:66", dst="ff:ff:ff:ff:ff:ff", tx=MAC_L)
        self.assertEqual(role, "TRANSMITTER")

    def test_F4_destination_role(self):
        """F4: destmac matches only -> DESTINATION."""
        role = self._role(src="11:22:33:44:55:66", dst=MAC_L, tx="22:33:44:55:66:77")
        self.assertEqual(role, "DESTINATION")


# ---------------------------------------------------------------------------
# N — Noise Filtering Contract
# ---------------------------------------------------------------------------

class NoiseFilteringContractTests(unittest.TestCase):
    """Contract section 7 — Noise Filtering (N1–N3)."""

    def test_N1_ack_excluded_by_default(self):
        """N1: ACK control frames are dropped when include_noise=False (default)."""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "test.kismet"
            _create_kismet_db(db, [(T_BASE, 0, MAC_L, "ff:ff:ff:ff:ff:ff", MAC_L, -60, 2412000, 10, "ds", 127, _make_ack_blob(), "ack")])
            svc = _make_svc(Path(tmp))
            result = svc.query_wireless_observations("any", lookback_minutes="all", include_noise=False)
        self.assertEqual(len(result["observations"]), 0, "ACK must be dropped by default")

    def test_N1_ack_included_when_noise_enabled(self):
        """N1: ACK frames appear when include_noise=True."""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "test.kismet"
            _create_kismet_db(db, [(T_BASE, 0, MAC_L, "ff:ff:ff:ff:ff:ff", MAC_L, -60, 2412000, 10, "ds", 127, _make_ack_blob(), "ack")])
            svc = _make_svc(Path(tmp))
            result = svc.query_wireless_observations("any", lookback_minutes="all", include_noise=True)
        self.assertGreater(len(result["observations"]), 0)

    def test_N3_noise_filtered_flag_true_by_default(self):
        """N3: summary.noise_filtered is True when include_noise=False."""
        svc = KismetInvestigationService(capture_dirs=[])
        svc.resolve_device = lambda _: _fake_device()
        result = svc.query_wireless_observations("any")
        self.assertTrue(result["summary"]["noise_filtered"])

    def test_N3_noise_filtered_flag_false_when_enabled(self):
        """N3: summary.noise_filtered is False when include_noise=True."""
        svc = KismetInvestigationService(capture_dirs=[])
        svc.resolve_device = lambda _: _fake_device()
        result = svc.query_wireless_observations("any", include_noise=True)
        self.assertFalse(result["summary"]["noise_filtered"])


# ---------------------------------------------------------------------------
# E — Response Envelope Contract
# ---------------------------------------------------------------------------

class EnvelopeContractTests(unittest.TestCase):
    """Contract section 8 — Response Envelope."""

    def _empty_result(self):
        svc = KismetInvestigationService(capture_dirs=[])
        svc.resolve_device = lambda _: _fake_device()
        return svc.query_wireless_observations("any")

    def test_E_status_always_ok(self):
        """Envelope: status is always 'ok' on success."""
        self.assertEqual(self._empty_result()["status"], "ok")

    def test_E_source_always_kismet_server(self):
        """Envelope: top-level source is always 'KISMET_SERVER'."""
        self.assertEqual(self._empty_result()["source"], "KISMET_SERVER")

    def test_E_required_top_level_keys(self):
        """Envelope: all required top-level keys must be present."""
        required = {"status", "source", "device", "query_window", "summary", "observations", "capture_files_scanned"}
        result = self._empty_result()
        self.assertFalse(required - result.keys(), f"Missing keys: {required - result.keys()}")

    def test_E_summary_keys_present(self):
        """Envelope: summary contains all required keys."""
        required = {"observation_count", "total_matched_packets", "avg_signal_dbm",
                    "min_signal_dbm", "max_signal_dbm", "channels", "frame_types", "noise_filtered"}
        summary = self._empty_result()["summary"]
        self.assertFalse(required - summary.keys(), f"Missing summary keys: {required - summary.keys()}")

    def test_E_per_observation_source_provenance(self):
        """Envelope: each observation carries source='KISMET_SERVER'."""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "test.kismet"
            _create_kismet_db(db, [(T_BASE, 0, MAC_L, "ff:ff:ff:ff:ff:ff", MAC_L, -60, 2412000, 50, "ds", 127, _make_beacon_blob(), "h")])
            svc = _make_svc(Path(tmp))
            result = svc.query_wireless_observations("any", lookback_minutes="all")
        for obs in result["observations"]:
            self.assertEqual(obs.get("source"), "KISMET_SERVER")

    def test_E_required_observation_fields(self):
        """Envelope: each observation has all required fields."""
        required = {"timestamp", "epoch_sec", "epoch_usec", "role",
                    "source_mac", "destination_mac", "transmitter_mac",
                    "frame_type", "frame_subtype", "signal_dbm",
                    "frequency_khz", "channel", "packet_length",
                    "sensor", "source", "capture_file", "packet_hash"}
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "test.kismet"
            _create_kismet_db(db, [(T_BASE, 0, MAC_L, "ff:ff:ff:ff:ff:ff", MAC_L, -60, 2412000, 50, "ds", 127, _make_beacon_blob(), "h")])
            svc = _make_svc(Path(tmp))
            result = svc.query_wireless_observations("any", lookback_minutes="all")
        for obs in result["observations"]:
            missing = required - obs.keys()
            self.assertFalse(missing, f"Observation missing keys: {missing}")

    def test_E_channels_sorted_ascending(self):
        """Envelope: summary.channels is sorted ascending."""
        rows = [
            (T_BASE,     0, MAC_L, "ff:ff:ff:ff:ff:ff", MAC_L, -60, 5180000, 50, "ds", 127, _make_data_blob(), "h1"),  # ch36
            (T_BASE + 1, 0, MAC_L, "ff:ff:ff:ff:ff:ff", MAC_L, -60, 2412000, 50, "ds", 127, _make_data_blob(), "h2"),  # ch1
        ]
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "test.kismet"
            _create_kismet_db(db, rows)
            svc = _make_svc(Path(tmp))
            result = svc.query_wireless_observations("any", lookback_minutes="all")
        ch = result["summary"]["channels"]
        self.assertEqual(ch, sorted(ch))


if __name__ == "__main__":
    unittest.main()
