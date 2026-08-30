"""Persistent orchestration for the unified action API."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from database import get_connection
from server_components import server_lib
from server_components.action_framework import (
    ActionState,
    ActionType,
    LEGACY_SCREENSHOT_COMMAND,
    normalize_action_name,
)
from server_components.client_health import record_client_health


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _action_id(payload: Dict[str, Any]) -> str:
    supplied = payload.get("action_id") or payload.get("idempotency_key")
    return str(supplied).strip() if supplied else uuid.uuid4().hex


def _json(value: Any) -> str:
    from api_server import DecimalJSONEncoder

    return json.dumps(value, ensure_ascii=False, cls=DecimalJSONEncoder)


def _row_to_action(row: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(row)
    for key in ("parameters", "result", "error"):
        value = result.get(key)
        if isinstance(value, str) and value:
            try:
                result[key] = json.loads(value)
            except json.JSONDecodeError:
                pass
    for key in ("created_at", "started_at", "completed_at", "expires_at"):
        if result.get(key) is not None and hasattr(result[key], "isoformat"):
            result[key] = result[key].isoformat()
    return result


def _row_to_target(row: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(row)
    for key in ("result", "error"):
        value = result.get(key)
        if isinstance(value, str) and value:
            try:
                result[key] = json.loads(value)
            except json.JSONDecodeError:
                pass
    for key in ("sent_at", "acknowledged_at", "started_at", "completed_at"):
        if result.get(key) is not None and hasattr(result[key], "isoformat"):
            result[key] = result[key].isoformat()
    return result


def create_action(
    action_type: str,
    targets: List[str],
    parameters: Any = None,
    requested_by: Optional[str] = None,
    action_id: Optional[str] = None,
) -> Dict[str, Any]:
    normalized = normalize_action_name(action_type)
    if not normalized:
        raise ValueError("Field 'action_type' is required.")
    if not targets or not all(isinstance(target, str) and target.strip() for target in targets):
        raise ValueError("Field 'targets' must contain at least one client ID.")

    action_id = action_id or uuid.uuid4().hex
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM actions WHERE action_id = %s", (action_id,))
        existing = cursor.fetchone()
        if existing:
            return _row_to_action(existing)

        cursor.execute(
            """INSERT INTO actions
               (action_id, action_type, requested_by, status, parameters)
               VALUES (%s, %s, %s, %s, %s)""",
            (action_id, normalized, requested_by, ActionState.PENDING.value, _json(parameters or {})),
        )
        action_pk = cursor.lastrowid
        for order, client_id in enumerate(dict.fromkeys(targets)):
            cursor.execute("SELECT id FROM clients WHERE client_id = %s", (client_id.strip(),))
            client = cursor.fetchone()
            if client:
                cursor.execute(
                    """INSERT INTO action_targets (action_id, client_id, target_order)
                       VALUES (%s, %s, %s)""",
                    (action_pk, client["id"], order),
                )
        conn.commit()
        return {
            "action_id": action_id,
            "action_type": normalized,
            "requested_by": requested_by,
            "status": ActionState.PENDING.value,
            "parameters": parameters or {},
            "targets": list(dict.fromkeys(targets)),
        }
    finally:
        cursor.close()
        conn.close()


def _transport_command(action_type: str) -> str:
    if action_type == ActionType.SCREENSHOT.value:
        return LEGACY_SCREENSHOT_COMMAND
    return action_type


def execute_action(action: Dict[str, Any]) -> Dict[str, Any]:
    action_id = action["action_id"]
    action_type = action["action_type"]
    parameters = action.get("parameters") or {}
    targets = action.get("targets") or []
    target_results = []

    for client_id in targets:
        if action_type == ActionType.SCREENSHOT.value:
            result = server_lib.request_client_screenshot(
                client_id, requested_by=action.get("requested_by") or "local-network-operator"
            )
            ok = result.get("status") == "completed"
        elif action_type == ActionType.ISOLATE_DEVICE.value:
            reason = (
                parameters.get("reason")
                if isinstance(parameters, dict)
                else None
            )
            result = server_lib.isolate_client(
                client_id,
                reason=reason or "Administrator requested device isolation",
            )
            ok = result.get("status") == "ok"
        elif action_type in {
            ActionType.SHUTDOWN.value,
            ActionType.RESTART.value,
            ActionType.KILL_PROCESS.value,
            ActionType.START_PROCESS.value,
            ActionType.REFRESH_HEALTH.value,
            ActionType.COLLECT_DIAGNOSTICS.value,
            ActionType.UPDATE_LOCATION.value,
            ActionType.GET_SYSTEM_INFO.value,
            ActionType.GET_NETWORK_INFO.value,
            ActionType.GET_CPU_INFO.value,
            ActionType.GET_MEMORY_INFO.value,
            ActionType.GET_DISK_INFO.value,
            ActionType.GET_PROCESSES.value,
            ActionType.GET_ACTIVITY_LOG.value,
            ActionType.PING.value,
            ActionType.DISCONNECT.value,
            ActionType.QUARANTINE_CLIENT.value,
            ActionType.RELEASE_CLIENT.value,
            ActionType.GET_QUARANTINE_STATUS.value,
            ActionType.GET_DEVICE_ISOLATION_STATUS.value,
            ActionType.UPDATE_FORBIDDEN_PROCESS_POLICY.value,
        }:
            if isinstance(parameters, dict):
                dispatch_parameters = dict(parameters)
                dispatch_parameters.setdefault("command_id", action_id)
            else:
                dispatch_parameters = parameters
            result = server_lib.execute_client_command(
                client_id, _transport_command(action_type), dispatch_parameters, timeout=12.0
            )
            ok = result.get("status") == "ok"
        else:
            result = {"status": "error", "message": f"Action '{action_type}' is not implemented."}
            ok = False
        if ok and action_type in {
            ActionType.REFRESH_HEALTH.value,
            ActionType.COLLECT_DIAGNOSTICS.value,
        }:
            record_client_health(client_id, result)
        target_results.append({"client_id": client_id, "status": ActionState.SUCCESS.value if ok else ActionState.FAILED.value, "result": result})

    successes = sum(item["status"] == ActionState.SUCCESS.value for item in target_results)
    status = (
        ActionState.SUCCESS.value if successes == len(target_results)
        else ActionState.FAILED.value if successes == 0
        else ActionState.PARTIAL_SUCCESS.value
    )
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE actions SET status = %s, started_at = %s, completed_at = %s, result = %s WHERE action_id = %s",
            (status, _now(), _now(), _json({"targets": target_results}), action_id),
        )
        for item in target_results:
            cursor.execute(
                """UPDATE action_targets at JOIN actions a ON a.id = at.action_id
                   JOIN clients c ON c.id = at.client_id
                   SET at.status = %s, at.completed_at = %s, at.result = %s, at.error = %s
                   WHERE a.action_id = %s AND c.client_id = %s""",
                (item["status"], _now(), _json(item["result"]) if item["status"] == ActionState.SUCCESS.value else None,
                 _json(item["result"]) if item["status"] == ActionState.FAILED.value else None, action_id, item["client_id"]),
            )
        conn.commit()
    finally:
        cursor.close()
        conn.close()
    return {**action, "status": status, "result": {"targets": target_results}}


def get_action(action_id: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM actions WHERE action_id = %s", (action_id,))
        row = cursor.fetchone()
        if not row:
            return None
        action = _row_to_action(row)
        cursor.execute(
            """SELECT at.*, c.client_id FROM action_targets at
               JOIN actions a ON a.id = at.action_id JOIN clients c ON c.id = at.client_id
               WHERE a.action_id = %s ORDER BY at.target_order""",
            (action_id,),
        )
        action["targets"] = [_row_to_target(item) for item in cursor.fetchall()]
        return action
    finally:
        cursor.close()
        conn.close()


def list_actions(limit: int = 50) -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM actions ORDER BY created_at DESC LIMIT %s", (max(1, min(limit, 200)),))
        return [_row_to_action(row) for row in cursor.fetchall()]
    finally:
        cursor.close()
        conn.close()


def cancel_action(action_id: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE actions SET status = %s, completed_at = %s WHERE action_id = %s AND status IN (%s, %s, %s, %s)",
            (ActionState.CANCELLED.value, _now(), action_id, ActionState.PENDING.value, ActionState.DISPATCHED.value, ActionState.ACKNOWLEDGED.value, ActionState.RUNNING.value),
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()
    return get_action(action_id)
