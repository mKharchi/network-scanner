"""Server-side action vocabulary and catalog helpers.

The goal is to keep the action names, aliases, and supported client command
inventory in one place so the REST API and future persistent Action model can
share the same source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


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


def summarize_action_progress(targets: List[Dict[str, Any]]) -> Dict[str, int]:
    """Roll up per-target statuses into aggregate deployment progress counts."""
    statuses = [str(item.get("status") or ActionState.PENDING.value) for item in targets]
    return summarize_action_progress_from_statuses(statuses)


def summarize_action_progress_from_statuses(statuses: List[str]) -> Dict[str, int]:
    total = len(statuses)
    succeeded = sum(1 for status in statuses if status == ActionState.SUCCESS.value)
    failed = sum(1 for status in statuses if status == ActionState.FAILED.value)
    in_progress = sum(1 for status in statuses if status == ActionState.RUNNING.value)
    completed = succeeded + failed
    pending = max(0, total - completed - in_progress)
    return {
        "total": total,
        "completed": completed,
        "succeeded": succeeded,
        "failed": failed,
        "in_progress": in_progress,
        "pending": pending,
    }


LEGACY_SCREENSHOT_COMMAND = "REQUEST_SCREENSHOT"
DEPLOY_PACKAGE_INIT_COMMAND = "DEPLOY_PACKAGE_INIT"
DEPLOY_PACKAGE_CANCEL_COMMAND = "DEPLOY_PACKAGE_CANCEL"

_COMMAND_ALIASES = {
    LEGACY_SCREENSHOT_COMMAND: ActionType.SCREENSHOT.value,
}

_SUPPORTED_COMMANDS = (
    {"command": ActionType.SHUTDOWN.value, "label": "Shut down client"},
    {"command": ActionType.RESTART.value, "label": "Restart client"},
    {"command": ActionType.COLLECT_DIAGNOSTICS.value, "label": "Collect diagnostics"},
    {"command": ActionType.REFRESH_HEALTH.value, "label": "Refresh health"},
    {"command": ActionType.GET_SYSTEM_INFO.value, "label": "System information"},
    {"command": ActionType.GET_NETWORK_INFO.value, "label": "Network information"},
    {"command": ActionType.GET_CPU_INFO.value, "label": "CPU information"},
    {"command": ActionType.GET_MEMORY_INFO.value, "label": "Memory information"},
    {"command": ActionType.GET_DISK_INFO.value, "label": "Disk information"},
    {"command": ActionType.GET_PROCESSES.value, "label": "Processes"},
    {"command": ActionType.GET_ACTIVITY_LOG.value, "label": "Activity log"},
    {"command": LEGACY_SCREENSHOT_COMMAND, "label": "Request screenshot"},
    {"command": ActionType.PING.value, "label": "Ping"},
    {"command": ActionType.KILL_PROCESS.value, "label": "Kill process"},
    {"command": ActionType.START_PROCESS.value, "label": "Start process"},
    {"command": ActionType.GET_NETWORK_NEIGHBOURHOOD.value, "label": "Network neighbourhood"},
    {"command": ActionType.GET_PASSIVE_NEIGHBOURHOOD.value, "label": "Passive neighbourhood"},
    {"command": ActionType.ISOLATE_DEVICE.value, "label": "Isolate device"},
    {"command": ActionType.DISCONNECT.value, "label": "Disconnect client"},
    {"command": ActionType.DEPLOY_PACKAGE.value, "label": "Deploy package"},
)


def normalize_action_name(name: Optional[str]) -> Optional[str]:
    if not isinstance(name, str):
        return None
    normalized = name.strip().upper()
    return _COMMAND_ALIASES.get(normalized, normalized)


def get_supported_client_commands() -> List[Dict[str, str]]:
    """Return the legacy command inventory for the REST API and GUI."""

    commands: List[Dict[str, str]] = []
    for item in _SUPPORTED_COMMANDS:
        command = item["command"]
        commands.append(
            {
                "command": command,
                "action_type": normalize_action_name(command) or command,
                "label": item["label"],
            }
        )
    return commands


@dataclass(frozen=True)
class ActionRecord:
    """Lightweight future Action table representation."""

    action_id: str
    action_type: str
    requested_by: Optional[str] = None
    status: str = ActionState.PENDING.value
    parameters: Dict[str, Any] = field(default_factory=dict)
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class ActionTargetRecord:
    """Lightweight future ActionTarget table representation."""

    action_id: str
    client_id: str
    status: str = ActionState.PENDING.value
    sent_at: Optional[str] = None
    acknowledged_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None


__all__ = [
    "ActionRecord",
    "ActionState",
    "ActionTargetRecord",
    "ActionType",
    "LEGACY_SCREENSHOT_COMMAND",
    "get_supported_client_commands",
    "normalize_action_name",
]
