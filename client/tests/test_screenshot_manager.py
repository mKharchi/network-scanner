"""Tests for explicit, local screenshot capture management."""

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


CLIENT_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLIENT_DIRECTORY))

from screenshot_manager import (  # noqa: E402
    ScreenshotManager,
    build_screenshot_filename,
    sanitize_device_name,
    screenshot_capture_enabled,
)


class FakeImage:
    def __init__(self):
        self.saved = []

    def save(self, path, format):
        self.saved.append((Path(path), format))
        Path(path).write_bytes(b"fake-png")


class ScreenshotManagerTests(unittest.TestCase):
    def test_user_session_roles_can_capture_screenshots(self):
        self.assertTrue(screenshot_capture_enabled("interactive"))
        self.assertTrue(screenshot_capture_enabled("combined"))
        self.assertFalse(screenshot_capture_enabled("service"))

    def test_sanitize_device_name_removes_path_characters(self):
        self.assertEqual(sanitize_device_name(r"DESKTOP/ABC\\.."), "DESKTOP_ABC")
        self.assertEqual(sanitize_device_name("   "), "unknown-device")

    def test_filename_is_utc_safe_and_uses_command_suffix(self):
        filename = build_screenshot_filename(
            "DESKTOP/ABC",
            datetime(2026, 8, 23, 15, 0, 12, tzinfo=timezone.utc),
            "cmd/123",
        )
        self.assertEqual(filename, "DESKTOP_ABC-20260823-150012-cmd123.png")

    def test_capture_writes_png_to_bounded_temp_directory(self):
        image = FakeImage()
        captured_at = datetime(2026, 8, 23, 15, 0, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            manager = ScreenshotManager(
                directory,
                image_grabber=lambda **kwargs: image,
                hostname_provider=lambda: "DESKTOP/ABC",
                clock=lambda: captured_at,
            )

            result = manager.capture(command_id="command-123")

            self.assertTrue(result.path.exists())
            self.assertEqual(result.path.read_bytes(), b"fake-png")
            self.assertEqual(result.filename, "DESKTOP_ABC-20260823-150012-command-123.png")
            self.assertEqual(result.mime_type, "image/png")
            self.assertEqual(image.saved[0][1], "PNG")
            self.assertTrue(manager.include_all_screens)

    def test_capture_removes_partial_file_when_grabber_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ScreenshotManager(
                directory,
                image_grabber=lambda **kwargs: (_ for _ in ()).throw(OSError("desktop unavailable")),
                clock=lambda: datetime(2026, 8, 23, tzinfo=timezone.utc),
            )

            with self.assertRaisesRegex(RuntimeError, "desktop unavailable"):
                manager.capture(command_id="failed-capture")

            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_cleanup_removes_expired_and_excess_files(self):
        now = datetime(2026, 8, 23, 15, 0, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            temp_dir = Path(directory)
            old_file = temp_dir / "old.png"
            old_file.write_bytes(b"old")
            os.utime(old_file, ((now - timedelta(hours=2)).timestamp(),) * 2)

            keep_file = temp_dir / "keep.png"
            keep_file.write_bytes(b"keep")
            os.utime(keep_file, ((now - timedelta(minutes=5)).timestamp(),) * 2)

            extra_file = temp_dir / "extra.png"
            extra_file.write_bytes(b"extra")
            os.utime(extra_file, ((now - timedelta(minutes=4)).timestamp(),) * 2)

            manager = ScreenshotManager(
                temp_dir,
                max_temp_files=1,
                max_temp_age_seconds=3600,
                clock=lambda: now,
            )
            manager.cleanup_stale_files()

            self.assertEqual([path.name for path in temp_dir.glob("*.png")], ["extra.png"])


if __name__ == "__main__":
    unittest.main()
