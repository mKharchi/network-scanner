"""Unit tests for Phase 1 Bounded Raw-File Retention & Storage Pruning Manager."""

import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

CLIENT_DIR = Path(__file__).resolve().parents[1]
APP_DIR = CLIENT_DIR / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from retention_manager import (
    FileProcessingState,
    RetentionManager,
    RetentionStateTracker,
)


class RetentionManagerTests(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="test_retention_"))
        self.passive_packets_dir = self.test_dir / "passive_packets"
        self.network_telemetry_dir = self.test_dir / "network_telemetry"
        self.passive_packets_dir.mkdir(parents=True, exist_ok=True)
        self.network_telemetry_dir.mkdir(parents=True, exist_ok=True)

        self.fixed_now = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)
        self.now_provider = lambda: self.fixed_now

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_v1_packet_file(self, date_str: str, packet_count: int = 10) -> Path:
        file_path = self.passive_packets_dir / f"{date_str}.json"
        data = {
            "date": date_str,
            "observer_client_id": "test_client",
            "packet_count": packet_count,
            "packets": [{"timestamp": f"{date_str}T10:00:00Z", "protocol": "tcp"} for _ in range(packet_count)],
        }
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        return file_path

    def _create_v2_packet_file(self, date_str: str, protocol: str = "tcp", count: int = 5) -> Path:
        packets_dir = self.network_telemetry_dir / date_str / "packets"
        packets_dir.mkdir(parents=True, exist_ok=True)
        file_path = packets_dir / f"{protocol}.json"
        data = [{"timestamp": f"{date_str}T10:00:00Z", "protocol": protocol} for _ in range(count)]
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        return file_path

    def _create_v2_flows_file(self, date_str: str) -> Path:
        day_dir = self.network_telemetry_dir / date_str
        day_dir.mkdir(parents=True, exist_ok=True)
        flows_path = day_dir / "flows.json"
        data = [{"flow_id": f"flow_{date_str}_1", "first_seen": f"{date_str}T09:00:00Z"}]
        with open(flows_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        return flows_path

    def test_validation_scenario_1_and_2_successful_processing_expired(self):
        """Scenario 1, 2, 3: Processed files past retention window are eligible and deleted."""
        # Date is 4 days ago (2026-09-01) vs fixed now (2026-09-05 12:00:00) -> >48h old
        v1_file = self._create_v1_packet_file("2026-09-01")
        v2_file = self._create_v2_packet_file("2026-09-01", protocol="tcp")
        self._create_v2_flows_file("2026-09-01")

        manager = RetentionManager(
            self.test_dir,
            retention_hours=48.0,
            dry_run=False,
            now_provider=self.now_provider,
        )
        manager.state_tracker.mark_success("2026-09-01")

        summary = manager.run_once()
        self.assertEqual(summary.evaluated_count, 2)
        self.assertEqual(summary.eligible_count, 2)
        self.assertEqual(summary.deleted_count, 2)
        self.assertFalse(v1_file.exists())
        self.assertFalse(v2_file.exists())

    def test_validation_scenario_4_and_5_failed_file_preserved(self):
        """Scenario 4, 5: Failed flow processing preserves raw capture regardless of age."""
        v1_file = self._create_v1_packet_file("2026-09-01")
        v2_file = self._create_v2_packet_file("2026-09-01", protocol="udp")

        manager = RetentionManager(
            self.test_dir,
            retention_hours=48.0,
            dry_run=False,
            now_provider=self.now_provider,
        )
        # Mark 2026-09-01 as FAILED
        manager.state_tracker.mark_failed("2026-09-01", "Flow calculation exception")

        summary = manager.run_once()
        self.assertEqual(summary.evaluated_count, 2)
        self.assertEqual(summary.eligible_count, 0)
        self.assertEqual(summary.preserved_count, 2)
        self.assertEqual(summary.deleted_count, 0)
        self.assertTrue(v1_file.exists())
        self.assertTrue(v2_file.exists())

    def test_validation_scenario_6_and_7_processing_file_preserved(self):
        """Scenario 6, 7: In-progress/processing files are strictly preserved."""
        v1_file = self._create_v1_packet_file("2026-09-01")

        manager = RetentionManager(
            self.test_dir,
            retention_hours=48.0,
            dry_run=False,
            now_provider=self.now_provider,
        )
        manager.state_tracker.mark_processing("2026-09-01")

        summary = manager.run_once()
        self.assertEqual(summary.eligible_count, 0)
        self.assertEqual(summary.preserved_count, 1)
        self.assertTrue(v1_file.exists())

    def test_validation_scenario_recent_file_under_retention_window_preserved(self):
        """Files within retention window (e.g. yesterday, 24h ago < 48h) are preserved."""
        # 2026-09-04 is yesterday (1 day / 24h ago < 48h)
        v1_file = self._create_v1_packet_file("2026-09-04")
        self._create_v2_flows_file("2026-09-04")

        manager = RetentionManager(
            self.test_dir,
            retention_hours=48.0,
            dry_run=False,
            now_provider=self.now_provider,
        )
        manager.state_tracker.mark_success("2026-09-04")

        summary = manager.run_once()
        self.assertEqual(summary.eligible_count, 0)
        self.assertEqual(summary.preserved_count, 1)
        self.assertTrue(v1_file.exists())

    def test_validation_scenario_8_dry_run_mode(self):
        """Scenario 8: Dry-run mode evaluates eligibility and logs without deleting files."""
        v1_file = self._create_v1_packet_file("2026-09-01")
        self._create_v2_flows_file("2026-09-01")

        manager = RetentionManager(
            self.test_dir,
            retention_hours=48.0,
            dry_run=True,
            now_provider=self.now_provider,
        )
        manager.state_tracker.mark_success("2026-09-01")

        summary = manager.run_once()
        self.assertTrue(summary.dry_run)
        self.assertEqual(summary.evaluated_count, 1)
        self.assertEqual(summary.eligible_count, 1)
        self.assertEqual(summary.deleted_count, 1)  # recorded as dry-run deleted
        self.assertTrue(v1_file.exists())  # File still exists on disk!

    def test_empty_packets_directory_cleanup(self):
        """Empty packets directories are cleaned up after files are pruned."""
        v2_file = self._create_v2_packet_file("2026-09-01", protocol="tcp")
        self._create_v2_flows_file("2026-09-01")
        packets_dir = v2_file.parent

        manager = RetentionManager(
            self.test_dir,
            retention_hours=48.0,
            dry_run=False,
            now_provider=self.now_provider,
        )
        manager.state_tracker.mark_success("2026-09-01")

        manager.run_once()
        self.assertFalse(packets_dir.exists())

    def test_error_handling_graceful_missing_or_permission_error(self):
        """Filesystem errors are caught and reported without crashing."""
        manager = RetentionManager(
            self.test_dir,
            retention_hours=48.0,
            dry_run=False,
            now_provider=self.now_provider,
        )
        # Non-existent file eligibility check
        eligible, reason = manager.check_file_eligibility(self.test_dir / "nonexistent.json")
        self.assertFalse(eligible)
        self.assertIn("does not exist", reason)


if __name__ == "__main__":
    unittest.main()
