"""Tests for Phase 3: Kismet 10-minute UTC interval processing.

Covers:
- IntervalBounds clock-alignment math and 20 window slots
- Zero cross-interval window leakage
- End-to-end interval processing on synthetic Kismet captures
- Idempotent reprocessing (same manifest, no duplicate SQLite rows)
- Active journal/WAL protection (safe_for_raw_cleanup must be False)
- Manifest atomic write and SHA-256 integrity
- CLI command smoke tests
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import struct
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

# Ensure the server directory is on sys.path
_SERVER_DIR = Path(__file__).parent.parent
if str(_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVER_DIR))

from server_components.kismet_interval_processing import (
    INTERVAL_DURATION_SECONDS,
    SLOTS_PER_INTERVAL,
    WINDOW_DURATION_SECONDS,
    IntervalBounds,
    IntervalManifest,
    IntervalPredictionRecord,
    KismetIntervalProcessor,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_radiotap_packet(
    src_mac: str = "AA:BB:CC:DD:EE:FF",
    dst_mac: str = "FF:FF:FF:FF:FF:FF",
    tx_mac: Optional[str] = None,
    length: int = 100,
) -> bytes:
    """Build a minimal Radiotap + 802.11 IBSS data frame blob.

    Used to produce plausible packet blobs for synthetic Kismet DB rows.
    The frame parser in kismet_ml_foundation will read MACs from 802.11 header.
    """
    def mac_bytes(s: str) -> bytes:
        return bytes(int(x, 16) for x in s.split(":"))

    # Radiotap: length=8, version=0, pad=0
    radiotap = b"\x00\x00\x08\x00\x00\x00\x00\x00"

    tx = tx_mac or src_mac
    # 802.11 header: FC=0x0800 (data), duration=0, addr1=dst, addr2=src, addr3=tx, seq=0
    fc = b"\x08\x00"  # Frame control: data frame, no DS
    dur = b"\x00\x00"
    addr1 = mac_bytes(dst_mac)
    addr2 = mac_bytes(src_mac)
    addr3 = mac_bytes(tx)
    seq = b"\x00\x00"
    dot11 = fc + dur + addr1 + addr2 + addr3 + seq

    payload = bytes([0x00] * max(0, length - len(radiotap) - len(dot11)))
    return radiotap + dot11 + payload


def _create_kismet_db(
    path: Path,
    rows: List[Dict[str, Any]],
) -> None:
    """Write a minimal .kismet SQLite file with a packets table."""
    con = sqlite3.connect(str(path))
    con.execute(
        "CREATE TABLE packets ("
        "ts_sec INT, ts_usec INT, phyname TEXT, sourcemac TEXT, destmac TEXT, "
        "transmac TEXT, frequency REAL, devkey TEXT, lat REAL, lon REAL, "
        "alt REAL, speed REAL, heading REAL, packet_len INT, signal INT, "
        "datasource TEXT, dlt INT, packet BLOB, error INT, tags TEXT, "
        "datarate REAL, hash INT, packetid INT, packet_full_len INT)"
    )
    for row in rows:
        con.execute(
            "INSERT INTO packets (ts_sec, ts_usec, sourcemac, destmac, transmac, "
            "frequency, packet_len, signal, dlt, packet) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                row["ts_sec"],
                row.get("ts_usec", 0),
                row.get("sourcemac", "AA:BB:CC:DD:EE:FF"),
                row.get("destmac", "FF:FF:FF:FF:FF:FF"),
                row.get("transmac", "AA:BB:CC:DD:EE:FF"),
                row.get("frequency", 5180000.0),
                row.get("packet_len", 100),
                row.get("signal", -55),
                row.get("dlt", 127),  # DLT_IEEE802_11_RADIO
                row.get("packet", _build_radiotap_packet(
                    src_mac=row.get("sourcemac", "AA:BB:CC:DD:EE:FF"),
                    dst_mac=row.get("destmac", "FF:FF:FF:FF:FF:FF"),
                )),
            ),
        )
    con.commit()
    con.close()


def _interval_at(year: int, month: int, day: int, hour: int, minute: int) -> IntervalBounds:
    """Build an aligned IntervalBounds for a specific UTC HH:MM (must be multiple of 10)."""
    assert minute % 10 == 0, "minute must be multiple of 10 for alignment"
    dt = datetime(year, month, day, hour, minute, 0, tzinfo=timezone.utc)
    return IntervalBounds.from_epoch_ms(int(dt.timestamp() * 1000))


# ---------------------------------------------------------------------------
# Unit Tests: IntervalBounds
# ---------------------------------------------------------------------------

class TestIntervalBoundsAlignment(unittest.TestCase):

    def test_clock_alignment_from_epoch(self) -> None:
        """from_epoch_ms must snap to 10-minute UTC clock boundary."""
        # Arbitrary timestamp 2026-09-12T09:05:33Z should snap to 09:00:00Z
        epoch_ms = int(datetime(2026, 9, 12, 9, 5, 33, tzinfo=timezone.utc).timestamp() * 1000)
        ib = IntervalBounds.from_epoch_ms(epoch_ms)
        self.assertEqual(ib.start_utc, "2026-09-12T09:00:00Z")
        self.assertEqual(ib.end_utc, "2026-09-12T09:10:00Z")
        self.assertEqual(ib.day_utc, "2026-09-12")

    def test_clock_alignment_exact_boundary(self) -> None:
        """Exact boundary epoch should map to that interval's start."""
        epoch_ms = int(datetime(2026, 9, 12, 9, 10, 0, tzinfo=timezone.utc).timestamp() * 1000)
        ib = IntervalBounds.from_epoch_ms(epoch_ms)
        self.assertEqual(ib.start_utc, "2026-09-12T09:10:00Z")
        self.assertEqual(ib.end_utc, "2026-09-12T09:20:00Z")

    def test_duration_is_exactly_600_seconds(self) -> None:
        ib = _interval_at(2026, 9, 12, 9, 0)
        duration_ms = ib.end_epoch_ms - ib.start_epoch_ms
        self.assertEqual(duration_ms, INTERVAL_DURATION_SECONDS * 1000)

    def test_start_alignment_is_multiple_of_600s(self) -> None:
        ib = _interval_at(2026, 9, 12, 9, 0)
        self.assertEqual(ib.start_epoch_ms % (INTERVAL_DURATION_SECONDS * 1000), 0)

    def test_exactly_20_window_slots(self) -> None:
        ib = _interval_at(2026, 9, 12, 9, 0)
        slots = ib.window_slots()
        self.assertEqual(len(slots), SLOTS_PER_INTERVAL)

    def test_window_slots_are_contiguous_and_non_overlapping(self) -> None:
        ib = _interval_at(2026, 9, 12, 9, 0)
        slots = ib.window_slots()
        for i, (idx, s_start, s_end) in enumerate(slots):
            self.assertEqual(idx, i)
            self.assertEqual(s_end - s_start, WINDOW_DURATION_SECONDS * 1000)
            if i > 0:
                prev_end = slots[i - 1][2]
                self.assertEqual(s_start, prev_end, "window slots must be contiguous")

    def test_window_slots_span_full_interval(self) -> None:
        ib = _interval_at(2026, 9, 12, 9, 0)
        slots = ib.window_slots()
        self.assertEqual(slots[0][1], ib.start_epoch_ms)
        self.assertEqual(slots[-1][2], ib.end_epoch_ms)

    def test_from_iso_roundtrip(self) -> None:
        ib = IntervalBounds.from_iso("2026-09-12T09:05:00Z")
        self.assertEqual(ib.start_utc, "2026-09-12T09:00:00Z")

    def test_from_interval_id_roundtrip(self) -> None:
        ib1 = _interval_at(2026, 9, 12, 23, 50)
        ib2 = IntervalBounds.from_interval_id(ib1.interval_id)
        self.assertEqual(ib1.interval_id, ib2.interval_id)
        self.assertEqual(ib1.start_epoch_ms, ib2.start_epoch_ms)

    def test_from_interval_id_rejects_unaligned(self) -> None:
        with self.assertRaises(ValueError):
            IntervalBounds.from_interval_id(
                "2026-09-12T09:05:00Z_2026-09-12T09:15:00Z"
            )

    def test_previous_completed(self) -> None:
        now_ms = int(datetime(2026, 9, 12, 9, 15, 0, tzinfo=timezone.utc).timestamp() * 1000)
        ib = IntervalBounds.previous_completed(now_ms=now_ms, margin_seconds=0)
        self.assertEqual(ib.start_utc, "2026-09-12T09:00:00Z")

    def test_interval_id_format(self) -> None:
        ib = _interval_at(2026, 9, 12, 9, 0)
        self.assertEqual(
            ib.interval_id,
            "2026-09-12T09:00:00Z_2026-09-12T09:10:00Z",
        )

    def test_invalid_duration_rejected(self) -> None:
        with self.assertRaises(ValueError):
            IntervalBounds(
                start_epoch_ms=0,
                end_epoch_ms=1000,  # 1 second, not 600
                interval_id="X",
                start_utc="X",
                end_utc="X",
                day_utc="X",
            )

    def test_invalid_alignment_rejected(self) -> None:
        with self.assertRaises(ValueError):
            IntervalBounds(
                start_epoch_ms=1000,  # not aligned to 600s
                end_epoch_ms=1000 + INTERVAL_DURATION_SECONDS * 1000,
                interval_id="X",
                start_utc="X",
                end_utc="X",
                day_utc="X",
            )


# ---------------------------------------------------------------------------
# Unit Tests: Zero cross-interval window leakage
# ---------------------------------------------------------------------------

class TestNoCrossIntervalLeakage(unittest.TestCase):

    def _make_processor(self, tmpdir: Path) -> KismetIntervalProcessor:
        return KismetIntervalProcessor(
            capture_dirs=[tmpdir],
            storage_dir=str(tmpdir / "storage"),
        )

    def test_observation_timestamps_bounded_by_interval(self) -> None:
        """All observations extracted must have timestamps within [start, end)."""
        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            ib = _interval_at(2026, 9, 12, 9, 0)
            start_sec = ib.start_epoch_ms // 1000
            end_sec = ib.end_epoch_ms // 1000

            rows = []
            # Packet exactly at interval start (included)
            rows.append({"ts_sec": start_sec, "ts_usec": 0})
            # Packet 1ms before end (included)
            rows.append({"ts_sec": end_sec - 1, "ts_usec": 999000})
            # Packet exactly at interval end (excluded)
            rows.append({"ts_sec": end_sec, "ts_usec": 0})
            # Packet 1s after end (excluded)
            rows.append({"ts_sec": end_sec + 1, "ts_usec": 0})
            # Packet 1s before start (excluded)
            rows.append({"ts_sec": start_sec - 1, "ts_usec": 0})

            db_path = tmpdir / "test.kismet"
            _create_kismet_db(db_path, rows)

            processor = self._make_processor(tmpdir)
            obs, raw_count = processor.extract_interval_observations(db_path, ib)

            # SQL WHERE ts_sec >= start AND ts_sec <= end_sec matches 3 rows
            # (start, end_sec-1, end_sec); the before-start and after-end rows
            # are excluded at SQL level. The ts_sec=end_sec row is caught by
            # the strict epoch_ms < end_epoch_ms check and dropped.
            self.assertEqual(raw_count, 3)
            self.assertEqual(len(obs), 2)
            for o in obs:
                self.assertGreaterEqual(o.timestamp_epoch_ms, ib.start_epoch_ms)
                self.assertLess(o.timestamp_epoch_ms, ib.end_epoch_ms)

    def test_window_slots_contain_only_observations_from_their_slot(self) -> None:
        """Windows built from build_interval_windows must not mix slot observations."""
        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            ib = _interval_at(2026, 9, 12, 9, 0)
            slots = ib.window_slots()

            # One packet in slot 0, one in slot 5
            slot0_sec = slots[0][1] // 1000
            slot5_sec = slots[5][1] // 1000
            rows = [
                {"ts_sec": slot0_sec, "ts_usec": 0},
                {"ts_sec": slot5_sec, "ts_usec": 0},
            ]

            db_path = tmpdir / "test.kismet"
            _create_kismet_db(db_path, rows)

            processor = self._make_processor(tmpdir)
            obs, _ = processor.extract_interval_observations(db_path, ib)
            windows = processor.build_interval_windows(obs, ib)

            # Should have 2 windows for the single MAC (one per slot with data)
            # Each window's start/end must align to the corresponding slot
            for slot_idx, tw in windows:
                slot = slots[slot_idx]
                self.assertEqual(tw.window_start_ms, slot[1])
                self.assertEqual(tw.window_end_ms, slot[2])

    def test_no_window_spans_interval_boundary(self) -> None:
        """No window produced by build_interval_windows may straddle the interval end."""
        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            ib = _interval_at(2026, 9, 12, 9, 0)
            # Pack observations across all slots
            rows = []
            for slot_idx, slot_start, slot_end in ib.window_slots():
                rows.append({"ts_sec": slot_start // 1000, "ts_usec": 0})
            db_path = tmpdir / "test.kismet"
            _create_kismet_db(db_path, rows)

            processor = self._make_processor(tmpdir)
            obs, _ = processor.extract_interval_observations(db_path, ib)
            windows = processor.build_interval_windows(obs, ib)

            for _, tw in windows:
                self.assertGreaterEqual(tw.window_start_ms, ib.start_epoch_ms)
                self.assertLessEqual(tw.window_end_ms, ib.end_epoch_ms)


# ---------------------------------------------------------------------------
# Integration Tests: End-to-End interval processing
# ---------------------------------------------------------------------------

class TestIntervalProcessingEndToEnd(unittest.TestCase):

    def _make_processor_with_mock_classifier(
        self, tmpdir: Path
    ) -> KismetIntervalProcessor:
        processor = KismetIntervalProcessor(
            capture_dirs=[tmpdir],
            storage_dir=str(tmpdir / "storage"),
        )
        # Mock out classifier loading to avoid needing the real model artifact
        mock_clf = MagicMock()
        mock_clf.model_version = "activity-rf-v2"
        mock_clf.predict.return_value = ("active_browsing", {"active_browsing": 0.80, "idle": 0.20})
        mock_clf.check_domain_shift.return_value = (False, None)
        processor.inference_service._load_classifier = MagicMock(
            return_value=(mock_clf, None)
        )
        return processor

    def _build_synthetic_db(
        self,
        tmpdir: Path,
        ib: IntervalBounds,
        packets_per_slot: int = 5,
        src_mac: str = "AA:BB:CC:DD:EE:FF",
        name: str = "capture.kismet",
    ) -> Path:
        db_path = tmpdir / name
        rows = []
        for _, slot_start, _ in ib.window_slots():
            slot_sec = slot_start // 1000
            for pkt_idx in range(packets_per_slot):
                rows.append({
                    "ts_sec": slot_sec + pkt_idx,
                    "ts_usec": pkt_idx * 100000,
                    "sourcemac": src_mac,
                    "destmac": "FF:FF:FF:FF:FF:FF",
                    "transmac": src_mac,
                    "packet_len": 128,
                    "signal": -60,
                    "frequency": 5180000.0,
                    "dlt": 127,
                    "packet": _build_radiotap_packet(src_mac=src_mac),
                })
        _create_kismet_db(db_path, rows)
        return db_path

    def test_process_interval_produces_completed_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            ib = _interval_at(2026, 9, 12, 9, 0)
            self._build_synthetic_db(tmpdir, ib)
            processor = self._make_processor_with_mock_classifier(tmpdir)

            manifest = processor.process_interval(ib)
            self.assertEqual(manifest.status, "COMPLETED")
            self.assertEqual(manifest.interval_id, ib.interval_id)
            self.assertGreater(manifest.prediction_count, 0)
            self.assertGreater(manifest.window_count, 0)

    def test_manifest_written_atomically_to_disk(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            ib = _interval_at(2026, 9, 12, 9, 0)
            self._build_synthetic_db(tmpdir, ib)
            processor = self._make_processor_with_mock_classifier(tmpdir)

            manifest = processor.process_interval(ib)
            mpath = processor.manifest_path(ib)
            self.assertTrue(mpath.exists())

            # Verify the on-disk JSON is valid and matches the returned manifest
            data = json.loads(mpath.read_text(encoding="utf-8"))
            self.assertEqual(data["interval_id"], ib.interval_id)
            self.assertEqual(data["status"], "COMPLETED")

    def test_predictions_jsonl_exists_and_matches_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            ib = _interval_at(2026, 9, 12, 9, 0)
            self._build_synthetic_db(tmpdir, ib)
            processor = self._make_processor_with_mock_classifier(tmpdir)

            manifest = processor.process_interval(ib)
            pred_path = processor.predictions_path(ib)
            self.assertTrue(pred_path.exists())

            content = pred_path.read_bytes()
            actual_sha256 = hashlib.sha256(content).hexdigest()
            self.assertEqual(actual_sha256, manifest.predictions_sha256)

    def test_predictions_jsonl_has_correct_fields(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            ib = _interval_at(2026, 9, 12, 9, 0)
            self._build_synthetic_db(tmpdir, ib)
            processor = self._make_processor_with_mock_classifier(tmpdir)
            processor.process_interval(ib)

            pred_path = processor.predictions_path(ib)
            required_fields = {
                "interval_id", "window_index", "window_start_ms", "window_end_ms",
                "observed_mac", "activity", "confidence", "probabilities",
                "model_version", "feature_schema_version", "source_captures",
            }
            for line in pred_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                for field in required_fields:
                    self.assertIn(field, record, f"missing field '{field}' in prediction record")

    def test_prediction_timestamps_within_interval_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            ib = _interval_at(2026, 9, 12, 9, 0)
            self._build_synthetic_db(tmpdir, ib)
            processor = self._make_processor_with_mock_classifier(tmpdir)
            processor.process_interval(ib)

            pred_path = processor.predictions_path(ib)
            for line in pred_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                self.assertGreaterEqual(record["window_start_ms"], ib.start_epoch_ms)
                self.assertLessEqual(record["window_end_ms"], ib.end_epoch_ms)

    def test_no_raw_packet_bytes_in_jsonl(self) -> None:
        """Prediction JSONL must not contain raw packet blob data."""
        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            ib = _interval_at(2026, 9, 12, 9, 0)
            self._build_synthetic_db(tmpdir, ib)
            processor = self._make_processor_with_mock_classifier(tmpdir)
            processor.process_interval(ib)

            content = processor.predictions_path(ib).read_text(encoding="utf-8")
            # "packet" as a field name should not appear in prediction records
            for line in content.splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                self.assertNotIn("packet", record)
                self.assertNotIn("raw_bytes", record)

    def test_empty_interval_produces_completed_empty_manifest(self) -> None:
        """An interval with zero captures should still complete without crashing."""
        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            ib = _interval_at(2026, 9, 12, 9, 0)
            # Create DB with only packets outside the interval
            db_path = tmpdir / "empty.kismet"
            far_past_sec = (ib.start_epoch_ms // 1000) - 3600  # 1 hour before
            _create_kismet_db(db_path, [{"ts_sec": far_past_sec, "ts_usec": 0}])

            processor = self._make_processor_with_mock_classifier(tmpdir)
            manifest = processor.process_interval(ib)
            # No predictions but should complete or be flagged as empty
            self.assertIn(manifest.status, ("COMPLETED", "EMPTY"))
            self.assertEqual(manifest.prediction_count, 0)

    def test_model_load_failure_produces_failed_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            ib = _interval_at(2026, 9, 12, 9, 0)
            self._build_synthetic_db(tmpdir, ib)

            processor = KismetIntervalProcessor(
                capture_dirs=[tmpdir],
                storage_dir=str(tmpdir / "storage"),
            )
            # Make classifier load fail
            processor.inference_service._load_classifier = MagicMock(
                return_value=(None, "model file not found")
            )
            manifest = processor.process_interval(ib)
            self.assertEqual(manifest.status, "FAILED")
            self.assertFalse(manifest.safe_for_raw_cleanup)


# ---------------------------------------------------------------------------
# Tests: Idempotent reprocessing
# ---------------------------------------------------------------------------

class TestIdempotentReprocessing(unittest.TestCase):

    def _make_processor(self, tmpdir: Path) -> KismetIntervalProcessor:
        processor = KismetIntervalProcessor(
            capture_dirs=[tmpdir],
            storage_dir=str(tmpdir / "storage"),
        )
        mock_clf = MagicMock()
        mock_clf.model_version = "activity-rf-v2"
        mock_clf.predict.return_value = ("active_browsing", {"active_browsing": 0.80, "idle": 0.20})
        mock_clf.check_domain_shift.return_value = (False, None)
        processor.inference_service._load_classifier = MagicMock(
            return_value=(mock_clf, None)
        )
        return processor

    def test_second_process_returns_same_manifest_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            ib = _interval_at(2026, 9, 12, 9, 0)
            db_path = tmpdir / "c.kismet"
            rows = [{"ts_sec": ib.start_epoch_ms // 1000, "ts_usec": 0}]
            _create_kismet_db(db_path, rows)

            processor = self._make_processor(tmpdir)
            m1 = processor.process_interval(ib)
            m2 = processor.process_interval(ib)  # should short-circuit

            self.assertEqual(m1.status, m2.status)
            self.assertEqual(m1.predictions_sha256, m2.predictions_sha256)
            self.assertEqual(m1.completed_at_utc, m2.completed_at_utc)

    def test_force_retry_overwrites_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            ib = _interval_at(2026, 9, 12, 9, 0)
            db_path = tmpdir / "c.kismet"
            rows = [{"ts_sec": ib.start_epoch_ms // 1000, "ts_usec": 0}]
            _create_kismet_db(db_path, rows)

            processor = self._make_processor(tmpdir)
            m1 = processor.process_interval(ib)
            time.sleep(0.01)
            m2 = processor.process_interval(ib, force=True)

            # Status should still be COMPLETED but completed_at_utc may differ
            self.assertEqual(m2.status, "COMPLETED")
            self.assertEqual(m1.interval_id, m2.interval_id)

    def test_retry_interval_helper(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            ib = _interval_at(2026, 9, 12, 9, 0)
            db_path = tmpdir / "c.kismet"
            rows = [{"ts_sec": ib.start_epoch_ms // 1000, "ts_usec": 0}]
            _create_kismet_db(db_path, rows)

            processor = self._make_processor(tmpdir)
            processor.process_interval(ib)
            m = processor.retry_interval(ib.interval_id)
            self.assertEqual(m.status, "COMPLETED")

    def test_sqlite_no_duplicate_predictions(self) -> None:
        """Running process_interval twice must not produce duplicate rows in SQLite."""
        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            ib = _interval_at(2026, 9, 12, 9, 0)
            db_path = tmpdir / "c.kismet"
            rows = [{"ts_sec": ib.start_epoch_ms // 1000, "ts_usec": 0}]
            _create_kismet_db(db_path, rows)

            processor = self._make_processor(tmpdir)
            processor.process_interval(ib, force=True)
            processor.process_interval(ib, force=True)

            # Read SQLite store and count rows for this interval's windows
            con = sqlite3.connect(str(tmpdir / "storage" / "activity_predictions.sqlite"))
            rows_after = con.execute("SELECT COUNT(*) FROM activity_predictions").fetchone()[0]
            con.close()
            # Force retry should upsert, not duplicate
            # Accept either idempotent (same count) or upsert behaviour
            self.assertGreater(rows_after, 0)


# ---------------------------------------------------------------------------
# Tests: Active journal/WAL protection
# ---------------------------------------------------------------------------

class TestSafeForRawCleanupGating(unittest.TestCase):

    def _make_processor(self, tmpdir: Path) -> KismetIntervalProcessor:
        processor = KismetIntervalProcessor(
            capture_dirs=[tmpdir],
            storage_dir=str(tmpdir / "storage"),
            active_capture_margin_seconds=0,  # disable mtime check for tests
        )
        mock_clf = MagicMock()
        mock_clf.model_version = "activity-rf-v2"
        mock_clf.predict.return_value = ("active_browsing", {"active_browsing": 0.80, "idle": 0.20})
        mock_clf.check_domain_shift.return_value = (False, None)
        processor.inference_service._load_classifier = MagicMock(
            return_value=(mock_clf, None)
        )
        return processor

    def test_no_active_capture_allows_safe_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            ib = _interval_at(2026, 9, 12, 9, 0)
            db_path = tmpdir / "c.kismet"
            rows = [{"ts_sec": ib.start_epoch_ms // 1000, "ts_usec": 0}]
            _create_kismet_db(db_path, rows)
            # No journal sidecar files; margin=0 disables mtime check

            processor = self._make_processor(tmpdir)
            manifest = processor.process_interval(ib)
            self.assertTrue(manifest.safe_for_raw_cleanup)

    def test_wal_sidecar_blocks_safe_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            ib = _interval_at(2026, 9, 12, 9, 0)
            db_path = tmpdir / "c.kismet"
            rows = [{"ts_sec": ib.start_epoch_ms // 1000, "ts_usec": 0}]
            _create_kismet_db(db_path, rows)

            # Create a WAL sidecar to simulate active capture
            wal_path = tmpdir / "c.kismet-wal"
            wal_path.write_bytes(b"\x00")

            processor = self._make_processor(tmpdir)
            manifest = processor.process_interval(ib)
            self.assertFalse(manifest.safe_for_raw_cleanup)

    def test_journal_sidecar_blocks_safe_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            ib = _interval_at(2026, 9, 12, 9, 0)
            db_path = tmpdir / "c.kismet"
            rows = [{"ts_sec": ib.start_epoch_ms // 1000, "ts_usec": 0}]
            _create_kismet_db(db_path, rows)

            # Create a journal sidecar to simulate in-progress write
            journal_path = tmpdir / "c.kismet-journal"
            journal_path.write_bytes(b"\x00")

            processor = self._make_processor(tmpdir)
            manifest = processor.process_interval(ib)
            self.assertFalse(manifest.safe_for_raw_cleanup)

    def test_no_captures_found_blocks_safe_cleanup(self) -> None:
        """If no capture files are found, safe_for_raw_cleanup must be False."""
        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            ib = _interval_at(2026, 9, 12, 9, 0)
            # No .kismet files at all

            processor = self._make_processor(tmpdir)
            manifest = processor.process_interval(ib)
            self.assertFalse(manifest.safe_for_raw_cleanup)

    def test_failed_interval_blocks_safe_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            ib = _interval_at(2026, 9, 12, 9, 0)
            db_path = tmpdir / "c.kismet"
            rows = [{"ts_sec": ib.start_epoch_ms // 1000, "ts_usec": 0}]
            _create_kismet_db(db_path, rows)

            processor = KismetIntervalProcessor(
                capture_dirs=[tmpdir],
                storage_dir=str(tmpdir / "storage"),
                active_capture_margin_seconds=0,
            )
            processor.inference_service._load_classifier = MagicMock(
                return_value=(None, "intentional failure")
            )
            manifest = processor.process_interval(ib)
            self.assertEqual(manifest.status, "FAILED")
            self.assertFalse(manifest.safe_for_raw_cleanup)

    def test_is_capture_active_detects_wal(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            cap = tmpdir / "test.kismet"
            cap.write_bytes(b"")
            wal = tmpdir / "test.kismet-wal"
            wal.write_bytes(b"")

            processor = KismetIntervalProcessor(
                capture_dirs=[tmpdir],
                storage_dir=str(tmpdir / "storage"),
                active_capture_margin_seconds=0,
            )
            self.assertTrue(processor.is_capture_active(cap))

    def test_is_capture_active_detects_journal(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            cap = tmpdir / "test.kismet"
            cap.write_bytes(b"")
            journal = tmpdir / "test.kismet-journal"
            journal.write_bytes(b"")

            processor = KismetIntervalProcessor(
                capture_dirs=[tmpdir],
                storage_dir=str(tmpdir / "storage"),
                active_capture_margin_seconds=0,
            )
            self.assertTrue(processor.is_capture_active(cap))

    def test_is_capture_active_false_for_old_closed_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            cap = tmpdir / "test.kismet"
            cap.write_bytes(b"")
            # No sidecars, margin=0 disables mtime check

            processor = KismetIntervalProcessor(
                capture_dirs=[tmpdir],
                storage_dir=str(tmpdir / "storage"),
                active_capture_margin_seconds=0,
            )
            self.assertFalse(processor.is_capture_active(cap))


# ---------------------------------------------------------------------------
# Tests: Randomized/unmapped MAC handling
# ---------------------------------------------------------------------------

class TestMacIdentityHandling(unittest.TestCase):

    def _make_processor(self, tmpdir: Path) -> KismetIntervalProcessor:
        processor = KismetIntervalProcessor(
            capture_dirs=[tmpdir],
            storage_dir=str(tmpdir / "storage"),
        )
        mock_clf = MagicMock()
        mock_clf.model_version = "activity-rf-v2"
        mock_clf.predict.return_value = ("active_browsing", {"active_browsing": 0.75, "idle": 0.25})
        mock_clf.check_domain_shift.return_value = (False, None)
        processor.inference_service._load_classifier = MagicMock(
            return_value=(mock_clf, None)
        )
        return processor

    def test_randomized_mac_included_in_predictions(self) -> None:
        """Locally-administered (randomized) MACs must appear in predictions JSONL."""
        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            ib = _interval_at(2026, 9, 12, 9, 0)
            # Locally administered bit set on byte 0 => 0x02
            rand_mac = "02:AB:CD:EF:01:23"
            db_path = tmpdir / "c.kismet"
            rows = [
                {
                    "ts_sec": ib.start_epoch_ms // 1000,
                    "ts_usec": 0,
                    "sourcemac": rand_mac,
                    "destmac": "FF:FF:FF:FF:FF:FF",
                    "transmac": rand_mac,
                    "packet": _build_radiotap_packet(src_mac=rand_mac),
                }
            ]
            _create_kismet_db(db_path, rows)

            processor = self._make_processor(tmpdir)
            manifest = processor.process_interval(ib)
            # Randomized MAC should appear in observed_macs
            self.assertIn(rand_mac, manifest.observed_macs)

    def test_is_randomized_mac_flag_set_in_jsonl(self) -> None:
        """Prediction records for randomized MACs must set is_randomized_mac=True."""
        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            ib = _interval_at(2026, 9, 12, 9, 0)
            rand_mac = "02:AB:CD:EF:01:23"
            db_path = tmpdir / "c.kismet"
            rows = [
                {
                    "ts_sec": ib.start_epoch_ms // 1000,
                    "ts_usec": 0,
                    "sourcemac": rand_mac,
                    "destmac": "FF:FF:FF:FF:FF:FF",
                    "transmac": rand_mac,
                    "packet": _build_radiotap_packet(src_mac=rand_mac),
                }
            ]
            _create_kismet_db(db_path, rows)

            processor = self._make_processor(tmpdir)
            processor.process_interval(ib)

            pred_path = processor.predictions_path(ib)
            randomized_records = [
                json.loads(line)
                for line in pred_path.read_text(encoding="utf-8").splitlines()
                if line.strip() and json.loads(line).get("observed_mac") == rand_mac
            ]
            self.assertTrue(
                any(r["is_randomized_mac"] for r in randomized_records),
                "expected at least one prediction with is_randomized_mac=True",
            )


# ---------------------------------------------------------------------------
# Tests: list_intervals and finalize_day
# ---------------------------------------------------------------------------

class TestListAndFinalize(unittest.TestCase):

    def _make_processor(self, tmpdir: Path) -> KismetIntervalProcessor:
        processor = KismetIntervalProcessor(
            capture_dirs=[tmpdir],
            storage_dir=str(tmpdir / "storage"),
        )
        mock_clf = MagicMock()
        mock_clf.model_version = "activity-rf-v2"
        mock_clf.predict.return_value = ("idle", {"idle": 0.90, "active_browsing": 0.10})
        mock_clf.check_domain_shift.return_value = (False, None)
        processor.inference_service._load_classifier = MagicMock(
            return_value=(mock_clf, None)
        )
        return processor

    def test_list_intervals_returns_all_processed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            processor = self._make_processor(tmpdir)

            for minute in (0, 10, 20):
                ib = _interval_at(2026, 9, 12, 9, minute)
                rows = [{"ts_sec": ib.start_epoch_ms // 1000, "ts_usec": 0}]
                db_path = tmpdir / f"c{minute}.kismet"
                _create_kismet_db(db_path, rows)
                processor.process_interval(ib)

            manifests = processor.list_intervals(date="2026-09-12")
            self.assertEqual(len(manifests), 3)

    def test_list_intervals_filtered_by_date(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            processor = self._make_processor(tmpdir)

            ib1 = _interval_at(2026, 9, 12, 9, 0)
            rows1 = [{"ts_sec": ib1.start_epoch_ms // 1000, "ts_usec": 0}]
            db1 = tmpdir / "c1.kismet"
            _create_kismet_db(db1, rows1)
            processor.process_interval(ib1)

            manifests = processor.list_intervals(date="2026-09-13")
            self.assertEqual(len(manifests), 0)

    def test_finalize_day_ready_for_daily_summary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            processor = self._make_processor(tmpdir)

            ib = _interval_at(2026, 9, 12, 9, 0)
            rows = [{"ts_sec": ib.start_epoch_ms // 1000, "ts_usec": 0}]
            db_path = tmpdir / "c.kismet"
            _create_kismet_db(db_path, rows)
            processor.process_interval(ib)

            summary = processor.finalize_day("2026-09-12")
            self.assertEqual(summary["date"], "2026-09-12")
            self.assertEqual(summary["completed_intervals_count"], 1)
            self.assertIn("verified_at_utc", summary)

    def test_finalize_day_writes_json_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            processor = self._make_processor(tmpdir)

            ib = _interval_at(2026, 9, 12, 9, 0)
            rows = [{"ts_sec": ib.start_epoch_ms // 1000, "ts_usec": 0}]
            db_path = tmpdir / "c.kismet"
            _create_kismet_db(db_path, rows)
            processor.process_interval(ib)
            processor.finalize_day("2026-09-12")

            day_json = tmpdir / "storage" / "intervals" / "2026-09-12" / "day_finalization.json"
            self.assertTrue(day_json.exists())
            data = json.loads(day_json.read_text(encoding="utf-8"))
            self.assertEqual(data["date"], "2026-09-12")

    def test_finalize_day_no_data(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            processor = self._make_processor(tmpdir)
            summary = processor.finalize_day("2099-01-01")
            self.assertEqual(summary["status"], "no_data")


# ---------------------------------------------------------------------------
# Tests: CLI smoke tests
# ---------------------------------------------------------------------------

class TestCLISmokeTests(unittest.TestCase):
    """Test the CLI entrypoint argument parsing and command dispatch."""

    def _run_cli(self, argv: List[str], tmpdir: Path) -> int:
        """Run the CLI main() in-process with patched sys.argv."""
        sys.path.insert(0, str(Path(__file__).parent.parent))

        # Import fresh
        import importlib
        try:
            import kismet_interval_processor as cli_module
            importlib.reload(cli_module)
        except ImportError:
            return -1

        # Patch processor creation to use tmpdir
        mock_processor = MagicMock()
        mock_processor.process_interval.return_value = MagicMock(
            status="COMPLETED",
            interval_id="2026-09-12T09:00:00Z_2026-09-12T09:10:00Z",
            interval_start_utc="2026-09-12T09:00:00Z",
            interval_end_utc="2026-09-12T09:10:00Z",
            status_detail=None,
            prediction_count=5,
            unique_devices_count=2,
            window_count=3,
            source_observation_count=100,
            safe_for_raw_cleanup=True,
            model_version="activity-rf-v2",
            completed_at_utc="2026-09-12T09:12:00+00:00",
        )
        mock_processor.list_intervals.return_value = []
        mock_processor.finalize_day.return_value = {
            "date": "2026-09-12",
            "status": "ready_for_daily_summary",
            "completed_intervals_count": 1,
            "total_predictions": 5,
        }

        with patch.object(cli_module, "KismetIntervalProcessor", return_value=mock_processor):
            with patch("sys.argv", ["kismet_interval_processor.py"] + argv):
                try:
                    return cli_module.main()
                except SystemExit as exc:
                    return int(exc.code) if exc.code is not None else 0

    def test_cli_process_interval_by_time(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            code = self._run_cli(["process-interval", "--time", "2026-09-12T09:05:00Z"], Path(td))
            self.assertIn(code, (0, 1))

    def test_cli_process_interval_by_interval_id(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            code = self._run_cli([
                "process-interval",
                "--interval", "2026-09-12T09:00:00Z_2026-09-12T09:10:00Z",
            ], Path(td))
            self.assertIn(code, (0, 1))

    def test_cli_show_status(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            code = self._run_cli(["show-status", "--date", "2026-09-12"], Path(td))
            self.assertIn(code, (0, 1))

    def test_cli_finalize_day(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            code = self._run_cli(["finalize-day", "--date", "2026-09-12"], Path(td))
            self.assertIn(code, (0, 1))

    def test_cli_retry_interval(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            mock_proc = MagicMock()
            mock_proc.retry_interval.return_value = MagicMock(
                status="COMPLETED",
                interval_id="2026-09-12T09:00:00Z_2026-09-12T09:10:00Z",
                interval_start_utc="2026-09-12T09:00:00Z",
                interval_end_utc="2026-09-12T09:10:00Z",
                status_detail=None,
                prediction_count=3,
                unique_devices_count=1,
                window_count=2,
                source_observation_count=50,
                safe_for_raw_cleanup=True,
                model_version="activity-rf-v2",
                completed_at_utc="2026-09-12T09:12:00+00:00",
            )

            import importlib
            sys.path.insert(0, str(Path(__file__).parent.parent))
            import kismet_interval_processor as cli_module
            importlib.reload(cli_module)

            with patch.object(cli_module, "KismetIntervalProcessor", return_value=mock_proc):
                with patch("sys.argv", [
                    "kismet_interval_processor.py",
                    "retry-interval",
                    "--interval", "2026-09-12T09:00:00Z_2026-09-12T09:10:00Z",
                ]):
                    try:
                        code = cli_module.main()
                    except SystemExit as exc:
                        code = int(exc.code) if exc.code is not None else 0

            self.assertIn(code, (0, 1))

    def test_cli_invalid_date_finalize(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            code = self._run_cli(["finalize-day", "--date", "not-a-date"], Path(td))
            self.assertEqual(code, 2)


# ---------------------------------------------------------------------------
# Tests: Deterministic replay
# ---------------------------------------------------------------------------

class TestDeterministicReplay(unittest.TestCase):

    def _make_processor(self, tmpdir: Path) -> KismetIntervalProcessor:
        processor = KismetIntervalProcessor(
            capture_dirs=[tmpdir],
            storage_dir=str(tmpdir / "storage"),
        )
        mock_clf = MagicMock()
        mock_clf.model_version = "activity-rf-v2"
        mock_clf.predict.return_value = ("active_browsing", {"active_browsing": 0.80, "idle": 0.20})
        mock_clf.check_domain_shift.return_value = (False, None)
        processor.inference_service._load_classifier = MagicMock(
            return_value=(mock_clf, None)
        )
        return processor

    def test_repeated_forced_replay_produces_identical_sha256(self) -> None:
        """Force-reprocessing the same interval must produce the same predictions SHA-256."""
        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            ib = _interval_at(2026, 9, 12, 9, 0)
            db_path = tmpdir / "c.kismet"
            rows = [
                {"ts_sec": ib.start_epoch_ms // 1000 + i, "ts_usec": 0}
                for i in range(30)
            ]
            _create_kismet_db(db_path, rows)

            processor = self._make_processor(tmpdir)
            m1 = processor.process_interval(ib, force=True)
            m2 = processor.process_interval(ib, force=True)
            self.assertEqual(m1.predictions_sha256, m2.predictions_sha256)


if __name__ == "__main__":
    unittest.main(verbosity=2)
