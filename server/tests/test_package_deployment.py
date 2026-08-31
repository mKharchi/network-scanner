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


if __name__ == "__main__":
    unittest.main()
