"""Constants and helpers for hybrid auto/manual client location assignment."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

ASSIGNMENT_METHOD_AUTO = "AUTO"
ASSIGNMENT_METHOD_MANUAL = "MANUAL"
ASSIGNMENT_METHODS = frozenset({ASSIGNMENT_METHOD_AUTO, ASSIGNMENT_METHOD_MANUAL})

ASSIGNMENT_STATUS_PENDING = "PENDING"
ASSIGNMENT_STATUS_ASSIGNED = "ASSIGNED"
ASSIGNMENT_STATUS_CONFIRMED = "CONFIRMED"
ASSIGNMENT_STATUSES = frozenset({
    ASSIGNMENT_STATUS_PENDING,
    ASSIGNMENT_STATUS_ASSIGNED,
    ASSIGNMENT_STATUS_CONFIRMED,
})

SOURCE_LOCALIZATION_ENGINE = "localization_engine"
SOURCE_ADMINISTRATOR = "administrator"


def normalize_assignment_method(value: Optional[str], *, default: str = ASSIGNMENT_METHOD_MANUAL) -> str:
    if value is None or value == "":
        return default
    normalized = str(value).strip().upper()
    if normalized not in ASSIGNMENT_METHODS:
        raise ValueError(f"Invalid assignment method '{value}'. Expected AUTO or MANUAL.")
    return normalized


def normalize_assignment_status(value: Optional[str], *, default: str = ASSIGNMENT_STATUS_ASSIGNED) -> str:
    if value is None or value == "":
        return default
    normalized = str(value).strip().upper()
    if normalized not in ASSIGNMENT_STATUSES:
        raise ValueError(
            f"Invalid assignment status '{value}'. Expected PENDING, ASSIGNED, or CONFIRMED."
        )
    return normalized


def serialize_evidence(evidence: Any) -> Optional[str]:
    if evidence is None:
        return None
    if isinstance(evidence, str):
        return evidence
    return json.dumps(evidence)


def parse_evidence(evidence: Any) -> Any:
    if evidence is None:
        return None
    if not isinstance(evidence, str):
        return evidence
    try:
        return json.loads(evidence)
    except (TypeError, ValueError, json.JSONDecodeError):
        return evidence


def assignment_payload(
    *,
    method: Optional[str],
    status: Optional[str],
    confidence: Optional[float] = None,
    verified: bool = False,
    assigned_at: Optional[str] = None,
    assigned_by: Optional[str] = None,
    last_calculated_at: Optional[str] = None,
    source: Optional[str] = None,
    evidence: Any = None,
    failure_reason: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Build the API assignment object, or None when the client has no assignment state."""
    if (
        method is None
        and status is None
        and assigned_at is None
        and assigned_by is None
        and failure_reason is None
    ):
        return None
    return {
        "method": method,
        "status": status,
        "confidence": confidence,
        "verified": bool(verified),
        "assigned_at": assigned_at,
        "assigned_by": assigned_by,
        "last_calculated_at": last_calculated_at,
        "source": source,
        "evidence": parse_evidence(evidence),
        "failure_reason": failure_reason,
    }
