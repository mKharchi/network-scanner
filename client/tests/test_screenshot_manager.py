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
    SessionTopology,
    build_screenshot_filename,
    get_session_topology,
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

    def test_session_topology_diagnostics(self):
        topology = get_session_topology()
        self.assertIsInstance(topology, SessionTopology)
        self.assertTrue(len(topology.agent_user) > 0)
        d = topology.to_dict()
        self.assertIn("agent_user", d)
        self.assertIn("can_capture", d)
        self.assertIn("reason", d)

    def test_session_0_service_capture_blocked(self):
        # Case B (Plan §4.1): Agent is running in Session 0 (service), user is in Session 1
        service_topology = SessionTopology(
            agent_user="SYSTEM",
            agent_session_id=0,
            active_session_id=1,
            interactive_user="alice",
            window_station="WinSta0",
            desktop_name="Default",
            is_active_session=False,
            can_capture=False,
            reason="Agent running in Session 0 (service); active console is Session 1 (alice). Desktop capture requires an interactive user-session agent.",
        )

        with tempfile.TemporaryDirectory() as directory:
            manager = ScreenshotManager(
                temp_dir=directory,
                image_grabber=lambda **k: FakeImage(),
                topology_provider=lambda: service_topology,
            )
            with self.assertRaises(RuntimeError) as ctx:
                manager.capture()
            self.assertIn("Session 0", str(ctx.exception))
            self.assertIn("alice", str(ctx.exception))

    def test_session_matching_capture_succeeds(self):
        # Case A (Plan §4.1): Same user, same interactive session
        interactive_topology = SessionTopology(
            agent_user="alice",
            agent_session_id=1,
            active_session_id=1,
            interactive_user="alice",
            window_station="WinSta0",
            desktop_name="Default",
            is_active_session=True,
            can_capture=True,
            reason="Session matches active console desktop.",
        )

        with tempfile.TemporaryDirectory() as directory:
            manager = ScreenshotManager(
                temp_dir=directory,
                image_grabber=lambda **k: FakeImage(),
                topology_provider=lambda: interactive_topology,
            )
            result = manager.capture(command_id="test-cmd")
            self.assertTrue(result.path.is_file())


if __name__ == "__main__":
    unittest.main()
