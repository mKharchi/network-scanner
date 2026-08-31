"""End-to-end integration tests for remote package deployment across real sockets."""

import base64
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import socket
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import MagicMock, patch
import zipfile

SERVER_DIRECTORY = Path(__file__).resolve().parents[1]
CLIENT_DIRECTORY = SERVER_DIRECTORY.parent / "client"
sys.path.insert(0, str(SERVER_DIRECTORY))
sys.path.insert(0, str(CLIENT_DIRECTORY))

try:
    import mysql.connector  # noqa: F401
except ModuleNotFoundError:
    mysql_module = types.ModuleType("mysql")
    mysql_module.connector = types.ModuleType("mysql.connector")
    sys.modules["mysql"] = mysql_module
    sys.modules["mysql.connector"] = mysql_module.connector

from server_components.action_framework import ActionState, ActionType  # noqa: E402
from server_components import action_service, server_lib  # noqa: E402
import client_lib  # noqa: E402


def _create_test_zip(content_bytes: bytes, inner_filename: str = "test.txt") -> bytes:
    buf = tempfile.NamedTemporaryFile("wb", suffix=".zip", delete=False)
    try:
        with zipfile.ZipFile(buf.name, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(inner_filename, content_bytes)
        return Path(buf.name).read_bytes()
    finally:
        Path(buf.name).unlink(missing_ok=True)


class PackageDeploymentE2ETests(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="pkg_e2e_"))
        self.client_staging_dir = self.test_dir / "client_updates" / "incoming"
        self.orig_client_dir = client_lib.PACKAGE_INCOMING_DIR
        client_lib.PACKAGE_INCOMING_DIR = self.client_staging_dir
        client_lib.ACTIVE_PACKAGE_SESSIONS.clear()

    def tearDown(self):
        client_lib.PACKAGE_INCOMING_DIR = self.orig_client_dir
        for session in list(client_lib.ACTIVE_PACKAGE_SESSIONS.values()):
            if session.get("file_handle") and not session["file_handle"].closed:
                session["file_handle"].close()
        client_lib.ACTIVE_PACKAGE_SESSIONS.clear()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _setup_connected_pair(self):
        """Create a real local TCP socket pair and wire up server/client reader threads."""
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]

        client_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_sock.connect(("127.0.0.1", port))
        server_conn, _ = listener.accept()
        listener.close()

        server_send_lock = threading.Lock()
        client_send_lock = threading.Lock()
        stop_event = threading.Event()

        # Register server client representation
        client_id = f"test-client-{int(time.time() * 1000)}"
        mac = "AA:BB:CC:11:22:33"
        server_client = {
            "client_id": client_id,
            "mac": mac,
            "hostname": "test-host",
            "connection": server_conn,
            "send_lock": server_send_lock,
            "responses": queue.Queue(),
            "registered_at": time.time(),
        }

        with server_lib.clients_lock:
            server_lib.clients[mac] = server_client

        # Client receive worker
        def client_reader():
            while not stop_event.is_set():
                try:
                    msg = client_lib.receive_message(client_sock, stop_event=stop_event, poll_interval=0.1)
                    if msg is None:
                        break
                    mtype = msg.get("type")
                    if mtype == "COMMAND":
                        cmd = msg.get("command")
                        result = client_lib.handle_command(msg)
                        with client_send_lock:
                            client_lib.send_message(client_sock, {"type": "RESPONSE", "command": cmd, "data": result})
                    elif mtype == "PACKAGE_CHUNK":
                        chunk_res = client_lib.process_package_chunk(msg)
                        if chunk_res:
                            with client_send_lock:
                                client_lib.send_message(client_sock, chunk_res)
                except Exception:
                    break

        # Server receive worker
        def server_reader():
            server_lib.receive_client_messages(mac, server_conn)

        client_thread = threading.Thread(target=client_reader, daemon=True)
        server_thread = threading.Thread(target=server_reader, daemon=True)
        client_thread.start()
        server_thread.start()

        return {
            "client_id": client_id,
            "mac": mac,
            "client_sock": client_sock,
            "server_conn": server_conn,
            "stop_event": stop_event,
            "client_thread": client_thread,
            "server_thread": server_thread,
        }

    def _cleanup_pair(self, env):
        env["stop_event"].set()
        try:
            env["client_sock"].close()
        except Exception:
            pass
        try:
            env["server_conn"].close()
        except Exception:
            pass
        with server_lib.clients_lock:
            server_lib.clients.pop(env["mac"], None)

    @patch("server_components.action_service.get_connection")
    def test_e2e_small_package_deployment(self, mock_get_conn):
        mock_get_conn.return_value = MagicMock()
        env = self._setup_connected_pair()
        try:
            test_content = b"Hello, remote package deployment! Testing Milestone B."
            zip_bytes = _create_test_zip(test_content)
            expected_hash = hashlib.sha256(zip_bytes).hexdigest()

            action = {
                "action_id": "act-e2e-small",
                "action_type": ActionType.DEPLOY_PACKAGE.value,
                "targets": [env["client_id"]],
                "parameters": {
                    "package_id": "pkg-small-v1",
                    "package_bytes": zip_bytes,
                    "chunk_size": 256,  # Force multiple chunks
                    "timeout": 10.0,
                },
            }

            res = action_service.execute_action(action)
            self.assertEqual(res["status"], ActionState.SUCCESS.value)

            # Independently check client received file on disk
            received_zip = self.client_staging_dir / "pkg-small-v1.zip"
            self.assertTrue(received_zip.exists())
            self.assertEqual(received_zip.read_bytes(), zip_bytes)
            self.assertEqual(hashlib.sha256(received_zip.read_bytes()).hexdigest(), expected_hash)

            # Check zip extraction independently
            with zipfile.ZipFile(received_zip, "r") as zf:
                self.assertEqual(zf.read("test.txt"), test_content)
        finally:
            self._cleanup_pair(env)

    @patch("server_components.action_service.get_connection")
    def test_e2e_large_multimegabyte_package_deployment(self, mock_get_conn):
        mock_get_conn.return_value = MagicMock()
        env = self._setup_connected_pair()
        try:
            # 5 MB of zip payload
            large_content = os.urandom(5 * 1024 * 1024)
            zip_bytes = _create_test_zip(large_content, inner_filename="large_data.bin")
            expected_hash = hashlib.sha256(zip_bytes).hexdigest()

            action = {
                "action_id": "act-e2e-large",
                "action_type": ActionType.DEPLOY_PACKAGE.value,
                "targets": [env["client_id"]],
                "parameters": {
                    "package_id": "pkg-large-v1",
                    "package_bytes": zip_bytes,
                    "chunk_size": 131072,  # 128KB chunks
                    "timeout": 20.0,
                },
            }

            res = action_service.execute_action(action)
            self.assertEqual(res["status"], ActionState.SUCCESS.value)

            received_zip = self.client_staging_dir / "pkg-large-v1.zip"
            self.assertTrue(received_zip.exists())
            self.assertEqual(received_zip.stat().st_size, len(zip_bytes))
            self.assertEqual(hashlib.sha256(received_zip.read_bytes()).hexdigest(), expected_hash)
        finally:
            self._cleanup_pair(env)

    @patch("server_components.action_service.get_connection")
    def test_e2e_interrupted_connection_fails_cleanly(self, mock_get_conn):
        mock_get_conn.return_value = MagicMock()
        env = self._setup_connected_pair()
        try:
            zip_bytes = _create_test_zip(b"Some payload")

            # Kill client socket immediately after init
            orig_process_chunk = client_lib.process_package_chunk
            def kill_on_chunk(msg):
                env["client_sock"].close()
                return orig_process_chunk(msg)

            with patch("client_lib.process_package_chunk", side_effect=kill_on_chunk):
                action = {
                    "action_id": "act-e2e-interrupt",
                    "action_type": ActionType.DEPLOY_PACKAGE.value,
                    "targets": [env["client_id"]],
                    "parameters": {
                        "package_id": "pkg-interrupted",
                        "package_bytes": zip_bytes,
                        "chunk_size": 32,
                        "timeout": 2.0,
                    },
                }
                res = action_service.execute_action(action)
                self.assertEqual(res["status"], ActionState.FAILED.value)

            # Confirm no valid .zip was written to client staging
            final_zip = self.client_staging_dir / "pkg-interrupted.zip"
            self.assertFalse(final_zip.exists())
        finally:
            self._cleanup_pair(env)


if __name__ == "__main__":
    unittest.main()
