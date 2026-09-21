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
        # First call is get_package (no existing), second is upsert.
        cursor.fetchone.return_value = None

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
        self.assertFalse(record["replaced"])
        stored_path = Path(record["storage_path"])
        self.assertTrue(stored_path.is_file())
        self.assertEqual(stored_path.read_bytes(), payload)
        self.assertGreaterEqual(cursor.execute.call_count, 1)

    @patch("server_components.package_service.get_connection")
    def test_stream_to_storage_replaces_existing_package(self, mock_get_conn):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        mock_get_conn.return_value = conn

        first = b"PK\x03\x04first-payload"
        second = b"PK\x03\x04second-payload-longer"

        # First upload: no existing row
        cursor.fetchone.return_value = None
        first_record = package_service.stream_to_storage(
            io.BytesIO(first),
            filename="client-update-9.9.9.zip",
            package_id="client-update-9.9.9",
        )
        path = Path(first_record["storage_path"])
        self.assertEqual(path.read_bytes(), first)

        # Second upload: pretend DB still has the row (retry after failed deploy)
        cursor.fetchone.return_value = {
            "package_id": "client-update-9.9.9",
            "filename": "client-update-9.9.9.zip",
            "size_bytes": len(first),
            "sha256": first_record["sha256"],
            "storage_path": str(path),
            "uploaded_by": None,
            "created_at": None,
        }
        second_record = package_service.stream_to_storage(
            io.BytesIO(second),
            filename="client-update-9.9.9.zip",
            package_id="client-update-9.9.9",
        )
        self.assertTrue(second_record["replaced"])
        self.assertEqual(path.read_bytes(), second)
        self.assertNotEqual(first_record["sha256"], second_record["sha256"])

        # replace=False must still reject
        with self.assertRaises(ValueError) as raised:
            package_service.stream_to_storage(
                io.BytesIO(second),
                filename="client-update-9.9.9.zip",
                package_id="client-update-9.9.9",
                replace=False,
            )
        self.assertIn("already exists", str(raised.exception))

    @patch("server_components.package_service.get_connection")
    def test_stream_to_storage_repairs_orphaned_db_row(self, mock_get_conn):
        """Deleting the zip by hand left a DB row — re-upload must upsert, not fail."""
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        mock_get_conn.return_value = conn
        cursor.fetchone.return_value = {
            "package_id": "client-update-1.2.3",
            "filename": "client-update-1.2.3.zip",
            "size_bytes": 10,
            "sha256": "a" * 64,
            "storage_path": str(self._storage_dir / "client-update-1.2.3.zip"),
            "uploaded_by": None,
            "created_at": None,
        }

        payload = b"PK\x03\x04restored"
        record = package_service.stream_to_storage(
            io.BytesIO(payload),
            filename="client-update-1.2.3.zip",
            package_id="client-update-1.2.3",
        )
        self.assertTrue(record["replaced"])
        self.assertTrue(Path(record["storage_path"]).is_file())
        # Upsert SQL must be used (ON DUPLICATE KEY UPDATE)
        upsert_calls = [
            call for call in cursor.execute.call_args_list
            if call.args and "ON DUPLICATE KEY UPDATE" in str(call.args[0])
        ]
        self.assertTrue(upsert_calls)

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
