"""Unit tests for client-side package deployment handling and safe extraction."""

import base64
import hashlib
import io
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import zipfile

CLIENT_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLIENT_DIRECTORY))

import client_lib  # noqa: E402
from action_framework import ActionManager, ActionType  # noqa: E402


def _make_zip(files_dict: dict) -> bytes:
    """Create in-memory zip bytes mapping relative paths to content bytes."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for fname, content in files_dict.items():
            zf.writestr(fname, content)
    return buf.getvalue()


class ClientPackageDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="test_client_pkg_"))
        self.incoming_dir = self.test_dir / "updates" / "incoming"
        self.staging_dir = self.test_dir / "updates" / "staging"
        self.current_dir = self.test_dir / "updates" / "current"
        self.sent_files_dir = self.test_dir / "storage" / "sent-files"

        client_lib.configure_package_paths(
            incoming=self.incoming_dir,
            staging=self.staging_dir,
            current=self.current_dir,
            sent_files=self.sent_files_dir,
        )

    def tearDown(self):
        client_lib.reset_all_package_states()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_deploy_package_init_creates_staging_dir_and_part_file(self):
        init_message = {
            "command": "DEPLOY_PACKAGE_INIT",
            "action_id": "act-101",
            "args": {
                "package_id": "pkg-v1",
                "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "total_size": 0,
                "chunk_size": 131072,
                "total_chunks": 1,
            },
        }

        res = client_lib.handle_command(init_message)
        self.assertEqual(res.get("status"), "ready")
        self.assertEqual(res.get("package_id"), "pkg-v1")
        self.assertIn("act-101", client_lib.ACTIVE_PACKAGE_SESSIONS)

        part_file = self.incoming_dir / "pkg-v1.zip.part"
        self.assertTrue(part_file.exists())

    def test_chunk_streaming_sha256_match_and_safe_extraction_success(self):
        payload = _make_zip({
            "app.py": b"print('Hello from deployed package!')",
            "config/settings.json": b'{"version": "1.0.0"}',
        })
        expected_hash = hashlib.sha256(payload).hexdigest()

        init_message = {
            "command": "DEPLOY_PACKAGE_INIT",
            "action_id": "act-success",
            "args": {
                "package_id": "pkg-success",
                "sha256": expected_hash,
                "total_size": len(payload),
                "chunk_size": 16,
                "total_chunks": (len(payload) + 15) // 16,
            },
        }
        init_res = client_lib.handle_command(init_message)
        self.assertEqual(init_res.get("status"), "ready")

        total_chunks = init_res["total_chunks"]
        chunk_size = 16
        for seq in range(1, total_chunks + 1):
            chunk_data = payload[(seq - 1) * chunk_size : seq * chunk_size]
            msg = {
                "type": "PACKAGE_CHUNK",
                "action_id": "act-success",
                "seq": seq,
                "total_chunks": total_chunks,
                "data": base64.b64encode(chunk_data).decode("ascii"),
            }
            res = client_lib.process_package_chunk(msg)
            if seq < total_chunks:
                self.assertIsNone(res)
            else:
                self.assertIsNotNone(res)
                self.assertEqual(res.get("type"), "PACKAGE_RESULT")
                self.assertEqual(res.get("status"), "SUCCESS")
                self.assertEqual(res.get("sha256"), expected_hash)

        # Confirm incoming zip landed
        final_zip = self.incoming_dir / "pkg-success.zip"
        part_file = self.incoming_dir / "pkg-success.zip.part"
        self.assertTrue(final_zip.exists())
        self.assertFalse(part_file.exists())
        self.assertEqual(final_zip.read_bytes(), payload)

        # Confirm files landed in current deployed directory via atomic swap
        current_dir = self.current_dir
        self.assertTrue(current_dir.exists())
        self.assertTrue((current_dir / "app.py").exists())
        self.assertEqual((current_dir / "app.py").read_text(), "print('Hello from deployed package!')")
        self.assertTrue((current_dir / "config" / "settings.json").exists())
        self.assertEqual((current_dir / "config" / "settings.json").read_text(), '{"version": "1.0.0"}')

    def test_send_file_lands_in_sent_files_without_touching_updates(self):
        payload = b"plain file sent to the client"
        expected_hash = hashlib.sha256(payload).hexdigest()
        init_res = client_lib.handle_command({
            "command": "SEND_FILE",
            "action_id": "act-send-file",
            "args": {
                "package_id": "file-001",
                "filename": "notes.txt",
                "sha256": expected_hash,
                "total_size": len(payload),
                "chunk_size": len(payload),
                "total_chunks": 1,
                "operation": "SEND_FILE",
            },
        })
        self.assertEqual(init_res.get("status"), "ready")
        result = client_lib.process_package_chunk({
            "type": "PACKAGE_CHUNK",
            "action_id": "act-send-file",
            "seq": 1,
            "total_chunks": 1,
            "data": base64.b64encode(payload).decode("ascii"),
        })
        self.assertEqual(result.get("status"), "SUCCESS")
        self.assertEqual((self.sent_files_dir / "notes.txt").read_bytes(), payload)
        self.assertFalse(self.current_dir.exists())
        self.assertFalse((self.incoming_dir / "file-001.zip").exists())

    def test_send_file_rejects_traversal_filename(self):
        payload = b"unsafe destination"
        with self.assertRaisesRegex(ValueError, "single relative filename"):
            client_lib.handle_command({
                "command": "SEND_FILE",
                "action_id": "act-send-file-unsafe",
                "args": {
                    "package_id": "file-002",
                    "filename": "..\\\\outside.txt",
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "total_size": len(payload),
                    "total_chunks": 1,
                    "operation": "SEND_FILE",
                },
            })

    def test_safe_extract_rejects_path_traversal_zip_slip(self):
        # Craft malicious zip with ../ traversal
        malicious_zip_bytes = _make_zip({
            "valid.txt": b"good file",
            "../../evil.txt": b"malicious content trying to escape sandbox",
        })
        expected_hash = hashlib.sha256(malicious_zip_bytes).hexdigest()

        init_message = {
            "command": "DEPLOY_PACKAGE_INIT",
            "action_id": "act-zipslip",
            "args": {
                "package_id": "pkg-zipslip",
                "sha256": expected_hash,
                "total_size": len(malicious_zip_bytes),
                "chunk_size": len(malicious_zip_bytes),
                "total_chunks": 1,
            },
        }
        client_lib.handle_command(init_message)

        msg = {
            "type": "PACKAGE_CHUNK",
            "action_id": "act-zipslip",
            "seq": 1,
            "total_chunks": 1,
            "data": base64.b64encode(malicious_zip_bytes).decode("ascii"),
        }
        res = client_lib.process_package_chunk(msg)

        self.assertIsNotNone(res)
        self.assertEqual(res.get("status"), "FAILED")
        self.assertIn("unsafe path in archive", res.get("error", "").lower())

        # Verify nothing escaped and no evil.txt was created anywhere
        self.assertFalse((self.test_dir / "evil.txt").exists())
        self.assertFalse((self.test_dir.parent / "evil.txt").exists())
        self.assertFalse(self.current_dir.exists())

    def test_safe_extract_rejects_uncompressed_size_zip_bomb(self):
        # Create a small archive claiming 200MB uncompressed, test against 10MB limit
        large_fake_data = b"0" * (15 * 1024 * 1024)
        bomb_bytes = _make_zip({"large.txt": large_fake_data})

        dest = self.test_dir / "extract_test"
        zip_path = self.test_dir / "bomb.zip"
        zip_path.write_bytes(bomb_bytes)

        # Enforce max limit of 5 MB (below 15 MB)
        with self.assertRaises(ValueError) as ctx:
            client_lib.safe_extract(zip_path, dest, max_uncompressed_bytes=5 * 1024 * 1024)

        self.assertIn("archive too large", str(ctx.exception).lower())
        # Confirm destination was not populated
        self.assertFalse((dest / "large.txt").exists())

    def test_failed_extraction_leaves_previous_good_deployment_untouched(self):
        # First deploy a good package v1
        good_payload = _make_zip({"version.txt": b"version 1.0"})
        good_hash = hashlib.sha256(good_payload).hexdigest()

        init_good = {
            "command": "DEPLOY_PACKAGE_INIT",
            "action_id": "act-v1",
            "args": {
                "package_id": "pkg-v1",
                "sha256": good_hash,
                "total_size": len(good_payload),
                "chunk_size": len(good_payload),
                "total_chunks": 1,
            },
        }
        client_lib.handle_command(init_good)
        res_good = client_lib.process_package_chunk({
            "type": "PACKAGE_CHUNK",
            "action_id": "act-v1",
            "seq": 1,
            "total_chunks": 1,
            "data": base64.b64encode(good_payload).decode("ascii"),
        })
        self.assertEqual(res_good.get("status"), "SUCCESS")
        self.assertEqual((self.current_dir / "version.txt").read_text(), "version 1.0")

        # Now deploy bad package v2 with zip slip
        bad_payload = _make_zip({
            "version.txt": b"version 2.0 corrupted",
            "../escape.txt": b"attack",
        })
        bad_hash = hashlib.sha256(bad_payload).hexdigest()

        init_bad = {
            "command": "DEPLOY_PACKAGE_INIT",
            "action_id": "act-v2",
            "args": {
                "package_id": "pkg-v2",
                "sha256": bad_hash,
                "total_size": len(bad_payload),
                "chunk_size": len(bad_payload),
                "total_chunks": 1,
            },
        }
        client_lib.handle_command(init_bad)
        res_bad = client_lib.process_package_chunk({
            "type": "PACKAGE_CHUNK",
            "action_id": "act-v2",
            "seq": 1,
            "total_chunks": 1,
            "data": base64.b64encode(bad_payload).decode("ascii"),
        })
        self.assertEqual(res_bad.get("status"), "FAILED")

        # Confirm the previous good deployment v1 is completely UNTOUCHED
        self.assertTrue(self.current_dir.exists())
        self.assertEqual((self.current_dir / "version.txt").read_text(), "version 1.0")
        self.assertFalse((self.current_dir / "escape.txt").exists())

    def test_atomic_swap_directory_replaces_old_directory(self):
        target_dir = self.test_dir / "target_app"
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "old_file.txt").write_text("old content")

        new_source_dir = self.test_dir / "new_app"
        new_source_dir.mkdir(parents=True, exist_ok=True)
        (new_source_dir / "new_file.txt").write_text("new content")

        client_lib.atomic_swap_directory(new_source_dir, target_dir)

        self.assertTrue(target_dir.exists())
        self.assertTrue((target_dir / "new_file.txt").exists())
        self.assertEqual((target_dir / "new_file.txt").read_text(), "new content")
        self.assertFalse((target_dir / "old_file.txt").exists())
        self.assertFalse(new_source_dir.exists())


if __name__ == "__main__":
    unittest.main()
