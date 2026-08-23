"""HTTP REST API Server for Network Monitoring Console.

Exposes `/api/v1/*` endpoints and real-time SSE stream `/api/v1/events`
consumed by the desktop GUI (Tauri / React), implementing the contract
defined in `server/docs/API_CONTRACT.md`.
"""

from __future__ import annotations

import json
import os
import queue
import re
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Optional, Tuple

from server_components import api_service, event_broadcaster, server_lib

API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8080"))


class ApiRequestHandler(BaseHTTPRequestHandler):
    """Handles HTTP requests for /api/v1 endpoints with JSON envelopes, SSE streaming, and CORS support."""

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress default noisy stdlib logging
        pass

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Accept, Authorization")

    def do_OPTIONS(self) -> None:  # noqa: N802
        print(f"[REST API] OPTIONS (CORS preflight) {self.path}")
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def _send_json(self, status_code: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def send_data(self, data: Any, meta: Optional[Dict[str, Any]] = None, status_code: int = 200) -> None:
        print(f"[REST API RESPONSE] {status_code} OK -> {self.path}")
        self._send_json(status_code, {
            "data": data,
            "meta": meta or {},
        })

    def send_error_response(self, status_code: int, code: str, message: str) -> None:
        print(f"[REST API ERROR] {status_code} [{code}] on {self.path}: {message}")
        self._send_json(status_code, {
            "error": {
                "code": code,
                "message": message,
            }
        })

    def _read_json_payload(self) -> Optional[Dict[str, Any]]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8") if length else "{}"
            payload = json.loads(body) if body else {}
            return payload if isinstance(payload, dict) else None
        except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
            return None

    def do_GET(self) -> None:  # noqa: N802
        print(f"[REST API REQUEST] GET {self.path} (from {self.client_address[0]})")
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path.rstrip("/")
        query_params = urllib.parse.parse_qs(parsed_url.query)

        def get_param(name: str, default: Optional[str] = None) -> Optional[str]:
            vals = query_params.get(name)
            return vals[0] if vals else default

        def get_int_param(name: str, default: int) -> int:
            val = get_param(name)
            if val and val.isdigit():
                return int(val)
            return default

        try:
            # 1. Health check / root
            if path == "" or path == "/health":
                self.send_data({"status": "ok", "service": "network-monitoring-api"})
                return

            # 2. Server-Sent Events (Real-time stream for live alerts and telemetry)
            if path == "/api/v1/events":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache, no-transform")
                self.send_header("Connection", "keep-alive")
                self._send_cors_headers()
                self.end_headers()

                q = event_broadcaster.subscribe()
                print(f"[SSE] Client connected to live event stream from {self.client_address[0]}")
                try:
                    # Initial connection handshake
                    self.wfile.write(b": connected\n\n")
                    self.wfile.flush()

                    while True:
                        try:
                            event_type, data = q.get(timeout=15.0)
                            payload = json.dumps(data, ensure_ascii=False)
                            msg = f"event: {event_type}\ndata: {payload}\n\n"
                            self.wfile.write(msg.encode("utf-8"))
                            self.wfile.flush()
                        except queue.Empty:
                            # Periodic keepalive ping to prevent proxy / idle timeout
                            self.wfile.write(b": ping\n\n")
                            self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                finally:
                    event_broadcaster.unsubscribe(q)
                    print(f"[SSE] Client disconnected from live event stream ({self.client_address[0]})")
                return

            # 3. Dashboard
            if path == "/api/v1/dashboard":
                data = api_service.get_dashboard_data()
                self.send_data(data)
                return

            # 4. Clients
            if path == "/api/v1/clients":
                state_filter = get_param("state")
                search = get_param("search")
                limit = get_int_param("limit", 50)
                items = api_service.list_clients(state_filter=state_filter, search=search, limit=limit)
                self.send_data({"items": items, "next_cursor": None})
                return

            # Supported commands list for client
            m = re.match(r"^/api/v1/clients/([^/]+)/commands$", path)
            if m:
                commands = [
                    {"command": "GET_SYSTEM_INFO", "label": "System information"},
                    {"command": "GET_NETWORK_INFO", "label": "Network information"},
                    {"command": "GET_PROCESSES", "label": "Processes"},
                    {"command": "GET_ACTIVITY_LOG", "label": "Activity log"},
                    {"command": "PING", "label": "Ping"},
                    {"command": "KILL_PROCESS", "label": "Kill process"},
                    {"command": "START_PROCESS", "label": "Start process"},
                    {"command": "ISOLATE_DEVICE", "label": "Isolate device (static IP)"},
                    {"command": "DISCONNECT", "label": "Disconnect client"},
                ]
                self.send_data({"items": commands})
                return

            m = re.match(r"^/api/v1/clients/([^/]+)$", path)
            if m:
                client_id = urllib.parse.unquote(m.group(1))
                detail = api_service.get_client_detail(client_id)
                if not detail:
                    self.send_error_response(404, "NOT_FOUND", f"Client '{client_id}' not found.")
                    return
                self.send_data(detail)
                return

            # Client quarantine status GET
            m = re.match(r"^/api/v1/clients/([^/]+)/quarantine$", path)
            if m:
                client_id = urllib.parse.unquote(m.group(1))
                status_res = server_lib.get_client_quarantine_status(client_id)
                if status_res.get("status") == "ok":
                    self.send_data(status_res.get("data", status_res))
                else:
                    self.send_error_response(400, "COMMAND_FAILED", status_res.get("message", "Failed to retrieve quarantine status."))
                return

            # Device-isolation dispatch status is server-side because the
            # client intentionally disconnects after its active route is removed.
            m = re.match(r"^/api/v1/clients/([^/]+)/isolation$", path)
            if m:
                client_id = urllib.parse.unquote(m.group(1))
                status_res = server_lib.get_device_isolation_status(client_id)
                self.send_data(status_res.get("data", status_res))
                return

            # 5. Network Scans
            if path == "/api/v1/network/scans/latest":
                scan_data = api_service.get_latest_scan()
                if not scan_data:
                    self.send_data({
                        "scan": {
                            "id": "none",
                            "completed_at": "",
                            "network": {"interface": "none", "local_ip": None, "network": "none", "gateway": None},
                            "devices_found": 0,
                            "devices": [],
                        }
                    })
                    return
                self.send_data(scan_data)
                return

            if path == "/api/v1/network/scans":
                from_date = get_param("from")
                to_date = get_param("to")
                limit = get_int_param("limit", 50)
                items = api_service.list_scans(from_date=from_date, to_date=to_date, limit=limit)
                self.send_data({"items": items, "next_cursor": None})
                return

            if path == "/api/v1/network/scans/global-active":
                from server_components.global_network_scan import global_network_scan_manager

                active_scan = global_network_scan_manager.active()
                if not active_scan:
                    self.send_error_response(404, "NOT_FOUND", "No global active scan is running.")
                    return
                self.send_data(active_scan)
                return

            if path == "/api/v1/network/neighbourhood/collections/active":
                from server_components.global_network_scan import (
                    global_neighbourhood_collection_manager,
                )

                collection = global_neighbourhood_collection_manager.active()
                if not collection:
                    self.send_error_response(
                        404,
                        "NOT_FOUND",
                        "No global neighbourhood collection is running.",
                    )
                    return
                self.send_data(collection)
                return

            m = re.match(r"^/api/v1/network/neighbourhood/collections/([^/]+)$", path)
            if m:
                from server_components.global_network_scan import (
                    global_neighbourhood_collection_manager,
                )

                collection_id = urllib.parse.unquote(m.group(1))
                collection = global_neighbourhood_collection_manager.get(collection_id)
                if not collection:
                    self.send_error_response(
                        404,
                        "NOT_FOUND",
                        f"Global neighbourhood collection '{collection_id}' not found.",
                    )
                    return
                self.send_data(collection)
                return

            m = re.match(r"^/api/v1/network/scans/global-active/([^/]+)$", path)
            if m:
                from server_components.global_network_scan import global_network_scan_manager

                scan_id = urllib.parse.unquote(m.group(1))
                scan = global_network_scan_manager.get(scan_id)
                if not scan:
                    self.send_error_response(404, "NOT_FOUND", f"Global scan '{scan_id}' not found.")
                    return
                self.send_data(scan)
                return

            m = re.match(r"^/api/v1/network/scans/([^/]+)$", path)
            if m:
                scan_id = urllib.parse.unquote(m.group(1))
                scan_data = api_service.get_scan_by_id(scan_id)
                if not scan_data:
                    self.send_error_response(404, "NOT_FOUND", f"Scan '{scan_id}' not found.")
                    return
                self.send_data(scan_data)
                return

            # 6a. Network Devices — list all
            if path == "/api/v1/network/devices":
                search = get_param("search")
                limit = get_int_param("limit", 500)
                offset = get_int_param("offset", 0)
                devices_data = api_service.list_network_devices(search=search, limit=limit, offset=offset)
                self.send_data(devices_data)
                return

            # 6b. Network Device — single device by MAC
            m = re.match(r"^/api/v1/network/devices/([^/]+)$", path)
            if m:
                mac_addr = urllib.parse.unquote(m.group(1))
                device_data = api_service.get_network_device_detail(mac_addr)
                if not device_data:
                    self.send_error_response(404, "NOT_FOUND", f"Device with MAC '{mac_addr}' not found.")
                    return
                self.send_data(device_data)
                return

            # 7. DHCP Activity
            if path == "/api/v1/network/dhcp":
                date_param = get_param("date")
                reporter_mac = get_param("reporter_mac")
                limit = get_int_param("limit", 100)
                dhcp_data = api_service.get_dhcp_activity(date_str=date_param, reporter_mac=reporter_mac, limit=limit)
                self.send_data(dhcp_data)
                return

            # 8. Alerts
            if path == "/api/v1/alerts":
                status = get_param("status")
                severity = get_param("severity")
                client_id = get_param("client_id")
                limit = get_int_param("limit", 50)
                alerts = api_service.list_alerts(status=status, severity=severity, client_id=client_id, limit=limit)
                self.send_data({"items": alerts, "next_cursor": None})
                return

            m = re.match(r"^/api/v1/alerts/(\d+)$", path)
            if m:
                alert_id = int(m.group(1))
                alert_data = api_service.get_alert_detail(alert_id)
                if not alert_data:
                    self.send_error_response(404, "NOT_FOUND", f"Alert #{alert_id} not found.")
                    return
                self.send_data(alert_data)
                return

            # 9. Activity Logs
            if path == "/api/v1/activity-logs":
                client_id = get_param("client_id")
                period = get_param("period")
                limit = get_int_param("limit", 50)
                logs = api_service.list_activity_logs(client_id=client_id, period=period, limit=limit)
                self.send_data({"items": logs, "next_cursor": None})
                return

            m = re.match(r"^/api/v1/activity-logs/(\d+)$", path)
            if m:
                log_id = int(m.group(1))
                log_detail = api_service.get_activity_log_detail(log_id)
                if not log_detail:
                    self.send_error_response(404, "NOT_FOUND", f"Activity log #{log_id} not found.")
                    return
                self.send_data(log_detail)
                return

            # 10. Settings
            if path == "/api/v1/settings/working-hours":
                wh_data = api_service.get_working_hours_settings()
                self.send_data(wh_data)
                return

            if path == "/api/v1/settings/forbidden-processes":
                fp_data = api_service.get_forbidden_processes_settings()
                self.send_data(fp_data)
                return

            m = re.match(r"^/api/v1/settings/forbidden-processes/([^/]+)$", path)
            if m:
                rule = api_service.get_forbidden_process(urllib.parse.unquote(m.group(1)))
                if rule is None:
                    self.send_error_response(404, "NOT_FOUND", "Forbidden process rule not found.")
                else:
                    self.send_data(rule)
                return

            # Fallback 404
            self.send_error_response(404, "NOT_FOUND", f"Unknown endpoint '{path}'.")

        except Exception as e:
            import traceback
            print(f"[REST API EXCEPTION] Error handling {path}: {e}")
            traceback.print_exc()
            self.send_error_response(500, "INTERNAL_ERROR", f"An unexpected server error occurred: {e}")

    def do_POST(self) -> None:  # noqa: N802
        print(f"[REST API REQUEST] POST {self.path} (from {self.client_address[0]})")
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path.rstrip("/")

        try:
            if path == "/api/v1/settings/forbidden-processes":
                payload = self._read_json_payload()
                if payload is None:
                    self.send_error_response(400, "INVALID_PAYLOAD", "Invalid JSON payload.")
                    return
                try:
                    rule = api_service.create_forbidden_process(payload)
                except ValueError as exc:
                    self.send_error_response(400, "INVALID_RULE", str(exc))
                    return
                server_lib.broadcast_forbidden_processes()
                self.send_data(rule, status_code=201)
                return

            # Request bounded passive-protocol observations from one connected client.
            m = re.match(r"^/api/v1/clients/([^/]+)/passive-neighbourhood$", path)
            if m:
                client_id = urllib.parse.unquote(m.group(1))
                result = server_lib.request_client_passive_neighbourhood(client_id)
                if result["status"] == "completed":
                    self.send_data(result, status_code=200)
                elif result["status"] == "client_timeout":
                    self.send_error_response(504, "CLIENT_TIMEOUT", result["message"])
                elif result["status"] == "client_unavailable":
                    self.send_error_response(409, "CLIENT_UNAVAILABLE", result["message"])
                else:
                    self.send_error_response(502, "CLIENT_REQUEST_FAILED", result["message"])
                return

            # Direct passive neighbourhood collection from one connected client.
            m = re.match(r"^/api/v1/clients/([^/]+)/network-neighbourhood$", path)
            if m:
                client_id = urllib.parse.unquote(m.group(1))
                result = server_lib.request_client_network_neighbourhood(client_id)
                if result["status"] == "completed":
                    self.send_data(result, status_code=200)
                elif result["status"] == "client_timeout":
                    self.send_error_response(504, "CLIENT_TIMEOUT", result["message"])
                elif result["status"] == "client_unavailable":
                    self.send_error_response(409, "CLIENT_UNAVAILABLE", result["message"])
                else:
                    self.send_error_response(502, "CLIENT_REQUEST_FAILED", result["message"])
                return

            # Client commands dispatch (POST /api/v1/clients/{client_id}/commands)
            m = re.match(r"^/api/v1/clients/([^/]+)/commands$", path)
            if m:
                client_id = urllib.parse.unquote(m.group(1))
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    body = self.rfile.read(length).decode("utf-8") if length else "{}"
                    payload = json.loads(body) if body else {}
                except Exception:
                    self.send_error_response(400, "INVALID_PAYLOAD", "Invalid JSON payload.")
                    return

                command = payload.get("command")
                args = payload.get("args")
                if not command or not isinstance(command, str):
                    self.send_error_response(400, "MISSING_COMMAND", 'Field "command" is required.')
                    return

                if command in ("SCAN_NETWORK", "TRIGGER_ARP_SCAN"):
                    self.send_error_response(
                        409,
                        "ACTIVE_NETWORK_SCAN_DISABLED",
                        "Active ARP scanning is disabled while passive neighbourhood collection is being rolled out.",
                    )
                    return

                if command == "ISOLATE_DEVICE":
                    reason = args.get("reason") if isinstance(args, dict) else None
                    res = server_lib.isolate_client(
                        client_id,
                        reason=reason or "Administrator requested static device isolation",
                    )
                    if res.get("status") == "ok":
                        self.send_data(res, status_code=200)
                    else:
                        self.send_error_response(400, "ISOLATION_FAILED", res.get("message", "Failed to isolate client."))
                    return

                res = server_lib.execute_client_command(
                    client_id,
                    command,
                    args,
                    timeout=25.0 if command == "SCAN_NETWORK" else 12.0,
                )
                if res.get("status") == "ok":
                    self.send_data(res, status_code=200)
                else:
                    self.send_error_response(400, "COMMAND_FAILED", res.get("message", "Command execution failed."))
                return

            # Client Quarantine (POST /api/v1/clients/{client_id}/quarantine)
            m = re.match(r"^/api/v1/clients/([^/]+)/quarantine$", path)
            if m:
                client_id = urllib.parse.unquote(m.group(1))
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    body = self.rfile.read(length).decode("utf-8") if length else "{}"
                    payload = json.loads(body) if body else {}
                except Exception:
                    payload = {}
                reason = payload.get("reason", "Administrator requested network quarantine")
                duration = payload.get("duration_minutes", 60)
                res = server_lib.quarantine_client(client_id, reason=reason, duration_minutes=duration)
                if res.get("status") == "ok":
                    self.send_data(res, status_code=200)
                else:
                    self.send_error_response(400, "QUARANTINE_FAILED", res.get("message", "Failed to quarantine client."))
                return

            # Device isolation (POST /api/v1/clients/{client_id}/isolation).
            m = re.match(r"^/api/v1/clients/([^/]+)/isolation$", path)
            if m:
                client_id = urllib.parse.unquote(m.group(1))
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    body = self.rfile.read(length).decode("utf-8") if length else "{}"
                    payload = json.loads(body) if body else {}
                except Exception:
                    payload = {}
                reason = payload.get("reason", "Administrator requested static device isolation")
                res = server_lib.isolate_client(client_id, reason=reason)
                if res.get("status") == "ok":
                    self.send_data(res, status_code=200)
                else:
                    self.send_error_response(400, "ISOLATION_FAILED", res.get("message", "Failed to isolate client."))
                return

            # Client Release Quarantine (POST /api/v1/clients/{client_id}/release-quarantine)
            m = re.match(r"^/api/v1/clients/([^/]+)/release-quarantine$", path)
            if m:
                client_id = urllib.parse.unquote(m.group(1))
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    body = self.rfile.read(length).decode("utf-8") if length else "{}"
                    payload = json.loads(body) if body else {}
                except Exception:
                    payload = {}
                reason = payload.get("reason", "Administrator released network quarantine")
                res = server_lib.release_client_quarantine(client_id, reason=reason)
                if res.get("status") == "ok":
                    self.send_data(res, status_code=200)
                else:
                    self.send_error_response(400, "RELEASE_FAILED", res.get("message", "Failed to release client quarantine."))
                return

            # Manual Network Scan Trigger / Report Merge (POST /api/v1/network/scans)
            if path == "/api/v1/network/scans":
                try:
                    from server_components.network_discovery import run_manual_scan
                    context, devices, result_path = run_manual_scan()
                    scan_id = context.get("scan_id", "manual")
                    event_broadcaster.broadcast_network_update(scan_id, len(devices))
                    self.send_data({
                        "status": "success",
                        "scan_id": scan_id,
                        "devices_found": len(devices),
                        "result_path": str(result_path),
                    }, status_code=201)
                    return
                except Exception as err:
                    print(f"Manual network scan failed: {err}")
                    self.send_error_response(500, "SCAN_FAILED", f"Network discovery failed: {err}")
                    return

            # Active Server-Side ARP Scan (POST /api/v1/network/scans/active)
            if path == "/api/v1/network/scans/active":
                self.send_error_response(
                    409,
                    "ACTIVE_NETWORK_SCAN_DISABLED",
                    "Active ARP scanning is disabled while passive neighbourhood collection is being rolled out.",
                )
                return
            # Global Active Neighbourhood Scan via All Clients.
            if path == "/api/v1/network/scans/global-active":
                self.send_error_response(
                    409,
                    "ACTIVE_NETWORK_SCAN_DISABLED",
                    "Global active ARP scanning is disabled; global passive neighbourhood collection will replace it.",
                )
                return

            if path == "/api/v1/network/neighbourhood/collections":
                from server_components.network_discovery import (
                    run_global_neighbourhood_collection,
                )

                collection, created = run_global_neighbourhood_collection()
                response = {
                    **collection,
                    "status": "started" if created else "already_running",
                }
                self.send_data(response, status_code=202 if created else 200)
                return

            # Fallback 404
            self.send_error_response(404, "NOT_FOUND", f"Unknown POST endpoint '{path}'.")

        except Exception as e:
            import traceback
            print(f"[REST API EXCEPTION] POST Error on {path}: {e}")
            traceback.print_exc()
            self.send_error_response(500, "INTERNAL_ERROR", f"An unexpected server error occurred: {e}")

    def do_PUT(self) -> None:  # noqa: N802
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path.rstrip("/")
        m = re.match(r"^/api/v1/settings/forbidden-processes/([^/]+)$", path)
        if not m:
            self.send_error_response(404, "NOT_FOUND", f"Unknown endpoint '{path}'.")
            return
        payload = self._read_json_payload()
        if payload is None:
            self.send_error_response(400, "INVALID_PAYLOAD", "Invalid JSON payload.")
            return
        try:
            rule = api_service.update_forbidden_process(urllib.parse.unquote(m.group(1)), payload)
        except ValueError as exc:
            self.send_error_response(400, "INVALID_RULE", str(exc))
            return
        if rule is None:
            self.send_error_response(404, "NOT_FOUND", "Forbidden process rule not found.")
            return
        server_lib.broadcast_forbidden_processes()
        self.send_data(rule)

    def do_DELETE(self) -> None:  # noqa: N802
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path.rstrip("/")
        m = re.match(r"^/api/v1/settings/forbidden-processes/([^/]+)$", path)
        if not m:
            self.send_error_response(404, "NOT_FOUND", f"Unknown endpoint '{path}'.")
            return
        if not api_service.delete_forbidden_process(urllib.parse.unquote(m.group(1))):
            self.send_error_response(404, "NOT_FOUND", "Forbidden process rule not found.")
            return
        server_lib.broadcast_forbidden_processes()
        self.send_data({"deleted": True})

    def do_PATCH(self) -> None:  # noqa: N802
        self.do_PUT()


def run_api_server(host: str = API_HOST, port: int = API_PORT) -> ThreadingHTTPServer:
    """Instantiate and return the ThreadingHTTPServer for the API."""
    server = ThreadingHTTPServer((host, port), ApiRequestHandler)
    return server


def main() -> None:
    server = run_api_server()
    print(f"Network Monitoring REST API running at http://{API_HOST}:{API_PORT}/api/v1")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping API server.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
