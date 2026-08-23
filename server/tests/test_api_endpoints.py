"""Unit and integration tests for Network Monitoring REST API endpoints."""

import json
import sys
import threading
import types
import unittest
import urllib.request
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

from api_server import run_api_server
from server_components import api_service, server_lib


class ApiEndpointsTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Bind to port 0 to get an OS-assigned free ephemeral port
        cls.httpd = run_api_server(host="127.0.0.1", port=0)
        cls.port = cls.httpd.server_address[1]
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def _fetch(self, path: str):
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(req) as resp:
                status = resp.status
                body = json.loads(resp.read().decode("utf-8"))
                return status, body
        except urllib.error.HTTPError as e:
            status = e.code
            body = json.loads(e.read().decode("utf-8"))
            return status, body

    # 1. Health check
    def test_health_check(self):
        status, body = self._fetch("/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["data"]["status"], "ok")

    # 2. Dashboard
    @patch("server_components.api_service.get_connection")
    def test_dashboard_endpoint(self, mock_db):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        # Mock total clients & alerts
        mock_cursor.fetchone.side_effect = [
            {"total": 2},  # clients count
            {"total_new": 1, "total_critical": 0},  # alerts count
        ]
        mock_cursor.fetchall.return_value = []

        status, body = self._fetch("/api/v1/dashboard")
        self.assertEqual(status, 200)
        self.assertIn("data", body)
        self.assertIn("clients", body["data"])
        self.assertIn("alerts", body["data"])
        self.assertIn("generated_at", body["data"])

    # 3. Clients list & detail
    @patch("server_components.api_service.get_connection")
    def test_clients_list_endpoint(self, mock_db):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        mock_cursor.fetchall.return_value = [
            {
                "id": 1,
                "client_id": "client-1234567890ab",
                "mac": "12-34-56-78-90-AB",
                "hostname": "TEST-HOST",
                "ip": "192.168.1.50",
                "os_system": "Linux",
                "os_release": "6.8.0",
                "os_version": "#1",
                "os_machine": "x86_64",
                "created_at": None,
                "updated_at": None,
            }
        ]

        status, body = self._fetch("/api/v1/clients")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["data"]["items"]), 1)
        self.assertEqual(body["data"]["items"][0]["mac_address"], "12:34:56:78:90:AB")
        self.assertEqual(body["data"]["items"][0]["hostname"], "TEST-HOST")

    @patch("server_components.api_service.get_connection")
    def test_client_detail_not_found(self, mock_db):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None

        status, body = self._fetch("/api/v1/clients/non-existent-client")
        self.assertEqual(status, 404)
        self.assertEqual(body["error"]["code"], "NOT_FOUND")

    @patch("server_components.api_service.get_connection")
    def test_clients_list_and_detail_isolated_state(self, mock_db):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        row = {
            "id": 1,
            "client_id": "client-isolated-1",
            "mac": "12-34-56-78-90-AB",
            "hostname": "ISOLATED-HOST",
            "ip": "192.168.1.50",
            "os_system": "Windows",
            "os_release": "10",
            "os_version": "10.0.19041",
            "os_machine": "AMD64",
            "created_at": None,
            "updated_at": None,
        }
        mock_cursor.fetchall.side_effect = [
            [row],  # for list_clients
            [],     # for connections query in get_client_detail
            [],     # for activity logs in get_client_detail
        ]
        mock_cursor.fetchone.side_effect = [
            row,                           # 1. for get_client_detail main client query
            {"total": 0, "total_new": 0},  # 2. for alert_counts query
            None,                          # 3. for latest_activity_log query
        ]

        with patch.dict(
            "server_components.server_lib.device_isolation_status",
            {
                "client-isolated-1": {
                    "status": "CONNECTION_LOST_AFTER_ISOLATION",
                    "reason": "Repeated forbidden process execution",
                    "sent_at": "2026-08-23T14:20:00Z",
                    "updated_at": "2026-08-23T14:20:32Z",
                }
            },
        ):
            status, body = self._fetch("/api/v1/clients")
            self.assertEqual(status, 200)
            client_item = body["data"]["items"][0]
            self.assertEqual(client_item["connection"]["state"], "ISOLATED")
            self.assertEqual(
                client_item["connection"]["isolation"]["status"],
                "CONNECTION_LOST_AFTER_ISOLATION",
            )
            self.assertEqual(
                client_item["connection"]["isolation"]["reason"],
                "Repeated forbidden process execution",
            )

            status, body = self._fetch("/api/v1/clients/client-isolated-1")
            self.assertEqual(status, 200)
            self.assertEqual(
                body["data"]["client"]["connection"]["state"], "ISOLATED"
            )
            self.assertEqual(
                body["data"]["client"]["connection"]["isolation"]["reason"],
                "Repeated forbidden process execution",
            )

    # 4. Network Scans
    def test_latest_scan_empty(self):
        status, body = self._fetch("/api/v1/network/scans/latest")
        self.assertEqual(status, 200)
        self.assertIn("scan", body["data"])

    def test_scan_history(self):
        status, body = self._fetch("/api/v1/network/scans")
        self.assertEqual(status, 200)
        self.assertIn("items", body["data"])

    # 5. Network Devices
    @patch("server_components.api_service.get_connection")
    def test_network_devices_list_endpoint(self, mock_db):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = {"total": 1}
        mock_cursor.fetchall.return_value = [
            {
                "mac_address": "AA:BB:CC:DD:EE:FF",
                "ip_address": "192.168.1.50",
                "hostname": "DEVICE-1",
                "vendor": "TestVendor",
                "first_seen": "2026-08-20T10:00:00Z",
                "last_seen": "2026-08-22T12:00:00Z",
                "managed_client_id": "client-1",
                "client_hostname": "DEVICE-1",
            }
        ]

        status, body = self._fetch("/api/v1/network/devices")
        self.assertEqual(status, 200)
        self.assertIn("devices", body["data"])
        self.assertEqual(len(body["data"]["devices"]), 1)
        self.assertEqual(body["data"]["devices"][0]["mac_address"], "AA:BB:CC:DD:EE:FF")
        self.assertTrue(body["data"]["devices"][0]["is_managed"])

    @patch("server_components.api_service.get_connection")
    def test_device_detail_not_found(self, mock_db):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None

        status, body = self._fetch("/api/v1/network/devices/AA:BB:CC:DD:EE:FF")
        self.assertEqual(status, 404)
        self.assertEqual(body["error"]["code"], "NOT_FOUND")

    # 6. DHCP
    def test_dhcp_activity_endpoint(self):
        status, body = self._fetch("/api/v1/network/dhcp?date=2026-08-18")
        self.assertEqual(status, 200)
        self.assertEqual(body["data"]["date"], "2026-08-18")
        self.assertIsInstance(body["data"]["items"], list)

    # 7. Alerts list & detail
    @patch("server_components.api_service.get_connection")
    def test_alerts_list_endpoint(self, mock_db):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            {
                "id": 42,
                "client_id": "client-123",
                "hostname": "HOST-1",
                "alert_type": "FORBIDDEN_PROCESS",
                "severity": "HIGH",
                "status": "NEW",
                "detected_at": None,
                "activity_time": None,
                "title": "Forbidden App",
                "description": "Discord running",
                "log_id": 5,
            }
        ]

        status, body = self._fetch("/api/v1/alerts?status=NEW")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["data"]["items"]), 1)
        self.assertEqual(body["data"]["items"][0]["severity"], "HIGH")

    # 8. Activity logs
    @patch("server_components.api_service.get_connection")
    def test_activity_logs_list(self, mock_db):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []

        status, body = self._fetch("/api/v1/activity-logs")
        self.assertEqual(status, 200)
        self.assertEqual(body["data"]["items"], [])

    # 9. Settings: working hours & forbidden processes
    @patch("server_components.api_service.get_connection")
    def test_settings_working_hours(self, mock_db):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            {
                "day_of_week": 0,
                "start_time": "09:30:00",
                "end_time": "18:00:00",
                "enabled": 1,
            }
        ]

        status, body = self._fetch("/api/v1/settings/working-hours")
        self.assertEqual(status, 200)
        self.assertIn("rules", body["data"])
        self.assertIn("current_status", body["data"])

    @patch("server_components.api_service.get_connection")
    def test_settings_forbidden_processes(self, mock_db):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            {
                "process_name": "discord",
                "severity": "HIGH",
                "enabled": 1,
                "description": "Unauthorized communication client",
            }
        ]

        status, body = self._fetch("/api/v1/settings/forbidden-processes")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["data"]["items"]), 1)
        self.assertEqual(body["data"]["items"][0]["process_name"], "discord")

    # 10. Real-time SSE Events
    def test_sse_events_handshake(self):
        url = f"{self.base_url}/api/v1/events"
        req = urllib.request.Request(url, headers={"Accept": "text/event-stream"})
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.headers.get("Content-Type"), "text/event-stream; charset=utf-8")
            # Read first line (: connected\n\n)
            first_line = resp.readline().decode("utf-8")
            self.assertTrue(first_line.startswith(":") or first_line.startswith("event:"))

    # 11. Client commands POST
    @patch("server_components.server_lib.execute_client_command")
    def test_post_client_command(self, mock_exec):
        mock_exec.return_value = {"status": "ok", "command": "GET_PROCESSES", "data": []}
        url = f"{self.base_url}/api/v1/clients/client-123/commands"
        payload = json.dumps({"command": "GET_PROCESSES"}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            body = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(body["data"]["status"], "ok")

    @patch("server_components.server_lib.request_client_network_neighbourhood")
    def test_post_client_neighbourhood_request(self, request_neighbourhood):
        request_neighbourhood.return_value = {
            "status": "completed",
            "client_id": "client-123",
            "observations_sent": 2,
            "timeout_seconds": 12.0,
        }
        req = urllib.request.Request(
            f"{self.base_url}/api/v1/clients/client-123/network-neighbourhood",
            data=b"{}",
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            body = json.loads(resp.read().decode("utf-8"))

        self.assertEqual(body["data"]["observations_sent"], 2)
        request_neighbourhood.assert_called_once_with("client-123")

    @patch("server_components.server_lib.request_client_network_neighbourhood")
    def test_post_client_neighbourhood_request_returns_controlled_timeout(self, request_neighbourhood):
        request_neighbourhood.return_value = {
            "status": "client_timeout",
            "client_id": "client-123",
            "message": "Command timed out after 12.0s.",
        }
        req = urllib.request.Request(
            f"{self.base_url}/api/v1/clients/client-123/network-neighbourhood",
            data=b"{}",
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(req)

        self.assertEqual(error.exception.code, 504)
        body = json.loads(error.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "CLIENT_TIMEOUT")

    @patch("server_components.server_lib.request_client_passive_neighbourhood")
    def test_post_client_passive_neighbourhood_request(self, request_passive_neighbourhood):
        request_passive_neighbourhood.return_value = {
            "status": "completed",
            "client_id": "client-123",
            "timeout_seconds": 10.0,
            "observed_at": "2026-08-22T10:10:00+00:00",
            "reporter": "AA:BB:CC:DD:EE:FF",
            "observations": [{"protocol": "mdns", "hostname": "printer.local"}],
            "observation_count": 1,
        }
        req = urllib.request.Request(
            f"{self.base_url}/api/v1/clients/client-123/passive-neighbourhood",
            data=b"{}",
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            body = json.loads(resp.read().decode("utf-8"))

        self.assertEqual(body["data"]["observation_count"], 1)
        self.assertEqual(body["data"]["observations"][0]["protocol"], "mdns")
        request_passive_neighbourhood.assert_called_once_with("client-123")

    @patch("server_components.server_lib.request_client_passive_neighbourhood")
    def test_post_client_passive_neighbourhood_request_returns_controlled_errors(self, request_passive_neighbourhood):
        request_passive_neighbourhood.return_value = {
            "status": "client_unavailable",
            "client_id": "client-123",
            "message": "Client 'client-123' is not connected.",
        }
        req = urllib.request.Request(
            f"{self.base_url}/api/v1/clients/client-123/passive-neighbourhood",
            data=b"{}",
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(req)

        self.assertEqual(error.exception.code, 409)
        body = json.loads(error.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "CLIENT_UNAVAILABLE")

    @patch("server_components.network_discovery.run_global_neighbourhood_collection")
    def test_global_neighbourhood_collection_endpoints(self, start_collection):
        collection = {
            "id": "neighbourhood-test",
            "status": "pending",
            "clients_requested": 2,
            "clients_succeeded": 0,
            "clients_failed": 0,
            "clients_timed_out": 0,
            "devices_discovered": 0,
            "buckets_completed": 0,
        }
        start_collection.return_value = (collection, True)
        req = urllib.request.Request(
            f"{self.base_url}/api/v1/network/neighbourhood/collections",
            data=b"{}",
            method="POST",
        )
        with urllib.request.urlopen(req) as response:
            self.assertEqual(response.status, 202)
            body = json.loads(response.read().decode("utf-8"))

        self.assertEqual(body["data"]["id"], "neighbourhood-test")
        self.assertEqual(body["data"]["status"], "started")

        with patch(
            "server_components.global_network_scan.global_neighbourhood_collection_manager.get",
            return_value={**collection, "status": "completed", "devices_discovered": 3},
        ):
            status, body = self._fetch(
                "/api/v1/network/neighbourhood/collections/neighbourhood-test"
            )

        self.assertEqual(status, 200)
        self.assertEqual(body["data"]["status"], "completed")
        self.assertEqual(body["data"]["devices_discovered"], 3)

    def test_post_global_active_scan_is_disabled(self):
        url = f"{self.base_url}/api/v1/network/scans/global-active"
        req = urllib.request.Request(url, data=b"{}", method="POST")

        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(req)

        self.assertEqual(error.exception.code, 409)
        body = json.loads(error.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "ACTIVE_NETWORK_SCAN_DISABLED")

    def test_active_scan_routes_are_disabled(self):
        requests = [
            urllib.request.Request(
                f"{self.base_url}/api/v1/clients/client-123/commands",
                data=json.dumps({"command": "SCAN_NETWORK"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            ),
            urllib.request.Request(
                f"{self.base_url}/api/v1/network/scans/active",
                data=b"{}",
                method="POST",
            ),
        ]

    @patch("server_components.server_lib.quarantine_client")
    def test_post_client_quarantine_endpoint(self, mock_quarantine):
        mock_quarantine.return_value = {
            "status": "ok",
            "state": "QUARANTINED",
            "message": "Endpoint successfully quarantined.",
        }
        url = f"{self.base_url}/api/v1/clients/client-test-1/quarantine"
        payload = json.dumps({"reason": "Repeated violations", "duration_minutes": 30}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")

        with urllib.request.urlopen(req) as resp:
            status = resp.status
            body = json.loads(resp.read().decode("utf-8"))

        self.assertEqual(status, 200)
        self.assertEqual(body["data"]["status"], "ok")
        self.assertEqual(body["data"]["state"], "QUARANTINED")
        mock_quarantine.assert_called_once_with("client-test-1", reason="Repeated violations", duration_minutes=30)

    @patch("server_components.server_lib.release_client_quarantine")
    def test_post_client_release_quarantine_endpoint(self, mock_release):
        mock_release.return_value = {
            "status": "ok",
            "state": "NORMAL",
            "message": "Quarantine released and normal network access restored.",
        }
        url = f"{self.base_url}/api/v1/clients/client-test-1/release-quarantine"
        payload = json.dumps({"reason": "Admin approval"}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")

        with urllib.request.urlopen(req) as resp:
            status = resp.status
            body = json.loads(resp.read().decode("utf-8"))

        self.assertEqual(status, 200)
        self.assertEqual(body["data"]["status"], "ok")
        self.assertEqual(body["data"]["state"], "NORMAL")
        mock_release.assert_called_once_with("client-test-1", reason="Admin approval")

    @patch("server_components.server_lib.get_client_quarantine_status")
    def test_get_client_quarantine_status_endpoint(self, mock_status):
        mock_status.return_value = {
            "status": "ok",
            "data": {
                "state": "QUARANTINED",
                "is_quarantined": True,
                "reason": "Test reason",
            },
        }
        status, body = self._fetch("/api/v1/clients/client-test-1/quarantine")
        self.assertEqual(status, 200)
        self.assertEqual(body["data"]["state"], "QUARANTINED")
        self.assertTrue(body["data"]["is_quarantined"])

    @patch("server_components.server_lib.isolate_client")
    def test_post_client_isolation_endpoint(self, mock_isolate):
        mock_isolate.return_value = {
            "status": "ok",
            "isolation_status": "CONNECTION_LOST_AFTER_ISOLATION",
        }
        url = f"{self.base_url}/api/v1/clients/client-test-1/isolation"
        payload = json.dumps({"reason": "Controlled response"}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")

        with urllib.request.urlopen(req) as resp:
            status = resp.status
            body = json.loads(resp.read().decode("utf-8"))

        self.assertEqual(status, 200)
        self.assertEqual(body["data"]["isolation_status"], "CONNECTION_LOST_AFTER_ISOLATION")
        mock_isolate.assert_called_once_with("client-test-1", reason="Controlled response")

    @patch("server_components.server_lib.get_device_isolation_status")
    def test_get_client_isolation_status_endpoint(self, mock_status):
        mock_status.return_value = {
            "status": "ok",
            "data": {"status": "CONNECTION_LOST_AFTER_ISOLATION"},
        }

        status, body = self._fetch("/api/v1/clients/client-test-1/isolation")

        self.assertEqual(status, 200)
        self.assertEqual(body["data"]["status"], "CONNECTION_LOST_AFTER_ISOLATION")


if __name__ == "__main__":
    unittest.main()
