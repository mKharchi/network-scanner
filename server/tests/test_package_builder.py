"""Unit and API tests for automatic client update package building and listing."""

import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add server to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from server_components import package_service


class TestPackageBuilder(unittest.TestCase):
    """Test package_service.build_client_update_package and list_packages."""

    def setUp(self):
        self.temp_storage = tempfile.mkdtemp(prefix="test_pkg_storage_")
        self.temp_client_app = tempfile.mkdtemp(prefix="test_client_app_")
        
        # Create sample client app files
        app_path = Path(self.temp_client_app)
        (app_path / "client.py").write_text("print('client v2')", encoding="utf-8")
        (app_path / "client_lib.py").write_text("def run(): pass", encoding="utf-8")
        (app_path / "requirements.txt").write_text("psutil>=5.9.0\n", encoding="utf-8")

        self.storage_patcher = patch.object(
            package_service, "PACKAGE_STORAGE_DIR", Path(self.temp_storage)
        )
        self.storage_patcher.start()

    def tearDown(self):
        self.storage_patcher.stop()
        shutil.rmtree(self.temp_storage, ignore_errors=True)
        shutil.rmtree(self.temp_client_app, ignore_errors=True)

    @patch("server_components.package_service.get_connection")
    def test_build_client_update_package_success(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        record = package_service.build_client_update_package(
            version="2.5.0",
            release_notes="Automated test release",
            base_app_dir=Path(self.temp_client_app),
            uploaded_by="test-admin",
        )

        self.assertEqual(record["package_id"], "client-update-2.5.0")
        self.assertEqual(record["filename"], "client-update-2.5.0.zip")
        self.assertTrue(record["size_bytes"] > 0)
        self.assertTrue(len(record["sha256"]) == 64)

        # Verify archive structure
        zip_path = Path(record["storage_path"])
        self.assertTrue(zip_path.is_file())

        with zipfile.ZipFile(zip_path, "r") as zf:
            namelist = zf.namelist()
            self.assertIn("manifest.json", namelist)
            self.assertIn("app/client.py", namelist)
            self.assertIn("app/client_lib.py", namelist)
            self.assertIn("app/version.json", namelist)

            # Read manifest
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            self.assertEqual(manifest["version"], "2.5.0")
            self.assertEqual(manifest["package_type"], "client-update")
            self.assertEqual(manifest["release_notes"], "Automated test release")
            self.assertIn("client.py", manifest["file_hashes"])
            self.assertIn("version.json", manifest["file_hashes"])

            # Read version.json
            vjson = json.loads(zf.read("app/version.json").decode("utf-8"))
            self.assertEqual(vjson["version"], "2.5.0")

    def test_build_invalid_version_raises(self):
        with self.assertRaises(ValueError):
            package_service.build_client_update_package(
                version="invalid_ver_format!",
                base_app_dir=Path(self.temp_client_app),
            )


if __name__ == "__main__":
    unittest.main()
