"""Server relay and REST tests for the v2 on-demand Flow API."""

import json
import sys
import threading
import types
import unittest
import urllib.error
import urllib.parse
import urllib.request
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

from api_server import run_api_server  # noqa: E402
from server_components import server_lib  # noqa: E402


WINDOW = "2026-09-02T00:00:00Z_2026-09-02T00:15:00Z"


class TelemetryFlowApiTests(unittest.TestCase):
    def test_relay_passes_query_and_validates_response(self):
        response = {
            "status": "ok",
            "device_mac": "aa:bb:cc:dd:ee:01",
            "window_id": WINDOW,
            "flows": [{"flow_id": "one"}],
        }
        with patch.object(
            server_lib,
            "execute_client_command",
            return_value={"status": "ok", "data": response},
        ) as execute:
            result = server_lib.request_client_telemetry_flows(
                "client-a", "AA:BB:CC:DD:EE:01", WINDOW, timeout=4.0
            )

        execute.assert_called_once_with(
            "client-a",
            "GET_TELEMETRY_FLOWS",
            args={"device_mac": "AA:BB:CC:DD:EE:01", "window": WINDOW},
            timeout=4.0,
            process_network_scan=False,
        )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["flow_count"], 1)

    def test_rest_endpoint_maps_client_unavailable(self):
        httpd = run_api_server(host="127.0.0.1", port=0)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            path = "/api/v1/clients/client-a/devices/AA:BB:CC:DD:EE:01/flows?window=" + urllib.parse.quote(WINDOW)
            with patch(
                "server_components.server_lib.request_client_telemetry_flows",
                return_value={
                    "status": "client_unavailable",
                    "message": "Client is not connected.",
                },
            ):
                request = urllib.request.Request(
                    f"http://127.0.0.1:{httpd.server_address[1]}{path}",
                    headers={"Accept": "application/json"},
                )
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(request)
                self.assertEqual(raised.exception.code, 409)
                body = json.loads(raised.exception.read().decode("utf-8"))
                self.assertEqual(body["error"]["code"], "CLIENT_UNAVAILABLE")
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
