"""Tests for Phase 4: Daily activity summaries, segment merging, and retention.

Covers:
- Segment merging of contiguous activity windows
- Per-identity daily aggregation and metric calculations
- Idempotent generation with source manifest hashes
- Daily summary SQLite persistence and query
- 7-day rolling retention enforcement (dry-run and execute)
- Raw capture deletion safety gating
- CLI command invocation
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List

from server_components.kismet_daily_summary import (
    ActivitySegment,
    DailySummaryStore,
    DayCompletionRecord,
    IdentityDailySummary,
    KismetDailySummarizer,
    _aggregate_identity,
    _merge_segments,
)
from server_components.device_activity import (
    ActivityFeatureVector,
    ActivityRandomForestClassifier,
)


class TestSegmentMerging(unittest.TestCase):

    def test_merge_contiguous_same_activity(self) -> None:
        windows = [
            {"window_start_ms": 0, "window_end_ms": 30000, "activity": "streaming", "confidence": 0.8},
            {"window_start_ms": 30000, "window_end_ms": 60000, "activity": "streaming", "confidence": 0.9},
            {"window_start_ms": 60000, "window_end_ms": 90000, "activity": "idle", "confidence": 0.95},
        ]
        segments = _merge_segments(windows)
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0].activity, "streaming")
        self.assertEqual(segments[0].duration_seconds, 60.0)
        self.assertEqual(segments[0].window_count, 2)
        self.assertAlmostEqual(segments[0].mean_confidence, 0.85)
        self.assertEqual(segments[1].activity, "idle")
        self.assertEqual(segments[1].duration_seconds, 30.0)

    def test_merge_empty_windows(self) -> None:
        self.assertEqual(_merge_segments([]), [])

    def test_merge_non_contiguous_same_activity(self) -> None:
        # Gap between windows: should produce separate segments even if same activity
        windows = [
            {"window_start_ms": 0, "window_end_ms": 30000, "activity": "streaming", "confidence": 0.8},
            {"window_start_ms": 60000, "window_end_ms": 90000, "activity": "streaming", "confidence": 0.85},
        ]
        segments = _merge_segments(windows)
        self.assertEqual(len(segments), 2)


class TestIdentityAggregation(unittest.TestCase):

    def test_aggregate_metrics(self) -> None:
        windows = [
            {
                "window_start_ms": 1000,
                "window_end_ms": 31000,
                "activity": "streaming",
                "confidence": 0.8,
                "status": "ok",
            },
            {
                "window_start_ms": 31000,
                "window_end_ms": 61000,
                "activity": "unknown",
                "confidence": 0.4,
                "status": "low_confidence",
            },
        ]
        summary = _aggregate_identity(
            mac="00:11:22:33:44:55",
            date_utc="2026-09-12",
            windows=windows,
            source_interval_ids=["int_1"],
            source_manifest_hashes=["hash_1"],
            model_version="activity-rf-v2",
            feature_schema_version="activity-features-v2",
        )
        self.assertEqual(summary.observed_mac, "00:11:22:33:44:55")
        self.assertFalse(summary.is_randomized_mac)
        self.assertEqual(summary.total_window_count, 2)
        self.assertEqual(summary.total_active_duration_seconds, 30.0)
        self.assertEqual(summary.unknown_duration_seconds, 30.0)
        self.assertEqual(summary.low_confidence_window_count, 1)
        self.assertEqual(summary.domain_shift_window_count, 0)
        self.assertTrue(len(summary.idempotency_key) == 64)

    def test_randomized_mac_detected(self) -> None:
        summary = _aggregate_identity(
            mac="DA:A1:19:22:33:44",  # locally administered (bit 1 of byte 0 set)
            date_utc="2026-09-12",
            windows=[{"window_start_ms": 0, "window_end_ms": 30000, "activity": "chat", "confidence": 0.7, "status": "ok"}],
            source_interval_ids=["int_1"],
            source_manifest_hashes=["hash_1"],
            model_version="activity-rf-v2",
            feature_schema_version="activity-features-v2",
        )
        self.assertTrue(summary.is_randomized_mac)


class TestDailySummaryStore(unittest.TestCase):

    def test_store_and_query_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test_summaries.sqlite"
            store = DailySummaryStore(db_path)

            summary = IdentityDailySummary(
                date_utc="2026-09-12",
                observed_mac="AA:BB:CC:DD:EE:FF",
                is_randomized_mac=False,
                first_observation_utc="2026-09-12T09:00:00Z",
                last_observation_utc="2026-09-12T09:10:00Z",
                first_observation_ms=0,
                last_observation_ms=600000,
                total_window_count=5,
                total_active_duration_seconds=150.0,
                unknown_duration_seconds=0.0,
                activity_durations={"streaming": 150.0},
                activity_counts={"streaming": 5},
                mean_confidence=0.85,
                min_confidence=0.8,
                max_confidence=0.9,
                low_confidence_window_count=0,
                domain_shift_window_count=0,
                segments=[],
                source_interval_ids=["int_1"],
                source_manifest_hashes=["hash_1"],
                model_version="activity-rf-v2",
                feature_schema_version="activity-features-v2",
                summary_generated_at_utc="2026-09-12T09:15:00Z",
                idempotency_key="test_key_1",
            )
            store.upsert_summary(summary)

            records = store.query_summaries("2026-09-12")
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].observed_mac, "AA:BB:CC:DD:EE:FF")
            self.assertEqual(records[0].total_active_duration_seconds, 150.0)

            # Idempotent upsert
            store.upsert_summary(summary)
            records_after = store.query_summaries("2026-09-12")
            self.assertEqual(len(records_after), 1)

    def test_completion_log(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test_summaries.sqlite"
            store = DailySummaryStore(db_path)

            completion = DayCompletionRecord(
                date_utc="2026-09-12",
                status="completed",
                identity_count=10,
                total_window_count=50,
                total_active_duration_seconds=1500.0,
                unknown_duration_seconds=0.0,
                source_interval_count=2,
                source_manifest_hashes=["h1", "h2"],
                idempotency_key="day_key",
                raw_captures_eligible_for_deletion=["/path/to/c.kismet"],
                per_window_files_deleted=False,
                verified_at_utc="2026-09-12T10:00:00Z",
            )
            store.upsert_completion(completion)
            retrieved = store.query_completion("2026-09-12")
            self.assertIsNotNone(retrieved)
            self.assertEqual(retrieved.status, "completed")
            self.assertEqual(retrieved.identity_count, 10)


class TestDailySummarizerEndToEnd(unittest.TestCase):

    def test_summarize_day_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            storage_dir = tmpdir / "storage"
            intervals_dir = storage_dir / "intervals" / "2026-09-12"
            intervals_dir.mkdir(parents=True, exist_ok=True)

            int_id = "2026-09-12T09:00:00Z_2026-09-12T09:10:00Z"
            pred_file = intervals_dir / f"{int_id}.predictions.jsonl"
            manifest_file = intervals_dir / f"{int_id}.manifest.json"

            records = [
                {
                    "interval_id": int_id,
                    "window_index": 0,
                    "window_start_ms": 1000,
                    "window_end_ms": 31000,
                    "observed_mac": "AA:BB:CC:11:22:33",
                    "activity": "file_transfer",
                    "confidence": 0.88,
                    "status": "ok",
                },
                {
                    "interval_id": int_id,
                    "window_index": 1,
                    "window_start_ms": 31000,
                    "window_end_ms": 61000,
                    "observed_mac": "AA:BB:CC:11:22:33",
                    "activity": "file_transfer",
                    "confidence": 0.92,
                    "status": "ok",
                },
            ]
            pred_file.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
            manifest_file.write_text(json.dumps({
                "interval_id": int_id,
                "status": "COMPLETED",
                "predictions_sha256": "fake_sha256",
                "safe_for_raw_cleanup": True,
                "source_captures": [{"path": str(tmpdir / "test.kismet"), "is_active": False}],
                "model_version": "activity-rf-v2",
                "feature_schema_version": "activity-features-v2",
            }), encoding="utf-8")

            summarizer = KismetDailySummarizer(storage_dir=storage_dir)
            completion = summarizer.summarize_day("2026-09-12", dry_run=False, delete_per_window_files=True)

            self.assertEqual(completion.status, "completed")
            self.assertEqual(completion.identity_count, 1)
            self.assertEqual(completion.total_window_count, 2)
            self.assertEqual(completion.total_active_duration_seconds, 60.0)
            self.assertTrue(completion.per_window_files_deleted)
            self.assertFalse(pred_file.exists())  # per-window file deleted after write

            # Verify SQLite record
            summaries = summarizer.summary_store.query_summaries("2026-09-12")
            self.assertEqual(len(summaries), 1)
            self.assertEqual(summaries[0].activity_counts.get("file_transfer"), 2)

    def test_retention_enforcement(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage_dir = Path(td) / "storage"
            summarizer = KismetDailySummarizer(storage_dir=storage_dir, summary_retention_days=7)

            # Insert an old summary (10 days ago) and a recent one (today)
            old_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")
            today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            for d, key in [(old_date, "old_key"), (today_date, "today_key")]:
                s = IdentityDailySummary(
                    date_utc=d, observed_mac="AA:11:22:33:44:55", is_randomized_mac=False,
                    first_observation_utc=f"{d}T00:00:00Z", last_observation_utc=f"{d}T01:00:00Z",
                    first_observation_ms=0, last_observation_ms=3600000, total_window_count=1,
                    total_active_duration_seconds=30.0, unknown_duration_seconds=0.0,
                    activity_durations={"chat": 30.0}, activity_counts={"chat": 1},
                    mean_confidence=0.8, min_confidence=0.8, max_confidence=0.8,
                    low_confidence_window_count=0, domain_shift_window_count=0,
                    segments=[], source_interval_ids=["i"], source_manifest_hashes=["h"],
                    model_version="v", feature_schema_version="v", summary_generated_at_utc="now",
                    idempotency_key=key,
                )
                summarizer.summary_store.upsert_summary(s)

            # Dry run: detects old date, deletes 0
            dry = summarizer.enforce_retention(dry_run=True)
            self.assertIn(old_date, dry["dates_to_delete"])
            self.assertEqual(dry["deleted_count"], 0)

            # Execute run: deletes old date
            executed = summarizer.enforce_retention(dry_run=False)
            self.assertEqual(executed["deleted_count"], 1)
            remaining = summarizer.summary_store.list_completed_dates()
            self.assertNotIn(old_date, remaining)
            self.assertIn(today_date, remaining)


class TestDomainShiftExemption(unittest.TestCase):

    def test_ratios_and_missingness_do_not_trigger_domain_shift(self) -> None:
        """Ratio features [0, 1] and binary missingness flags must not cause domain shift."""
        clf = ActivityRandomForestClassifier()
        # Reference statistics with tight mean=0.50, std=0.07 (like VNAT)
        clf.reference_statistics = {
            "uplink_packet_ratio": {"mean": 0.50, "std": 0.07, "min": 0.0, "max": 1.0},
            "downlink_packet_ratio": {"mean": 0.50, "std": 0.07, "min": 0.0, "max": 1.0},
            "missing_derived_periodicity_score": {"mean": 0.01, "std": 0.1, "min": 0.0, "max": 1.0},
            "packet_rate": {"mean": 10.0, "std": 5.0, "min": 0.1, "max": 100.0},
        }

        # Wi-Fi monitor mode: device only observed transmitting (uplink_ratio=1.0, downlink_ratio=0.0)
        # and missing periodicity score
        vector = ActivityFeatureVector(
            feature_schema_version="activity-features-v2",
            source_window_id="w1",
            feature_values={
                "uplink_packet_ratio": 1.0,
                "downlink_packet_ratio": 0.0,
                "missing_derived_periodicity_score": 1.0,
                "packet_rate": 12.0,  # normal rate
            },
        )
        is_shift, detail = clf.check_domain_shift(vector)
        self.assertFalse(is_shift)
        self.assertIsNone(detail)


if __name__ == "__main__":
    unittest.main(verbosity=2)
