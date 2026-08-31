"""Unit tests for server-side package deployment orchestration."""

import base64
import hashlib
import json
from pathlib import Path
import queue
import sys
import threading
import time
import types
import unittest
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

from server_components.action_framework import ActionState, ActionType  # noqa: E402
from server_components import action_service, server_lib  # noqa: E402
from api_server import LONG_RUNNING_ACTION_TYPES  # noqa: E402


def _connection(cursor=None):
    conn = MagicMock()
    conn.cursor.return_value = cursor or MagicMock()
    conn.is_connected.return_value = True
    return conn


class ServerPackageDeploymentTests(unittest.TestCase):
    def test_long_running_action_types_contains_deploy_package(self):
        self.assertIn("DEPLOY_PACKAGE", LONG_RUNNING_ACTION_TYPES)
        self.assertNotIn("GET_PROCESSES", LONG_RUNNING_ACTION_TYPES)
        self.assertNotIn("SCREENSHOT", LONG_RUNNING_ACTION_TYPES)
        self.assertNotIn("SHUTDOWN", LONG_RUNNING_ACTION_TYPES)

    @patch("server_components.action_service.get_connection")
    @patch("server_components.action_service.server_lib.get_client")
    @patch("server_components.action_service.server_lib.execute_client_command")
    @patch("server_components.action_service.server_lib.send_message")
    def test_deploy_package_success_flow(self, mock_send_message, mock_exec_cmd, mock_get_client, mock_get_conn):
        mock_get_conn.return_value = _connection()

        fake_conn = MagicMock()
        send_lock = threading.Lock()
        mock_get_client.return_value = {
            "client_id": "CLIENT-01",
            "mac": "AA:BB:CC:DD:EE:01",
            "connection": fake_conn,
            "send_lock": send_lock,
        }

        # Step 1: Mock DEPLOY_PACKAGE_INIT returning ready
        mock_exec_cmd.return_value = {
            "status": "ok",
            "data": {"status": "ready", "package_id": "pkg-test"},
        }

        payload = b"Package binary test content"
        expected_hash = hashlib.sha256(payload).hexdigest()

        # Simulate client sending back PACKAGE_RESULT when last chunk arrives
        def _send_side_effect(conn, frame):
            if frame.get("type") == "PACKAGE_CHUNK" and frame.get("seq") == frame.get("total_chunks"):
                # Deliver asynchronous PACKAGE_RESULT
                server_lib.handle_package_result(
                    "AA:BB:CC:DD:EE:01",
                    {
                        "type": "PACKAGE_RESULT",
                        "action_id": frame["action_id"],
                        "package_id": frame["package_id"],
                        "status": "SUCCESS",
                        "sha256": expected_hash,
                    },
                )

        mock_send_message.side_effect = _send_side_effect

        action = {
            "action_id": "act-deploy-01",
            "action_type": ActionType.DEPLOY_PACKAGE.value,
            "targets": ["CLIENT-01"],
            "parameters": {
                "package_id": "pkg-test",
                "package_bytes": payload,
                "chunk_size": 10,
                "timeout": 5.0,
            },
        }

        res = action_service.execute_action(action)

        self.assertEqual(res["status"], ActionState.SUCCESS.value)
        self.assertEqual(len(res["result"]["targets"]), 1)
        target_res = res["result"]["targets"][0]
        self.assertEqual(target_res["client_id"], "CLIENT-01")
        self.assertEqual(target_res["status"], ActionState.SUCCESS.value)

        # Confirm init was called with correct metadata
        mock_exec_cmd.assert_called_once()
        init_args = mock_exec_cmd.call_args[0][2]
        self.assertEqual(init_args["sha256"], expected_hash)
        self.assertEqual(init_args["total_size"], len(payload))
        self.assertEqual(init_args["total_chunks"], 3)

        # Confirm 3 chunk frames were sent over the socket
        self.assertEqual(mock_send_message.call_count, 3)

    @patch("server_components.action_service.get_connection")
    @patch("server_components.action_service.server_lib.get_client")
    @patch("server_components.action_service.server_lib.execute_client_command")
    def test_deploy_package_init_failure_stops_transfer(self, mock_exec_cmd, mock_get_client, mock_get_conn):
        mock_get_conn.return_value = _connection()
        mock_get_client.return_value = {
            "client_id": "CLIENT-01",
            "connection": MagicMock(),
            "send_lock": threading.Lock(),
        }

        mock_exec_cmd.return_value = {
            "status": "ok",
            "data": {"status": "error", "message": "Disk full"},
        }

        action = {
            "action_id": "act-fail-init",
            "action_type": ActionType.DEPLOY_PACKAGE.value,
            "targets": ["CLIENT-01"],
            "parameters": {
                "package_data_base64": base64.b64encode(b"Some content").decode("ascii"),
            },
        }

        res = action_service.execute_action(action)
        self.assertEqual(res["status"], ActionState.FAILED.value)
        self.assertIn("Disk full", str(res["result"]["targets"][0]["result"]))

    @patch("server_components.action_service.get_connection")
    def test_execute_action_sets_running_status_before_dispatch(self, mock_get_conn):
        cursor = MagicMock()
        mock_get_conn.return_value = _connection(cursor)

        action = {
            "action_id": "act-running-test",
            "action_type": ActionType.PING.value,
            "targets": [],
            "parameters": {},
        }

        action_service.execute_action(action)

        # Verify UPDATE actions SET status = 'RUNNING' was executed first
        running_update_calls = [
            call for call in cursor.execute.call_args_list
            if "status = %s" in call.args[0] and call.args[1][0] == ActionState.RUNNING.value
        ]
        self.assertTrue(len(running_update_calls) >= 1)

    def test_deploy_package_max_concurrent_constant(self):
        self.assertGreaterEqual(action_service.DEPLOY_PACKAGE_MAX_CONCURRENT, 1)
        self.assertLessEqual(action_service.DEPLOY_PACKAGE_MAX_CONCURRENT, 20)

    @patch("server_components.action_service.get_connection")
    @patch("server_components.action_service.deploy_package_to_client")
    def test_multi_client_deploy_concurrent_fan_out(self, mock_deploy, mock_get_conn):
        """All clients are dispatched concurrently; total wallclock ≈ single transfer time."""
        mock_get_conn.return_value = _connection()

        call_order = []
        call_lock = threading.Lock()

        def _slow_deploy(client_id, action_id, params):
            # Each "transfer" sleeps 0.05s — if sequential, 5 would take 0.25s
            time.sleep(0.05)
            with call_lock:
                call_order.append(client_id)
            return {"status": "ok", "package_id": "pkg-multi", "sha256": "abc", "file_path": "/tmp/pkg.zip"}

        mock_deploy.side_effect = _slow_deploy

        targets = ["client-1", "client-2", "client-3", "client-4", "client-5"]
        action = {
            "action_id": "act-multi",
            "action_type": ActionType.DEPLOY_PACKAGE.value,
            "targets": targets,
            "parameters": {"package_bytes": b"fakebytes", "package_id": "pkg-multi"},
        }

        start = time.monotonic()
        res = action_service.execute_action(action)
        elapsed = time.monotonic() - start

        # Concurrently: expect well under 5 × 0.05 = 0.25s sequential time
        self.assertLess(elapsed, 0.20, f"Fan-out too slow ({elapsed:.3f}s) — likely running sequentially")
        self.assertEqual(res["status"], ActionState.SUCCESS.value)
        self.assertEqual(len(res["result"]["targets"]), 5)
        self.assertEqual(sorted(t["client_id"] for t in res["result"]["targets"]), sorted(targets))
        self.assertEqual(mock_deploy.call_count, 5)

    @patch("server_components.action_service.get_connection")
    @patch("server_components.action_service.deploy_package_to_client")
    def test_multi_client_deploy_one_fails_others_succeed(self, mock_deploy, mock_get_conn):
        """One failing client doesn't prevent others from deploying; final status is PARTIAL_SUCCESS."""
        mock_get_conn.return_value = _connection()

        def _selective_deploy(client_id, action_id, params):
            if client_id == "client-bad":
                return {"status": "error", "message": "Disk full on client-bad"}
            return {"status": "ok", "package_id": "pkg-x", "sha256": "abc"}

        mock_deploy.side_effect = _selective_deploy

        action = {
            "action_id": "act-partial",
            "action_type": ActionType.DEPLOY_PACKAGE.value,
            "targets": ["client-good-1", "client-bad", "client-good-2"],
            "parameters": {"package_bytes": b"data", "package_id": "pkg-x"},
        }

        res = action_service.execute_action(action)

        self.assertEqual(res["status"], ActionState.PARTIAL_SUCCESS.value)
        statuses = {t["client_id"]: t["status"] for t in res["result"]["targets"]}
        self.assertEqual(statuses["client-good-1"], ActionState.SUCCESS.value)
        self.assertEqual(statuses["client-bad"], ActionState.FAILED.value)
        self.assertEqual(statuses["client-good-2"], ActionState.SUCCESS.value)

    @patch("server_components.action_service.get_connection")
    @patch("server_components.action_service.deploy_package_to_client")
    def test_throttle_cap_limits_concurrent_workers(self, mock_deploy, mock_get_conn):
        """Even with 10 targets, at most DEPLOY_PACKAGE_MAX_CONCURRENT run simultaneously."""
        mock_get_conn.return_value = _connection()

        concurrent_high_water = [0]
        current_running = [0]
        hwm_lock = threading.Lock()

        def _counting_deploy(client_id, action_id, params):
            with hwm_lock:
                current_running[0] += 1
                if current_running[0] > concurrent_high_water[0]:
                    concurrent_high_water[0] = current_running[0]
            time.sleep(0.02)
            with hwm_lock:
                current_running[0] -= 1
            return {"status": "ok", "package_id": "pkg-throttle", "sha256": "abc"}

        mock_deploy.side_effect = _counting_deploy

        targets = [f"client-{i}" for i in range(10)]
        action = {
            "action_id": "act-throttle",
            "action_type": ActionType.DEPLOY_PACKAGE.value,
            "targets": targets,
            "parameters": {"package_bytes": b"data", "package_id": "pkg-throttle"},
        }

        action_service.execute_action(action)

        self.assertLessEqual(
            concurrent_high_water[0],
            action_service.DEPLOY_PACKAGE_MAX_CONCURRENT,
            f"High-water mark {concurrent_high_water[0]} exceeded cap of {action_service.DEPLOY_PACKAGE_MAX_CONCURRENT}",
        )
        self.assertGreater(concurrent_high_water[0], 1, "Expected concurrent execution but ran sequentially")

    @patch("server_components.action_service.get_connection")
    @patch("server_components.action_service.server_lib.execute_client_command")
    def test_non_deploy_actions_unchanged_sequential_behavior(self, mock_exec_cmd, mock_get_conn):
        """GET_PROCESSES still dispatches sequentially and returns full results synchronously."""
        mock_get_conn.return_value = _connection()
        dispatch_order = []

        def _ordered_dispatch(client_id, *args, **kwargs):
            dispatch_order.append(client_id)
            return {"status": "ok", "processes": []}

        mock_exec_cmd.side_effect = _ordered_dispatch

        action = {
            "action_id": "act-get-procs",
            "action_type": ActionType.GET_PROCESSES.value,
            "targets": ["client-a", "client-b", "client-c"],
            "parameters": {},
        }

        res = action_service.execute_action(action)

        # Sequential: exactly in-order
        self.assertEqual(dispatch_order, ["client-a", "client-b", "client-c"])
        self.assertEqual(res["status"], ActionState.SUCCESS.value)


if __name__ == "__main__":
    unittest.main()
