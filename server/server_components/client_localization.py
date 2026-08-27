"""Automatic localization and confidence-gated assignment for managed clients.

Reuses spatial_engine triangulation without rewriting it. Automatic assignment
only applies when a client has no protected manual location and confidence
meets the configured threshold.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from database import get_connection
from server_components.center_layout import ASSIGNABLE_LOCATION_TYPES, LOCATION_TYPE_PC_POSITION
from server_components.location_assignment import (
    ASSIGNMENT_METHOD_AUTO,
    ASSIGNMENT_METHOD_MANUAL,
    ASSIGNMENT_STATUS_ASSIGNED,
    ASSIGNMENT_STATUS_PENDING,
    SOURCE_LOCALIZATION_ENGINE,
    serialize_evidence,
)
from server_components.spatial_engine import find_closest_location, triangulate_position


DEFAULT_AUTO_CONFIDENCE_THRESHOLD = 0.80

REASON_INSUFFICIENT_EVIDENCE = "insufficient_evidence"
REASON_NO_LOCATION_MATCH = "no_location_match"
REASON_LOW_CONFIDENCE = "low_confidence"
REASON_LOCALIZATION_UNAVAILABLE = "localization_unavailable"
REASON_LOCATION_OCCUPIED = "location_occupied"
REASON_ALREADY_ASSIGNED = "already_assigned"
REASON_MANUAL_PROTECTED = "manual_assignment_protected"
REASON_CONFIRMED_PROTECTED = "confirmed_assignment_protected"
REASON_CLIENT_NOT_FOUND = "client_not_found"


def get_auto_confidence_threshold() -> float:
    raw = os.getenv(
        "CLIENT_LOCATION_AUTO_CONFIDENCE_THRESHOLD",
        str(DEFAULT_AUTO_CONFIDENCE_THRESHOLD),
    )
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_AUTO_CONFIDENCE_THRESHOLD
    return max(0.0, min(value, 1.0))


def _iso_utc(dt: Optional[Any] = None) -> str:
    value = dt or datetime.now(timezone.utc)
    if isinstance(value, str):
        return value
    if getattr(value, "tzinfo", None) is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _format_mac(mac: Optional[str]) -> Optional[str]:
    if not mac:
        return None
    return mac.upper().replace("-", ":")


def _collect_sensor_readings(cursor, *, device_id: Optional[int]) -> List[Dict[str, Any]]:
    """Build triangulation inputs from recent observations of this client's MAC."""
    readings: List[Dict[str, Any]] = []
    if not device_id:
        return readings

    cursor.execute(
        """
        SELECT o.rssi, o.switch_port,
               s.sensor_id AS sensor_code, s.x AS sensor_x, s.y AS sensor_y, s.z AS sensor_z,
               cl_loc.x AS client_x, cl_loc.y AS client_y, cl_loc.z AS client_z,
               cl.client_id AS client_code
        FROM network_device_observations o
        LEFT JOIN sensors s ON s.id = o.sensor_id
        LEFT JOIN clients cl ON cl.id = o.source_client_id
        LEFT JOIN locations cl_loc ON cl_loc.id = cl.location_id
        WHERE o.device_id = %s
        ORDER BY o.observed_at DESC
        LIMIT 50
        """,
        (device_id,),
    )
    for obs in cursor.fetchall() or []:
        sx = obs.get("sensor_x") if obs.get("sensor_x") is not None else obs.get("client_x")
        sy = obs.get("sensor_y") if obs.get("sensor_y") is not None else obs.get("client_y")
        sz = obs.get("sensor_z") if obs.get("sensor_z") is not None else obs.get("client_z")
        sensor_id = obs.get("sensor_code") or (
            f"client-{obs['client_code']}" if obs.get("client_code") else None
        )
        if sx is None or sy is None:
            continue
        readings.append({
            "sensor_id": sensor_id or "collector",
            "x": sx,
            "y": sy,
            "z": sz,
            "rssi": obs.get("rssi"),
            "switch_port": obs.get("switch_port"),
        })
    return readings


def calculate_client_location(client_id: str) -> Dict[str, Any]:
    """Run localization for a managed client without writing an assignment."""
    conn = get_connection()
    if not conn:
        return {
            "success": False,
            "location_id": None,
            "confidence": 0.0,
            "source": "automatic",
            "evidence": [],
            "reason": REASON_LOCALIZATION_UNAVAILABLE,
            "method": None,
            "coordinates": {"x": None, "y": None, "z": None},
            "calculated_at": _iso_utc(),
        }

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, client_id, mac, location_id,
                   location_assignment_method, location_assignment_status,
                   location_verified
            FROM clients
            WHERE client_id = %s
            """,
            (client_id,),
        )
        client = cursor.fetchone()
        if not client:
            return {
                "success": False,
                "location_id": None,
                "confidence": 0.0,
                "source": "automatic",
                "evidence": [],
                "reason": REASON_CLIENT_NOT_FOUND,
                "method": None,
                "coordinates": {"x": None, "y": None, "z": None},
                "calculated_at": _iso_utc(),
            }

        mac = _format_mac(client.get("mac"))
        cursor.execute(
            "SELECT id FROM network_devices WHERE mac_address = %s LIMIT 1",
            (mac,),
        )
        device = cursor.fetchone()
        device_id = device["id"] if device else None

        readings = _collect_sensor_readings(cursor, device_id=device_id)
        triangulation = triangulate_position(readings)
        evidence: Dict[str, Any] = {
            "triangulation_method": triangulation.get("method"),
            "supporting_sensors": triangulation.get("supporting_sensors") or [],
            "observation_count": len(readings),
            "device_id": device_id,
            "calculated_coordinates": {
                "x": triangulation.get("x"),
                "y": triangulation.get("y"),
                "z": triangulation.get("z"),
            },
        }

        if not readings or triangulation.get("confidence", 0) <= 0 or triangulation.get("x") is None:
            return {
                "success": False,
                "location_id": None,
                "confidence": float(triangulation.get("confidence") or 0.0),
                "source": "automatic",
                "evidence": evidence,
                "reason": REASON_INSUFFICIENT_EVIDENCE,
                "method": triangulation.get("method"),
                "coordinates": {
                    "x": triangulation.get("x"),
                    "y": triangulation.get("y"),
                    "z": triangulation.get("z"),
                },
                "calculated_at": _iso_utc(),
            }

        cursor.execute(
            "SELECT * FROM locations WHERE location_type = %s OR location_type IS NULL",
            (LOCATION_TYPE_PC_POSITION,),
        )
        locations = [
            row
            for row in (cursor.fetchall() or [])
            if (row.get("location_type") or LOCATION_TYPE_PC_POSITION) in ASSIGNABLE_LOCATION_TYPES
        ]
        nearest = find_closest_location(
            triangulation.get("x"),
            triangulation.get("y"),
            triangulation.get("z"),
            locations,
        )
        if not nearest:
            return {
                "success": False,
                "location_id": None,
                "confidence": float(triangulation.get("confidence") or 0.0),
                "source": "automatic",
                "evidence": evidence,
                "reason": REASON_NO_LOCATION_MATCH,
                "method": triangulation.get("method"),
                "coordinates": {
                    "x": triangulation.get("x"),
                    "y": triangulation.get("y"),
                    "z": triangulation.get("z"),
                },
                "calculated_at": _iso_utc(),
            }

        evidence["matched_location_label"] = nearest.get("label")
        proposed_location = {
            "id": nearest["id"],
            "label": nearest.get("label"),
            "floor": nearest.get("floor"),
        }
        confidence = float(triangulation.get("confidence") or 0.0)
        return {
            # ``success`` means a candidate was calculated. The caller still
            # gates unattended assignment by the configured confidence threshold.
            "success": True,
            "location_id": nearest["id"],
            "location": proposed_location,
            "proposed_location": proposed_location,
            "confidence": confidence,
            "source": "automatic",
            "evidence": evidence,
            "reason": None,
            "method": triangulation.get("method"),
            "coordinates": {
                "x": triangulation.get("x"),
                "y": triangulation.get("y"),
                "z": triangulation.get("z"),
            },
            "calculated_at": _iso_utc(),
        }
    finally:
        conn.close()


def _record_assignment_failure(
    client_id: str,
    *,
    reason: str,
    confidence: Optional[float] = None,
    evidence: Any = None,
) -> None:
    conn = get_connection()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE clients
            SET location_assignment_method = %s,
                location_assignment_status = %s,
                location_confidence = %s,
                location_verified = FALSE,
                location_last_calculated_at = CURRENT_TIMESTAMP,
                location_source = %s,
                location_evidence = %s,
                location_failure_reason = %s
            WHERE client_id = %s
              AND location_id IS NULL
            """,
            (
                ASSIGNMENT_METHOD_AUTO,
                ASSIGNMENT_STATUS_PENDING,
                confidence,
                SOURCE_LOCALIZATION_ENGINE,
                serialize_evidence(evidence),
                reason,
                client_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _client_assignment_guard(client_id: str) -> Optional[Dict[str, Any]]:
    """Return a skip result when auto-assignment must not overwrite the client."""
    conn = get_connection()
    if not conn:
        return {
            "success": False,
            "assigned": False,
            "reason": REASON_LOCALIZATION_UNAVAILABLE,
            "client_id": client_id,
        }
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT client_id, location_id, location_assignment_method,
                   location_assignment_status, location_verified
            FROM clients
            WHERE client_id = %s
            """,
            (client_id,),
        )
        client = cursor.fetchone()
        if not client:
            return {
                "success": False,
                "assigned": False,
                "reason": REASON_CLIENT_NOT_FOUND,
                "client_id": client_id,
            }
        if client.get("location_id") is not None:
            method = (client.get("location_assignment_method") or "").upper()
            verified = bool(client.get("location_verified"))
            status = (client.get("location_assignment_status") or "").upper()
            if method == ASSIGNMENT_METHOD_MANUAL and (verified or status == "CONFIRMED"):
                return {
                    "success": False,
                    "assigned": False,
                    "reason": REASON_MANUAL_PROTECTED,
                    "client_id": client_id,
                    "location_id": client["location_id"],
                }
            if verified or status == "CONFIRMED":
                return {
                    "success": False,
                    "assigned": False,
                    "reason": REASON_CONFIRMED_PROTECTED,
                    "client_id": client_id,
                    "location_id": client["location_id"],
                }
            # An unconfirmed AUTO assignment is intentionally eligible for a
            # fresh calculation; the caller may accept a better result or send
            # the client to the manual correction flow.
            return None
        return None
    finally:
        conn.close()


def try_automatic_client_location_assignment(
    client_id: str,
    *,
    threshold: Optional[float] = None,
) -> Dict[str, Any]:
    """Calculate location and auto-assign when confidence is sufficient."""
    from server_components import api_service

    guard = _client_assignment_guard(client_id)
    if guard is not None:
        return guard

    result = calculate_client_location(client_id)
    confidence = float(result.get("confidence") or 0.0)
    min_confidence = get_auto_confidence_threshold() if threshold is None else threshold
    calculated_at = result.get("calculated_at")

    if not result.get("success") or not result.get("location_id"):
        reason = result.get("reason") or REASON_INSUFFICIENT_EVIDENCE
        _record_assignment_failure(
            client_id,
            reason=reason,
            confidence=confidence,
            evidence=result.get("evidence"),
        )
        return {
            "success": False,
            "assigned": False,
            "client_id": client_id,
            "reason": reason,
            "confidence": confidence,
            "threshold": min_confidence,
            "evidence": result.get("evidence"),
            "localization": result,
        }

    if confidence < min_confidence:
        _record_assignment_failure(
            client_id,
            reason=REASON_LOW_CONFIDENCE,
            confidence=confidence,
            evidence=result.get("evidence"),
        )
        return {
            "success": False,
            "assigned": False,
            "client_id": client_id,
            "reason": REASON_LOW_CONFIDENCE,
            "confidence": confidence,
            "threshold": min_confidence,
            "location_id": result.get("location_id"),
            "location": result.get("location"),
            "proposed_location": result.get("proposed_location") or result.get("location"),
            "evidence": result.get("evidence"),
            "localization": result,
        }

    try:
        location = api_service.assign_client_location(
            client_id,
            int(result["location_id"]),
            assigned_by="localization_engine",
            method=ASSIGNMENT_METHOD_AUTO,
            status=ASSIGNMENT_STATUS_ASSIGNED,
            confidence=confidence,
            verified=False,
            source=SOURCE_LOCALIZATION_ENGINE,
            evidence=result.get("evidence"),
            last_calculated_at=datetime.now(timezone.utc),
        )
    except ValueError as exc:
        message = str(exc)
        reason = (
            REASON_LOCATION_OCCUPIED
            if "already assigned" in message.lower()
            else REASON_NO_LOCATION_MATCH
        )
        _record_assignment_failure(
            client_id,
            reason=reason,
            confidence=confidence,
            evidence={**(result.get("evidence") or {}), "error": message},
        )
        return {
            "success": False,
            "assigned": False,
            "client_id": client_id,
            "reason": reason,
            "confidence": confidence,
            "threshold": min_confidence,
            "message": message,
            "localization": result,
        }

    return {
        "success": True,
        "assigned": True,
        "client_id": client_id,
        "assignment": {
            "method": ASSIGNMENT_METHOD_AUTO,
            "status": ASSIGNMENT_STATUS_ASSIGNED,
            "verified": False,
        },
        "location": {
            "id": location.get("id"),
            "name": location.get("label"),
            "label": location.get("label"),
        },
        "confidence": confidence,
        "threshold": min_confidence,
        "evidence": result.get("evidence"),
        "calculated_at": calculated_at,
        "localization": result,
    }


def schedule_automatic_client_location_assignment(client_id: Optional[str]) -> None:
    """Fire-and-forget auto assignment so TCP registration is never blocked."""
    if not client_id:
        return

    def _run() -> None:
        try:
            outcome = try_automatic_client_location_assignment(client_id)
            if outcome.get("assigned"):
                label = (outcome.get("location") or {}).get("label")
                print(
                    f"Auto-assigned {client_id} → {label} "
                    f"(confidence={outcome.get('confidence')})"
                )
            else:
                print(
                    f"Auto-location pending for {client_id}: "
                    f"{outcome.get('reason')} "
                    f"(confidence={outcome.get('confidence')})"
                )
        except Exception as exc:  # noqa: BLE001 - never break client connectivity
            print(f"Auto location assignment skipped for {client_id}: {exc}")

    threading.Thread(
        target=_run,
        daemon=True,
        name=f"auto-locate-{client_id}",
    ).start()
