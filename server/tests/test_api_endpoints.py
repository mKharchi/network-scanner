"""Unit and integration tests for Network Monitoring REST API endpoints."""

import json
import sys
import threading
import types
import unittest
import tempfile
import urllib.error
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

    def _fetch_raw(self, path: str):
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url, headers={"Accept": "*/*"})
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    @patch("server_components.api_service.get_client_localization_debug")
    def test_client_localization_debug_endpoint(self, get_debug):
        get_debug.return_value = {
            "client": {"client_id": "client-a", "hostname": "PC-A", "mac": "AA:BB", "ip": "192.168.1.20"},
            "location": {"id": 42, "label": "F1-A1-T1-C1-P1", "floor": 1},
            "server_coordinates": {"x": 8.5, "y": 6.5, "z": 3.0},
            "coordinate_system": {"name": "center-layout-v1"},
            "render_coordinates": None,
            "transformation": {"name": "digital-twin-isometric-projection"},
            "last_updated": "2026-08-26T10:00:00+00:00",
        }
        status, body = self._fetch("/api/v1/debug/clients/client-a/localization")
        self.assertEqual(status, 200)
        self.assertEqual(body["data"]["client"]["client_id"], "client-a")
        self.assertEqual(body["data"]["server_coordinates"]["z"], 3.0)

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
            {"total_unassigned": 0},
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

        mock_cursor.fetchall.side_effect = [
            [
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
                    "health_cpu_percent": None,
                    "health_memory_percent": None,
                    "health_disk_percent": None,
                    "health_updated_at": None,
                    "location_id": None,
                }
            ],
            [],  # open alerts
        ]

        status, body = self._fetch("/api/v1/clients")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["data"]["items"]), 1)
        self.assertEqual(body["data"]["items"][0]["mac_address"], "12:34:56:78:90:AB")
        self.assertEqual(body["data"]["items"][0]["hostname"], "TEST-HOST")

    @patch("server_components.api_service.list_clients")
    def test_clients_list_unassigned_filter(self, list_clients):
        list_clients.return_value = []

        status, body = self._fetch("/api/v1/clients?location=unassigned")

        self.assertEqual(status, 200)
        self.assertEqual(body["data"]["items"], [])
        list_clients.assert_called_once_with(
            state_filter=None,
            search=None,
            limit=50,
            location_filter="unassigned",
        )

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
            [],     # open alerts for list_clients
            [],     # open alerts for get_client_detail
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

    @patch("server_components.api_service.get_connection")
    def test_client_screenshots_list_endpoint(self, mock_db):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_db.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.side_effect = [
            {"id": 1},
        ]
        mock_cursor.fetchall.return_value = [
            {
                "id": 7,
                "command_id": "screenshot-1",
                "requested_by": "operator",
                "filename": "DESKTOP-ABC.png",
                "mime_type": "image/png",
                "file_size": 2048,
                "device_name": "DESKTOP-ABC",
                "captured_at": "2026-08-23T15:00:00+00:00",
                "uploaded_at": "2026-08-23T15:01:00+00:00",
                "status": "UPLOADED",
            }
        ]

        status, body = self._fetch("/api/v1/clients/client-123/screenshots?limit=1")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["data"]["items"]), 1)
        self.assertEqual(body["data"]["items"][0]["filename"], "DESKTOP-ABC.png")
        self.assertEqual(body["data"]["items"][0]["client_id"], "client-123")

    def test_screenshot_file_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            file_path = Path(directory) / "shot.png"
            payload = b"fake-png-bytes"
            file_path.write_bytes(payload)

            with patch.object(
                api_service,
                "get_screenshot_record",
                return_value={
                    "id": 9,
                    "client_id": "client-123",
                    "filename": "shot.png",
                    "storage_path": str(file_path),
                    "mime_type": "image/png",
                    "file_size": len(payload),
                    "device_name": "DESKTOP-ABC",
                    "captured_at": "2026-08-23T15:00:00+00:00",
                    "uploaded_at": "2026-08-23T15:01:00+00:00",
                    "status": "UPLOADED",
                },
            ):
                status, headers, body = self._fetch_raw("/api/v1/screenshots/9/file")

        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Type"), "image/png")
        self.assertEqual(body, payload)

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

    @patch("server_components.action_service.execute_action")
    @patch("server_components.action_service.create_action")
    @patch("server_components.action_service.get_action", return_value=None)
    def test_create_unified_action(self, get_action, create_action, execute_action):
        create_action.return_value = {
            "action_id": "action-1",
            "action_type": "PING",
            "status": "PENDING",
            "targets": ["client-a", "client-b"],
        }
        execute_action.return_value = {
            **create_action.return_value,
            "status": "PARTIAL_SUCCESS",
            "result": {"targets": []},
        }
        payload = json.dumps({
            "action_type": "PING",
            "targets": ["client-a", "client-b"],
            "action_id": "action-1",
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/actions",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 201)
            body = json.loads(resp.read().decode("utf-8"))
        self.assertEqual(body["data"]["status"], "PARTIAL_SUCCESS")
        create_action.assert_called_once()
        execute_action.assert_called_once()

    @patch("server_components.action_service.get_action", return_value=None)
    @patch("server_components.action_service.create_action")
    @patch("server_components.action_service.execute_action")
    def test_post_deploy_package_action_is_asynchronous(self, execute_action, create_action, get_action):
        create_action.return_value = {
            "action_id": "pkg-action-1",
            "action_type": "DEPLOY_PACKAGE",
            "status": "PENDING",
            "targets": ["client-a"],
            "parameters": {"package_id": "v1"},
        }
        payload = json.dumps({
            "action_type": "DEPLOY_PACKAGE",
            "targets": ["client-a"],
            "action_id": "pkg-action-1",
            "parameters": {"package_id": "v1"},
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/actions",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 201)
            body = json.loads(resp.read().decode("utf-8"))
        # Immediately returns HTTP 201 with status PENDING
        self.assertEqual(body["data"]["status"], "PENDING")
        self.assertEqual(body["data"]["action_type"], "DEPLOY_PACKAGE")
        create_action.assert_called_once()

    @patch("server_components.action_service.get_action")
    def test_replaying_unified_action_is_idempotent(self, get_action):
        get_action.return_value = {
            "action_id": "action-1",
            "action_type": "PING",
            "status": "SUCCESS",
            "targets": [],
        }
        payload = json.dumps({"action_type": "PING", "targets": ["client-a"], "action_id": "action-1"}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/actions",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            body = json.loads(resp.read().decode("utf-8"))
        self.assertEqual(body["data"]["status"], "SUCCESS")
        get_action.assert_called_once_with("action-1")

    @patch("server_components.server_lib.request_client_screenshot")
    def test_screenshot_endpoint_requests_interactive_capture(self, request_screenshot):
        request_screenshot.return_value = {
            "status": "completed",
            "client_id": "client-a",
            "filename": "capture.png",
        }
        req = urllib.request.Request(
            f"{self.base_url}/api/v1/clients/client-a/screenshot",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            body = json.loads(resp.read().decode("utf-8"))
        self.assertEqual(body["data"]["filename"], "capture.png")
        request_screenshot.assert_called_once_with(
            "client-a", requested_by="local-network-operator"
        )

    @patch("server_components.api_service.list_locations")
    def test_list_locations_endpoint(self, list_locations):
        list_locations.return_value = [{"id": 1, "floor": 1, "label": "F1-A1-T1-P1"}]

        status, body = self._fetch("/api/locations")

        self.assertEqual(status, 200)
        self.assertEqual(body["data"]["items"][0]["label"], "F1-A1-T1-P1")

    @patch("server_components.api_service.create_location")
    def test_create_location_endpoint(self, create_location):
        create_location.return_value = {
            "id": 7,
            "floor": 1,
            "zone_type": "training",
            "label": "F1-A1-T1-P2",
        }
        payload = json.dumps({
            "floor": 1,
            "zone_type": "training",
            "label": "F1-A1-T1-P2",
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/locations",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 201)
            body = json.loads(resp.read().decode("utf-8"))

        self.assertEqual(body["data"]["label"], "F1-A1-T1-P2")
        create_location.assert_called_once_with({
            "floor": 1,
            "zone_type": "training",
            "label": "F1-A1-T1-P2",
        })

    @patch("server_components.action_service.execute_action")
    @patch("server_components.action_service.create_action")
    @patch("server_components.api_service.assign_client_location")
    def test_assign_client_location_endpoint(self, assign_location, create_action, execute_action):
        assign_location.return_value = {
            "id": 4,
            "floor": 1,
            "zone_type": "training",
            "label": "F1-A1-T1-P1",
            "client_id": "client-a",
        }
        create_action.return_value = {"action_id": "location-sync-1", "status": "PENDING"}
        execute_action.return_value = {"action_id": "location-sync-1", "status": "SUCCESS"}
        payload = json.dumps({"location_id": 4}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/clients/client-a/location",
            data=payload,
            headers={"Content-Type": "application/json", "X-Operator-Id": "admin"},
            method="PATCH",
        )

        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            body = json.loads(resp.read().decode("utf-8"))

        self.assertEqual(body["data"]["location"]["client_id"], "client-a")
        self.assertEqual(body["data"]["location_sync"]["status"], "SUCCESS")
        assign_location.assert_called_once_with("client-a", 4, assigned_by="admin")
        create_action.assert_called_once()
        self.assertEqual(create_action.call_args[0][0], "UPDATE_LOCATION")
        self.assertEqual(create_action.call_args[0][1], ["client-a"])

    @patch("server_components.api_service.assign_client_location")
    def test_assign_occupied_location_returns_clear_error(self, assign_location):
        assign_location.side_effect = ValueError(
            "This physical position is already assigned to DESKTOP-ABC."
        )
        payload = json.dumps({"location_id": 4}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/clients/client-b/location",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="PATCH",
        )

        with self.assertRaises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(req)

        self.assertEqual(raised.exception.code, 400)
        body = json.loads(raised.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "INVALID_LOCATION")
        self.assertIn("DESKTOP-ABC", body["error"]["message"])

    @patch("server_components.api_service.get_client_location")
    def test_unassigned_client_location_endpoint(self, get_client_location):
        get_client_location.return_value = None

        status, body = self._fetch("/api/clients/client-a/location")

        self.assertEqual(status, 200)
        self.assertIsNone(body["data"])

    @patch("server_components.api_service.get_client_location_history")
    def test_client_location_history_endpoint(self, get_history):
        get_history.return_value = [
            {"id": 1, "assigned_by": "admin", "location": {"label": "F1-A1-T1-R1-P1"}}
        ]

        status, body = self._fetch("/api/clients/client-a/location-history")

        self.assertEqual(status, 200)
        self.assertEqual(body["data"]["items"][0]["assigned_by"], "admin")
        get_history.assert_called_once_with("client-a")

    @patch("server_components.api_service.get_physical_neighbors")
    def test_physical_neighbors_endpoint(self, get_physical_neighbors):
        get_physical_neighbors.return_value = [
            {
                "client_id": "client-b",
                "hostname": "PC-B",
                "relationship": "same_row",
                "distance": 1,
            }
        ]

        status, body = self._fetch("/api/clients/client-a/physical-neighbors")

        self.assertEqual(status, 200)
        self.assertEqual(body["data"]["items"][0]["relationship"], "same_row")
        get_physical_neighbors.assert_called_once_with("client-a")

    @patch("server_components.api_service.get_location_layout")
    def test_location_layout_endpoint(self, get_location_layout):
        get_location_layout.return_value = {
            "floor": 1,
            "available_floors": [0, 1, 2],
            "rooms": [],
            "aisles": [],
            "shows_clients": True,
        }

        status, body = self._fetch("/api/locations/layout?floor=1")

        self.assertEqual(status, 200)
        self.assertEqual(body["data"]["floor"], 1)
        get_location_layout.assert_called_once_with(1)


if __name__ == "__main__":
    unittest.main()
