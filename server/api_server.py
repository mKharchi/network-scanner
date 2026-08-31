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
from datetime import date, datetime
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# Load the same server-local database configuration when the REST API is
# launched independently from server.py.
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

from server_components import action_service, api_service, event_broadcaster, package_service, server_lib
from server_components.action_framework import ActionState, ActionType, get_supported_client_commands

API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8080"))
LONG_RUNNING_ACTION_TYPES = {ActionType.DEPLOY_PACKAGE.value}


class DecimalJSONEncoder(json.JSONEncoder):
    """Serialize Decimal and date-like values for REST/SSE JSON payloads."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, Decimal):
            try:
                return int(obj) if obj == obj.to_integral_value() else float(obj)
            except (ValueError, OverflowError, ArithmeticError):
                return float(obj)
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super().default(obj)


class ApiRequestHandler(BaseHTTPRequestHandler):
    """Handles HTTP requests for /api/v1 endpoints with JSON envelopes, SSE streaming, and CORS support."""

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress default noisy stdlib logging
        pass

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Accept, Authorization, X-Package-Filename, X-Package-Id, X-Operator-Id")

    def do_OPTIONS(self) -> None:  # noqa: N802
        print(f"[REST API] OPTIONS (CORS preflight) {self.path}")
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def _send_json(self, status_code: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, cls=DecimalJSONEncoder).encode("utf-8")
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

    def _stream_package_upload(self) -> Dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            raise ValueError("Package upload body is empty.")
        if content_length > package_service.MAX_PACKAGE_SIZE_BYTES:
            raise ValueError(
                f"Package exceeds the {package_service.MAX_PACKAGE_SIZE_BYTES // (1024 * 1024)} MB size limit."
            )

        filename = (
            self.headers.get("X-Package-Filename")
            or self.headers.get("X-Filename")
            or "package.zip"
        )
        package_id = self.headers.get("X-Package-Id")
        uploaded_by = self.headers.get("X-Operator-Id") or "local-network-operator"

        class _RequestReader:
            def __init__(self, handler: ApiRequestHandler, remaining: int) -> None:
                self._handler = handler
                self._remaining = remaining

            def read(self, size: int = -1) -> bytes:
                if self._remaining <= 0:
                    return b""
                chunk_size = self._remaining if size < 0 else min(size, self._remaining)
                data = self._handler.rfile.read(chunk_size)
                self._remaining -= len(data)
                return data

        return package_service.stream_to_storage(
            _RequestReader(self, content_length),
            filename=filename,
            package_id=package_id,
            uploaded_by=uploaded_by,
        )

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
                            payload = json.dumps(data, ensure_ascii=False, cls=DecimalJSONEncoder)
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

            if path == "/api/locations":
                assignable = (get_param("assignable") or "").lower() in {"1", "true", "yes"}
                self.send_data({"items": api_service.list_locations(assignable_only=assignable)})
                return

            if path == "/api/locations/layout":
                floor = get_int_param("floor", 1)
                self.send_data(api_service.get_location_layout(floor))
                return

            m = re.match(r"^/api/locations/(\d+)/clients$", path)
            if m:
                self.send_data({"items": api_service.get_location_clients(int(m.group(1)))})
                return

            m = re.match(r"^/api/locations/(\d+)$", path)
            if m:
                location = api_service.get_location(int(m.group(1)))
                if not location:
                    self.send_error_response(404, "NOT_FOUND", "Location not found.")
                    return
                self.send_data(location)
                return

            m = re.match(r"^/api/clients/([^/]+)/location-history$", path)
            if m:
                client_id = urllib.parse.unquote(m.group(1))
                self.send_data({"items": api_service.get_client_location_history(client_id)})
                return

            m = re.match(r"^/api/clients/([^/]+)/physical-neighbors$", path)
            if m:
                client_id = urllib.parse.unquote(m.group(1))
                self.send_data({"items": api_service.get_physical_neighbors(client_id)})
                return

            if path == "/api/locations/calibration":
                client_id = get_param("client_id")
                limit = get_int_param("limit", 200)
                self.send_data(api_service.get_calibration_report(client_id=client_id, limit=limit))
                return

            m = re.match(r"^/api/clients/([^/]+)/location$", path)
            if m:
                client_id = urllib.parse.unquote(m.group(1))
                location = api_service.get_client_location(client_id)
                if not location:
                    self.send_data(None)
                    return
                self.send_data(location)
                return

            # Unified action history and per-target status.
            if path == "/api/actions":
                limit = get_int_param("limit", 50)
                self.send_data({"items": action_service.list_actions(limit=limit)})
                return

            m = re.match(r"^/api/actions/([^/]+)/targets$", path)
            if m:
                action = action_service.get_action(urllib.parse.unquote(m.group(1)))
                if not action:
                    self.send_error_response(404, "NOT_FOUND", "Action not found.")
                    return
                self.send_data({"items": action.get("targets", [])})
                return

            m = re.match(r"^/api/actions/([^/]+)$", path)
            if m:
                action = action_service.get_action(urllib.parse.unquote(m.group(1)))
                if not action:
                    self.send_error_response(404, "NOT_FOUND", "Action not found.")
                    return
                self.send_data(action)
                return

            # 3a. Development-only localization validation chain
            m = re.match(r"^/api/v1/debug/clients/([^/]+)/localization$", path)
            if m:
                client_id = urllib.parse.unquote(m.group(1))
                debug_data = api_service.get_client_localization_debug(client_id)
                if not debug_data:
                    self.send_error_response(404, "NOT_FOUND", f"Client '{client_id}' not found.")
                    return
                self.send_data(debug_data)
                return

            # 4. Clients
            if path in {"/api/clients/unassigned", "/api/v1/clients/unassigned"}:
                limit = get_int_param("limit", 100)
                items = api_service.list_unassigned_clients(limit=limit)
                self.send_data({"items": items, "total": len(items)})
                return

            if path == "/api/v1/clients":
                state_filter = get_param("state")
                search = get_param("search")
                location_filter = get_param("location")
                limit = get_int_param("limit", 50)
                items = api_service.list_clients(
                    state_filter=state_filter,
                    search=search,
                    limit=limit,
                    location_filter=location_filter,
                )
                self.send_data({"items": items, "next_cursor": None})
                return

            # Supported commands list for client
            m = re.match(r"^/api/v1/clients/([^/]+)/commands$", path)
            if m:
                self.send_data({"items": get_supported_client_commands()})
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

            m = re.match(r"^/api/v1/clients/([^/]+)/screenshots$", path)
            if m:
                client_id = urllib.parse.unquote(m.group(1))
                limit = get_int_param("limit", 12)
                screenshots = api_service.list_client_screenshots(client_id, limit=limit)
                if screenshots is None:
                    self.send_error_response(404, "NOT_FOUND", f"Client '{client_id}' not found.")
                    return
                self.send_data({"items": screenshots, "next_cursor": None})
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

            # 6c. Device Classification & Review Endpoints
            if path in {"/api/v1/classification/stats", "/api/classification/stats"}:
                self.send_data(api_service.get_classification_stats())
                return

            if path in {"/api/v1/classification/review", "/api/v1/devices/classification-review"}:
                limit = get_int_param("limit", 50)
                items = api_service.get_classification_review_queue(limit=limit)
                self.send_data({"items": items, "total": len(items)})
                return

            m = re.match(r"^/api/v1/(?:network/)?devices/([^/]+)/classification$", path)
            if m:
                device_id = urllib.parse.unquote(m.group(1))
                classification = api_service.get_device_classification_by_identifier(device_id)
                if not classification:
                    self.send_error_response(404, "NOT_FOUND", f"Device '{device_id}' classification not found.")
                    return
                self.send_data(classification)
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

            m = re.match(r"^/api/v1/screenshots/(\d+)/file$", path)
            if m:
                screenshot_id = int(m.group(1))
                screenshot = api_service.get_screenshot_record(screenshot_id)
                if not screenshot:
                    self.send_error_response(404, "NOT_FOUND", f"Screenshot #{screenshot_id} not found.")
                    return

                file_path = Path(screenshot["storage_path"])
                if not file_path.is_file():
                    self.send_error_response(404, "NOT_FOUND", "Screenshot file is no longer available.")
                    return

                payload = file_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", screenshot.get("mime_type") or "application/octet-stream")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Content-Disposition", f'inline; filename="{screenshot["filename"]}"')
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(payload)
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
            # 11. Spatial & Rogue Device Triangulation
            if path == "/api/v1/sensors" or path == "/api/sensors":
                self.send_data({"items": api_service.list_sensors()})
                return

            if path == "/api/v1/rogue-devices" or path == "/api/rogue-devices":
                min_score = get_int_param("min_score", 35)
                active_only = query_params.get("active_only", ["false"])[0].lower() in {"1", "true", "yes"}
                max_age_raw = query_params.get("max_age_seconds", [None])[0]
                max_age_val = int(max_age_raw) if max_age_raw and str(max_age_raw).isdigit() else None
                items = api_service.list_rogue_devices(
                    min_score=min_score,
                    active_only=active_only,
                    max_age_seconds=max_age_val,
                )
                self.send_data({"items": items, "total": len(items)})
                return

            m = re.match(r"^/(?:api/v1/|api/)rogue-devices/([^/]+)$", path)
            if m:
                device_id = urllib.parse.unquote(m.group(1))
                detail = api_service.get_rogue_device_detail(device_id)
                if not detail:
                    self.send_error_response(404, "NOT_FOUND", f"Device '{device_id}' rogue details not found.")
                    return
                self.send_data(detail)
                return

            m = re.match(r"^/(?:api/v1/|api/)(?:spatial/)?devices/([^/]+)/location$", path)
            if m:
                device_id = urllib.parse.unquote(m.group(1))
                loc = api_service.get_device_spatial_location(device_id)
                if not loc:
                    self.send_error_response(404, "NOT_FOUND", f"Spatial location for device '{device_id}' not found.")
                    return
                self.send_data(loc)
                return

            m = re.match(r"^/(?:api/v1/|api/)(?:spatial/)?devices/([^/]+)/(?:location-history|history)$", path)
            if m:
                device_id = urllib.parse.unquote(m.group(1))
                limit = get_int_param("limit", 50)
                history = api_service.get_device_spatial_history(device_id, limit=limit)
                self.send_data({"items": history})
                return

            if path == "/api/v1/spatial/events" or path == "/api/spatial/events":
                limit = get_int_param("limit", 50)
                self.send_data({"items": api_service.list_spatial_events(limit=limit)})
                return

            if path.startswith("/api/v1/spatial/floor/") or path.startswith("/api/spatial/floor/"):
                floor_str = path.rstrip("/").rsplit("/", 1)[-1]
                floor_num = int(floor_str) if floor_str.isdigit() else 1
                self.send_data(api_service.get_floor_spatial_map(floor_num))
                return

            if path == "/api/v1/spatial/scene" or path == "/api/spatial/scene":
                floor_str = query_params.get("floor", [None])[0]
                floor_val = int(floor_str) if floor_str and floor_str.isdigit() else None
                active_only = query_params.get("active_only", ["true"])[0].lower() not in {"0", "false", "no"}
                max_age_raw = query_params.get("max_age_seconds", [None])[0]
                max_age_val = int(max_age_raw) if max_age_raw and str(max_age_raw).isdigit() else None
                scene = api_service.get_spatial_scene(
                    floor=floor_val,
                    active_only=active_only,
                    max_age_seconds=max_age_val,
                )
                self.send_data(scene)
                return

            if path == "/api/v1/spatial/topology" or path == "/api/spatial/topology":
                topology = api_service.get_spatial_topology()
                self.send_data(topology)
                return

            if path == "/api/v1/spatial/threats" or path == "/api/spatial/threats":
                threats = api_service.get_spatial_threats()
                self.send_data({"items": threats})
                return

            if path == "/api/v1/spatial/replay" or path == "/api/spatial/replay":
                from_time = query_params.get("from", [None])[0]
                to_time = query_params.get("to", [None])[0]
                interval_str = query_params.get("interval", ["60"])[0]
                interval_val = int(interval_str) if interval_str and interval_str.isdigit() else 60
                replay = api_service.get_spatial_replay(
                    from_time=from_time,
                    to_time=to_time,
                    interval_seconds=interval_val,
                )
                self.send_data(replay)
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
            if path == "/api/locations":
                payload = self._read_json_payload()
                if payload is None:
                    self.send_error_response(400, "INVALID_PAYLOAD", "Invalid JSON payload.")
                    return
                try:
                    location = api_service.create_location(payload)
                except ValueError as exc:
                    self.send_error_response(400, "INVALID_LOCATION", str(exc))
                    return
                self.send_data(location, status_code=201)
                return

            m = re.match(r"^/api/clients/([^/]+)/location/auto$", path)
            if m:
                client_id = urllib.parse.unquote(m.group(1))
                try:
                    from server_components.client_localization import (
                        try_automatic_client_location_assignment,
                    )
                    outcome = try_automatic_client_location_assignment(client_id)
                except Exception as exc:  # noqa: BLE001
                    self.send_error_response(500, "LOCALIZATION_FAILED", str(exc))
                    return
                if outcome.get("reason") == "client_not_found":
                    self.send_error_response(404, "NOT_FOUND", f"Client '{client_id}' not found.")
                    return
                self.send_data(outcome)
                return

            m = re.match(r"^/api/clients/([^/]+)/location/confirm$", path)
            if m:
                client_id = urllib.parse.unquote(m.group(1))
                try:
                    location = api_service.confirm_client_location(
                        client_id,
                        confirmed_by=self.headers.get("X-Operator-Id")
                        or "local-network-operator",
                    )
                except ValueError as exc:
                    message = str(exc)
                    code = "NOT_FOUND" if "not found" in message.lower() else "INVALID_LOCATION"
                    status = 404 if code == "NOT_FOUND" else 400
                    self.send_error_response(status, code, message)
                    return
                self.send_data({"location": location})
                return

            if path == "/api/packages":
                try:
                    package = self._stream_package_upload()
                except ValueError as exc:
                    message = str(exc)
                    code = "UPLOAD_TOO_LARGE" if "size limit" in message.lower() else "INVALID_PACKAGE"
                    status = 413 if code == "UPLOAD_TOO_LARGE" else 400
                    self.send_error_response(status, code, message)
                    return
                self.send_data(package, status_code=201)
                return

            if path == "/api/actions":
                payload = self._read_json_payload()
                if payload is None:
                    self.send_error_response(400, "INVALID_PAYLOAD", "Invalid JSON payload.")
                    return
                action_type = payload.get("action_type")
                targets = payload.get("targets")
                if not isinstance(action_type, str) or not isinstance(targets, list):
                    self.send_error_response(400, "INVALID_ACTION", "Fields 'action_type' and 'targets' are required.")
                    return
                try:
                    requested_action_id = payload.get("action_id") or payload.get("idempotency_key")
                    existing_action = (
                        action_service.get_action(str(requested_action_id))
                        if requested_action_id
                        else None
                    )
                    if existing_action:
                        self.send_data(existing_action, status_code=200)
                        return
                    action = action_service.create_action(
                        action_type,
                        targets,
                        parameters=payload.get("parameters", {}),
                        requested_by=self.headers.get("X-Operator-Id") or "local-network-operator",
                        action_id=requested_action_id,
                    )
                    # Replaying an existing action is idempotent and must not dispatch it again.
                    if action.get("status") == ActionState.PENDING.value:
                        normalized_type = action.get("action_type")
                        if normalized_type in LONG_RUNNING_ACTION_TYPES:
                            threading.Thread(
                                target=action_service.execute_action,
                                args=(action,),
                                daemon=True,
                                name=f"action-{action.get('action_id')}",
                            ).start()
                        else:
                            action = action_service.execute_action(action)
                except ValueError as exc:
                    self.send_error_response(400, "INVALID_ACTION", str(exc))
                    return
                self.send_data(action, status_code=201)
                return

            m = re.match(r"^/api/actions/([^/]+)/cancel$", path)
            if m:
                action = action_service.cancel_action(urllib.parse.unquote(m.group(1)))
                if not action:
                    self.send_error_response(404, "NOT_FOUND", "Action not found.")
                    return
                self.send_data(action)
                return

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

            # Request one screenshot from the matching interactive/combined user-session agent.
            m = re.match(r"^/api/v1/clients/([^/]+)/screenshot$", path)
            if m:
                client_id = urllib.parse.unquote(m.group(1))
                requested_by = self.headers.get("X-Operator-Id") or "local-network-operator"
                result = server_lib.request_client_screenshot(
                    client_id, requested_by=requested_by
                )
                if result["status"] == "completed":
                    self.send_data(result, status_code=200)
                elif result["status"] == "client_timeout":
                    self.send_error_response(504, "CLIENT_TIMEOUT", result["message"])
                elif result["status"] == "client_unavailable":
                    self.send_error_response(409, "INTERACTIVE_AGENT_UNAVAILABLE", result["message"])
                elif result["status"] == "storage_error":
                    self.send_error_response(422, "INVALID_SCREENSHOT", result["message"])
                else:
                    self.send_error_response(502, "SCREENSHOT_FAILED", result["message"])
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

            if path == "/api/v1/network/neighbourhood/flush":
                from server_components.network_discovery import (
                    run_global_neighbourhood_storage_flush,
                )

                result = run_global_neighbourhood_storage_flush()
                self.send_data(result, status_code=200)
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
            if path == "/api/v1/sensors" or path == "/api/sensors":
                payload = self._read_json_payload()
                if payload is None:
                    self.send_error_response(400, "INVALID_PAYLOAD", "Invalid JSON payload.")
                    return
                try:
                    sensor = api_service.create_sensor(payload)
                    self.send_data(sensor, status_code=201)
                except Exception as exc:
                    self.send_error_response(400, "SENSOR_CREATION_FAILED", str(exc))
                return

            if path == "/api/v1/spatial/evaluate" or path == "/api/spatial/evaluate":
                eval_res = api_service.trigger_spatial_scan_evaluation()
                self.send_data({"status": "ok", "evaluated_devices": len(eval_res), "items": eval_res})
                return

            # Device Classification POST endpoints
            if path in {"/api/v1/classification/retrain", "/api/classification/retrain"}:
                res = api_service.retrain_classification_model()
                self.send_data(res, status_code=200)
                return

            m = re.match(r"^/api/v1/(?:network/)?devices/([^/]+)/classify$", path)
            if m:
                device_id = urllib.parse.unquote(m.group(1))
                res = api_service.classify_device_by_identifier(device_id, force=True)
                if not res:
                    self.send_error_response(404, "NOT_FOUND", f"Device '{device_id}' not found.")
                    return
                self.send_data(res, status_code=200)
                return

            m = re.match(r"^/api/v1/(?:network/)?devices/([^/]+)/label$", path)
            if m:
                device_id = urllib.parse.unquote(m.group(1))
                payload = self._read_json_payload() or {}
                label = payload.get("label")
                if not label or not isinstance(label, str):
                    self.send_error_response(400, "MISSING_LABEL", "Field 'label' is required.")
                    return
                confirmed_by = payload.get("confirmed_by") or self.headers.get("X-Operator-Id") or "admin"
                notes = payload.get("notes")
                try:
                    res = api_service.record_device_human_label_by_identifier(
                        device_identifier=device_id,
                        label=label,
                        confirmed_by=confirmed_by,
                        notes=notes,
                    )
                    if not res:
                        self.send_error_response(404, "NOT_FOUND", f"Device '{device_id}' not found.")
                        return
                    self.send_data(res, status_code=201)
                except ValueError as err:
                    self.send_error_response(400, "INVALID_LABEL", str(err))
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
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path.rstrip("/")
        m = re.match(r"^/api/clients/([^/]+)/location$", path)
        if m:
            payload = self._read_json_payload()
            if payload is None or not isinstance(payload.get("location_id"), int):
                self.send_error_response(400, "INVALID_LOCATION", "Field 'location_id' must be an integer.")
                return
            try:
                client_id = urllib.parse.unquote(m.group(1))
                location = api_service.assign_client_location(
                    client_id,
                    payload["location_id"],
                    assigned_by=self.headers.get("X-Operator-Id") or "local-network-operator",
                )
            except ValueError as exc:
                self.send_error_response(400, "INVALID_LOCATION", str(exc))
                return
            try:
                location_action = action_service.create_action(
                    ActionType.UPDATE_LOCATION.value,
                    [client_id],
                    parameters=location,
                    requested_by=self.headers.get("X-Operator-Id") or "local-network-operator",
                )
                location_sync = action_service.execute_action(location_action)
            except Exception as exc:
                # Assignment is authoritative even when the client is offline.
                location_sync = {"status": "not_attempted", "message": str(exc)}
            self.send_data({"location": location, "location_sync": location_sync})
            return
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
