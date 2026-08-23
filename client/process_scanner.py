import hashlib
import os
import re

import psutil


def _normalize_process_name(name):
    if not name:
        return ""
    normalized = str(name).strip().lower().replace("\\", "/")
    normalized = os.path.basename(normalized)
    if normalized.endswith(".exe"):
        normalized = normalized[:-4]
    return re.sub(r"\s+", " ", normalized).strip()


def _iter_rule_names(rule):
    names = []
    for key in ("process_name", "name", "keyword"):
        value = rule.get(key)
        if isinstance(value, str) and value.strip():
            names.append(value)

    aliases = rule.get("aliases") or rule.get("alias") or rule.get("process_aliases")
    if isinstance(aliases, str):
        names.append(aliases)
    elif isinstance(aliases, (list, tuple, set)):
        names.extend(alias for alias in aliases if isinstance(alias, str) and alias.strip())

    normalized = []
    seen = set()
    for value in names:
        candidate = _normalize_process_name(value)
        if candidate and candidate not in seen:
            seen.add(candidate)
            normalized.append(candidate)
    return normalized


def _contains_keyword(text, keyword):
    if not text or not keyword:
        return False
    return bool(
        re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", str(text).lower())
    )


def _is_matching_process(proc_name, exe_name, rule_names):
    normalized_name = _normalize_process_name(proc_name)
    normalized_exe = _normalize_process_name(exe_name)
    for rule_name in rule_names:
        if (
            rule_name == normalized_name
            or rule_name == normalized_exe
        ):
            return True
    return False


def scan_for_forbidden_processes(log_data, forbidden_processes, reported_alerts):
    """
    log_data: dict from get_activity_log
    forbidden_processes: list of {process_name, severity, description}
    reported_alerts: set of alert identity hashes already sent
    Returns: list of new alert candidates, updated reported_alerts
    """
    new_alerts = []

    for fb in forbidden_processes:
        if not isinstance(fb, dict):
            continue

        process_name = fb.get("process_name") or fb.get("name")
        if not isinstance(process_name, str) or not process_name.strip():
            continue

        rule_names = _iter_rule_names(fb)
        severity = str(fb.get("severity", "HIGH")).upper()
        description = fb.get("description") or (
            f"Forbidden process '{process_name}' was detected in activity log."
        )

        # 1. Scan activity log
        if log_data and "activity" in log_data:
            for entry in log_data["activity"]:
                if not isinstance(entry, dict):
                    continue

                entry_type = entry.get("type", "")
                entry_detail = entry.get("detail", "")
                matched_keyword = None
                for candidate in rule_names:
                    if _contains_keyword(entry_type, candidate) or _contains_keyword(
                        entry_detail, candidate
                    ):
                        matched_keyword = candidate
                        break

                if not matched_keyword:
                    continue

                time_str = entry.get("time", "Unknown")
                detail = str(entry_detail)
                alert_id = hashlib.sha256(
                    f"{process_name}\0{matched_keyword}\0{time_str}\0{detail}".encode()
                ).hexdigest()
                if alert_id not in reported_alerts:
                    reported_alerts.add(alert_id)
                    new_alerts.append(
                        {
                            "alert_type": "FORBIDDEN_PROCESS",
                            "severity": severity,
                            "title": f"Forbidden process detected: {process_name}",
                            "description": description,
                            "process_name": process_name,
                            "matched_keyword": matched_keyword,
                            "log_source": entry_type or "activity",
                            "activity_time": time_str,
                        }
                    )

        # 2. Scan running processes
        for proc in psutil.process_iter(["pid", "name", "exe"]):
            try:
                proc_name = proc.info.get("name")
                exe_path = proc.info.get("exe")
                exe_name = os.path.basename(exe_path) if exe_path else ""
                if _is_matching_process(proc_name, exe_name, rule_names):
                    # For running processes, use a stable synthetic time context
                    # so the client does not repeatedly alert on the same binary.
                    time_str = "CURRENTLY_RUNNING"
                    alert_id = hashlib.sha256(
                        f"{process_name}\0{time_str}".encode()
                    ).hexdigest()
                    if alert_id not in reported_alerts:
                        reported_alerts.add(alert_id)
                        new_alerts.append(
                            {
                                "alert_type": "FORBIDDEN_PROCESS",
                                "severity": severity,
                                "title": f"Forbidden process running: {process_name}",
                                "description": fb.get(
                                    "description",
                                    f"Forbidden process '{process_name}' is currently running.",
                                ),
                                "process_name": process_name,
                                "activity_time": None,
                                "log_source": "process_list",
                                "matched_keyword": _normalize_process_name(process_name),
                                "detected_process_name": proc_name,
                            }
                        )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    # Limit set size
    if len(reported_alerts) > 1000:
        reported_alerts = set(list(reported_alerts)[-500:])

    return new_alerts, reported_alerts
