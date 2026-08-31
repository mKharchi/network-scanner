"""Client-side action vocabulary and dispatch helpers.

This module introduces a central action registry so the client can move away
from a single command if/elif ladder while remaining backward compatible with
the current wire protocol.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional


class ActionType(str, Enum):
    SHUTDOWN = "SHUTDOWN"
    RESTART = "RESTART"
    SCREENSHOT = "SCREENSHOT"
    KILL_PROCESS = "KILL_PROCESS"
    START_PROCESS = "START_PROCESS"
    ISOLATE_DEVICE = "ISOLATE_DEVICE"
    COLLECT_DIAGNOSTICS = "COLLECT_DIAGNOSTICS"
    REFRESH_HEALTH = "REFRESH_HEALTH"
    UPDATE_LOCATION = "UPDATE_LOCATION"
    GET_SYSTEM_INFO = "GET_SYSTEM_INFO"
    GET_NETWORK_INFO = "GET_NETWORK_INFO"
    GET_CPU_INFO = "GET_CPU_INFO"
    GET_MEMORY_INFO = "GET_MEMORY_INFO"
    GET_DISK_INFO = "GET_DISK_INFO"
    GET_PROCESSES = "GET_PROCESSES"
    GET_ACTIVITY_LOG = "GET_ACTIVITY_LOG"
    GET_NETWORK_NEIGHBOURHOOD = "GET_NETWORK_NEIGHBOURHOOD"
    GET_PASSIVE_NEIGHBOURHOOD = "GET_PASSIVE_NEIGHBOURHOOD"
    PING = "PING"
    DISCONNECT = "DISCONNECT"
    QUARANTINE_CLIENT = "QUARANTINE_CLIENT"
    RELEASE_CLIENT = "RELEASE_CLIENT"
    GET_QUARANTINE_STATUS = "GET_QUARANTINE_STATUS"
    GET_DEVICE_ISOLATION_STATUS = "GET_DEVICE_ISOLATION_STATUS"
    UPDATE_FORBIDDEN_PROCESS_POLICY = "UPDATE_FORBIDDEN_PROCESS_POLICY"
    SCAN_NETWORK = "SCAN_NETWORK"
    TRIGGER_ARP_SCAN = "TRIGGER_ARP_SCAN"
    FLUSH_NEIGHBOURHOOD_STORAGE = "FLUSH_NEIGHBOURHOOD_STORAGE"
    DEPLOY_PACKAGE = "DEPLOY_PACKAGE"


class ActionState(str, Enum):
    PENDING = "PENDING"
    DISPATCHED = "DISPATCHED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


SCREENSHOT_COMMAND = "REQUEST_SCREENSHOT"
PASSIVE_NEIGHBOURHOOD_COMMAND = "GET_PASSIVE_NEIGHBOURHOOD"
NETWORK_NEIGHBOURHOOD_COMMAND = "GET_NETWORK_NEIGHBOURHOOD"
DEPLOY_PACKAGE_INIT_COMMAND = "DEPLOY_PACKAGE_INIT"

_COMMAND_ALIASES = {
    SCREENSHOT_COMMAND: ActionType.SCREENSHOT.value,
}


def normalize_action_name(name: Optional[str]) -> Optional[str]:
    if not isinstance(name, str):
        return None
    normalized = name.strip().upper()
    return _COMMAND_ALIASES.get(normalized, normalized)


def _extract_action_id(message: Dict[str, Any]) -> Optional[str]:
    action_id = message.get("action_id")
    if isinstance(action_id, str) and action_id.strip():
        return action_id.strip()

    args = message.get("args")
    if isinstance(args, dict):
        command_id = args.get("command_id")
        if isinstance(command_id, str) and command_id.strip():
            return command_id.strip()

    return None


@dataclass(frozen=True)
class ActionResult:
    action_id: str
    action_type: str
    status: ActionState
    started_at: str
    completed_at: str
    result: Any = None
    error: Optional[Dict[str, Any]] = None
    parameters: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "action_type": self.action_type,
            "status": self.status.value,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "result": self.result,
            "error": self.error,
            "parameters": self.parameters,
        }


class ActionManager:
    """Simple registry that dispatches client commands through named handlers."""

    def __init__(self) -> None:
        self._handlers: Dict[str, Callable[..., Any]] = {}
        self._seen_actions: Dict[str, Any] = {}

    def register(self, action_type: str, handler: Callable[..., Any]) -> None:
        normalized = normalize_action_name(action_type)
        if not normalized:
            raise ValueError("action_type is required")
        self._handlers[normalized] = handler

    def dispatch(self, message: Dict[str, Any], **context: Any) -> Any:
        if not isinstance(message, dict):
            return {"error": "Invalid message format"}

        action_type = normalize_action_name(message.get("action_type") or message.get("command"))
        if not action_type:
            return {"error": "Command missing"}

        action_id = _extract_action_id(message)
        if action_id and action_id in self._seen_actions:
            return self._seen_actions[action_id]

        handler = self._handlers.get(action_type)
        if handler is None:
            result = {"error": f"Unknown command: {action_type}"}
        else:
            result = handler(message, **context)

        if action_id:
            self._seen_actions[action_id] = result
        return result


__all__ = [
    "ActionManager",
    "ActionState",
    "ActionType",
    "ActionResult",
    "DEPLOY_PACKAGE_INIT_COMMAND",
    "NETWORK_NEIGHBOURHOOD_COMMAND",
    "PASSIVE_NEIGHBOURHOOD_COMMAND",
    "SCREENSHOT_COMMAND",
    "normalize_action_name",
]
