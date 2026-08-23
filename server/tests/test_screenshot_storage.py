"""Tests for screenshot payload validation and storage."""

import base64
import struct
import sys
import zlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SERVER_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIRECTORY))

from server_components import screenshot_storage  # noqa: E402


def _chunk(chunk_type, data):
    return (
        struct.pack(">I", len(data))
        + chunk_type
        + data
        + struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
    )


def png_payload():
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\x00\x00")
    return base64.b64encode(
        signature
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", idat)
        + _chunk(b"IEND", b"")
    ).decode("ascii")


class ScreenshotStorageTests(unittest.TestCase):
    def test_valid_png_is_stored_under_client_directory(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            screenshot_storage, "SCREENSHOT_STORAGE_DIR", Path(directory)
        ):
            result = screenshot_storage.store_screenshot(
                "client-123",
                {
                    "image_base64": png_payload(),
                    "filename": "DESKTOP-ABC-20260823.png",
                    "command_id": "cmd-1",
                    "device_name": "DESKTOP-ABC",
                    "captured_at": "2026-08-23T15:00:00+00:00",
                },
            )
            path = Path(result["storage_path"])
            self.assertTrue(path.is_file())
            self.assertEqual(path.parent.name, "client-123")
            self.assertEqual(result["mime_type"], "image/png")

    def test_non_image_payload_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "valid PNG"):
            screenshot_storage.decode_and_validate_png(
                base64.b64encode(b"not an image").decode("ascii")
            )


if __name__ == "__main__":
    unittest.main()
