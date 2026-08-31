"""Persistent orchestration for the unified action API."""

from __future__ import annotations

import base64
import concurrent.futures
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import queue
import threading
from typing import Any, Dict, List, Optional
import uuid

# Maximum number of concurrent `DEPLOY_PACKAGE` transfers to active clients.
# Keeps chunk-stream threads from saturating the TCP server's event loop or
# starving heartbeat processing for uninvolved clients.
DEPLOY_PACKAGE_MAX_CONCURRENT = 5

from database import get_connection
from server_components import server_lib
from server_components.action_framework import (
    ActionState,
    ActionType,
    LEGACY_SCREENSHOT_COMMAND,
    normalize_action_name,
    summarize_action_progress,
)
from server_components.client_health import record_client_health
from server_components.package_service import (
    MAX_PACKAGE_SIZE_BYTES,
    calculate_sha256_file,
    get_package,
    get_package_path,
)

# Maximum package payload accepted for DEPLOY_PACKAGE (raw zip bytes).
DEPLOY_PACKAGE_MAX_BYTES = MAX_PACKAGE_SIZE_BYTES


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _action_id(payload: Dict[str, Any]) -> str:
    supplied = payload.get("action_id") or payload.get("idempotency_key")
    return str(supplied).strip() if supplied else uuid.uuid4().hex


def _json(value: Any) -> str:
    from api_server import DecimalJSONEncoder

    return json.dumps(value, ensure_ascii=False, cls=DecimalJSONEncoder)


def _sanitize_action_parameters(action_type: str, parameters: Any) -> Any:
    """Strip bulky package payloads before persisting action parameters in MySQL."""
    if action_type != ActionType.DEPLOY_PACKAGE.value:
        return parameters or {}
    if not isinstance(parameters, dict):
        return {}
    sanitized = dict(parameters)
    sanitized.pop("package_data_base64", None)
    sanitized.pop("package_bytes", None)
    sanitized.pop("package_path", None)
    return sanitized


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
            (
                action_id,
                normalized,
                requested_by,
                ActionState.PENDING.value,
                _json(_sanitize_action_parameters(normalized, parameters)),
            ),
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
        stored_parameters = _sanitize_action_parameters(normalized, parameters)
        return {
            "action_id": action_id,
            "action_type": normalized,
            "requested_by": requested_by,
            "status": ActionState.PENDING.value,
            "parameters": stored_parameters,
            "targets": list(dict.fromkeys(targets)),
        }
    finally:
        cursor.close()
        conn.close()


def _transport_command(action_type: str) -> str:
    if action_type == ActionType.SCREENSHOT.value:
        return LEGACY_SCREENSHOT_COMMAND
    return action_type


def _deploy_transfer_timeout_seconds(total_size: int, chunk_size: int) -> float:
    """Scale watchdog timeout with package size (3s per chunk, minimum 5 minutes)."""
    total_chunks = max(1, math.ceil(total_size / chunk_size)) if total_size > 0 else 1
    return max(300.0, float(total_chunks) * 3.0)


def _resolve_package_source(params: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve package metadata and optional in-memory bytes for deployment."""
    package_record = None
    pkg_path: Optional[Path] = None
    raw_bytes: Optional[bytes] = None

    if "package_bytes" in params and isinstance(params["package_bytes"], (bytes, bytearray)):
        raw_bytes = bytes(params["package_bytes"])
    elif "package_data_base64" in params and isinstance(params["package_data_base64"], str):
        try:
            raw_bytes = base64.b64decode(params["package_data_base64"], validate=True)
        except Exception as exc:
            return {
                "error": {
                    "status": "error",
                    "message": f"Invalid base64 package data: {exc}",
                }
            }
    elif "package_path" in params and isinstance(params["package_path"], str):
        pkg_path = Path(params["package_path"])
        if not pkg_path.is_file():
            return {
                "error": {
                    "status": "error",
                    "message": f"Package file not found: {pkg_path}",
                }
            }
    else:
        package_ref = str(params.get("package_id") or "").strip()
        if not package_ref:
            return {
                "error": {
                    "status": "error",
                    "message": (
                        "No package reference provided (must supply package_id, package_path, "
                        "package_data_base64, or package_bytes)."
                    ),
                }
            }
        package_record = get_package(package_ref)
        if not package_record:
            return {
                "error": {
                    "status": "error",
                    "message": f"Package '{package_ref}' was not found.",
                }
            }
        pkg_path = get_package_path(package_ref)
        if pkg_path is None:
            return {
                "error": {
                    "status": "error",
                    "message": f"Package file for '{package_ref}' is missing from storage.",
                }
            }

    if pkg_path is not None:
        try:
            total_size = pkg_path.stat().st_size
        except OSError as exc:
            return {
                "error": {
                    "status": "error",
                    "message": f"Could not read package file: {exc}",
                }
            }
        sha256 = (
            str(package_record.get("sha256")).lower()
            if package_record and package_record.get("sha256")
            else calculate_sha256_file(pkg_path)
        )
        package_id = str(
            package_record.get("package_id")
            if package_record
            else params.get("package_id") or pkg_path.stem
        ).strip()
    else:
        assert raw_bytes is not None
        total_size = len(raw_bytes)
        sha256 = hashlib.sha256(raw_bytes).hexdigest().lower()
        package_id = str(params.get("package_id") or "update-package").strip()

    if total_size > DEPLOY_PACKAGE_MAX_BYTES:
        return {
            "error": {
                "status": "error",
                "message": (
                    f"Package too large: {total_size} bytes exceeds limit of "
                    f"{DEPLOY_PACKAGE_MAX_BYTES} bytes ({DEPLOY_PACKAGE_MAX_BYTES // (1024 * 1024)} MB)."
                ),
            }
        }

    return {
        "package_id": package_id,
        "sha256": sha256,
        "total_size": total_size,
        "pkg_path": pkg_path,
        "raw_bytes": raw_bytes,
    }


def deploy_package_to_client(
    client_id: str,
    action_id: str,
    parameters: Any = None,
) -> Dict[str, Any]:
    """Stream a deployment package zip to a target client in chunks and verify."""
    params = parameters if isinstance(parameters, dict) else {}
    resolved = _resolve_package_source(params)
    if "error" in resolved:
        return resolved["error"]

    sha256 = resolved["sha256"]
    total_size = resolved["total_size"]
    pkg_path = resolved.get("pkg_path")
    raw_bytes = resolved.get("raw_bytes")
    package_id = resolved["package_id"]
    chunk_size = max(1, int(params.get("chunk_size", 131072)))
    total_chunks = max(1, math.ceil(total_size / chunk_size)) if total_size > 0 else 1

    client = server_lib.get_client(client_id)
    if not client:
        return {"status": "error", "message": f"Client '{client_id}' is not connected."}
    conn = client["connection"]
    mac = client.get("mac") or ""

    # Step 1: Send DEPLOY_PACKAGE_INIT command
    init_args = {
        "action_id": action_id,
        "package_id": package_id,
        "sha256": sha256,
        "total_size": total_size,
        "chunk_size": chunk_size,
        "total_chunks": total_chunks,
    }
    init_res = server_lib.execute_client_command(
        client_id,
        "DEPLOY_PACKAGE_INIT",
        init_args,
        timeout=15.0,
    )
    if init_res.get("status") != "ok":
        return {
            "status": "error",
            "message": f"Client init failed: {init_res.get('message')}",
        }

    init_data = init_res.get("data")
    if not isinstance(init_data, dict) or init_data.get("status") != "ready":
        err_msg = (
            init_data.get("message")
            if isinstance(init_data, dict)
            else "Client returned invalid init response."
        )
        return {"status": "error", "message": f"Client not ready: {err_msg}"}

    # Mark target as RUNNING in database
    try:
        db_conn = get_connection()
        if db_conn:
            db_cur = db_conn.cursor()
            db_cur.execute(
                """UPDATE action_targets at
                   JOIN actions a ON a.id = at.action_id
                   JOIN clients c ON c.id = at.client_id
                   SET at.status = %s, at.started_at = %s
                   WHERE a.action_id = %s AND c.client_id = %s""",
                (ActionState.RUNNING.value, _now(), action_id, client_id),
            )
            db_conn.commit()
            db_cur.close()
            if db_conn.is_connected():
                db_conn.close()
    except Exception:
        pass

    # Step 2: Stream PACKAGE_CHUNK frames
    result_queue = server_lib.register_package_result_waiter(action_id, mac)
    try:
        if pkg_path is not None:
            with pkg_path.open("rb") as package_file:
                for seq in range(1, total_chunks + 1):
                    chunk_raw = package_file.read(chunk_size)
                    if not chunk_raw:
                        break
                    chunk_b64 = base64.b64encode(chunk_raw).decode("ascii")
                    frame = {
                        "type": "PACKAGE_CHUNK",
                        "action_id": action_id,
                        "package_id": package_id,
                        "seq": seq,
                        "total_chunks": total_chunks,
                        "data": chunk_b64,
                    }
                    with client["send_lock"]:
                        server_lib.send_message(conn, frame)
        else:
            assert raw_bytes is not None
            for seq in range(1, total_chunks + 1):
                start_idx = (seq - 1) * chunk_size
                end_idx = min(total_size, seq * chunk_size)
                chunk_raw = raw_bytes[start_idx:end_idx]
                chunk_b64 = base64.b64encode(chunk_raw).decode("ascii")

                frame = {
                    "type": "PACKAGE_CHUNK",
                    "action_id": action_id,
                    "package_id": package_id,
                    "seq": seq,
                    "total_chunks": total_chunks,
                    "data": chunk_b64,
                }

                with client["send_lock"]:
                    server_lib.send_message(conn, frame)

        # Step 3: Wait for PACKAGE_RESULT with watchdog timeout
        timeout = float(
            params.get("timeout", _deploy_transfer_timeout_seconds(total_size, chunk_size))
        )
        try:
            result_msg = result_queue.get(timeout=timeout)
        except queue.Empty:
            return {
                "status": "error",
                "message": f"Package deployment timed out after {timeout}s waiting for verification result.",
            }

        if result_msg.get("status") == "SUCCESS":
            return {
                "status": "ok",
                "package_id": package_id,
                "sha256": result_msg.get("sha256"),
                "file_path": result_msg.get("file_path"),
                "total_bytes": result_msg.get("total_bytes", total_size),
                "message": "Package deployed and verified successfully.",
            }
        else:
            return {
                "status": "error",
                "package_id": package_id,
                "sha256": result_msg.get("sha256"),
                "message": result_msg.get("error", "Package deployment failed on client."),
            }
    except (ConnectionResetError, BrokenPipeError, OSError) as exc:
        return {"status": "error", "message": f"Client connection lost during transfer: {exc}"}
    finally:
        server_lib.unregister_package_result_waiter(action_id, mac)


def execute_action(action: Dict[str, Any]) -> Dict[str, Any]:
    action_id = action["action_id"]
    action_type = action["action_type"]
    parameters = action.get("parameters") or {}
    targets = action.get("targets") or []
    target_results = []

    # Step B.1.1: Set RUNNING at the start of execute_action before dispatching to any target
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE actions SET status = %s, started_at = %s WHERE action_id = %s",
            (ActionState.RUNNING.value, _now(), action_id),
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()
    action["status"] = ActionState.RUNNING.value
    action["started_at"] = _now().isoformat()

    # ── DEPLOY_PACKAGE: concurrent fan-out with a throttle cap ──────────────
    # Each per-client transfer can take minutes; running them sequentially
    # would multiply that delay by the number of targets. We use a
    # ThreadPoolExecutor capped at DEPLOY_PACKAGE_MAX_CONCURRENT so chunk
    # streams run in parallel without saturating the TCP server thread pool.
    # All other action types keep the original sequential loop below.
    if action_type == ActionType.DEPLOY_PACKAGE.value:
        target_results_lock = threading.Lock()

        def _deploy_one(client_id: str):
            result = deploy_package_to_client(client_id, action_id, parameters)
            ok = result.get("status") == "ok"
            entry = {
                "client_id": client_id,
                "status": ActionState.SUCCESS.value if ok else ActionState.FAILED.value,
                "result": result,
            }
            with target_results_lock:
                target_results.append(entry)
            return entry

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(len(targets), DEPLOY_PACKAGE_MAX_CONCURRENT),
            thread_name_prefix=f"deploy-{action_id[:8]}",
        ) as executor:
            futures = {executor.submit(_deploy_one, cid): cid for cid in targets}
            # Surface any unexpected exceptions rather than silently dropping them
            for future in concurrent.futures.as_completed(futures):
                try:
                    future.result()
                except Exception as exc:
                    cid = futures[future]
                    with target_results_lock:
                        target_results.append({
                            "client_id": cid,
                            "status": ActionState.FAILED.value,
                            "result": {"status": "error", "message": f"Unexpected error: {exc}"},
                        })
    else:
        # ── All other action types: original sequential dispatch ──────────────
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
            "UPDATE actions SET status = %s, completed_at = %s, result = %s WHERE action_id = %s",
            (status, _now(), _json({"targets": target_results}), action_id),
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
        action["progress"] = summarize_action_progress(action["targets"])
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
