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
        self.client_incoming_dir = self.test_dir / "client_updates" / "incoming"
        self.client_staging_dir = self.test_dir / "client_updates" / "staging"
        self.client_current_dir = self.test_dir / "client_updates" / "current"

        self.orig_incoming_dir = client_lib.PACKAGE_INCOMING_DIR
        self.orig_staging_dir = client_lib.PACKAGE_STAGING_DIR
        self.orig_current_dir = client_lib.PACKAGE_CURRENT_DIR

        client_lib.configure_package_paths(
            incoming=self.client_incoming_dir,
            staging=self.client_staging_dir,
            current=self.client_current_dir,
        )

    def tearDown(self):
        client_lib.reset_all_package_states()

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
            client_lib.configure_package_paths(
                incoming=self.client_incoming_dir,
                staging=self.client_staging_dir,
                current=self.client_current_dir,
            )
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

    def _spawn_client_with_dirs(self, label: str):
        """Create an isolated connected client with its own package staging directories."""
        client_dir = self.test_dir / label
        incoming = client_dir / "incoming"
        staging = client_dir / "staging"
        current = client_dir / "current"

        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)

        client_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_sock.connect(("127.0.0.1", listener.getsockname()[1]))
        server_conn, _ = listener.accept()
        listener.close()

        client_id = f"{label}-{int(time.time() * 1000)}"
        if not hasattr(self, "_client_spawn_counter"):
            self._client_spawn_counter = 0
        self._client_spawn_counter += 1
        mac = f"DD:EE:FF:00:00:{self._client_spawn_counter:02X}"
        stop_event = threading.Event()
        client_send_lock = threading.Lock()

        with server_lib.clients_lock:
            server_lib.clients[mac] = {
                "client_id": client_id,
                "mac": mac,
                "hostname": label,
                "connection": server_conn,
                "send_lock": threading.Lock(),
                "responses": queue.Queue(),
                "registered_at": time.time(),
            }

        def client_reader():
            client_lib.configure_package_paths(incoming=incoming, staging=staging, current=current)
            try:
                while not stop_event.is_set():
                    try:
                        msg = client_lib.receive_message(client_sock, stop_event=stop_event, poll_interval=0.05)
                        if msg is None:
                            break
                        mtype = msg.get("type")
                        if mtype == "COMMAND":
                            cmd = msg.get("command")
                            result = client_lib.handle_command(msg)
                            with client_send_lock:
                                client_lib.send_message(
                                    client_sock,
                                    {"type": "RESPONSE", "command": cmd, "data": result},
                                )
                        elif mtype == "PACKAGE_CHUNK":
                            chunk_res = client_lib.process_package_chunk(msg)
                            if chunk_res:
                                with client_send_lock:
                                    client_lib.send_message(client_sock, chunk_res)
                    except Exception:
                        break
            finally:
                pass

        client_thread = threading.Thread(target=client_reader, daemon=True)
        server_thread = threading.Thread(
            target=server_lib.receive_client_messages,
            args=(mac, server_conn),
            daemon=True,
        )
        client_thread.start()
        server_thread.start()

        return {
            "client_id": client_id,
            "mac": mac,
            "client_sock": client_sock,
            "server_conn": server_conn,
            "stop_event": stop_event,
            "current_dir": current,
        }

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
            received_zip = self.client_incoming_dir / "pkg-small-v1.zip"
            self.assertTrue(received_zip.exists())
            self.assertEqual(received_zip.read_bytes(), zip_bytes)
            self.assertEqual(hashlib.sha256(received_zip.read_bytes()).hexdigest(), expected_hash)

            # Confirm files landed in current deployed directory
            self.assertTrue((self.client_current_dir / "test.txt").exists())
            self.assertEqual((self.client_current_dir / "test.txt").read_bytes(), test_content)
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

            received_zip = self.client_incoming_dir / "pkg-large-v1.zip"
            self.assertTrue(received_zip.exists())
            self.assertEqual(received_zip.stat().st_size, len(zip_bytes))
            self.assertEqual(hashlib.sha256(received_zip.read_bytes()).hexdigest(), expected_hash)
            self.assertTrue((self.client_current_dir / "large_data.bin").exists())
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

            # Confirm no valid .zip was written to client incoming
            final_zip = self.client_incoming_dir / "pkg-interrupted.zip"
            self.assertFalse(final_zip.exists())
        finally:
            self._cleanup_pair(env)

    @patch("server_components.action_service.get_connection")
    def test_e2e_zip_slip_rejected_cleanly(self, mock_get_conn):
        mock_get_conn.return_value = MagicMock()
        env = self._setup_connected_pair()
        try:
            zip_bytes = _create_test_zip(b"evil content", inner_filename="../../evil.txt")
            action = {
                "action_id": "act-e2e-zipslip",
                "action_type": ActionType.DEPLOY_PACKAGE.value,
                "targets": [env["client_id"]],
                "parameters": {
                    "package_id": "pkg-evil",
                    "package_bytes": zip_bytes,
                    "chunk_size": 64,
                    "timeout": 5.0,
                },
            }
            res = action_service.execute_action(action)
            self.assertEqual(res["status"], ActionState.FAILED.value)
            self.assertIn("unsafe path in archive", str(res["result"]["targets"][0]["result"]).lower())
            self.assertFalse((self.test_dir / "evil.txt").exists())
            self.assertFalse(self.client_current_dir.exists())
        finally:
            self._cleanup_pair(env)

    @patch("server_components.action_service.get_connection")
    def test_e2e_multi_client_three_targets_independent_tracking(self, mock_get_conn):
        """Deploy to 3 clients simultaneously; each tracked independently."""
        mock_get_conn.return_value = MagicMock()

        # Set up 3 real socket pairs with separate staging dirs per client
        envs = []
        client_dirs = []
        macs_used = []
        try:
            for i in range(3):
                # Each client gets its own isolated PACKAGE_CURRENT_DIR
                client_dir = self.test_dir / f"client_{i}"
                client_dirs.append(client_dir)

                listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                listener.bind(("127.0.0.1", 0))
                listener.listen(1)

                client_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                client_sock.connect(("127.0.0.1", listener.getsockname()[1]))
                server_conn, _ = listener.accept()
                listener.close()

                mac = f"BB:CC:DD:EE:FF:{i:02X}"
                client_id = f"multi-client-{i}"
                stop_event = threading.Event()
                client_send_lock = threading.Lock()
                macs_used.append(mac)

                server_client = {
                    "client_id": client_id,
                    "mac": mac,
                    "hostname": f"host-{i}",
                    "connection": server_conn,
                    "send_lock": threading.Lock(),
                    "responses": queue.Queue(),
                    "registered_at": time.time(),
                }
                with server_lib.clients_lock:
                    server_lib.clients[mac] = server_client

                # Per-client dedicated staging dirs patched inline via closure
                incoming = client_dir / "incoming"
                staging = client_dir / "staging"
                current = client_dir / "current"

                def _make_reader(sock, stop_ev, send_lock, incoming_dir, staging_dir, current_dir):
                    def _client_reader():
                        client_lib.configure_package_paths(
                            incoming=incoming_dir,
                            staging=staging_dir,
                            current=current_dir,
                        )
                        try:
                            while not stop_ev.is_set():
                                try:
                                    msg = client_lib.receive_message(sock, stop_event=stop_ev, poll_interval=0.05)
                                    if msg is None:
                                        break
                                    mtype = msg.get("type")
                                    if mtype == "COMMAND":
                                        cmd = msg.get("command")
                                        result = client_lib.handle_command(msg)
                                        with send_lock:
                                            client_lib.send_message(sock, {"type": "RESPONSE", "command": cmd, "data": result})
                                    elif mtype == "PACKAGE_CHUNK":
                                        chunk_res = client_lib.process_package_chunk(msg)
                                        if chunk_res:
                                            with send_lock:
                                                client_lib.send_message(sock, chunk_res)
                                except Exception:
                                    break
                        finally:
                            pass
                    return _client_reader

                client_thread = threading.Thread(
                    target=_make_reader(client_sock, stop_event, client_send_lock, incoming, staging, current),
                    daemon=True,
                )
                server_thread = threading.Thread(
                    target=server_lib.receive_client_messages,
                    args=(mac, server_conn),
                    daemon=True,
                )
                client_thread.start()
                server_thread.start()

                envs.append({
                    "client_id": client_id,
                    "mac": mac,
                    "client_sock": client_sock,
                    "server_conn": server_conn,
                    "stop_event": stop_event,
                    "client_thread": client_thread,
                    "server_thread": server_thread,
                    "current_dir": current,
                })

            # One shared zip for all clients
            test_content = b"Multi-client deployment payload"
            zip_bytes = _create_test_zip(test_content, inner_filename="multi.txt")
            expected_hash = hashlib.sha256(zip_bytes).hexdigest()

            action = {
                "action_id": "act-multi-e2e",
                "action_type": ActionType.DEPLOY_PACKAGE.value,
                "targets": [e["client_id"] for e in envs],
                "parameters": {
                    "package_id": "pkg-multi-e2e",
                    "package_bytes": zip_bytes,
                    "chunk_size": 256,
                    "timeout": 15.0,
                },
            }

            res = action_service.execute_action(action)

            # All 3 clients should succeed
            self.assertEqual(res["status"], ActionState.SUCCESS.value)
            self.assertEqual(len(res["result"]["targets"]), 3)
            for target in res["result"]["targets"]:
                self.assertEqual(target["status"], ActionState.SUCCESS.value, f"{target['client_id']} failed: {target['result']}")

            # Each client received the file independently
            for env in envs:
                current = env["current_dir"]
                self.assertTrue((current / "multi.txt").exists(), f"{current} missing multi.txt")
                self.assertEqual((current / "multi.txt").read_bytes(), test_content)

        finally:
            for env in envs:
                env["stop_event"].set()
                try:
                    env["client_sock"].close()
                except Exception:
                    pass
                try:
                    env["server_conn"].close()
                except Exception:
                    pass
            for mac in macs_used:
                with server_lib.clients_lock:
                    server_lib.clients.pop(mac, None)

    @patch("server_components.action_service.get_connection")
    def test_e2e_multi_client_one_fails_others_succeed(self, mock_get_conn):
        """When one client drops mid-transfer, the others still succeed (PARTIAL_SUCCESS)."""
        mock_get_conn.return_value = MagicMock()
        envs = []
        macs_used = []
        try:
            zip_bytes = _create_test_zip(b"Partial failure test payload", inner_filename="data.txt")

            for i in range(3):
                client_dir = self.test_dir / f"partial_{i}"
                listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                listener.bind(("127.0.0.1", 0))
                listener.listen(1)
                client_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                client_sock.connect(("127.0.0.1", listener.getsockname()[1]))
                server_conn, _ = listener.accept()
                listener.close()

                mac = f"CC:DD:EE:FF:00:{i:02X}"
                client_id = f"partial-client-{i}"
                macs_used.append(mac)
                stop_event = threading.Event()
                client_send_lock = threading.Lock()

                with server_lib.clients_lock:
                    server_lib.clients[mac] = {
                        "client_id": client_id, "mac": mac, "hostname": f"host-p{i}",
                        "connection": server_conn, "send_lock": threading.Lock(),
                        "responses": queue.Queue(), "registered_at": time.time(),
                    }

                incoming = client_dir / "incoming"
                staging = client_dir / "staging"
                current = client_dir / "current"

                # Client 1 (i==1): abort the connection immediately on first chunk
                should_drop = (i == 1)

                def _make_reader(sock, stop_ev, send_lock, inc, stg, cur, drop):
                    def _client_reader():
                        client_lib.configure_package_paths(incoming=inc, staging=stg, current=cur)
                        first_chunk_seen = [False]
                        try:
                            while not stop_ev.is_set():
                                try:
                                    msg = client_lib.receive_message(sock, stop_event=stop_ev, poll_interval=0.05)
                                    if msg is None:
                                        break
                                    mtype = msg.get("type")
                                    if mtype == "COMMAND":
                                        cmd = msg.get("command")
                                        result = client_lib.handle_command(msg)
                                        with send_lock:
                                            client_lib.send_message(sock, {"type": "RESPONSE", "command": cmd, "data": result})
                                    elif mtype == "PACKAGE_CHUNK":
                                        if drop and not first_chunk_seen[0]:
                                            first_chunk_seen[0] = True
                                            sock.close()
                                            break
                                        chunk_res = client_lib.process_package_chunk(msg)
                                        if chunk_res:
                                            with send_lock:
                                                client_lib.send_message(sock, chunk_res)
                                except Exception:
                                    break
                        finally:
                            pass
                    return _client_reader

                client_thread = threading.Thread(target=_make_reader(client_sock, stop_event, client_send_lock, incoming, staging, current, should_drop), daemon=True)
                server_thread = threading.Thread(target=server_lib.receive_client_messages, args=(mac, server_conn), daemon=True)
                client_thread.start()
                server_thread.start()

                envs.append({"client_id": client_id, "mac": mac, "client_sock": client_sock, "server_conn": server_conn, "stop_event": stop_event, "current_dir": current, "should_fail": should_drop})

            action = {
                "action_id": "act-partial-e2e",
                "action_type": ActionType.DEPLOY_PACKAGE.value,
                "targets": [e["client_id"] for e in envs],
                "parameters": {"package_id": "pkg-partial", "package_bytes": zip_bytes, "chunk_size": 128, "timeout": 5.0},
            }

            res = action_service.execute_action(action)

            self.assertEqual(res["status"], ActionState.PARTIAL_SUCCESS.value)
            statuses = {t["client_id"]: t["status"] for t in res["result"]["targets"]}
            for env in envs:
                if env["should_fail"]:
                    self.assertEqual(statuses[env["client_id"]], ActionState.FAILED.value)
                else:
                    self.assertEqual(statuses[env["client_id"]], ActionState.SUCCESS.value)
                    self.assertTrue((env["current_dir"] / "data.txt").exists())

        finally:
            for env in envs:
                env["stop_event"].set()
                try:
                    env["client_sock"].close()
                except Exception:
                    pass
                try:
                    env["server_conn"].close()
                except Exception:
                    pass
            for mac in macs_used:
                with server_lib.clients_lock:
                    server_lib.clients.pop(mac, None)

    @patch("server_components.action_service.get_connection")
    def test_e2e_unrelated_client_stays_responsive_during_bulk_deploy(self, mock_get_conn):
        """Bulk deploy must not block command handling for clients not in the action."""
        mock_get_conn.return_value = MagicMock()
        deploy_envs = []
        control_env = None
        try:
            control_env = self._spawn_client_with_dirs("control")
            zip_bytes = _create_test_zip(b"x" * 65536, inner_filename="bulk.txt")

            for index in range(3):
                deploy_envs.append(self._spawn_client_with_dirs(f"deploy-{index}"))

            deploy_result = [None]
            deploy_done = threading.Event()

            def _run_deploy():
                deploy_result[0] = action_service.execute_action(
                    {
                        "action_id": "act-bulk-heartbeat",
                        "action_type": ActionType.DEPLOY_PACKAGE.value,
                        "targets": [env["client_id"] for env in deploy_envs],
                        "parameters": {
                            "package_id": "pkg-bulk",
                            "package_bytes": zip_bytes,
                            "chunk_size": 512,
                            "timeout": 30.0,
                        },
                    }
                )
                deploy_done.set()

            deploy_thread = threading.Thread(target=_run_deploy, daemon=True)
            deploy_thread.start()
            time.sleep(0.1)

            start = time.monotonic()
            ping_res = server_lib.execute_client_command(
                control_env["client_id"],
                "PING",
                {"command_id": "ping-during-deploy"},
                timeout=2.0,
            )
            ping_elapsed = time.monotonic() - start

            self.assertLess(
                ping_elapsed,
                1.5,
                f"Unrelated client PING took {ping_elapsed:.3f}s during bulk deploy",
            )
            self.assertEqual(ping_res.get("status"), "ok")

            deploy_done.wait(timeout=30)
            self.assertTrue(deploy_done.is_set(), "Bulk deploy did not finish in time")
            self.assertEqual(deploy_result[0]["status"], ActionState.SUCCESS.value)
            for env in deploy_envs:
                self.assertTrue((env["current_dir"] / "bulk.txt").exists())
        finally:
            for env in deploy_envs + ([control_env] if control_env else []):
                self._cleanup_pair(env)


if __name__ == "__main__":
    unittest.main()

