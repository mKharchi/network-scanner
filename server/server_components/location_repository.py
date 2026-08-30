"""Database storage repository for client location assignments."""

from __future__ import annotations

import queue
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

try:
    from database import get_connection
except ImportError:
    from ..database import get_connection

from server_components.center_layout import (
    ASSIGNABLE_LOCATION_TYPES,
    LOCATION_TYPE_PC_POSITION,
)
from server_components.location_assignment import (
    ASSIGNMENT_METHOD_MANUAL,
    ASSIGNMENT_STATUS_ASSIGNED,
    SOURCE_ADMINISTRATOR,
    assignment_payload,
    normalize_assignment_method,
    normalize_assignment_status,
    serialize_evidence,
)

LOCATION_ASSIGNMENT_QUEUE_SIZE = 256
location_assignment_queue: queue.Queue = queue.Queue(
    maxsize=LOCATION_ASSIGNMENT_QUEUE_SIZE
)
location_assignment_worker_lock = threading.Lock()
location_assignment_worker_started = False


def _iso_utc(dt: Optional[Any] = None) -> Optional[str]:
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    if hasattr(dt, "tzinfo") and dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat() if hasattr(dt, "isoformat") else str(dt)


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
        assignment = _location_assignment_from_row(row)
        if assignment is not None:
            location["assignment"] = assignment
    return location


def _location_assignment_from_row(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract hybrid assignment metadata from a clients or history row."""
    method = row.get("location_assignment_method")
    if method is None:
        method = row.get("assignment_method")
    status = row.get("location_assignment_status")
    if status is None:
        status = row.get("assignment_status")
    if not method and not status:
        return None
    return assignment_payload(
        method=method,
        status=status,
        confidence=row.get("location_confidence", row.get("confidence")),
        verified=row.get("location_verified", row.get("verified")),
        assigned_at=_iso_utc(row.get("location_assigned_at", row.get("assigned_at"))),
        assigned_by=row.get("location_assigned_by", row.get("assigned_by")),
        last_calculated_at=_iso_utc(row.get("location_last_calculated_at")),
        source=row.get("location_source", row.get("source")),
        evidence=row.get("location_evidence", row.get("evidence")),
    )


def _get_db_connection():
    try:
        from server_components import api_service

        if (
            hasattr(api_service, "get_connection")
            and hasattr(api_service.get_connection, "return_value")
        ):
            return api_service.get_connection()
    except Exception:
        pass
    return get_connection()


def write_client_location_assignment(
    client_id: str,
    location_id: int,
    assigned_by: Optional[str] = None,
    *,
    method: str = ASSIGNMENT_METHOD_MANUAL,
    status: str = ASSIGNMENT_STATUS_ASSIGNED,
    confidence: Optional[float] = None,
    verified: Optional[bool] = None,
    source: Optional[str] = None,
    evidence: Any = None,
    last_calculated_at: Optional[Any] = None,
) -> Dict[str, Any]:
    """Execute the database writes for assigning a client to a physical location."""
    assignment_method = normalize_assignment_method(method)
    assignment_status = normalize_assignment_status(status)
    if verified is None:
        verified = assignment_method == ASSIGNMENT_METHOD_MANUAL
    if source is None:
        source = (
            SOURCE_ADMINISTRATOR
            if assignment_method == ASSIGNMENT_METHOD_MANUAL
            else "localization_engine"
        )
    evidence_json = serialize_evidence(evidence)

    conn = _get_db_connection()
    if not conn:
        raise ValueError("Database unavailable.")
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """SELECT id, client_id, location_id,
                      location_assignment_method, location_assignment_status
               FROM clients WHERE client_id = %s""",
            (client_id,),
        )
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

        location_changed = client["location_id"] != location_id
        if location_changed:
            cursor.execute(
                "UPDATE client_location_history SET unassigned_at = CURRENT_TIMESTAMP WHERE client_id = %s AND unassigned_at IS NULL",
                (client["id"],),
            )
            cursor.execute(
                """UPDATE clients
                   SET location_id = %s,
                       location_assignment_method = %s,
                       location_assignment_status = %s,
                       location_confidence = %s,
                       location_verified = %s,
                       location_assigned_at = CURRENT_TIMESTAMP,
                       location_assigned_by = %s,
                       location_last_calculated_at = %s,
                       location_source = %s,
                       location_evidence = %s,
                       location_failure_reason = NULL
                   WHERE id = %s""",
                (
                    location_id,
                    assignment_method,
                    assignment_status,
                    confidence,
                    bool(verified),
                    assigned_by,
                    last_calculated_at,
                    source,
                    evidence_json,
                    client["id"],
                ),
            )
            cursor.execute(
                """INSERT INTO client_location_history (
                       client_id, location_id, assigned_by,
                       assignment_method, assignment_status, confidence,
                       verified, source, evidence
                   ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    client["id"],
                    location_id,
                    assigned_by,
                    assignment_method,
                    assignment_status,
                    confidence,
                    bool(verified),
                    source,
                    evidence_json,
                ),
            )
        else:
            # Same seat: refresh assignment metadata (e.g. confirm / recalculate accept).
            cursor.execute(
                """UPDATE clients
                   SET location_assignment_method = %s,
                       location_assignment_status = %s,
                       location_confidence = %s,
                       location_verified = %s,
                       location_assigned_at = COALESCE(location_assigned_at, CURRENT_TIMESTAMP),
                       location_assigned_by = COALESCE(%s, location_assigned_by),
                       location_last_calculated_at = COALESCE(%s, location_last_calculated_at),
                       location_source = %s,
                       location_evidence = %s,
                       location_failure_reason = NULL
                   WHERE id = %s""",
                (
                    assignment_method,
                    assignment_status,
                    confidence,
                    bool(verified),
                    assigned_by,
                    last_calculated_at,
                    source,
                    evidence_json,
                    client["id"],
                ),
            )
        conn.commit()
        try:
            from server_components import event_broadcaster

            event_broadcaster.broadcast_client_location_updated(
                client_id=client_id,
                location=_location_from_row({
                    **location,
                    "client_id": client_id,
                    "location_assignment_method": assignment_method,
                    "location_assignment_status": assignment_status,
                    "location_confidence": confidence,
                    "location_verified": bool(verified),
                    "location_assigned_at": datetime.now(timezone.utc),
                    "location_assigned_by": assigned_by,
                    "location_last_calculated_at": last_calculated_at,
                    "location_source": source,
                    "location_evidence": evidence_json,
                }),
                assignment=assignment_payload(
                    method=assignment_method,
                    status=assignment_status,
                    confidence=confidence,
                    verified=bool(verified),
                    assigned_at=datetime.now(timezone.utc).isoformat(),
                    assigned_by=assigned_by,
                    last_calculated_at=_iso_utc(last_calculated_at),
                    source=source,
                    evidence=evidence_json,
                ),
                previous_location_id=client["location_id"] if location_changed else location_id,
                change="moved" if location_changed and client["location_id"] is not None else "assigned",
            )
        except Exception:
            # Database assignment remains authoritative if SSE delivery fails.
            pass

        assigned = _location_from_row({
            **location,
            "client_id": client_id,
            "location_assignment_method": assignment_method,
            "location_assignment_status": assignment_status,
            "location_confidence": confidence,
            "location_verified": bool(verified),
            "location_assigned_at": datetime.now(timezone.utc),
            "location_assigned_by": assigned_by,
            "location_last_calculated_at": last_calculated_at,
            "location_source": source,
            "location_evidence": evidence_json,
        }) or {}
        return assigned
    finally:
        conn.close()


def _run_location_assignment_worker():
    """Process location assignments sequentially to eliminate occupant-check TOCTOU races."""
    while True:
        task = location_assignment_queue.get()
        resp_q = task.get("response_queue")
        try:
            result = write_client_location_assignment(
                client_id=task["client_id"],
                location_id=task["location_id"],
                assigned_by=task.get("assigned_by"),
                method=task.get("method", ASSIGNMENT_METHOD_MANUAL),
                status=task.get("status", ASSIGNMENT_STATUS_ASSIGNED),
                confidence=task.get("confidence"),
                verified=task.get("verified"),
                source=task.get("source"),
                evidence=task.get("evidence"),
                last_calculated_at=task.get("last_calculated_at"),
            )
            if resp_q:
                resp_q.put({"status": "ok", "data": result})
        except Exception as error:
            if resp_q:
                resp_q.put({"status": "error", "error": error})
        finally:
            location_assignment_queue.task_done()


def ensure_location_assignment_worker_started():
    """Ensure the singleton location assignment worker thread is active."""
    global location_assignment_worker_started
    with location_assignment_worker_lock:
        if not location_assignment_worker_started:
            threading.Thread(
                target=_run_location_assignment_worker,
                daemon=True,
                name="location-assignment-worker",
            ).start()
            location_assignment_worker_started = True


def submit_client_location_assignment(
    client_id: str,
    location_id: int,
    assigned_by: Optional[str] = None,
    *,
    method: str = ASSIGNMENT_METHOD_MANUAL,
    status: str = ASSIGNMENT_STATUS_ASSIGNED,
    confidence: Optional[float] = None,
    verified: Optional[bool] = None,
    source: Optional[str] = None,
    evidence: Any = None,
    last_calculated_at: Optional[Any] = None,
    timeout: float = 10.0,
) -> Dict[str, Any]:
    """Enqueue a location assignment and block until completed or timed out."""
    ensure_location_assignment_worker_started()
    resp_q = queue.Queue(maxsize=1)
    task = {
        "client_id": client_id,
        "location_id": location_id,
        "assigned_by": assigned_by,
        "method": method,
        "status": status,
        "confidence": confidence,
        "verified": verified,
        "source": source,
        "evidence": evidence,
        "last_calculated_at": last_calculated_at,
        "response_queue": resp_q,
    }
    try:
        location_assignment_queue.put(task, timeout=min(timeout, 5.0))
    except queue.Full:
        raise RuntimeError("Location assignment queue is busy, please try again.")

    try:
        response = resp_q.get(timeout=timeout)
    except queue.Empty:
        raise TimeoutError("Location assignment timed out waiting for worker execution.")

    if response.get("status") == "ok":
        return response["data"]
    error = response.get("error")
    if isinstance(error, Exception):
        raise error
    raise RuntimeError(str(error or "Location assignment failed."))
