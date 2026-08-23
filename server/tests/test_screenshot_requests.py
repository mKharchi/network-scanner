"""Tests for request-driven interactive-agent screenshot dispatch."""

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

SERVER_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIRECTORY))

try:
    import mysql.connector  # noqa: F401
except ModuleNotFoundError:
    mysql_module = types.ModuleType("mysql")
    mysql_module.connector = types.ModuleType("mysql.connector")
    sys.modules["mysql"] = mysql_module
    sys.modules["mysql.connector"] = mysql_module.connector

from server_components import server_lib  # noqa: E402


class ScreenshotRequestTests(unittest.TestCase):
    def test_request_targets_interactive_agent_and_persists_metadata(self):
        response = {
            "status": "ok",
            "data": {
                "status": "ok",
                "command_id": "screenshot-1",
                "filename": "DESKTOP-ABC-20260823.png",
                "device_name": "DESKTOP-ABC",
                "captured_at": "2026-08-23T15:00:00+00:00",
                "image_base64": "validated-payload",
            },
        }
        metadata = {
            "filename": "DESKTOP-ABC-20260823-screenshot-1.png",
            "storage_path": "storage/screenshots/client-a/file.png",
            "mime_type": "image/png",
            "file_size": 128,
            "device_name": "DESKTOP-ABC",
            "command_id": "screenshot-1",
            "captured_at": "2026-08-23T15:00:00+00:00",
        }
        with patch.object(
            server_lib, "execute_client_command", return_value=response
        ) as execute, patch(
            "server_components.screenshot_storage.store_screenshot",
            return_value=metadata,
        ) as store, patch.object(
            server_lib, "_persist_screenshot_metadata"
        ) as persist, patch.object(
            server_lib.time, "time", return_value=1787497200.0
        ):
            result = server_lib.request_client_screenshot("client-a", timeout=4.0)

        execute.assert_called_once_with(
            "client-a",
            "REQUEST_SCREENSHOT",
            args={"command_id": "screenshot-1787497200000"},
            timeout=4.0,
            process_network_scan=False,
            agent_role="interactive",
        )
        store.assert_called_once_with("client-a", response["data"])
        persist.assert_called_once_with(
            "client-a", metadata, requested_by=None
        )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["mime_type"], "image/png")

    def test_request_reports_interactive_agent_unavailable(self):
        with patch.object(
            server_lib,
            "execute_client_command",
            return_value={"status": "error", "message": "Client 'client-a' is not connected."},
        ):
            result = server_lib.request_client_screenshot("client-a", timeout=2.0)

        self.assertEqual(result["status"], "client_unavailable")
        self.assertEqual(result["client_id"], "client-a")


if __name__ == "__main__":
    unittest.main()
