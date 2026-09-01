"""Unit tests for deployment package storage."""

import io
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

SERVER_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIRECTORY))

try:
    import mysql.connector  # noqa: F401
except ModuleNotFoundError:
    mysql_module = types.ModuleType("mysql")
    mysql_module.connector = types.ModuleType("mysql.connector")
    sys.modules["mysql"] = mysql_module
    sys.modules["mysql.connector"] = mysql_module.connector

from server_components import action_service, package_service  # noqa: E402
from server_components.action_framework import ActionType  # noqa: E402


class PackageServiceTests(unittest.TestCase):
    def setUp(self):
        self._storage_dir = Path(self._tmp_dir()) / "packages"
        self._storage_patch = patch.object(package_service, "PACKAGE_STORAGE_DIR", self._storage_dir)
        self._storage_patch.start()

    def tearDown(self):
        self._storage_patch.stop()

    def _tmp_dir(self):
        import tempfile

        return tempfile.mkdtemp()

    @patch("server_components.package_service.get_connection")
    def test_stream_to_storage_persists_metadata(self, mock_get_conn):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        mock_get_conn.return_value = conn

        payload = b"PK\x03\x04test zip payload"
        record = package_service.stream_to_storage(
            io.BytesIO(payload),
            filename="agent-update.zip",
            package_id="pkg-test-1",
            uploaded_by="operator",
        )

        self.assertEqual(record["package_id"], "pkg-test-1")
        self.assertEqual(record["filename"], "agent-update.zip")
        self.assertEqual(record["size_bytes"], len(payload))
        self.assertEqual(len(record["sha256"]), 64)
        stored_path = Path(record["storage_path"])
        self.assertTrue(stored_path.is_file())
        self.assertEqual(stored_path.read_bytes(), payload)
        cursor.execute.assert_called_once()

    def test_sanitize_action_parameters_strips_package_payload(self):
        sanitized = action_service._sanitize_action_parameters(
            ActionType.DEPLOY_PACKAGE.value,
            {
                "package_id": "pkg-1",
                "package_data_base64": "aGVsbG8=",
                "package_bytes": b"hello",
                "timeout": 120,
            },
        )
        self.assertEqual(sanitized, {"package_id": "pkg-1", "timeout": 120})


if __name__ == "__main__":
    unittest.main()
