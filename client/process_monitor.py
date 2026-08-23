"""Forbidden Process Monitoring, Termination, and Escalation Engine.

Continuously monitors running processes against forbidden process policies,
enforces termination (graceful -> force-kill verification), and tracks rolling
violation frequency to emit critical escalation alerts.
"""

from __future__ import annotations

import collections
from datetime import datetime, timezone, timedelta
import logging
import os
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import psutil

LOG = logging.getLogger("process_monitor")


def utc_iso_now() -> str:
    """Return current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def normalize_process_name(name: Optional[str]) -> str:
    """Normalize process name for cross-platform and case-insensitive comparison."""
    if not name:
        return ""
    clean = name.strip().lower()
    if clean.endswith(".exe"):
        clean = clean[:-4]
    return clean


class ViolationRecord:
    """Represents a single detected forbidden process occurrence."""

    def __init__(
        self,
        process_name: str,
        pid: int,
        action: str,
        result: str,
        timestamp: Optional[datetime] = None,
    ):
        self.process_name = process_name
        self.pid = pid
        self.action = action
        self.result = result
        self.timestamp = timestamp or datetime.now(timezone.utc)

    @property
    def iso_timestamp(self) -> str:
        return self.timestamp.isoformat()


class ViolationTracker:
    """Sliding-window violation history tracker for escalation detection."""

    def __init__(self, threshold: int = 3, window_seconds: int = 120, max_history: int = 500):
        self.threshold = max(1, threshold)
        self.window_seconds = max(1, window_seconds)
        self.max_history = max_history
        self._violations: collections.deque[ViolationRecord] = collections.deque(maxlen=max_history)
        self._lock = threading.Lock()

    def record_violation(
        self,
        process_name: str,
        pid: int,
        action: str = "TERMINATED",
        result: str = "SUCCESS",
        timestamp: Optional[datetime] = None,
    ) -> Tuple[int, List[ViolationRecord], bool]:
        """Record a violation and evaluate if the sliding window exceeds the escalation threshold.

        Returns:
            (violation_count_in_window, matching_violations, is_escalated)
        """
        ts = timestamp or datetime.now(timezone.utc)
        record = ViolationRecord(process_name, pid, action, result, ts)
        normalized = normalize_process_name(process_name)

        with self._lock:
            self._violations.append(record)
            cutoff = ts - timedelta(seconds=self.window_seconds)

            # Count violations for this specific process within the window
            matching = [
                v for v in self._violations
                if normalize_process_name(v.process_name) == normalized and v.timestamp >= cutoff
            ]
            count = len(matching)
            is_escalated = count >= self.threshold

            return count, matching, is_escalated

    def clear(self) -> None:
        """Clear all violation history."""
        with self._lock:
            self._violations.clear()


class ForbiddenProcessMonitor:
    """Continuous background forbidden process inspector and enforcement engine."""

    def __init__(
        self,
        rules: Optional[List[Dict[str, Any]]] = None,
        *,
        scan_interval_seconds: float = 10.0,
        escalation_threshold: int = 3,
        escalation_window_seconds: int = 120,
        alert_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        isolation_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        auto_terminate: bool = True,
        termination_timeout_seconds: float = 1.5,
    ):
        self.scan_interval = max(1.0, float(scan_interval_seconds))
        self.auto_terminate = auto_terminate
        self.termination_timeout = max(0.2, float(termination_timeout_seconds))
        self.alert_callback = alert_callback
        self.isolation_callback = isolation_callback
        self.violation_tracker = ViolationTracker(
            threshold=escalation_threshold,
            window_seconds=escalation_window_seconds,
        )

        self._rules_lock = threading.Lock()
        self._rules: List[Dict[str, Any]] = []
        if rules:
            self.set_rules(rules)

        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None

    def set_rules(self, rules: List[Dict[str, Any]]) -> None:
        """Update forbidden process rules safely."""
        with self._rules_lock:
            self._rules = list(rules) if isinstance(rules, list) else []
            LOG.info("[PROCESS MONITOR] Loaded %d forbidden process rules.", len(self._rules))

    def get_rules(self) -> List[Dict[str, Any]]:
        """Return a copy of the active forbidden process rules."""
        with self._rules_lock:
            return list(self._rules)

    def terminate_process(self, pid: int, process_name: str) -> Dict[str, Any]:
        """Execute two-phase process termination (graceful -> force-kill verification)."""
        result: Dict[str, Any] = {
            "pid": pid,
            "process_name": process_name,
            "action": "TERMINATE_ATTEMPTED",
            "status": "FAILED",
            "message": "",
        }

        try:
            proc = psutil.Process(pid)
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            result["status"] = "ALREADY_EXITED"
            result["message"] = f"Process {process_name} (PID {pid}) is no longer running."
            return result
        except psutil.AccessDenied as err:
            result["status"] = "ACCESS_DENIED"
            result["message"] = f"Access denied terminating {process_name} (PID {pid}): {err}"
            return result

        # Phase 1: Graceful termination request
        try:
            proc.terminate()
            try:
                proc.wait(timeout=self.termination_timeout)
                result["action"] = "TERMINATED"
                result["status"] = "SUCCESS"
                result["message"] = f"Gracefully terminated process {process_name} (PID {pid})."
                return result
            except psutil.TimeoutExpired:
                pass
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            result["action"] = "TERMINATED"
            result["status"] = "SUCCESS"
            result["message"] = f"Process {process_name} (PID {pid}) exited."
            return result
        except psutil.AccessDenied as err:
            result["status"] = "ACCESS_DENIED"
            result["message"] = f"Access denied on terminate for {process_name} (PID {pid}): {err}"
            return result

        # Phase 2: Force kill if still running
        try:
            proc.kill()
            try:
                proc.wait(timeout=self.termination_timeout)
                result["action"] = "FORCE_KILLED"
                result["status"] = "SUCCESS"
                result["message"] = f"Force-killed process {process_name} (PID {pid})."
                return result
            except psutil.TimeoutExpired:
                result["action"] = "FORCE_KILL_TIMEOUT"
                result["status"] = "FAILED"
                result["message"] = f"Process {process_name} (PID {pid}) did not exit after force kill."
                return result
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            result["action"] = "FORCE_KILLED"
            result["status"] = "SUCCESS"
            result["message"] = f"Force-killed process {process_name} (PID {pid}) successfully."
            return result
        except psutil.AccessDenied as err:
            result["status"] = "ACCESS_DENIED"
            result["message"] = f"Access denied on force-kill for {process_name} (PID {pid}): {err}"
            return result

    def scan_and_enforce(self) -> List[Dict[str, Any]]:
        """Enumerate active processes, match against rules, terminate violations, and emit alerts."""
        with self._rules_lock:
            active_rules = [
                r for r in self._rules
                if r.get("enabled", True) and (r.get("process_name") or r.get("name"))
            ]

        if not active_rules:
            return []

        # Prepare normalized rule lookup table
        normalized_rules = []
        for rule in active_rules:
            raw_name = rule.get("process_name") or rule.get("name") or ""
            norm_name = normalize_process_name(raw_name)
            normalized_rules.append({
                "raw_name": raw_name,
                "norm_name": norm_name,
                "severity": (rule.get("severity") or "HIGH").upper(),
                "description": rule.get("description", f"Forbidden process: {raw_name}"),
                "rule_id": rule.get("rule_id") or rule.get("id"),
            })

        generated_alerts: List[Dict[str, Any]] = []

        # Enumerate running processes safely
        for proc in psutil.process_iter(["pid", "name", "exe"]):
            try:
                pid = proc.info.get("pid")
                proc_name = proc.info.get("name") or ""
                exe_path = proc.info.get("exe") or ""
                norm_proc_name = normalize_process_name(proc_name)
                norm_exe_name = normalize_process_name(os.path.basename(exe_path)) if exe_path else ""

                for rule in normalized_rules:
                    matched = False
                    if rule["norm_name"] and (
                        rule["norm_name"] == norm_proc_name
                        or rule["norm_name"] == norm_exe_name
                        or rule["norm_name"] in norm_proc_name
                    ):
                        matched = True

                    if not matched:
                        continue

                    # Violation detected!
                    detected_ts = utc_iso_now()
                    termination_info = {"status": "SKIPPED", "action": "DETECTED_ONLY"}
                    if self.auto_terminate and pid:
                        termination_info = self.terminate_process(pid, proc_name)

                    action_str = "TERMINATED" if termination_info.get("status") == "SUCCESS" else "TERMINATION_FAILED"
                    if not self.auto_terminate:
                        action_str = "DETECTED_ONLY"

                    # Track rolling violation history
                    v_count, v_history, is_escalated = self.violation_tracker.record_violation(
                        process_name=rule["raw_name"],
                        pid=pid or 0,
                        action=action_str,
                        result=termination_info.get("status", "UNKNOWN"),
                    )

                    # 1. Base violation alert
                    base_alert = {
                        "alert_type": "FORBIDDEN_PROCESS",
                        "event_type": "FORBIDDEN_PROCESS_DETECTED",
                        "severity": rule["severity"],
                        "process_name": rule["raw_name"],
                        "pid": pid,
                        "action": action_str,
                        "detected_at": detected_ts,
                        "activity_time": detected_ts,
                        "title": f"Forbidden process {action_str.lower()}: {rule['raw_name']}",
                        "description": (
                            f"Forbidden process '{proc_name}' (PID {pid}) was detected. "
                            f"Enforcement action: {termination_info.get('message', action_str)}."
                        ),
                    }
                    generated_alerts.append(base_alert)
                    if self.alert_callback:
                        try:
                            self.alert_callback(base_alert)
                        except Exception as cb_err:
                            LOG.warning("[PROCESS MONITOR] Alert callback error: %s", cb_err)

                    # 2. Escalation alert if threshold is reached within sliding window
                    if is_escalated and v_history:
                        first_ts = v_history[0].iso_timestamp
                        last_ts = v_history[-1].iso_timestamp
                        critical_alert = {
                            "alert_type": "FORBIDDEN_PROCESS",
                            "event_type": "CRITICAL_FORBIDDEN_PROCESS_REPEATED",
                            "severity": "CRITICAL",
                            "process_name": rule["raw_name"],
                            "violation_count": v_count,
                            "window_seconds": self.violation_tracker.window_seconds,
                            "first_violation": first_ts,
                            "last_violation": last_ts,
                            "detected_at": detected_ts,
                            "activity_time": detected_ts,
                            "title": f"Critical: Repeated Forbidden Process Violations ({rule['raw_name']})",
                            "description": (
                                f"Repeated launch attempts detected: process '{rule['raw_name']}' "
                                f"violated policy {v_count} times in the last {self.violation_tracker.window_seconds}s "
                                f"(threshold: {self.violation_tracker.threshold})."
                            ),
                        }
                        generated_alerts.append(critical_alert)
                        if self.alert_callback:
                            try:
                                self.alert_callback(critical_alert)
                            except Exception as cb_err:
                                LOG.warning("[PROCESS MONITOR] Critical alert callback error: %s", cb_err)

                        # Notify the isolation hook (opt-in).  This fires every
                        # time the window threshold is exceeded, so the caller is
                        # responsible for idempotency (e.g. skip if already
                        # isolated).  The payload matches the critical alert so
                        # callers need no additional imports.
                        if self.isolation_callback:
                            try:
                                self.isolation_callback(critical_alert)
                            except Exception as cb_err:
                                LOG.warning("[PROCESS MONITOR] Isolation callback error: %s", cb_err)

                    # Once matched for a PID, break out of rule checking for that PID
                    break

            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
            except Exception as loop_err:
                LOG.warning("[PROCESS MONITOR] Error inspecting process: %s", loop_err)
                continue

        return generated_alerts

    def run_loop(self, stop_event: Optional[threading.Event] = None) -> None:
        """Run continuous monitoring loop until stop event is signaled."""
        stop = stop_event or self._stop_event
        LOG.info("[PROCESS MONITOR] Started continuous enforcement loop (interval: %.1fs).", self.scan_interval)
        while not stop.is_set():
            try:
                self.scan_and_enforce()
            except Exception as err:
                LOG.exception("[PROCESS MONITOR] Unexpected error in enforcement loop: %s", err)

            if stop.wait(self.scan_interval):
                break
        LOG.info("[PROCESS MONITOR] Stopped enforcement loop.")

    def start(self) -> None:
        """Start background worker thread."""
        if self._worker_thread is not None and self._worker_thread.is_alive():
            return
        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self.run_loop,
            args=(self._stop_event,),
            name="forbidden-process-monitor",
            daemon=True,
        )
        self._worker_thread.start()

    def stop(self) -> None:
        """Stop background worker thread."""
        self._stop_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=3.0)
