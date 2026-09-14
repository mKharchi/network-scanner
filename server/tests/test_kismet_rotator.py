"""Unit tests for KismetLogRotator and automated capture cleanup."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from server_components.kismet_rotator import CleanupResult, KismetLogRotator, RotationResult


class TestKismetLogRotator(unittest.TestCase):

    def test_auth_header(self) -> None:
        rotator = KismetLogRotator(username="root", password="password123")
        header = rotator._auth_header()
        self.assertTrue(header.startswith("Basic "))

    @patch("urllib.request.urlopen")
    def test_get_active_logs(self, mock_urlopen: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps([
            {
                "kismet.logfile.uuid": "uuid-1234",
                "kismet.logfile.path": "/home/adonis/kismet/Kismet-test-1.kismet",
                "kismet.logfile.open": 1,
            }
        ]).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        rotator = KismetLogRotator()
        logs = rotator.get_active_logs()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["kismet.logfile.uuid"], "uuid-1234")

    @patch("urllib.request.urlopen")
    def test_rotate_success(self, mock_urlopen: MagicMock) -> None:
        # Mock active, stop, start
        mock_active = MagicMock()
        mock_active.status = 200
        mock_active.read.return_value = json.dumps([
            {
                "kismet.logfile.uuid": "uuid-1234",
                "kismet.logfile.path": "/home/adonis/kismet/old.kismet",
                "kismet.logfile.open": 1,
                "kismet.log.type_driver": {"kismet.logfile.type.class": "kismet"},
            }
        ]).encode("utf-8")

        mock_stop = MagicMock()
        mock_stop.status = 200
        mock_stop.read.return_value = b"OK\n"

        mock_start = MagicMock()
        mock_start.status = 200
        mock_start.read.return_value = json.dumps({
            "kismet.logfile.uuid": "uuid-5678",
            "kismet.logfile.path": "/home/adonis/kismet/new.kismet",
        }).encode("utf-8")

        mock_urlopen.return_value.__enter__.side_effect = [mock_active, mock_stop, mock_start]

        rotator = KismetLogRotator()
        res = rotator.rotate()
        self.assertTrue(res.success)
        self.assertEqual(res.closed_log_uuid, "uuid-1234")
        self.assertEqual(res.closed_log_path, "/home/adonis/kismet/old.kismet")
        self.assertEqual(res.new_log_path, "/home/adonis/kismet/new.kismet")

    def test_cleanup_verified_captures(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            cap_dir = tmpdir / "captures"
            cap_dir.mkdir()
            storage_dir = tmpdir / "storage"
            intervals_dir = storage_dir / "intervals" / "2026-09-12"
            intervals_dir.mkdir(parents=True)

            # Create 2 capture files: one verified/closed, one active/recent
            verified_cap = cap_dir / "verified.kismet"
            verified_cap.write_bytes(b"dummy capture content 12345")

            active_cap = cap_dir / "active.kismet"
            active_cap.write_bytes(b"active capture content")

            # Write manifest for verified_cap marking it safe
            manifest = {
                "interval_id": "int_1",
                "status": "COMPLETED",
                "safe_for_raw_cleanup": True,
                "source_captures": [{"path": str(verified_cap)}],
            }
            (intervals_dir / "int_1.manifest.json").write_text(json.dumps(manifest))

            rotator = KismetLogRotator(storage_dir=storage_dir, capture_dirs=[cap_dir])
            # Mock active check so active_cap is preserved
            rotator.is_file_active_in_kismet = lambda p: p.name == "active.kismet"  # type: ignore

            # Dry run: detects eligible file, deletes nothing
            dry = rotator.cleanup_verified_captures(dry_run=True)
            self.assertEqual(dry.deleted_captures, ["verified.kismet"])
            self.assertEqual(dry.preserved_active, ["active.kismet"])
            self.assertTrue(verified_cap.exists())

            # Execute run: deletes verified capture
            executed = rotator.cleanup_verified_captures(dry_run=False)
            self.assertEqual(executed.deleted_captures, ["verified.kismet"])
            self.assertFalse(verified_cap.exists())
            self.assertTrue(active_cap.exists())  # Active preserved!


if __name__ == "__main__":
    unittest.main(verbosity=2)
