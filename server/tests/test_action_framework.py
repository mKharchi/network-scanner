"""Tests for server-side action framework helpers and orchestration."""

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

from server_components.action_framework import (  # noqa: E402
    ActionState,
    ActionType,
    get_supported_client_commands,
    normalize_action_name,
)
from server_components.action_service import create_action, execute_action  # noqa: E402


def _connection(cursor):
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn


class ServerActionFrameworkTests(unittest.TestCase):
    def test_request_screenshot_alias_maps_to_canonical_action(self):
        self.assertEqual(normalize_action_name("REQUEST_SCREENSHOT"), ActionType.SCREENSHOT.value)

    def test_supported_client_commands_include_legacy_screenshot_command(self):
        commands = get_supported_client_commands()
        screenshot = next(item for item in commands if item["command"] == "REQUEST_SCREENSHOT")
        self.assertEqual(screenshot["action_type"], ActionType.SCREENSHOT.value)


class ActionOrchestrationTests(unittest.TestCase):
    @patch("server_components.action_service.get_connection")
    def test_create_action_inserts_one_action_and_one_target(self, get_connection):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [None, {"id": 11}]
        cursor.lastrowid = 101
        get_connection.return_value = _connection(cursor)

        action = create_action(
            ActionType.SHUTDOWN.value,
            ["PC-A"],
            parameters={"delay_seconds": 5},
            requested_by="admin",
            action_id="shutdown-a",
        )

        self.assertEqual(action["action_id"], "shutdown-a")
        self.assertEqual(action["action_type"], ActionType.SHUTDOWN.value)
        self.assertEqual(action["status"], ActionState.PENDING.value)
        self.assertEqual(action["targets"], ["PC-A"])
        inserts = [sql for sql, _params in (call.args for call in cursor.execute.call_args_list) if "INSERT INTO" in sql]
        self.assertEqual(len([sql for sql in inserts if "INSERT INTO actions" in sql]), 1)
        self.assertEqual(len([sql for sql in inserts if "INSERT INTO action_targets" in sql]), 1)

    @patch("server_components.action_service.get_connection")
    def test_create_action_bulk_inserts_three_targets_under_one_action(self, get_connection):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [None, {"id": 1}, {"id": 2}, {"id": 3}]
        cursor.lastrowid = 50
        get_connection.return_value = _connection(cursor)

        action = create_action(
            ActionType.SHUTDOWN.value,
            ["PC-A", "PC-B", "PC-C"],
            action_id="shutdown-bulk",
        )

        self.assertEqual(action["targets"], ["PC-A", "PC-B", "PC-C"])
        inserts = [sql for sql, _params in (call.args for call in cursor.execute.call_args_list) if "INSERT INTO" in sql]
        self.assertEqual(len([sql for sql in inserts if "INSERT INTO actions" in sql]), 1)
        self.assertEqual(len([sql for sql in inserts if "INSERT INTO action_targets" in sql]), 3)

    @patch("server_components.action_service.get_connection")
    def test_duplicate_action_id_returns_existing_row_without_insert(self, get_connection):
        existing = {
            "action_id": "shutdown-a",
            "action_type": ActionType.SHUTDOWN.value,
            "status": ActionState.SUCCESS.value,
            "parameters": "{}",
            "result": '{"targets": []}',
        }
        cursor = MagicMock()
        cursor.fetchone.return_value = existing
        get_connection.return_value = _connection(cursor)

        action = create_action(
            ActionType.SHUTDOWN.value,
            ["PC-A"],
            action_id="shutdown-a",
        )

        self.assertEqual(action["action_id"], "shutdown-a")
        self.assertEqual(action["status"], ActionState.SUCCESS.value)
        self.assertFalse(
            any("INSERT INTO" in (call.args[0] if call.args else "") for call in cursor.execute.call_args_list)
        )

    @patch("server_components.action_service.get_connection")
    @patch("server_components.action_service.server_lib.execute_client_command")
    def test_single_target_shutdown_succeeds(self, execute_command, get_connection):
        execute_command.return_value = {"status": "ok"}
        get_connection.return_value = _connection(MagicMock())

        result = execute_action({
            "action_id": "shutdown-a",
            "action_type": ActionType.SHUTDOWN.value,
            "targets": ["PC-A"],
            "parameters": {"delay_seconds": 5},
        })

        self.assertEqual(result["status"], ActionState.SUCCESS.value)
        self.assertEqual(len(result["result"]["targets"]), 1)
        self.assertEqual(result["result"]["targets"][0]["client_id"], "PC-A")
        self.assertEqual(result["result"]["targets"][0]["status"], ActionState.SUCCESS.value)
        execute_command.assert_called_once_with(
            "PC-A",
            ActionType.SHUTDOWN.value,
            {"delay_seconds": 5, "command_id": "shutdown-a"},
            timeout=12.0,
        )

    @patch("server_components.action_service.get_connection")
    @patch("server_components.action_service.server_lib.execute_client_command")
    def test_bulk_shutdown_dispatches_three_targets_as_one_action(self, execute_command, get_connection):
        execute_command.return_value = {"status": "ok"}
        get_connection.return_value = _connection(MagicMock())

        result = execute_action({
            "action_id": "shutdown-bulk",
            "action_type": ActionType.SHUTDOWN.value,
            "targets": ["PC-A", "PC-B", "PC-C"],
            "parameters": {},
        })

        self.assertEqual(result["status"], ActionState.SUCCESS.value)
        self.assertEqual(
            [item["client_id"] for item in result["result"]["targets"]],
            ["PC-A", "PC-B", "PC-C"],
        )
        self.assertEqual(execute_command.call_count, 3)

    @patch("server_components.action_service.get_connection")
    @patch("server_components.action_service.server_lib.execute_client_command")
    def test_partial_failure_marks_parent_partial_success(self, execute_command, get_connection):
        def _dispatch(client_id, *_args, **_kwargs):
            if client_id == "PC-A":
                return {"status": "ok"}
            if client_id == "PC-B":
                return {"status": "error", "message": "command failed"}
            return {"status": "error", "message": "Client is not connected."}

        execute_command.side_effect = _dispatch
        get_connection.return_value = _connection(MagicMock())

        result = execute_action({
            "action_id": "shutdown-partial",
            "action_type": ActionType.SHUTDOWN.value,
            "targets": ["PC-A", "PC-B", "PC-C"],
            "parameters": {},
        })

        statuses = {item["client_id"]: item["status"] for item in result["result"]["targets"]}
        self.assertEqual(result["status"], ActionState.PARTIAL_SUCCESS.value)
        self.assertEqual(statuses["PC-A"], ActionState.SUCCESS.value)
        self.assertEqual(statuses["PC-B"], ActionState.FAILED.value)
        self.assertEqual(statuses["PC-C"], ActionState.FAILED.value)

    @patch("server_components.action_service.record_client_health")
    @patch("server_components.action_service.get_connection")
    @patch("server_components.action_service.server_lib.execute_client_command")
    def test_refresh_health_persists_snapshot(self, execute_command, get_connection, record_health):
        snapshot = {"status": "ok", "health": {"cpu_percent": 11.0, "memory_percent": 22.0, "disk_percent": 33.0}}
        execute_command.return_value = snapshot
        get_connection.return_value = _connection(MagicMock())

        result = execute_action({
            "action_id": "health-1",
            "action_type": ActionType.REFRESH_HEALTH.value,
            "targets": ["PC-A"],
            "parameters": {},
        })

        self.assertEqual(result["status"], ActionState.SUCCESS.value)
        record_health.assert_called_once_with("PC-A", snapshot)


if __name__ == "__main__":
    unittest.main()
