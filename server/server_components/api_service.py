"""API Service Layer for Network Monitoring Console.

Provides modular query functions and data aggregation for all /api/v1 endpoints,
reusing existing database connections, in-memory client registry, and storage modules.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from database import get_connection
from server_components.network_device_classification import classify_devices
try:
    from server_components.network_scan_storage import NETWORK_SCAN_STORAGE_DIR
except ImportError:
    from server_components.network_scan_storage import DEFAULT_STORAGE_DIR
    NETWORK_SCAN_STORAGE_DIR = Path(os.getenv("NETWORK_SCAN_STORAGE_DIR", DEFAULT_STORAGE_DIR))

from server_components.server_lib import clients as memory_clients, clients_lock, get_working_hours_status


def _iso_utc(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _format_mac(mac: Optional[str]) -> Optional[str]:
    if not mac:
        return None
    return mac.upper().replace("-", ":")


# ============================================================
# DASHBOARD
# ============================================================

def get_dashboard_data() -> Dict[str, Any]:
    """Aggregate high-level overview metrics for the operator dashboard."""
    now_iso = datetime.now(timezone.utc).isoformat()
    
    # 1. Client counts and online list
    with clients_lock:
        online_macs = set(memory_clients.keys())
    
    total_clients = 0
    online_count = len(online_macs)
    online_client_summaries = []
    
    conn = get_connection()
    if conn:
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT COUNT(*) AS total FROM clients")
            row = cursor.fetchone()
            total_clients = row["total"] if row else 0
            
            # Fetch summary of online clients if any
            if online_macs:
                placeholders = ", ".join(["%s"] * len(online_macs))
                cursor.execute(
                    f"""
                    SELECT id, client_id, mac, hostname, ip,
                           os_system, os_release, os_version, os_machine,
                           created_at, updated_at
                    FROM clients
                    WHERE mac IN ({placeholders})
                    """,
                    list(online_macs),
                )
                for r in cursor.fetchall():
                    online_client_summaries.append({
                        "id": r["client_id"],
                        "database_id": r["id"],
                        "hostname": r["hostname"] or "Unknown",
                        "ip_address": r["ip"],
                        "mac_address": _format_mac(r["mac"]),
                        "os": {
                            "system": r["os_system"],
                            "release": r["os_release"],
                            "version": r["os_version"],
                            "machine": r["os_machine"],
                        },
                        "connection": {
                            "state": "ONLINE",
                            "last_connected_at": _iso_utc(r["updated_at"]),
                            "last_disconnected_at": None,
                        },
                        "created_at": _iso_utc(r["created_at"]),
                        "updated_at": _iso_utc(r["updated_at"]),
                    })
        finally:
            conn.close()

    offline_count = max(0, total_clients - online_count)
    
    # 2. Alerts count & recent list
    new_alerts = 0
    critical_alerts = 0
    recent_alerts = []
    
    conn = get_connection()
    if conn:
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT COUNT(*) as total_new,
                       SUM(CASE WHEN severity = 'CRITICAL' AND status = 'NEW' THEN 1 ELSE 0 END) as total_critical
                FROM alerts
                WHERE status = 'NEW'
                """
            )
            a_counts = cursor.fetchone()
            if a_counts:
                new_alerts = a_counts["total_new"] or 0
                critical_alerts = int(a_counts["total_critical"] or 0)
                
            cursor.execute(
                """
                SELECT a.id, a.alert_type, a.severity, a.status,
                       a.detected_at, a.activity_time, a.title, a.description,
                       a.log_id, c.client_id, c.hostname
                FROM alerts a
                LEFT JOIN clients c ON a.client_id = c.id
                ORDER BY a.detected_at DESC
                LIMIT 5
                """
            )
            for r in cursor.fetchall():
                recent_alerts.append({
                    "id": r["id"],
                    "client": {
                        "id": r["client_id"],
                        "hostname": r["hostname"] or "Unknown",
                    } if r["client_id"] else None,
                    "type": r["alert_type"],
                    "severity": r["severity"],
                    "status": r["status"],
                    "detected_at": _iso_utc(r["detected_at"]),
                    "activity_time": _iso_utc(r["activity_time"]),
                    "title": r["title"] or r["alert_type"],
                    "description": r["description"] or "",
                    "activity_log_id": r["log_id"],
                })
        finally:
            conn.close()

    # 3. Latest scan preview
    latest_scan_info = None
    latest_scan_obj = get_latest_scan()
    if latest_scan_obj:
        scan_data = latest_scan_obj.get("scan", {})
        latest_scan_info = {
            "scan_id": scan_data.get("id"),
            "completed_at": scan_data.get("completed_at"),
            "devices_found": scan_data.get("devices_found", 0),
        }

    # 4. DHCP today count
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    dhcp_file = NETWORK_SCAN_STORAGE_DIR / f"network_scan_{today_str}.json"
    dhcp_today = None
    if dhcp_file.is_file():
        try:
            with open(dhcp_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                observations = len(data.get("dhcp_observations", []))
                dhcp_today = {
                    "date": today_str,
                    "observations": observations,
                }
        except Exception:
            pass

    return {
        "generated_at": now_iso,
        "clients": {
            "online": online_count,
            "offline": offline_count,
            "total": total_clients,
        },
        "alerts": {
            "new": new_alerts,
            "critical": critical_alerts,
        },
        "latest_scan": latest_scan_info,
        "dhcp_today": dhcp_today,
        "recent_alerts": recent_alerts,
        "online_clients": online_client_summaries,
    }


# ============================================================
# CLIENTS
# ============================================================

def list_clients(
    state_filter: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """List managed clients with connection state from database and in-memory registry."""
    with clients_lock:
        online_macs = set(memory_clients.keys())

    conn = get_connection()
    if not conn:
        return []

    items = []
    try:
        cursor = conn.cursor(dictionary=True)
        query = """
            SELECT id, client_id, mac, hostname, ip,
                   os_system, os_release, os_version, os_machine,
                   created_at, updated_at
            FROM clients
        """
        params: List[Any] = []
        conditions = []

        if search:
            q = f"%{search}%"
            conditions.append("(hostname LIKE %s OR ip LIKE %s OR mac LIKE %s OR client_id LIKE %s)")
            params.extend([q, q, q, q])

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY updated_at DESC LIMIT %s"
        params.append(limit)

        cursor.execute(query, params)
        for r in cursor.fetchall():
            norm_mac = _format_mac(r["mac"])
            is_online = norm_mac in online_macs
            client_state = "ONLINE" if is_online else "OFFLINE"

            if state_filter and state_filter.upper() != client_state:
                continue

            items.append({
                "id": r["client_id"],
                "database_id": r["id"],
                "hostname": r["hostname"] or "Unknown",
                "ip_address": r["ip"],
                "mac_address": norm_mac,
                "os": {
                    "system": r["os_system"],
                    "release": r["os_release"],
                    "version": r["os_version"],
                    "machine": r["os_machine"],
                },
                "connection": {
                    "state": client_state,
                    "last_connected_at": _iso_utc(r["updated_at"]),
                    "last_disconnected_at": None,
                },
                "created_at": _iso_utc(r["created_at"]),
                "updated_at": _iso_utc(r["updated_at"]),
            })
    finally:
        conn.close()

    return items


def get_client_detail(client_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve complete client details, connection history, alerts summary, and latest log."""
    with clients_lock:
        online_macs = set(memory_clients.keys())

    conn = get_connection()
    if not conn:
        return None

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, client_id, mac, hostname, ip,
                   os_system, os_release, os_version, os_machine,
                   created_at, updated_at
            FROM clients
            WHERE client_id = %s
            """,
            (client_id,),
        )
        r = cursor.fetchone()
        if not r:
            return None

        norm_mac = _format_mac(r["mac"])
        is_online = norm_mac in online_macs
        client_state = "ONLINE" if is_online else "OFFLINE"
        db_id = r["id"]

        client_summary = {
            "id": r["client_id"],
            "database_id": db_id,
            "hostname": r["hostname"] or "Unknown",
            "ip_address": r["ip"],
            "mac_address": norm_mac,
            "os": {
                "system": r["os_system"],
                "release": r["os_release"],
                "version": r["os_version"],
                "machine": r["os_machine"],
            },
            "connection": {
                "state": client_state,
                "last_connected_at": _iso_utc(r["updated_at"]),
                "last_disconnected_at": None,
            },
            "created_at": _iso_utc(r["created_at"]),
            "updated_at": _iso_utc(r["updated_at"]),
        }

        # Recent connections
        cursor.execute(
            """
            SELECT connected_at, disconnected_at
            FROM connections
            WHERE client_id = %s
            ORDER BY connected_at DESC
            LIMIT 10
            """,
            (db_id,),
        )
        connections = [
            {
                "connected_at": _iso_utc(row["connected_at"]),
                "disconnected_at": _iso_utc(row["disconnected_at"]),
            }
            for row in cursor.fetchall()
        ]

        # Alert counts
        cursor.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN status = 'NEW' THEN 1 ELSE 0 END) AS total_new
            FROM alerts
            WHERE client_id = %s
            """,
            (db_id,),
        )
        ac = cursor.fetchone()
        alert_counts = {
            "total": ac["total"] if ac else 0,
            "new": int(ac["total_new"] or 0) if ac else 0,
        }

        # Latest activity log
        cursor.execute(
            """
            SELECT id, period, generated_at, received_at
            FROM activity_logs
            WHERE client_id = %s
            ORDER BY generated_at DESC
            LIMIT 1
            """,
            (db_id,),
        )
        latest_log_row = cursor.fetchone()
        latest_log = None
        if latest_log_row:
            latest_log = {
                "id": latest_log_row["id"],
                "client": {
                    "id": r["client_id"],
                    "hostname": r["hostname"] or "Unknown",
                },
                "period": latest_log_row["period"],
                "generated_at": _iso_utc(latest_log_row["generated_at"]),
                "received_at": _iso_utc(latest_log_row["received_at"]),
            }

        return {
            "client": client_summary,
            "recent_connections": connections,
            "alert_counts": alert_counts,
            "latest_activity_log": latest_log,
        }
    finally:
        conn.close()


# ============================================================
# NETWORK SCANS & DEVICES
# ============================================================

def get_latest_scan() -> Optional[Dict[str, Any]]:
    """Read the latest standalone network scan JSON file from disk."""
    scan_dir = NETWORK_SCAN_STORAGE_DIR
    if not scan_dir.is_dir():
        return None

    json_files = sorted(
        [p for p in scan_dir.glob("*.json") if not p.name.startswith("network_scan_")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not json_files:
        return None

    latest_file = json_files[0]
    return _parse_scan_file(latest_file)


def list_scans(from_date: Optional[str] = None, to_date: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """List historical standalone network scans."""
    scan_dir = NETWORK_SCAN_STORAGE_DIR
    if not scan_dir.is_dir():
        return []

    json_files = sorted(
        [p for p in scan_dir.glob("*.json") if not p.name.startswith("network_scan_")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    items = []
    for p in json_files:
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
                completed_at = data.get("completed_at", "")
                if from_date and completed_at < from_date:
                    continue
                if to_date and completed_at > (to_date + "T23:59:59"):
                    continue

                items.append({
                    "id": p.stem,
                    "completed_at": completed_at,
                    "devices_found": data.get("devices_found", len(data.get("devices", []))),
                    "network": data.get("network", {}),
                })
                if len(items) >= limit:
                    break
        except Exception:
            continue

    return items


def get_scan_by_id(scan_id: str) -> Optional[Dict[str, Any]]:
    """Load a specific scan file by its ID (filename stem)."""
    # Sanitize scan_id to prevent directory traversal
    clean_id = os.path.basename(scan_id)
    scan_file = NETWORK_SCAN_STORAGE_DIR / f"{clean_id}.json"
    if not scan_file.is_file():
        return None
    return _parse_scan_file(scan_file)


def _parse_scan_file(file_path: Path) -> Optional[Dict[str, Any]]:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        devices = data.get("devices", [])
        # Enrich/classify devices if not already classified
        classified = classify_devices(devices)

        formatted_devices = []
        for d in classified:
            formatted_devices.append({
                "mac_address": _format_mac(d.get("mac_address")),
                "ip_address": d.get("ip_address"),
                "hostname": d.get("hostname"),
                "vendor": d.get("vendor"),
                "os": {
                    "name": d.get("os_name"),
                    "family": d.get("os_family"),
                    "confidence": d.get("os_confidence"),
                },
                "classification": d.get("classification", "UNMANAGED"),
                "is_managed": bool(d.get("is_managed", False)),
                "managed_client_id": d.get("managed_client", {}).get("client_id") if d.get("is_managed") else None,
                "last_observed_at": d.get("observed_at") or data.get("completed_at"),
                "sources": d.get("sources", ["SERVER_SCAN"]),
            })

        net_ctx = data.get("network")
        if isinstance(net_ctx, str):
            net_obj = {"interface": "default", "local_ip": None, "network": net_ctx, "gateway": None}
        elif isinstance(net_ctx, dict):
            net_obj = net_ctx
        else:
            net_obj = {"interface": "unknown", "local_ip": None, "network": "unknown", "gateway": None}

        return {
            "scan": {
                "id": file_path.stem,
                "completed_at": data.get("completed_at", ""),
                "network": net_obj,
                "devices_found": data.get("devices_found", len(formatted_devices)),
                "devices": formatted_devices,
            }
        }
    except Exception:
        return None


def get_network_device_detail(mac_address: str) -> Optional[Dict[str, Any]]:
    """Fetch complete detail, observation history, and DHCP history for a MAC address."""
    norm_mac = _format_mac(mac_address)
    conn = get_connection()
    if not conn:
        return None

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, mac_address, ip_address, hostname, vendor, first_seen, last_seen
            FROM network_devices
            WHERE mac_address = %s
            """,
            (norm_mac,),
        )
        dev_row = cursor.fetchone()
        if not dev_row:
            return None

        # Check managed status against clients table
        cursor.execute("SELECT client_id, hostname, os_system, os_release FROM clients WHERE mac = %s", (norm_mac,))
        client_row = cursor.fetchone()
        is_managed = client_row is not None

        device_obj = {
            "mac_address": norm_mac,
            "ip_address": dev_row["ip_address"],
            "hostname": client_row["hostname"] if is_managed else dev_row["hostname"],
            "vendor": dev_row["vendor"],
            "os": {
                "name": client_row["os_system"] if is_managed else None,
                "family": client_row["os_system"] if is_managed else None,
                "confidence": 1.0 if is_managed else None,
            },
            "classification": "MANAGED" if is_managed else "UNMANAGED",
            "is_managed": is_managed,
            "managed_client_id": client_row["client_id"] if is_managed else None,
            "last_observed_at": _iso_utc(dev_row["last_seen"]),
            "sources": ["CLIENT_ARP"],
        }

        # Observations
        cursor.execute(
            """
            SELECT o.source_type, o.ip_address, o.interface_name, o.entry_type, o.observed_at,
                   c.client_id as source_client_id
            FROM network_device_observations o
            LEFT JOIN clients c ON o.source_client_id = c.id
            WHERE o.device_id = %s
            ORDER BY o.observed_at DESC
            LIMIT 50
            """,
            (dev_row["id"],),
        )
        observations = [
            {
                "source_type": row["source_type"],
                "source_client_id": row["source_client_id"],
                "ip_address": row["ip_address"],
                "interface": row["interface_name"],
                "entry_type": row["entry_type"],
                "observed_at": _iso_utc(row["observed_at"]),
            }
            for row in cursor.fetchall()
        ]

        return {
            "device": device_obj,
            "observations": observations,
            "dhcp_observations": [],
        }
    finally:
        conn.close()


# ============================================================
# DHCP ACTIVITY
# ============================================================

def get_dhcp_activity(date_str: Optional[str] = None, reporter_mac: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
    """Retrieve DHCP observations from daily scan audit JSON files."""
    if not date_str:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    clean_date = os.path.basename(date_str)
    file_path = NETWORK_SCAN_STORAGE_DIR / f"network_scan_{clean_date}.json"

    items = []
    if file_path.is_file():
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                raw_obs = data.get("dhcp_observations", [])
                for obs in raw_obs:
                    rep_mac = _format_mac(obs.get("reporting_client_mac"))
                    if reporter_mac and _format_mac(reporter_mac) != rep_mac:
                        continue

                    items.append({
                        "received_at": obs.get("received_at"),
                        "reporting_client_mac": rep_mac,
                        "neighbours": obs.get("neighbours", []),
                        "dhcp": obs.get("dhcp", {}),
                    })
                    if len(items) >= limit:
                        break
        except Exception:
            pass

    return {
        "date": clean_date,
        "items": items,
        "next_cursor": None,
    }


# ============================================================
# ALERTS
# ============================================================

def list_alerts(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    client_id: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Retrieve list of security and operational alerts with optional filtering."""
    conn = get_connection()
    if not conn:
        return []

    items = []
    try:
        cursor = conn.cursor(dictionary=True)
        query = """
            SELECT a.id, a.alert_type, a.severity, a.status,
                   a.detected_at, a.activity_time, a.title, a.description,
                   a.log_id, c.client_id, c.hostname
            FROM alerts a
            LEFT JOIN clients c ON a.client_id = c.id
        """
        conditions = []
        params: List[Any] = []

        if status:
            conditions.append("a.status = %s")
            params.append(status.upper())
        if severity:
            conditions.append("a.severity = %s")
            params.append(severity.upper())
        if client_id:
            conditions.append("c.client_id = %s")
            params.append(client_id)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY a.detected_at DESC LIMIT %s"
        params.append(limit)

        cursor.execute(query, params)
        for r in cursor.fetchall():
            items.append({
                "id": r["id"],
                "client": {
                    "id": r["client_id"],
                    "hostname": r["hostname"] or "Unknown",
                } if r["client_id"] else None,
                "type": r["alert_type"],
                "severity": r["severity"],
                "status": r["status"],
                "detected_at": _iso_utc(r["detected_at"]),
                "activity_time": _iso_utc(r["activity_time"]),
                "title": r["title"] or r["alert_type"],
                "description": r["description"] or "",
                "activity_log_id": r["log_id"],
            })
    finally:
        conn.close()

    return items


def get_alert_detail(alert_id: int) -> Optional[Dict[str, Any]]:
    """Retrieve full details for a single alert."""
    conn = get_connection()
    if not conn:
        return None

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT a.id, a.alert_type, a.severity, a.status,
                   a.detected_at, a.activity_time, a.title, a.description,
                   a.log_id, c.client_id, c.hostname, c.mac, c.ip, c.os_system
            FROM alerts a
            LEFT JOIN clients c ON a.client_id = c.id
            WHERE a.id = %s
            """,
            (alert_id,),
        )
        r = cursor.fetchone()
        if not r:
            return None

        client_data = None
        if r["client_id"]:
            client_data = {
                "id": r["client_id"],
                "hostname": r["hostname"] or "Unknown",
                "mac_address": _format_mac(r["mac"]),
                "ip_address": r["ip"],
            }

        return {
            "alert": {
                "id": r["id"],
                "client": {
                    "id": r["client_id"],
                    "hostname": r["hostname"] or "Unknown",
                } if r["client_id"] else None,
                "type": r["alert_type"],
                "severity": r["severity"],
                "status": r["status"],
                "detected_at": _iso_utc(r["detected_at"]),
                "activity_time": _iso_utc(r["activity_time"]),
                "title": r["title"] or r["alert_type"],
                "description": r["description"] or "",
                "activity_log_id": r["log_id"],
            },
            "client": client_data,
            "activity_log": {"id": r["log_id"]} if r["log_id"] else None,
        }
    finally:
        conn.close()


# ============================================================
# ACTIVITY LOGS
# ============================================================

def list_activity_logs(client_id: Optional[str] = None, period: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """List activity log metadata records."""
    conn = get_connection()
    if not conn:
        return []

    items = []
    try:
        cursor = conn.cursor(dictionary=True)
        query = """
            SELECT l.id, l.period, l.generated_at, l.received_at,
                   c.client_id, c.hostname
            FROM activity_logs l
            LEFT JOIN clients c ON l.client_id = c.id
        """
        conditions = []
        params: List[Any] = []

        if client_id:
            conditions.append("c.client_id = %s")
            params.append(client_id)
        if period:
            conditions.append("l.period = %s")
            params.append(period)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY l.generated_at DESC LIMIT %s"
        params.append(limit)

        cursor.execute(query, params)
        for r in cursor.fetchall():
            items.append({
                "id": r["id"],
                "client": {
                    "id": r["client_id"],
                    "hostname": r["hostname"] or "Unknown",
                } if r["client_id"] else None,
                "period": r["period"],
                "generated_at": _iso_utc(r["generated_at"]),
                "received_at": _iso_utc(r["received_at"]),
            })
    finally:
        conn.close()

    return items


def get_activity_log_detail(log_id: int) -> Optional[Dict[str, Any]]:
    """Load activity log JSON payload safely from the path recorded in DB."""
    conn = get_connection()
    if not conn:
        return None

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT l.id, l.file_path, l.period, l.generated_at, l.received_at,
                   c.client_id, c.hostname
            FROM activity_logs l
            LEFT JOIN clients c ON l.client_id = c.id
            WHERE l.id = %s
            """,
            (log_id,),
        )
        r = cursor.fetchone()
        if not r:
            return None

        file_path_str = r["file_path"]
        log_meta = {
            "id": r["id"],
            "client": {
                "id": r["client_id"],
                "hostname": r["hostname"] or "Unknown",
            } if r["client_id"] else None,
            "period": r["period"],
            "generated_at": _iso_utc(r["generated_at"]),
            "received_at": _iso_utc(r["received_at"]),
        }

        # Safely open file path
        if not file_path_str or not os.path.isfile(file_path_str):
            return {
                "log": log_meta,
                "since": None,
                "activity": [],
            }

        with open(file_path_str, "r", encoding="utf-8") as f:
            data = json.load(f)

        return {
            "log": log_meta,
            "since": data.get("since"),
            "activity": data.get("activity", []),
        }
    except Exception:
        return None
    finally:
        conn.close()


# ============================================================
# SETTINGS & POLICIES
# ============================================================

def get_working_hours_settings() -> Dict[str, Any]:
    """Retrieve working hours rules and current server evaluation status."""
    now_dt = datetime.now()
    status_str = get_working_hours_status(now_dt)
    within_hours = (status_str == "WITHIN")

    conn = get_connection()
    rules = []
    if conn:
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT day_of_week, start_time, end_time, enabled FROM working_hours ORDER BY day_of_week")
            for r in cursor.fetchall():
                start_t = str(r["start_time"]) if r["start_time"] else "00:00:00"
                end_t = str(r["end_time"]) if r["end_time"] else "23:59:59"
                rules.append({
                    "day_of_week": r["day_of_week"],
                    "start_time": start_t,
                    "end_time": end_t,
                    "enabled": bool(r["enabled"]),
                })
        finally:
            conn.close()

    return {
        "rules": rules,
        "current_status": {
            "within_working_hours": within_hours,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        },
    }


def get_forbidden_processes_settings() -> Dict[str, Any]:
    """Retrieve list of configured forbidden process policy rules."""
    conn = get_connection()
    items = []
    if conn:
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT process_name, severity, enabled, description FROM forbidden_processes ORDER BY process_name")
            for r in cursor.fetchall():
                items.append({
                    "process_name": r["process_name"],
                    "severity": r["severity"],
                    "enabled": bool(r["enabled"]),
                    "description": r["description"],
                })
        finally:
            conn.close()

    return {
        "items": items,
    }
