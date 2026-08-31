"""Unit tests for client-side package deployment handling."""

import base64
import hashlib
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

CLIENT_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLIENT_DIRECTORY))

import client_lib  # noqa: E402
from action_framework import ActionManager, ActionType  # noqa: E402


class ClientPackageDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="test_client_pkg_"))
        self.orig_staging_dir = client_lib.PACKAGE_INCOMING_DIR
        client_lib.PACKAGE_INCOMING_DIR = self.test_dir / "updates" / "incoming"
        client_lib.ACTIVE_PACKAGE_SESSIONS.clear()

    def tearDown(self):
        client_lib.PACKAGE_INCOMING_DIR = self.orig_staging_dir
        for session in list(client_lib.ACTIVE_PACKAGE_SESSIONS.values()):
            if session.get("file_handle") and not session["file_handle"].closed:
                session["file_handle"].close()
        client_lib.ACTIVE_PACKAGE_SESSIONS.clear()
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

        part_file = client_lib.PACKAGE_INCOMING_DIR / "pkg-v1.zip.part"
        self.assertTrue(part_file.exists())

    def test_chunk_streaming_and_sha256_match_success(self):
        payload = b"Test zip payload contents for remote package deployment milestone B"
        expected_hash = hashlib.sha256(payload).hexdigest()

        init_message = {
            "command": "DEPLOY_PACKAGE_INIT",
            "action_id": "act-success",
            "args": {
                "package_id": "pkg-success",
                "sha256": expected_hash,
                "total_size": len(payload),
                "chunk_size": 16,
                "total_chunks": 5,
            },
        }
        init_res = client_lib.handle_command(init_message)
        self.assertEqual(init_res.get("status"), "ready")

        # Send chunks 1 to 4
        chunk_size = 16
        for seq in range(1, 5):
            chunk_data = payload[(seq - 1) * chunk_size : seq * chunk_size]
            msg = {
                "type": "PACKAGE_CHUNK",
                "action_id": "act-success",
                "seq": seq,
                "total_chunks": 5,
                "data": base64.b64encode(chunk_data).decode("ascii"),
            }
            res = client_lib.process_package_chunk(msg)
            self.assertIsNone(res)

        # Send final chunk 5
        chunk_data = payload[4 * chunk_size :]
        msg = {
            "type": "PACKAGE_CHUNK",
            "action_id": "act-success",
            "seq": 5,
            "total_chunks": 5,
            "data": base64.b64encode(chunk_data).decode("ascii"),
        }
        res = client_lib.process_package_chunk(msg)

        self.assertIsNotNone(res)
        self.assertEqual(res.get("type"), "PACKAGE_RESULT")
        self.assertEqual(res.get("status"), "SUCCESS")
        self.assertEqual(res.get("sha256"), expected_hash)

        # Confirm atomic rename to .zip and .part removed
        final_zip = client_lib.PACKAGE_INCOMING_DIR / "pkg-success.zip"
        part_file = client_lib.PACKAGE_INCOMING_DIR / "pkg-success.zip.part"
        self.assertTrue(final_zip.exists())
        self.assertFalse(part_file.exists())
        self.assertEqual(final_zip.read_bytes(), payload)

    def test_chunk_streaming_hash_mismatch_fails_and_deletes_part_file(self):
        payload = b"Legitimate package contents"
        wrong_hash = "0000000000000000000000000000000000000000000000000000000000000000"

        init_message = {
            "command": "DEPLOY_PACKAGE_INIT",
            "action_id": "act-mismatch",
            "args": {
                "package_id": "pkg-bad",
                "sha256": wrong_hash,
                "total_size": len(payload),
                "chunk_size": 64,
                "total_chunks": 1,
            },
        }
        client_lib.handle_command(init_message)

        msg = {
            "type": "PACKAGE_CHUNK",
            "action_id": "act-mismatch",
            "seq": 1,
            "total_chunks": 1,
            "data": base64.b64encode(payload).decode("ascii"),
        }
        res = client_lib.process_package_chunk(msg)

        self.assertIsNotNone(res)
        self.assertEqual(res.get("status"), "FAILED")
        self.assertIn("hash mismatch", res.get("error", ""))

        final_zip = client_lib.PACKAGE_INCOMING_DIR / "pkg-bad.zip"
        part_file = client_lib.PACKAGE_INCOMING_DIR / "pkg-bad.zip.part"
        self.assertFalse(final_zip.exists())
        self.assertFalse(part_file.exists())

    def test_large_multi_megabyte_payload_chunking(self):
        # 2 MB payload chunked in 64KB blocks
        payload = os.urandom(2 * 1024 * 1024)
        expected_hash = hashlib.sha256(payload).hexdigest()
        chunk_size = 64 * 1024
        total_chunks = (len(payload) + chunk_size - 1) // chunk_size

        init_message = {
            "command": "DEPLOY_PACKAGE_INIT",
            "action_id": "act-large",
            "args": {
                "package_id": "pkg-large",
                "sha256": expected_hash,
                "total_size": len(payload),
                "chunk_size": chunk_size,
                "total_chunks": total_chunks,
            },
        }
        client_lib.handle_command(init_message)

        for seq in range(1, total_chunks + 1):
            chunk_data = payload[(seq - 1) * chunk_size : seq * chunk_size]
            msg = {
                "type": "PACKAGE_CHUNK",
                "action_id": "act-large",
                "seq": seq,
                "total_chunks": total_chunks,
                "data": base64.b64encode(chunk_data).decode("ascii"),
            }
            res = client_lib.process_package_chunk(msg)
            if seq < total_chunks:
                self.assertIsNone(res)
            else:
                self.assertIsNotNone(res)
                self.assertEqual(res.get("status"), "SUCCESS")

        final_zip = client_lib.PACKAGE_INCOMING_DIR / "pkg-large.zip"
        self.assertTrue(final_zip.exists())
        self.assertEqual(final_zip.stat().st_size, len(payload))
        self.assertEqual(hashlib.sha256(final_zip.read_bytes()).hexdigest(), expected_hash)


if __name__ == "__main__":
    unittest.main()
