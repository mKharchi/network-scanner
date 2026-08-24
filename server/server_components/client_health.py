"""Classify workstation health for the center visualization.

Connection isolation/offline still wins. Online seats use the last health
snapshot plus open alerts so the map is not only green/gray.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


WARNING_PERCENT = 80.0
CRITICAL_PERCENT = 90.0

SEVERITY_RANK = {
    "LOW": 1,
    "MEDIUM": 2,
    "HIGH": 3,
    "CRITICAL": 4,
}


def extract_health_metrics(payload: Any) -> Optional[Dict[str, float]]:
    if not isinstance(payload, dict):
        return None
    candidates = [payload, payload.get("health"), payload.get("data"), payload.get("result")]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        health = candidate.get("health") if "health" in candidate else candidate
        if not isinstance(health, dict):
            continue
        cpu = _metric(health, "cpu_percent", "usage_percent")
        memory = _metric(health, "memory_percent")
        disk = _metric(health, "disk_percent")
        if cpu is None and memory is None and disk is None:
            continue
        return {
            "cpu_percent": cpu,
            "memory_percent": memory,
            "disk_percent": disk,
        }
    return None


def classify_station_health(
    *,
    client_id: Optional[str] = None,
    connection_state: Optional[str] = None,
    cpu_percent: Optional[float] = None,
    memory_percent: Optional[float] = None,
    disk_percent: Optional[float] = None,
    open_alert_severity: Optional[str] = None,
    shows_clients: bool = True,
) -> str:
    if not shows_clients or not client_id:
        return "empty"
    state = (connection_state or "OFFLINE").upper()
    if state == "ISOLATED":
        return "isolated"
    if state != "ONLINE":
        return "offline"

    alert_rank = SEVERITY_RANK.get((open_alert_severity or "").upper(), 0)
    peak = max(
        value
        for value in (cpu_percent, memory_percent, disk_percent)
        if isinstance(value, (int, float))
    ) if any(isinstance(value, (int, float)) for value in (cpu_percent, memory_percent, disk_percent)) else None

    if alert_rank >= SEVERITY_RANK["HIGH"] or (peak is not None and peak >= CRITICAL_PERCENT):
        return "critical"
    if alert_rank >= SEVERITY_RANK["MEDIUM"] or (peak is not None and peak >= WARNING_PERCENT):
        return "warning"
    return "healthy"


def health_payload(
    *,
    client_id: Optional[str],
    connection_state: Optional[str],
    cpu_percent: Optional[float] = None,
    memory_percent: Optional[float] = None,
    disk_percent: Optional[float] = None,
    open_alert_severity: Optional[str] = None,
    updated_at: Optional[str] = None,
    shows_clients: bool = True,
) -> Dict[str, Any]:
    status = classify_station_health(
        client_id=client_id,
        connection_state=connection_state,
        cpu_percent=cpu_percent,
        memory_percent=memory_percent,
        disk_percent=disk_percent,
        open_alert_severity=open_alert_severity,
        shows_clients=shows_clients,
    )
    return {
        "status": status,
        "cpu_percent": cpu_percent,
        "memory_percent": memory_percent,
        "disk_percent": disk_percent,
        "open_alert_severity": open_alert_severity,
        "updated_at": updated_at,
    }


def record_client_health(client_id: str, payload: Any) -> bool:
    """Persist the last health snapshot from a client action result."""
    metrics = extract_health_metrics(payload)
    if not metrics or not client_id:
        return False
    from database import get_connection

    conn = get_connection()
    if not conn:
        return False
    try:
        cursor = conn.cursor()
        cursor.execute(
            """UPDATE clients
               SET health_cpu_percent = %s,
                   health_memory_percent = %s,
                   health_disk_percent = %s,
                   health_updated_at = UTC_TIMESTAMP()
               WHERE client_id = %s""",
            (
                metrics.get("cpu_percent"),
                metrics.get("memory_percent"),
                metrics.get("disk_percent"),
                client_id,
            ),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def _metric(source: Dict[str, Any], *keys: str) -> Optional[float]:
    for key in keys:
        value = source.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None
