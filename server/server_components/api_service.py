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

from server_components.center_layout import ASSIGNABLE_LOCATION_TYPES, LOCATION_TYPE_PC_POSITION
from server_components.physical_layout import available_floors, build_floor_layout
from server_components.physical_neighbors import classify_physical_neighbor, neighbor_sort_key
from server_components.client_health import health_payload
from server_components.server_lib import (
    clients as memory_clients,
    client_quarantine_status,
    clients_lock,
    device_isolation_status,
    get_working_hours_status,
)


def _iso_utc(dt: Optional[Any]) -> Optional[str]:
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    if hasattr(dt, "tzinfo"):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    return str(dt)


def _format_mac(mac: Optional[str]) -> Optional[str]:
    if not mac:
        return None
    return mac.upper().replace("-", ":")


def _location_from_row(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    location_type = row.get("location_type") or LOCATION_TYPE_PC_POSITION
    column = row.get("row_no")
    location = {
        "id": row.get("id"),
        "floor": row.get("floor"),
        "location_type": location_type,
        "zone_type": row.get("zone_type"),
        "zone_name": row.get("zone_name"),
        "aisle": row.get("aisle"),
        "table": row.get("table_no"),
        "row": column,
        "column": column,
        "position": row.get("position"),
        "label": row.get("label"),
        "parent_id": row.get("parent_id"),
        "x": row.get("x"),
        "y": row.get("y"),
        "z": row.get("z"),
        "is_restricted": bool(row.get("is_restricted")),
        "assignable": location_type in ASSIGNABLE_LOCATION_TYPES,
    }
    if row.get("metadata"):
        location["metadata"] = row["metadata"]
    if row.get("hostname") is not None:
        location["hostname"] = row["hostname"]
    if row.get("client_id") is not None:
        location["client_id"] = row["client_id"]
        location["client_state"] = row.get("client_state", "OFFLINE")
        location["health"] = row.get("health")
        location["health_status"] = (row.get("health") or {}).get("status")
    return location


def _numeric(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _open_alert_severity_by_client(cursor) -> Dict[str, str]:
    cursor.execute(
        """
        SELECT c.client_id,
               MAX(CASE a.severity
                     WHEN 'CRITICAL' THEN 4
                     WHEN 'HIGH' THEN 3
                     WHEN 'MEDIUM' THEN 2
                     WHEN 'LOW' THEN 1
                     ELSE 0 END) AS severity_rank
        FROM alerts a
        JOIN clients c ON c.id = a.client_id
        WHERE a.status = 'NEW'
        GROUP BY c.client_id
        """
    )
    rank_to_name = {4: "CRITICAL", 3: "HIGH", 2: "MEDIUM", 1: "LOW"}
    severities = {}
    for row in cursor.fetchall():
        rank = int(row.get("severity_rank") or 0)
        client_id = row.get("client_id")
        if rank and client_id:
            severities[client_id] = rank_to_name[rank]
    return severities


def _health_from_row(
    row: Dict[str, Any],
    *,
    client_id: Optional[str],
    connection_state: Optional[str],
    open_alert_severity: Optional[str] = None,
    shows_clients: bool = True,
) -> Dict[str, Any]:
    return health_payload(
        client_id=client_id,
        connection_state=connection_state,
        cpu_percent=_numeric(row.get("health_cpu_percent")),
        memory_percent=_numeric(row.get("health_memory_percent")),
        disk_percent=_numeric(row.get("health_disk_percent")),
        open_alert_severity=open_alert_severity,
        updated_at=_iso_utc(row.get("health_updated_at")),
        shows_clients=shows_clients,
    )


def _client_location_from_row(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if row.get("location_id") is None:
        return None
    return _location_from_row(
        {
            "id": row.get("location_id"),
            "floor": row.get("location_floor"),
            "zone_type": row.get("location_zone_type"),
            "zone_name": row.get("location_zone_name"),
            "location_type": row.get("location_type") or LOCATION_TYPE_PC_POSITION,
            "aisle": row.get("location_aisle"),
            "table_no": row.get("location_table"),
            "row_no": row.get("location_row"),
            "position": row.get("location_position"),
            "label": row.get("location_label"),
            "client_id": row.get("client_id"),
        }
    )


def list_locations(*, assignable_only: bool = False) -> List[Dict[str, Any]]:
    conn = get_connection()
    if not conn:
        return []
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """SELECT l.*, c.client_id, c.hostname, c.mac,
                      c.health_cpu_percent, c.health_memory_percent,
                      c.health_disk_percent, c.health_updated_at
               FROM locations l LEFT JOIN clients c ON c.location_id = l.id
               ORDER BY l.floor, l.zone_type, l.zone_name, l.aisle, l.table_no, l.row_no, l.position"""
        )
        rows = cursor.fetchall()
        alert_severities = _open_alert_severity_by_client(cursor)
        with clients_lock:
            online_macs = set(memory_clients.keys())
        locations = []
        for row in rows:
            if row.get("client_id"):
                isolation_info = _get_isolation_info(row["client_id"])
                row["client_state"] = "ISOLATED" if isolation_info else (
                    "ONLINE" if _format_mac(row.get("mac")) in online_macs else "OFFLINE"
                )
                row["health"] = _health_from_row(
                    row,
                    client_id=row["client_id"],
                    connection_state=row["client_state"],
                    open_alert_severity=alert_severities.get(row["client_id"]),
                )
            locations.append(_location_from_row(row))
        if assignable_only:
            return [item for item in locations if item and item.get("assignable")]
        return locations
    finally:
        conn.close()


def get_location_layout(floor: int) -> Dict[str, Any]:
    locations = list_locations()
    layout = build_floor_layout(locations, floor)
    layout["available_floors"] = available_floors(locations)
    return layout


def get_location(location_id: int) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    if not conn:
        return None
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """SELECT l.*, c.client_id, c.hostname, c.mac,
                      c.health_cpu_percent, c.health_memory_percent,
                      c.health_disk_percent, c.health_updated_at
               FROM locations l LEFT JOIN clients c ON c.location_id = l.id
               WHERE l.id = %s""",
            (location_id,),
        )
        row = cursor.fetchone()
        if row and row.get("client_id"):
            isolation_info = _get_isolation_info(row["client_id"])
            with clients_lock:
                online_macs = set(memory_clients.keys())
            row["client_state"] = "ISOLATED" if isolation_info else (
                "ONLINE" if _format_mac(row.get("mac")) in online_macs else "OFFLINE"
            )
            alert_severities = _open_alert_severity_by_client(cursor)
            row["health"] = _health_from_row(
                row,
                client_id=row["client_id"],
                connection_state=row["client_state"],
                open_alert_severity=alert_severities.get(row["client_id"]),
            )
        return _location_from_row(row)
    finally:
        conn.close()


def get_location_clients(location_id: int) -> List[Dict[str, Any]]:
    conn = get_connection()
    if not conn:
        return []
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """SELECT client_id, hostname, ip, mac, os_system, os_release, os_version, os_machine
               FROM clients WHERE location_id = %s ORDER BY hostname, client_id""",
            (location_id,),
        )
        return list(cursor.fetchall())
    finally:
        conn.close()


def get_client_location(client_id: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    if not conn:
        return None
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """SELECT l.*, c.client_id
               FROM clients c LEFT JOIN locations l ON l.id = c.location_id
               WHERE c.client_id = %s""",
            (client_id,),
        )
        row = cursor.fetchone()
        return _location_from_row(row) if row and row.get("id") is not None else None
    finally:
        conn.close()


def get_client_location_history(client_id: str) -> List[Dict[str, Any]]:
    conn = get_connection()
    if not conn:
        return []
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """SELECT h.id, h.assigned_at, h.unassigned_at, h.assigned_by,
                      l.id AS location_id, l.floor, l.zone_type, l.zone_name,
                      l.aisle, l.table_no, l.row_no, l.position, l.label
               FROM client_location_history h
               JOIN clients c ON c.id = h.client_id
               JOIN locations l ON l.id = h.location_id
               WHERE c.client_id = %s ORDER BY h.assigned_at DESC""",
            (client_id,),
        )
        history = []
        for row in cursor.fetchall():
            item = {
                "id": row["id"],
                "assigned_at": _iso_utc(row["assigned_at"]),
                "unassigned_at": _iso_utc(row["unassigned_at"]),
                "assigned_by": row["assigned_by"],
                "location": _location_from_row({**row, "id": row["location_id"]}),
            }
            history.append(item)
        return history
    finally:
        conn.close()


def get_physical_neighbors(client_id: str, limit: int = 8) -> List[Dict[str, Any]]:
    conn = get_connection()
    if not conn:
        return []
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """SELECT l.floor, l.zone_type, l.zone_name, l.aisle, l.table_no, l.row_no, l.position
               FROM clients c JOIN locations l ON l.id = c.location_id
               WHERE c.client_id = %s""",
            (client_id,),
        )
        origin = cursor.fetchone()
        if not origin:
            return []
        cursor.execute(
            """SELECT c.client_id, c.hostname, c.ip, c.mac,
                      l.id AS location_id, l.floor, l.zone_type, l.zone_name,
                      l.aisle, l.table_no, l.row_no, l.position, l.label
               FROM clients c JOIN locations l ON l.id = c.location_id
               WHERE l.floor = %s AND c.client_id <> %s""",
            (origin["floor"], client_id),
        )
        neighbors = []
        with clients_lock:
            online_macs = set(memory_clients.keys())
        for row in cursor.fetchall():
            classified = classify_physical_neighbor(origin, row)
            if not classified:
                continue
            relationship, distance = classified
            isolation_info = _get_isolation_info(row["client_id"])
            state = "ISOLATED" if isolation_info else (
                "ONLINE" if _format_mac(row.get("mac")) in online_macs else "OFFLINE"
            )
            neighbors.append({
                "client_id": row["client_id"],
                "hostname": row["hostname"] or "Unknown",
                "ip_address": row["ip"],
                "mac_address": _format_mac(row["mac"]),
                "state": state,
                "relationship": relationship,
                "distance": distance,
                "location": _location_from_row({
                    **row,
                    "id": row["location_id"],
                    "client_id": row["client_id"],
                    "client_state": state,
                }),
            })
        neighbors.sort(key=neighbor_sort_key)
        return neighbors[: max(1, min(limit, 50))]
    finally:
        conn.close()


def assign_client_location(
    client_id: str,
    location_id: int,
    assigned_by: Optional[str] = None,
) -> Dict[str, Any]:
    conn = get_connection()
    if not conn:
        raise ValueError("Database unavailable.")
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, client_id, location_id FROM clients WHERE client_id = %s", (client_id,))
        client = cursor.fetchone()
        if not client:
            raise ValueError(f"Client '{client_id}' not found.")
        cursor.execute("SELECT * FROM locations WHERE id = %s", (location_id,))
        location = cursor.fetchone()
        if not location:
            raise ValueError(f"Location '{location_id}' not found.")
        if (location.get("location_type") or LOCATION_TYPE_PC_POSITION) not in ASSIGNABLE_LOCATION_TYPES:
            raise ValueError(
                f"Location '{location.get('label') or location_id}' is not an assignable PC position."
            )
        cursor.execute(
            "SELECT client_id, hostname FROM clients WHERE location_id = %s AND client_id <> %s",
            (location_id, client_id),
        )
        occupant = cursor.fetchone()
        if occupant:
            occupant_name = occupant.get("hostname") or occupant["client_id"]
            raise ValueError(f"This physical position is already assigned to {occupant_name}.")

        if client["location_id"] != location_id:
            cursor.execute(
                "UPDATE client_location_history SET unassigned_at = CURRENT_TIMESTAMP WHERE client_id = %s AND unassigned_at IS NULL",
                (client["id"],),
            )
            cursor.execute("UPDATE clients SET location_id = %s WHERE id = %s", (location_id, client["id"]))
            cursor.execute(
                """INSERT INTO client_location_history (client_id, location_id, assigned_by)
                   VALUES (%s, %s, %s)""",
                (client["id"], location_id, assigned_by),
            )
        conn.commit()
        return _location_from_row({**location, "client_id": client_id}) or {}
    finally:
        conn.close()


def create_location(payload: Dict[str, Any]) -> Dict[str, Any]:
    required = ("floor", "zone_type", "label")
    if any(payload.get(field) in (None, "") for field in required):
        raise ValueError("Fields 'floor', 'zone_type', and 'label' are required.")
    try:
        floor = int(payload["floor"])
    except (TypeError, ValueError):
        raise ValueError("Field 'floor' must be an integer.")
    location_type = str(payload.get("location_type") or LOCATION_TYPE_PC_POSITION)
    conn = get_connection()
    if not conn:
        raise ValueError("Database unavailable.")
    try:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO locations
               (floor, zone_type, zone_name, aisle, table_no, row_no, position, label, location_type)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                floor,
                str(payload["zone_type"]),
                payload.get("zone_name"),
                payload.get("aisle"),
                payload.get("table"),
                payload.get("column", payload.get("row")),
                payload.get("position"),
                str(payload["label"]),
                location_type,
            ),
        )
        location_id = cursor.lastrowid
        conn.commit()
        return get_location(location_id) or {"id": location_id, **payload}
    except Exception as exc:
        conn.rollback()
        if "duplicate" in str(exc).lower() or "unique" in str(exc).lower():
            raise ValueError("A location with this label or physical position already exists.")
        raise
    finally:
        conn.close()


def _get_isolation_info(client_id: str) -> Optional[Dict[str, Any]]:
    """Return quarantine or static-isolation details for a client."""
    with clients_lock:
        quarantine = client_quarantine_status.get(client_id)
        if quarantine and isinstance(quarantine, dict):
            return {
                "status": quarantine.get("status", "QUARANTINED"),
                "reason": quarantine.get("reason"),
                "isolated_at": quarantine.get("updated_at"),
            }
        info = device_isolation_status.get(client_id)
        if info and isinstance(info, dict) and info.get("status") in (
            "SENT",
            "ACKNOWLEDGED",
            "CONNECTION_LOST_AFTER_ISOLATION",
        ):
            return {
                "status": info.get("status"),
                "reason": info.get("reason"),
                "isolated_at": info.get("updated_at") or info.get("sent_at"),
            }
    return None


# ============================================================
# DASHBOARD
# ============================================================

def get_dashboard_data() -> Dict[str, Any]:
    """Aggregate high-level overview metrics for the operator dashboard."""
    now_iso = datetime.now(timezone.utc).isoformat()
    
    # 1. Client counts and online list
    with clients_lock:
        online_macs = set(memory_clients.keys())
        isolated_client_ids = {
            cid
            for cid, info in device_isolation_status.items()
            if isinstance(info, dict)
            and info.get("status") in (
                "SENT",
                "ACKNOWLEDGED",
                "CONNECTION_LOST_AFTER_ISOLATION",
            )
        }

    total_clients = 0
    online_count = len(online_macs)
    isolated_count = len(isolated_client_ids)
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

    offline_count = max(0, total_clients - online_count - isolated_count)
    
    # 2. Alerts count & recent list
    new_alerts = 0
    critical_alerts = 0
    recent_alerts = []
    
    unassigned_clients = 0
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

            cursor.execute("SELECT COUNT(*) AS total_unassigned FROM clients WHERE location_id IS NULL")
            unassigned_row = cursor.fetchone()
            unassigned_clients = int((unassigned_row or {}).get("total_unassigned") or 0)
                
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
                    "id": r.get("id"),
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
            "isolated": isolated_count,
            "offline": offline_count,
            "total": total_clients,
            "unassigned": unassigned_clients,
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
    location_filter: Optional[str] = None,
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
            SELECT c.id, c.client_id, c.mac, c.hostname, c.ip,
                   c.os_system, c.os_release, c.os_version, c.os_machine,
                   c.created_at, c.updated_at,
                   c.health_cpu_percent, c.health_memory_percent,
                   c.health_disk_percent, c.health_updated_at,
                   l.id AS location_id, l.floor AS location_floor,
                   l.zone_type AS location_zone_type, l.zone_name AS location_zone_name,
                   l.location_type AS location_type,
                   l.aisle AS location_aisle, l.table_no AS location_table,
                   l.row_no AS location_row, l.position AS location_position,
                   l.label AS location_label
            FROM clients c LEFT JOIN locations l ON l.id = c.location_id
        """
        params: List[Any] = []
        conditions = []

        if search:
            q = f"%{search}%"
            conditions.append("(hostname LIKE %s OR ip LIKE %s OR mac LIKE %s OR client_id LIKE %s)")
            params.extend([q, q, q, q])

        if location_filter and location_filter.lower() == "unassigned":
            conditions.append("c.location_id IS NULL")

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY updated_at DESC LIMIT %s"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()
        alert_severities = _open_alert_severity_by_client(cursor)
        for r in rows:
            cid = r["client_id"]
            norm_mac = _format_mac(r["mac"])
            is_online = norm_mac in online_macs
            isolation_info = _get_isolation_info(cid)

            if isolation_info:
                client_state = "ISOLATED"
            elif is_online:
                client_state = "ONLINE"
            else:
                client_state = "OFFLINE"

            if state_filter and state_filter.upper() != client_state:
                continue

            conn_obj: Dict[str, Any] = {
                "state": client_state,
                "last_connected_at": _iso_utc(r["updated_at"]),
                "last_disconnected_at": None,
            }
            if isolation_info:
                conn_obj["isolation"] = isolation_info

            items.append({
                "id": cid,
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
                "connection": conn_obj,
                "location": _client_location_from_row(r),
                "health": _health_from_row(
                    r,
                    client_id=cid,
                    connection_state=client_state,
                    open_alert_severity=alert_severities.get(cid),
                ),
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
            SELECT c.id, c.client_id, c.mac, c.hostname, c.ip,
                   c.os_system, c.os_release, c.os_version, c.os_machine,
                   c.created_at, c.updated_at,
                   c.health_cpu_percent, c.health_memory_percent,
                   c.health_disk_percent, c.health_updated_at,
                   l.id AS location_id, l.floor AS location_floor,
                   l.zone_type AS location_zone_type, l.zone_name AS location_zone_name,
                   l.location_type AS location_type,
                   l.aisle AS location_aisle, l.table_no AS location_table,
                   l.row_no AS location_row, l.position AS location_position,
                   l.label AS location_label
            FROM clients c LEFT JOIN locations l ON l.id = c.location_id
            WHERE c.client_id = %s
            """,
            (client_id,),
        )
        r = cursor.fetchone()
        if not r:
            return None

        norm_mac = _format_mac(r["mac"])
        is_online = norm_mac in online_macs
        isolation_info = _get_isolation_info(client_id)

        if isolation_info:
            client_state = "ISOLATED"
        elif is_online:
            client_state = "ONLINE"
        else:
            client_state = "OFFLINE"

        db_id = r["id"]

        conn_obj: Dict[str, Any] = {
            "state": client_state,
            "last_connected_at": _iso_utc(r["updated_at"]),
            "last_disconnected_at": None,
        }
        if isolation_info:
            conn_obj["isolation"] = isolation_info

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
            "connection": conn_obj,
            "location": _client_location_from_row(r),
            "health": _health_from_row(
                r,
                client_id=client_id,
                connection_state=client_state,
                open_alert_severity=_open_alert_severity_by_client(cursor).get(client_id),
            ),
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


def list_client_screenshots(client_id: str, limit: int = 12) -> Optional[List[Dict[str, Any]]]:
    """List stored screenshots for one managed client."""
    if limit <= 0:
        limit = 12

    conn = get_connection()
    if not conn:
        return None

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id
            FROM clients
            WHERE client_id = %s
            """,
            (client_id,),
        )
        client_row = cursor.fetchone()
        if not client_row:
            return None

        cursor.execute(
            """
            SELECT id, command_id, requested_by, filename, mime_type,
                   file_size, device_name, captured_at, uploaded_at, status
            FROM screenshots
            WHERE client_id = %s
            ORDER BY uploaded_at DESC, id DESC
            LIMIT %s
            """,
            (client_row["id"], limit),
        )
        items: List[Dict[str, Any]] = []
        for row in cursor.fetchall():
            items.append(
                {
                    "id": row["id"],
                    "client_id": client_id,
                    "command_id": row.get("command_id"),
                    "requested_by": row.get("requested_by"),
                    "filename": row["filename"],
                    "mime_type": row["mime_type"],
                    "file_size": row["file_size"],
                    "device_name": row.get("device_name"),
                    "captured_at": _iso_utc(row.get("captured_at")),
                    "uploaded_at": _iso_utc(row.get("uploaded_at")),
                    "status": row["status"],
                }
            )
        return items
    finally:
        conn.close()


def get_screenshot_record(screenshot_id: int) -> Optional[Dict[str, Any]]:
    """Return one screenshot metadata row with its backing storage path."""
    conn = get_connection()
    if not conn:
        return None

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT s.id, c.client_id, s.command_id, s.requested_by, s.filename,
                   s.storage_path, s.mime_type, s.file_size, s.device_name,
                   s.captured_at, s.uploaded_at, s.status
            FROM screenshots s
            JOIN clients c ON c.id = s.client_id
            WHERE s.id = %s
            """,
            (screenshot_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "client_id": row["client_id"],
            "command_id": row.get("command_id"),
            "requested_by": row.get("requested_by"),
            "filename": row["filename"],
            "storage_path": row["storage_path"],
            "mime_type": row["mime_type"],
            "file_size": row["file_size"],
            "device_name": row.get("device_name"),
            "captured_at": _iso_utc(row.get("captured_at")),
            "uploaded_at": _iso_utc(row.get("uploaded_at")),
            "status": row["status"],
        }
    finally:
        conn.close()


# ============================================================
# NETWORK SCANS & DEVICES
# ============================================================

def get_latest_scan() -> Optional[Dict[str, Any]]:
    """Read the latest completed network scan JSON file from disk."""
    scan_dir = NETWORK_SCAN_STORAGE_DIR
    if not scan_dir.is_dir():
        try:
            scan_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            return None

    json_files = sorted(
        list(scan_dir.glob("*.json")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not json_files:
        try:
            from server_components.network_discovery import run_manual_scan
            _, _, scan_path = run_manual_scan()
            return _parse_scan_file(Path(scan_path))
        except Exception:
            return None

    for scan_file in json_files:
        parsed = _parse_scan_file(scan_file)
        if parsed is not None:
            return parsed
    return None


def list_scans(from_date: Optional[str] = None, to_date: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """List historical completed scans, with at most one new file per day."""
    scan_dir = NETWORK_SCAN_STORAGE_DIR
    if not scan_dir.is_dir():
        return []

    json_files = sorted(
        list(scan_dir.glob("*.json")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    items = []
    for p in json_files:
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
                completed_at = data.get("completed_at", "")
                if not isinstance(data.get("devices"), list) or not completed_at:
                    continue
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

        mac_list = [
            _format_mac(d.get("mac_address"))
            for d in classified
            if d.get("mac_address")
        ]
        db_device_map = {}
        if mac_list:
            try:
                conn = get_connection()
                if conn:
                    cursor = conn.cursor(dictionary=True)
                    placeholders = ", ".join(["%s"] * len(mac_list))
                    cursor.execute(
                        f"SELECT mac_address, last_seen, first_seen FROM network_devices WHERE mac_address IN ({placeholders})",
                        mac_list,
                    )
                    for row in cursor.fetchall():
                        db_device_map[_format_mac(row["mac_address"])] = row
                    cursor.close()
                    if conn.is_connected():
                        conn.close()
            except Exception:
                pass

        formatted_devices = []
        for d in classified:
            norm_mac = _format_mac(d.get("mac_address"))
            db_row = db_device_map.get(norm_mac, {})

            # Resolve actual last seen timestamp from database or observation sources
            actual_last_seen = None
            if db_row and db_row.get("last_seen"):
                actual_last_seen = _iso_utc(db_row["last_seen"])

            if not actual_last_seen:
                obs_sources = d.get("observation_sources") or []
                obs_timestamps = [
                    s.get("observed_at")
                    for s in obs_sources
                    if isinstance(s, dict) and s.get("observed_at")
                ]
                if obs_timestamps:
                    actual_last_seen = max(obs_timestamps)

            if not actual_last_seen:
                actual_last_seen = (
                    d.get("last_seen")
                    or d.get("last_observed_at")
                    or d.get("observed_at")
                    or data.get("completed_at")
                )

            formatted_devices.append({
                "mac_address": norm_mac,
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
                "last_observed_at": actual_last_seen,
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


def list_network_devices(
    search: Optional[str] = None,
    limit: int = 500,
    offset: int = 0,
) -> Dict[str, Any]:
    """Return a paginated list of all known network devices from the database."""
    conn = get_connection()
    if not conn:
        return {"devices": [], "total": 0}

    try:
        cursor = conn.cursor(dictionary=True)

        where_clause = ""
        params: list = []
        if search:
            like = f"%{search}%"
            where_clause = "WHERE (nd.mac_address LIKE %s OR nd.ip_address LIKE %s OR nd.hostname LIKE %s OR nd.vendor LIKE %s OR c.hostname LIKE %s)"
            params = [like, like, like, like, like]

        count_sql = f"""
            SELECT COUNT(*) AS total
            FROM network_devices nd
            LEFT JOIN clients c ON c.mac = nd.mac_address
            {where_clause}
        """
        cursor.execute(count_sql, params)
        total = (cursor.fetchone() or {}).get("total", 0)

        data_sql = f"""
            SELECT nd.mac_address, nd.ip_address, nd.hostname, nd.vendor,
                   nd.first_seen, nd.last_seen,
                   c.client_id AS managed_client_id,
                   c.hostname AS client_hostname
            FROM network_devices nd
            LEFT JOIN clients c ON c.mac = nd.mac_address
            {where_clause}
            ORDER BY nd.last_seen DESC
            LIMIT %s OFFSET %s
        """
        cursor.execute(data_sql, params + [limit, offset])
        rows = cursor.fetchall()

        devices = []
        for row in rows:
            is_managed = row.get("managed_client_id") is not None
            hostname = (row.get("client_hostname") if (is_managed and row.get("client_hostname")) else row.get("hostname"))
            devices.append({
                "mac_address": _format_mac(row["mac_address"]),
                "ip_address": row["ip_address"],
                "hostname": hostname,
                "vendor": row["vendor"],
                "classification": "MANAGED" if is_managed else "UNMANAGED",
                "is_managed": is_managed,
                "managed_client_id": row["managed_client_id"],
                "first_seen": _iso_utc(row["first_seen"]),
                "last_seen": _iso_utc(row["last_seen"]),
            })

        return {"devices": devices, "total": total, "limit": limit, "offset": offset}
    finally:
        conn.close()



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
        raw_rows = cursor.fetchall()
        observations = [
            {
                "source_type": row["source_type"],
                "source_client_id": row["source_client_id"],
                "ip_address": row["ip_address"],
                "interface": row["interface_name"],
                "entry_type": row["entry_type"],
                "observed_at": _iso_utc(row["observed_at"]),
            }
            for row in raw_rows
        ]

        distinct_sources = list(dict.fromkeys(row["source_type"] for row in raw_rows)) or ["CLIENT_ARP"]

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
            "sources": distinct_sources,
        }

        dhcp_observations = [
            obs for obs in observations if obs["source_type"] == "CLIENT_DHCP"
        ]

        return {
            "device": device_obj,
            "observations": observations,
            "dhcp_observations": dhcp_observations,
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

        # Alert timestamps can originate from clients in different time zones.
        # The auto-increment ID is the authoritative insertion order, so the
        # newest persisted alert cannot be hidden behind clock skew.
        query += " ORDER BY a.id DESC LIMIT %s"
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
            cursor.execute("SELECT id, process_name, severity, enabled, description FROM forbidden_processes ORDER BY process_name")
            for r in cursor.fetchall():
                items.append({
                    "id": r.get("id"),
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


def get_forbidden_process(identifier: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    if not conn:
        return None
    try:
        cursor = conn.cursor(dictionary=True)
        if identifier.isdigit():
            cursor.execute("SELECT id, process_name, severity, enabled, description FROM forbidden_processes WHERE id = %s", (int(identifier),))
        else:
            cursor.execute("SELECT id, process_name, severity, enabled, description FROM forbidden_processes WHERE process_name = %s", (identifier.strip().lower(),))
        row = cursor.fetchone()
        if not row:
            return None
        row["enabled"] = bool(row["enabled"])
        return row
    finally:
        conn.close()


FORBIDDEN_PROCESS_SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}


def _validate_forbidden_process_payload(payload: Dict[str, Any], *, require_name: bool = True) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Payload must be a JSON object.")

    process_name = str(payload.get("process_name", "")).strip().lower()
    if require_name and (not process_name or len(process_name) > 255):
        raise ValueError("process_name is required and must be at most 255 characters.")
    if process_name and any(char.isspace() for char in process_name):
        raise ValueError("process_name must be a binary name without whitespace.")

    severity = str(payload.get("severity", "HIGH")).strip().upper()
    if severity not in FORBIDDEN_PROCESS_SEVERITIES:
        raise ValueError("severity must be LOW, MEDIUM, HIGH, or CRITICAL.")

    description = payload.get("description")
    if description is not None:
        description = str(description).strip() or None
        if description and len(description) > 1000:
            raise ValueError("description must be at most 1000 characters.")

    return {
        "process_name": process_name,
        "severity": severity,
        "enabled": bool(payload.get("enabled", True)),
        "description": description,
    }


def create_forbidden_process(payload: Dict[str, Any]) -> Dict[str, Any]:
    rule = _validate_forbidden_process_payload(payload)
    conn = get_connection()
    if not conn:
        raise RuntimeError("Database connection unavailable.")
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO forbidden_processes (process_name, severity, enabled, description)
            VALUES (%s, %s, %s, %s)
            """,
            (rule["process_name"], rule["severity"], rule["enabled"], rule["description"]),
        )
        conn.commit()
        rule["id"] = cursor.lastrowid
        return rule
    except Exception as exc:
        if "duplicate" in str(exc).lower() or "unique" in str(exc).lower():
            raise ValueError(f"A rule for '{rule['process_name']}' already exists.") from exc
        raise
    finally:
        conn.close()


def update_forbidden_process(identifier: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    lookup_by_id = identifier.isdigit()
    current_name = identifier.strip().lower()
    if not current_name:
        raise ValueError("process_name is required.")
    conn = get_connection()
    if not conn:
        raise RuntimeError("Database connection unavailable.")
    try:
        cursor = conn.cursor()
        lookup_value = int(identifier) if lookup_by_id else current_name
        lookup_column = "id" if lookup_by_id else "process_name"
        if lookup_by_id:
            cursor.execute("SELECT process_name FROM forbidden_processes WHERE id = %s", (lookup_value,))
            existing = cursor.fetchone()
            if not existing:
                return None
            current_name = existing["process_name"] if isinstance(existing, dict) else existing[0]
        rule = _validate_forbidden_process_payload({**payload, "process_name": current_name})
        cursor.execute(
            f"""
            UPDATE forbidden_processes
            SET severity = %s, enabled = %s, description = %s
            WHERE {lookup_column} = %s
            """,
            (rule["severity"], rule["enabled"], rule["description"], lookup_value),
        )
        if cursor.rowcount == 0:
            return None
        conn.commit()
        rule["id"] = int(identifier) if lookup_by_id else None
        return rule
    finally:
        conn.close()


def delete_forbidden_process(identifier: str) -> bool:
    conn = get_connection()
    if not conn:
        raise RuntimeError("Database connection unavailable.")
    try:
        cursor = conn.cursor()
        if identifier.isdigit():
            cursor.execute("DELETE FROM forbidden_processes WHERE id = %s", (int(identifier),))
        else:
            cursor.execute("DELETE FROM forbidden_processes WHERE process_name = %s", (identifier.strip().lower(),))
        deleted = cursor.rowcount > 0
        if deleted:
            conn.commit()
        return deleted
    finally:
        conn.close()


# ============================================================
# SPATIAL & ROGUE DEVICE SENSORS / TRIANGULATION
# ============================================================


def list_sensors() -> List[Dict[str, Any]]:
    """Return all registered infrastructure and client sensors."""
    from server_components import spatial_engine
    return spatial_engine.list_sensors()


def create_sensor(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Register a new infrastructure sensor."""
    from server_components import spatial_engine
    sensor_id = payload.get("sensor_id") or f"sensor-{int(datetime.now(timezone.utc).timestamp())}"
    name = payload.get("name") or sensor_id
    sensor_type = payload.get("sensor_type") or payload.get("type") or "endpoint"
    location_id = payload.get("location_id")
    client_id = payload.get("client_id")
    x = payload.get("x")
    y = payload.get("y")
    z = payload.get("z")
    capabilities = payload.get("capabilities")
    return spatial_engine.register_sensor(
        sensor_id=sensor_id,
        name=name,
        sensor_type=sensor_type,
        location_id=location_id,
        client_id=client_id,
        x=float(x) if x is not None else None,
        y=float(y) if y is not None else None,
        z=float(z) if z is not None else None,
        capabilities=capabilities if isinstance(capabilities, list) else None,
    )


def get_device_spatial_location(device_identifier: Any) -> Optional[Dict[str, Any]]:
    """Return spatial location estimate, coordinates, confidence, and supporting sensors."""
    from server_components import spatial_engine
    return spatial_engine.get_device_location(device_identifier)


def get_device_spatial_history(device_identifier: Any, limit: int = 50) -> List[Dict[str, Any]]:
    """Return chronological location change and movement history for a device."""
    from server_components import spatial_engine
    return spatial_engine.get_device_location_history(device_identifier, limit=limit)


def list_rogue_devices(min_score: int = 35) -> List[Dict[str, Any]]:
    """List rogue device candidates and unmanaged endpoints sorted by threat score."""
    from server_components import spatial_engine
    return spatial_engine.list_rogue_devices(min_score=min_score)


def get_rogue_device_detail(device_identifier: Any) -> Optional[Dict[str, Any]]:
    """Return full rogue analysis report, evidence list, and spatial location for a device."""
    from server_components import spatial_engine
    loc_info = spatial_engine.get_device_location(device_identifier)
    if not loc_info:
        return None
    history = spatial_engine.get_device_location_history(device_identifier, limit=20)
    return {
        **loc_info,
        "movement_history": history,
    }


def list_spatial_events(limit: int = 50) -> List[Dict[str, Any]]:
    """Return recent global spatial localization and movement events."""
    from server_components import spatial_engine
    return spatial_engine.list_spatial_events(limit=limit)


def trigger_spatial_scan_evaluation() -> List[Dict[str, Any]]:
    """Evaluate spatial coordinates and rogue scores across all network devices."""
    from server_components import spatial_engine
    return spatial_engine.evaluate_all_devices()

