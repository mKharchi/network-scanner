"""Unit tests for Server Kismet Retention and Storage Manager (Phase 7)."""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

SERVER_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIRECTORY))

from server_components.kismet_retention import KismetRetentionManager


class KismetRetentionManagerTests(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="test_kismet_retention_"))
        self.manager = KismetRetentionManager(
            capture_dir=self.test_dir,
            retention_hours=24.0,
            min_free_bytes=0,  # 0 so disk pressure doesn't interfere with time-based tests
            write_grace_seconds=60.0,
            dry_run=True,
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_storage_metrics_empty(self):
        metrics = self.manager.get_storage_metrics()
        self.assertTrue(metrics["exists"])
        self.assertEqual(metrics["total_kismet_files"], 0)
        self.assertEqual(metrics["total_kismet_bytes"], 0)
        self.assertIsNone(metrics["newest_file"])

    def test_active_target_is_never_deleted(self):
        # Create single active file
        f1 = self.test_dir / "Kismet-active.kismet"
        f1.write_bytes(b"active-content" * 100)

        # Set mtime to 48h ago
        old_mtime = time.time() - (48 * 3600)
        os.utime(f1, (old_mtime, old_mtime))

        # Even though older than 24h, because it's the only/newest file, it's the active target
        summary = self.manager.prune_expired_captures(dry_run=False)
        self.assertEqual(summary.deleted_count, 0)
        self.assertEqual(summary.preserved_count, 1)
        self.assertTrue(f1.exists())
        self.assertEqual(summary.details[0]["reason"], "ACTIVE_TARGET")

    def test_dry_run_preserves_expired_files(self):
        now = time.time()
        # Older expired file (30h ago)
        f_old = self.test_dir / "Kismet-old.kismet"
        f_old.write_bytes(b"old-data" * 50)
        os.utime(f_old, (now - 30 * 3600, now - 30 * 3600))

        # Active newer file (10s ago)
        f_active = self.test_dir / "Kismet-active.kismet"
        f_active.write_bytes(b"active-data" * 100)

        summary = self.manager.prune_expired_captures(dry_run=True)
        self.assertEqual(summary.eligible_count, 1)
        self.assertEqual(summary.deleted_count, 1)
        self.assertTrue(summary.dry_run)
        # File must still physically exist because dry_run=True
        self.assertTrue(f_old.exists())
        self.assertTrue(f_active.exists())

    def test_actual_prune_deletes_expired_and_preserves_recent(self):
        now = time.time()
        # Older expired file (30h ago)
        f_old = self.test_dir / "Kismet-old.kismet"
        f_old.write_bytes(b"old-data" * 50)
        os.utime(f_old, (now - 30 * 3600, now - 30 * 3600))

        # Within retention window (5h ago)
        f_recent = self.test_dir / "Kismet-recent.kismet"
        f_recent.write_bytes(b"recent-data" * 50)
        os.utime(f_recent, (now - 5 * 3600, now - 5 * 3600))

        # Active newer file (1s ago)
        f_active = self.test_dir / "Kismet-active.kismet"
        f_active.write_bytes(b"active-data" * 100)

        summary = self.manager.prune_expired_captures(dry_run=False)
        self.assertEqual(summary.eligible_count, 1)
        self.assertEqual(summary.deleted_count, 1)
        self.assertEqual(summary.preserved_count, 2)
        # f_old was deleted, f_recent and f_active exist
        self.assertFalse(f_old.exists())
        self.assertTrue(f_recent.exists())
        self.assertTrue(f_active.exists())

    def test_active_sqlite_sidecar_preserves_capture(self):
        now = time.time()
        old_capture = self.test_dir / "Kismet-old.kismet"
        old_capture.write_bytes(b"old-data")
        os.utime(old_capture, (now - 30 * 3600, now - 30 * 3600))
        (self.test_dir / "Kismet-old.kismet-wal").write_bytes(b"active-wal")

        active_capture = self.test_dir / "Kismet-active.kismet"
        active_capture.write_bytes(b"active-data")

        summary = self.manager.prune_expired_captures(dry_run=False)

        self.assertEqual(summary.deleted_count, 0)
        self.assertTrue(old_capture.exists())
        self.assertEqual(summary.details[0]["reason"], "ACTIVE_SIDECAR")

    def test_investigation_hold_preserves_expired_capture(self):
        now = time.time()
        held_capture = self.test_dir / "Kismet-held.kismet"
        held_capture.write_bytes(b"held-data")
        os.utime(held_capture, (now - 30 * 3600, now - 30 * 3600))
        (self.test_dir / "Kismet-held.kismet.hold").write_text("case-123", encoding="utf-8")

        active_capture = self.test_dir / "Kismet-active.kismet"
        active_capture.write_bytes(b"active-data")

        summary = self.manager.prune_expired_captures(dry_run=False)

        self.assertEqual(summary.deleted_count, 0)
        self.assertTrue(held_capture.exists())
        self.assertEqual(summary.details[0]["reason"], "INVESTIGATION_HOLD")


if __name__ == "__main__":
    unittest.main()
