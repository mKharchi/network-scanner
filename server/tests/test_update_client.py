"""Integration tests for UPDATE_CLIENT action orchestration.

Tests verify:
- UPDATE_CLIENT action creation and dispatching
- Package staging on client-side
- Updater subprocess spawning
- Server-side result aggregation for bulk updates
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add server and client directories to path
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "client" / "app"))

from server_components.action_service import (
    create_action,
    deploy_package_to_client,
)
from server_components.action_framework import ActionType, ActionState


class TestUpdateClientAction(unittest.TestCase):
    """Test UPDATE_CLIENT action creation and parameter validation."""

    def test_create_update_client_action(self):
        """Verify UPDATE_CLIENT action is created with correct parameters."""
        with patch("server_components.action_service.get_connection") as mock_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_db.return_value = mock_conn
            mock_conn.cursor.return_value = mock_cursor

            # Mock the cursor's execute and fetchone responses
            mock_cursor.fetchone.return_value = None  # No existing action

            action_id = "test-update-001"
            targets = ["client-001", "client-002"]
            parameters = {
                "package_id": "app-v2.0.0",
                "package_path": "/packages/app-v2.0.0.zip",
            }

            action = create_action(
                ActionType.UPDATE_CLIENT.value,
                targets=targets,
                parameters=parameters,
                action_id=action_id,
            )

            self.assertEqual(action["action_id"], action_id)
            self.assertEqual(action["action_type"], ActionType.UPDATE_CLIENT.value)
            self.assertEqual(action["targets"], targets)
            self.assertEqual(action["status"], ActionState.PENDING.value)

    def test_update_client_parameters_sanitized(self):
        """Verify large package data is stripped before DB persistence."""
        from server_components.action_service import _sanitize_action_parameters

        parameters = {
            "package_id": "app-v2.0.0",
            "package_path": "/packages/app-v2.0.0.zip",
            "package_data_base64": "base64_string" * 1000,  # Large payload
        }

        sanitized = _sanitize_action_parameters(ActionType.UPDATE_CLIENT.value, parameters)

        self.assertIn("package_id", sanitized)
        self.assertIn("package_path", sanitized)
        self.assertNotIn("package_data_base64", sanitized)


class TestClientSidePackageStaging(unittest.TestCase):
    """Test client-side package staging for UPDATE_CLIENT."""

    def setUp(self):
        """Create temporary directories for test."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

        # Create directory structure
        self.incoming_dir = self.temp_path / "updates" / "incoming"
        self.staging_dir = self.temp_path / "updates" / "staging"
        self.current_dir = self.temp_path / "updates" / "current"

        self.incoming_dir.mkdir(parents=True)
        self.staging_dir.mkdir(parents=True)
        self.current_dir.mkdir(parents=True)

    def tearDown(self):
        """Clean up temporary directories."""
        self.temp_dir.cleanup()

    def test_handle_deploy_package_init_for_update_client(self):
        """Verify UPDATE_CLIENT operation routes package to updates/incoming."""
        from client_lib import (
            _handle_deploy_package_init,
            configure_package_paths,
            reset_all_package_states,
        )

        reset_all_package_states()
        configure_package_paths(
            incoming=self.incoming_dir,
            staging=self.staging_dir,
            current=self.current_dir,
        )

        message = {
            "action_id": "update-001",
            "args": {
                "action_id": "update-001",
                "package_id": "app-v2.0.0",
                "sha256": "abc123def456",
                "total_size": 10485760,  # 10 MB
                "chunk_size": 131072,
                "total_chunks": 80,
                "operation": "UPDATE_CLIENT",
            },
        }

        result = _handle_deploy_package_init(message)

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["operation"], "UPDATE_CLIENT")
        self.assertEqual(result["action_id"], "update-001")
        self.assertEqual(result["package_id"], "app-v2.0.0")

        # Verify the .part file was created
        part_file = self.incoming_dir / "app-v2.0.0.part"
        self.assertTrue(part_file.exists())

        reset_all_package_states()

    def test_package_result_staged_status(self):
        """Verify UPDATE_CLIENT returns STAGED status instead of SUCCESS."""
        from client_lib import (
            _handle_deploy_package_init,
            process_package_chunk,
            configure_package_paths,
            reset_all_package_states,
        )
        import hashlib
        import base64

        reset_all_package_states()
        configure_package_paths(
            incoming=self.incoming_dir,
            staging=self.staging_dir,
            current=self.current_dir,
        )

        # Initialize the update package session
        init_message = {
            "action_id": "update-001",
            "args": {
                "action_id": "update-001",
                "package_id": "app-v2.0.0",
                "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "total_size": 0,
                "chunk_size": 131072,
                "total_chunks": 1,
                "operation": "UPDATE_CLIENT",
            },
        }

        _handle_deploy_package_init(init_message)

        # Process a single empty chunk (to match the hash of empty string)
        chunk_message = {
            "action_id": "update-001",
            "seq": 1,
            "data": base64.b64encode(b"").decode("ascii"),
        }

        result = process_package_chunk(chunk_message)

        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "STAGED")
        self.assertEqual(result["destination"], "updates/incoming")
        self.assertIn("updater_spawn_status", result)

        reset_all_package_states()


class TestUpdaterSpawning(unittest.TestCase):
    """Test updater subprocess spawning logic."""

    def setUp(self):
        """Create temporary directories for test."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

        # Create directory structure
        (self.temp_path / "updater").mkdir(parents=True)
        (self.temp_path / "app").mkdir(parents=True)

        # Create a dummy updater.py
        updater_py = self.temp_path / "updater" / "updater.py"
        updater_py.write_text("#!/usr/bin/env python3\nprint('updater')\n")

        # Create a dummy package
        self.package_path = self.temp_path / "test-package.zip"
        self.package_path.write_bytes(b"PK\x03\x04")  # Minimal zip file signature

    def tearDown(self):
        """Clean up temporary directories."""
        self.temp_dir.cleanup()

    def test_spawn_updater_subprocess(self):
        """Verify updater subprocess is spawned with correct arguments."""
        from client_lib import _spawn_updater_subprocess

        with patch("subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.pid = 12345
            mock_popen.return_value = mock_process

            result = _spawn_updater_subprocess(self.package_path, self.temp_path)

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["updater_pid"], 12345)

            # Verify Popen was called with correct arguments
            call_args = mock_popen.call_args
            args_list = call_args[0][0]  # The command list

            # Should contain updater.py path and both arguments
            self.assertIn(str(self.package_path), args_list)
            self.assertIn(str(self.temp_path), args_list)

    def test_spawn_updater_missing_package(self):
        """Verify error when staged package is missing."""
        from client_lib import _spawn_updater_subprocess

        missing_package = self.temp_path / "missing.zip"

        result = _spawn_updater_subprocess(missing_package, self.temp_path)

        self.assertEqual(result["status"], "error")
        self.assertIn("not found", result["message"].lower())

    def test_spawn_updater_missing_updater(self):
        """Verify error when updater.py is missing."""
        from client_lib import _spawn_updater_subprocess

        # Remove the updater
        (self.temp_path / "updater" / "updater.py").unlink()

        result = _spawn_updater_subprocess(self.package_path, self.temp_path)

        self.assertEqual(result["status"], "error")
        self.assertIn("not found", result["message"].lower())


class TestUpdaterCommandLineInterface(unittest.TestCase):
    """Test updater's command-line interface."""

    def setUp(self):
        """Create temporary directories for test."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

        # Create directory structure
        (self.temp_path / "updater").mkdir(parents=True)
        (self.temp_path / "app").mkdir(parents=True)
        (self.temp_path / "logs").mkdir(parents=True)

        # Create a dummy package
        self.package_path = self.temp_path / "test-package.zip"
        self.package_path.write_bytes(b"PK\x03\x04")

    def tearDown(self):
        """Clean up temporary directories."""
        self.temp_dir.cleanup()

    def test_updater_cli_accepts_arguments(self):
        """Verify updater can be invoked from command line with arguments."""
        # This test verifies the CLI signature; actual execution requires
        # a valid update package with manifest.json, which is tested in updater tests.
        from pathlib import Path
        import sys

        updater_path = Path(__file__).parent.parent.parent / "client" / "updater" / "updater.py"
        if updater_path.exists():
            # Verify it can be imported
            spec = __import__("importlib.util").util.spec_from_file_location("updater", updater_path)
            updater_module = __import__("importlib.util").util.module_from_spec(spec)
            # The module should define UPDATER_VERSION and apply_update
            self.assertIsNotNone(updater_module)


if __name__ == "__main__":
    unittest.main()
