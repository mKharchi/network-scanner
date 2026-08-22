"""Tests for one-client passive-neighbourhood command requests."""

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


SERVER_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIRECTORY))

try:
    import mysql.connector  # noqa: F401
except ModuleNotFoundError:
    mysql_module = types.ModuleType("mysql")
    mysql_module.connector = types.ModuleType("mysql.connector")
    sys.modules["mysql"] = mysql_module
    sys.modules["mysql.connector"] = mysql_module.connector

from server_components import server_lib  # noqa: E402


class PassiveNeighbourhoodRequestTests(unittest.TestCase):
    def test_request_returns_one_client_passive_snapshot(self):
        response_data = {
            "observed_at": "2026-08-22T10:10:00+00:00",
            "reporter": "AA:BB:CC:DD:EE:FF",
            "observations": [
                {
                    "protocol": "ssdp",
                    "observed_at": "2026-08-22T10:09:00+00:00",
                    "ip_address": "172.16.0.30",
                }
            ],
        }
        with patch.object(
            server_lib,
            "execute_client_command",
            return_value={"status": "ok", "data": response_data},
        ) as execute:
            result = server_lib.request_client_passive_neighbourhood(
                "client-a", timeout=4.0
            )

        execute.assert_called_once_with(
            "client-a",
            "GET_PASSIVE_NEIGHBOURHOOD",
            timeout=4.0,
            process_network_scan=False,
        )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["client_id"], "client-a")
        self.assertEqual(result["observation_count"], 1)
        self.assertEqual(result["observations"], response_data["observations"])
        self.assertEqual(result["reporter"], "AA:BB:CC:DD:EE:FF")

    def test_request_does_not_enter_network_device_or_global_collection_paths(self):
        response_data = {
            "observed_at": "2026-08-22T10:10:00+00:00",
            "reporter": "AA:BB:CC:DD:EE:FF",
            "observations": [],
        }
        with patch.object(
            server_lib,
            "execute_client_command",
            return_value={"status": "ok", "data": response_data},
        ), patch.object(
            server_lib, "handle_network_neighbour_report", side_effect=AssertionError
        ), patch.object(
            server_lib, "merge_and_broadcast_neighbourhood", side_effect=AssertionError
        ):
            result = server_lib.request_client_passive_neighbourhood(
                "client-a", timeout=4.0
            )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["observations"], [])

    def test_request_rejects_malformed_observations_without_storing_them(self):
        with patch.object(
            server_lib,
            "execute_client_command",
            return_value={
                "status": "ok",
                "data": {
                    "observed_at": "2026-08-22T10:10:00+00:00",
                    "reporter": "AA:BB:CC:DD:EE:FF",
                    "observations": [{"protocol": "unknown"}],
                },
            },
        ):
            result = server_lib.request_client_passive_neighbourhood(
                "client-a", timeout=4.0
            )

        self.assertEqual(result["status"], "client_error")
        self.assertIn("invalid passive neighbourhood", result["message"])

    def test_request_maps_timeout_without_touching_other_clients(self):
        with patch.object(
            server_lib,
            "execute_client_command",
            return_value={
                "status": "error",
                "message": "Command 'GET_PASSIVE_NEIGHBOURHOOD' timed out after 4.0s.",
            },
        ):
            result = server_lib.request_client_passive_neighbourhood(
                "client-a", timeout=4.0
            )

        self.assertEqual(result["status"], "client_timeout")
        self.assertEqual(result["client_id"], "client-a")
        self.assertEqual(result["timeout_seconds"], 4.0)


if __name__ == "__main__":
    unittest.main()
