"""Forbidden Process & Resource Protection Engine.

Continuously monitors:
1. Running processes against forbidden process policies (graceful -> force-kill verification),
   tracking rolling violation frequency to emit critical escalation alerts.
2. System resource consumption (CPU & Memory), automatically identifying and terminating
   eligible runaway processes under sustained pressure with safety exclusions and cooldowns.
"""

from __future__ import annotations

import collections
from datetime import datetime, timezone, timedelta
import logging
import os
import sys
import threading
import time
from typing import Any, Callable, Deque, Dict, List, Optional, Set, Tuple

import psutil

LOG = logging.getLogger("process_monitor")

# Set of protected OS processes that must NEVER be terminated automatically
PROTECTED_PROCESS_NAMES: Set[str] = {
    # Windows Critical & Core System Processes
    "system",
    "system idle process",
    "idle",
    "registry",
    "smss",
    "csrss",
    "wininit",
    "services",
    "lsass",
    "winlogon",
    "svchost",
    "explorer",
    "spoolsv",
    "dwm",
    "fontdrvhost",
    "sihost",
    "taskhostw",
    "runtimebroker",
    "shellexperiencehost",
    "startmenuexperiencehost",
    "searchhost",
    "searchindexer",
    "audiodg",
    "conhost",
    "ctfmon",
    "werfault",
    # Linux / Unix System Processes
    "systemd",
    "init",
    "kthreadd",
    "systemd-journald",
    "systemd-udevd",
    "systemd-logind",
    "systemd-resolved",
    "systemd-timesyncd",
    "systemd-networkd",
    "sshd",
    "dbus-daemon",
    "dbus-broker",
    "polkitd",
    "cron",
    "crond",
    "rsyslogd",
    "syslogd",
    "networkmanager",
    "wpa_supplicant",
    "bash",
    "sh",
    "login",
    "agetty",
    "dockerd",
    "containerd",
}


def utc_iso_now() -> str:
    """Return current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def normalize_process_name(name: Optional[str]) -> str:
    """Normalize process name for cross-platform and case-insensitive comparison."""
    if not name:
        return ""
    clean = str(name).strip().lower().replace("\\", "/").rsplit("/", 1)[-1]
    if clean.endswith(".exe"):
        clean = clean[:-4]
    return clean.strip()


class ProtectedProcessValidator:
    """Validates whether a process is safe to terminate or protected."""

    @staticmethod
    def is_client_process(pid: int, name: Optional[str] = None, exe: Optional[str] = None) -> bool:
        """Return True if the process represents the client application itself."""
        current_pid = os.getpid()
        if pid == current_pid:
            return True

        # Check if parent or current process tree
        try:
            current_proc = psutil.Process(current_pid)
            if pid in {p.pid for p in current_proc.children(recursive=True)}:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, Exception):
            pass

        norm_name = normalize_process_name(name)
        norm_exe = normalize_process_name(exe)
        client_identifiers = {"networkscannerclient", "client", "agent"}
        if norm_name in client_identifiers or norm_exe in client_identifiers:
            try:
                proc = psutil.Process(pid)
                cmd = " ".join(proc.cmdline()).lower()
                if "client.py" in cmd or "networkscannerclient" in cmd:
                    return True
            except Exception:
                pass

        return False

    @staticmethod
    def is_protected_system_process(pid: int, name: Optional[str] = None, exe: Optional[str] = None) -> bool:
        """Return True if the process is a protected operating system process."""
        if pid in {0, 1, 2}:
            return True

        norm_name = normalize_process_name(name)
        norm_exe = normalize_process_name(exe)

        if norm_name in PROTECTED_PROCESS_NAMES or norm_exe in PROTECTED_PROCESS_NAMES:
            return True

        return False

    @classmethod
    def is_safe_to_terminate(cls, pid: int, name: Optional[str] = None, exe: Optional[str] = None) -> Tuple[bool, str]:
        """Check safety rules and return (is_safe, reason)."""
        if cls.is_client_process(pid, name, exe):
            return False, "client_process"
        if cls.is_protected_system_process(pid, name, exe):
            return False, "protected_process"
        return True, "safe"


class ProcessManager:
    """Shared process interaction and termination routines."""

    @staticmethod
    def terminate_process(pid: int, process_name: str, timeout: float = 1.5) -> Dict[str, Any]:
        """Execute two-phase process termination (graceful -> force-kill verification)."""
        result: Dict[str, Any] = {
            "pid": pid,
            "process_name": process_name,
            "action": "TERMINATE_ATTEMPTED",
            "status": "FAILED",
            "message": "",
        }

        # Safety validation
        is_safe, reason = ProtectedProcessValidator.is_safe_to_terminate(pid, process_name)
        if not is_safe:
            result["status"] = "REJECTED_PROTECTED"
            result["message"] = f"Termination of process {process_name} (PID {pid}) rejected: {reason}."
            return result

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
                proc.wait(timeout=timeout)
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
                proc.wait(timeout=timeout)
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
        """Execute process termination via shared ProcessManager."""
        return ProcessManager.terminate_process(pid, process_name, timeout=self.termination_timeout)

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
                "terminate_on_detection": bool(rule.get("terminate_on_detection", True)),
                "resource_protection_eligible": bool(rule.get("resource_protection_eligible", True)),
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

                    # Check safety exclusion
                    if pid:
                        is_safe, safe_reason = ProtectedProcessValidator.is_safe_to_terminate(pid, proc_name, exe_path)
                        if not is_safe:
                            LOG.warning(
                                "[PROCESS MONITOR] Skipped protected process '%s' (PID %s): %s",
                                proc_name,
                                pid,
                                safe_reason,
                            )
                            continue

                    # Violation detected!
                    detected_ts = utc_iso_now()
                    should_terminate = self.auto_terminate and rule["terminate_on_detection"] and pid
                    termination_info = {"status": "SKIPPED", "action": "DETECTED_ONLY"}
                    if should_terminate:
                        termination_info = self.terminate_process(pid, proc_name)

                    action_str = "TERMINATED" if termination_info.get("status") == "SUCCESS" else "TERMINATION_FAILED"
                    if not should_terminate:
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

                        if self.isolation_callback:
                            try:
                                self.isolation_callback(critical_alert)
                            except Exception as cb_err:
                                LOG.warning("[PROCESS MONITOR] Isolation callback error: %s", cb_err)

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


class ResourceProtectionMonitor:
    """Automatic client resource protection monitor for CPU & Memory pressure."""

    DEFAULT_CONFIG: Dict[str, Any] = {
        "enabled": True,
        "cpu": {
            "enabled": True,
            "threshold": 85.0,
            "sustained_seconds": 30,
        },
        "memory": {
            "enabled": True,
            "threshold": 90.0,
            "sustained_seconds": 30,
        },
        "cooldown_seconds": 300,
        "max_interventions_per_hour": 3,
    }

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        *,
        scan_interval_seconds: float = 5.0,
        alert_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        rules_provider: Optional[Callable[[], List[Dict[str, Any]]]] = None,
        auto_terminate: bool = True,
        termination_timeout_seconds: float = 1.5,
    ):
        self.scan_interval = max(0.5, float(scan_interval_seconds))
        self.auto_terminate = auto_terminate
        self.termination_timeout = max(0.2, float(termination_timeout_seconds))
        self.alert_callback = alert_callback
        self.rules_provider = rules_provider

        self._config_lock = threading.Lock()
        self._config: Dict[str, Any] = dict(self.DEFAULT_CONFIG)
        if config:
            self.set_config(config)

        # Sustained pressure state
        self._cpu_high_since: Optional[float] = None
        self._memory_high_since: Optional[float] = None

        # Intervention rate limiting state
        self._last_intervention_time: Optional[float] = None
        self._interventions: Deque[float] = collections.deque(maxlen=100)

        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None

    def set_config(self, config: Dict[str, Any]) -> None:
        """Safely update resource protection configuration."""
        if not isinstance(config, dict):
            return
        with self._config_lock:
            # Merge defaults
            merged = {
                "enabled": bool(config.get("enabled", self._config.get("enabled", True))),
                "cpu": {
                    "enabled": bool(config.get("cpu", {}).get("enabled", True)),
                    "threshold": float(config.get("cpu", {}).get("threshold", 85.0)),
                    "sustained_seconds": int(config.get("cpu", {}).get("sustained_seconds", 30)),
                },
                "memory": {
                    "enabled": bool(config.get("memory", {}).get("enabled", True)),
                    "threshold": float(config.get("memory", {}).get("threshold", 90.0)),
                    "sustained_seconds": int(config.get("memory", {}).get("sustained_seconds", 30)),
                },
                "cooldown_seconds": int(config.get("cooldown_seconds", 300)),
                "max_interventions_per_hour": int(config.get("max_interventions_per_hour", 3)),
            }
            self._config = merged
            LOG.info(
                "[RESOURCE PROTECTION] Loaded configuration: enabled=%s, CPU=%s%% (%ss), MEM=%s%% (%ss), cooldown=%ss",
                merged["enabled"],
                merged["cpu"]["threshold"],
                merged["cpu"]["sustained_seconds"],
                merged["memory"]["threshold"],
                merged["memory"]["sustained_seconds"],
                merged["cooldown_seconds"],
            )

    def get_config(self) -> Dict[str, Any]:
        """Return current configuration copy."""
        with self._config_lock:
            return dict(self._config)

    def set_rules_provider(self, provider: Callable[[], List[Dict[str, Any]]]) -> None:
        """Set the provider callback for active forbidden/eligible process rules."""
        self.rules_provider = provider

    def _get_active_rules(self) -> List[Dict[str, Any]]:
        if self.rules_provider:
            try:
                return self.rules_provider() or []
            except Exception as err:
                LOG.warning("[RESOURCE PROTECTION] Error fetching rules: %s", err)
        return []

    def _is_process_eligible(
        self,
        process_name: str,
        exe_path: str,
        rules: List[Dict[str, Any]],
    ) -> Tuple[bool, str]:
        """Check if process matches forbidden rule (Priority 1) or resource-protection eligibility (Priority 2)."""
        norm_name = normalize_process_name(process_name)
        norm_exe = normalize_process_name(os.path.basename(exe_path)) if exe_path else ""

        for rule in rules:
            if not rule.get("enabled", True):
                continue
            r_name = rule.get("process_name") or rule.get("name") or ""
            norm_r_name = normalize_process_name(r_name)
            if not norm_r_name:
                continue

            if norm_r_name == norm_name or norm_r_name == norm_exe or norm_r_name in norm_name:
                # Priority 1 & 2: Match against rule
                if rule.get("resource_protection_eligible", True):
                    return True, "forbidden_or_eligible_policy"

        return False, "not_eligible"

    def _evaluate_candidates(
        self,
        resource: str,
        system_usage: float,
        threshold: float,
    ) -> List[Dict[str, Any]]:
        """Find highest consuming eligible process and intervene if safe and allowed."""
        now = time.time()
        with self._config_lock:
            cooldown_seconds = self._config.get("cooldown_seconds", 300)
            max_interventions = self._config.get("max_interventions_per_hour", 3)

        # Enumerate candidate processes
        candidates: List[Dict[str, Any]] = []
        for proc in psutil.process_iter(["pid", "name", "exe", "cpu_percent", "memory_percent"]):
            try:
                pid = proc.info.get("pid")
                if not pid:
                    continue
                pname = proc.info.get("name") or ""
                pexe = proc.info.get("exe") or ""
                cpu_val = proc.info.get("cpu_percent") or 0.0
                mem_val = proc.info.get("memory_percent") or 0.0
                candidates.append({
                    "pid": pid,
                    "name": pname,
                    "exe": pexe,
                    "cpu_percent": float(cpu_val),
                    "memory_percent": float(mem_val),
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        # Sort descending by requested resource usage
        sort_key = "cpu_percent" if resource == "cpu" else "memory_percent"
        candidates.sort(key=lambda x: x[sort_key], reverse=True)

        if not candidates:
            return []

        rules = self._get_active_rules()
        events: List[Dict[str, Any]] = []

        chosen_candidate: Optional[Dict[str, Any]] = None
        skipped_first_candidate = False

        for candidate in candidates:
            pid = candidate["pid"]
            name = candidate["name"]
            exe = candidate["exe"]
            proc_val = candidate[sort_key]

            # 1. Safety check
            is_safe, safe_reason = ProtectedProcessValidator.is_safe_to_terminate(pid, name, exe)
            if not is_safe:
                if not skipped_first_candidate:
                    skipped_first_candidate = True
                    skip_event = {
                        "alert_type": "RESOURCE_PROTECTION",
                        "event_type": "RESOURCE_PROTECTION_SKIP",
                        "severity": "MEDIUM",
                        "resource": resource,
                        "system_usage": system_usage,
                        "threshold": threshold,
                        "process_name": name,
                        "pid": pid,
                        "process_usage": proc_val,
                        "reason": safe_reason,
                        "detected_at": utc_iso_now(),
                        "title": f"Resource protection skipped {name}: {safe_reason}",
                        "description": (
                            f"System {resource.upper()} reached {system_usage:.1f}% (threshold {threshold:.1f}%). "
                            f"Top consumer '{name}' (PID {pid}) was skipped because it is {safe_reason}."
                        ),
                    }
                    events.append(skip_event)
                    if self.alert_callback:
                        try:
                            self.alert_callback(skip_event)
                        except Exception as cb_err:
                            LOG.warning("[RESOURCE PROTECTION] Alert callback error: %s", cb_err)
                continue

            # 2. Eligibility check
            is_eligible, elig_reason = self._is_process_eligible(name, exe, rules)
            if not is_eligible:
                if not skipped_first_candidate:
                    skipped_first_candidate = True
                    skip_event = {
                        "alert_type": "RESOURCE_PROTECTION",
                        "event_type": "RESOURCE_PROTECTION_SKIP",
                        "severity": "MEDIUM",
                        "resource": resource,
                        "system_usage": system_usage,
                        "threshold": threshold,
                        "process_name": name,
                        "pid": pid,
                        "process_usage": proc_val,
                        "reason": "process not eligible for automatic termination",
                        "detected_at": utc_iso_now(),
                        "title": f"Resource protection skipped {name}: not eligible",
                        "description": (
                            f"System {resource.upper()} reached {system_usage:.1f}% (threshold {threshold:.1f}%). "
                            f"High consumer '{name}' (PID {pid}) was not terminated because it is not eligible for automatic termination."
                        ),
                    }
                    events.append(skip_event)
                    if self.alert_callback:
                        try:
                            self.alert_callback(skip_event)
                        except Exception as cb_err:
                            LOG.warning("[RESOURCE PROTECTION] Alert callback error: %s", cb_err)
                continue

            # Found an eligible, non-protected candidate!
            chosen_candidate = candidate
            break

        if not chosen_candidate:
            return events

        # Check rate limits & cooldown
        pid = chosen_candidate["pid"]
        name = chosen_candidate["name"]
        proc_val = chosen_candidate[sort_key]

        if self._last_intervention_time and (now - self._last_intervention_time < cooldown_seconds):
            cooldown_event = {
                "alert_type": "RESOURCE_PROTECTION",
                "event_type": "RESOURCE_PROTECTION_SKIP",
                "severity": "MEDIUM",
                "resource": resource,
                "system_usage": system_usage,
                "process_name": name,
                "pid": pid,
                "reason": "cooldown_active",
                "detected_at": utc_iso_now(),
                "title": f"Resource protection on {name} skipped: cooldown active",
                "description": f"Intervention on '{name}' skipped because cooldown period ({cooldown_seconds}s) is active.",
            }
            events.append(cooldown_event)
            return events

        # Hourly limit
        cutoff_hour = now - 3600
        recent_interventions = [t for t in self._interventions if t >= cutoff_hour]
        if len(recent_interventions) >= max_interventions:
            limit_event = {
                "alert_type": "RESOURCE_PROTECTION",
                "event_type": "RESOURCE_PROTECTION_SKIP",
                "severity": "HIGH",
                "resource": resource,
                "system_usage": system_usage,
                "process_name": name,
                "pid": pid,
                "reason": "max_interventions_per_hour_reached",
                "detected_at": utc_iso_now(),
                "title": f"Resource protection limit reached ({max_interventions}/hr)",
                "description": f"Cannot terminate '{name}' because max interventions per hour ({max_interventions}) was reached.",
            }
            events.append(limit_event)
            return events

        # Execute termination
        detected_ts = utc_iso_now()
        termination_info = {"status": "SKIPPED", "action": "DETECTED_ONLY"}
        if self.auto_terminate:
            termination_info = ProcessManager.terminate_process(pid, name, timeout=self.termination_timeout)
            self._last_intervention_time = now
            self._interventions.append(now)

        action_str = "TERMINATED" if termination_info.get("status") == "SUCCESS" else "TERMINATION_FAILED"
        if not self.auto_terminate:
            action_str = "DETECTED_ONLY"

        # Wait briefly and re-measure
        time.sleep(1.0)
        try:
            new_usage = (
                psutil.cpu_percent(interval=0.2)
                if resource == "cpu"
                else psutil.virtual_memory().percent
            )
        except Exception:
            new_usage = system_usage

        action_event = {
            "alert_type": "RESOURCE_PROTECTION",
            "event_type": "RESOURCE_PROTECTION_ACTION",
            "severity": "HIGH",
            "resource": resource,
            "system_usage": system_usage,
            "threshold": threshold,
            "post_action_usage": new_usage,
            "process_name": name,
            "pid": pid,
            "process_usage": proc_val,
            "action": action_str,
            "reason": "sustained_resource_pressure",
            "detected_at": detected_ts,
            "activity_time": detected_ts,
            "title": f"Resource protection action: {action_str.lower()} {name}",
            "description": (
                f"Sustained {resource.upper()} pressure ({system_usage:.1f}% >= {threshold:.1f}%). "
                f"Offending process '{name}' (PID {pid}, {resource.upper()}: {proc_val:.1f}%) was {action_str.lower()}. "
                f"New system usage: {new_usage:.1f}%."
            ),
        }
        events.append(action_event)
        LOG.warning(
            "[RESOURCE PROTECTION] Executed action: %s on %s (PID %s) due to sustained %s usage (%.1f%%).",
            action_str,
            name,
            pid,
            resource,
            system_usage,
        )

        if self.alert_callback:
            try:
                self.alert_callback(action_event)
            except Exception as cb_err:
                LOG.warning("[RESOURCE PROTECTION] Alert callback error: %s", cb_err)

        return events

    def evaluate_and_enforce(self) -> List[Dict[str, Any]]:
        """Check system metrics against sustained thresholds and intervene if needed."""
        with self._config_lock:
            config = dict(self._config)

        if not config.get("enabled", True):
            self._cpu_high_since = None
            self._memory_high_since = None
            return []

        now = time.time()
        generated_events: List[Dict[str, Any]] = []

        try:
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory_percent = psutil.virtual_memory().percent
        except Exception as err:
            LOG.warning("[RESOURCE PROTECTION] Could not measure system metrics: %s", err)
            return []

        # 1. CPU Protection
        cpu_conf = config.get("cpu", {})
        if cpu_conf.get("enabled", True):
            cpu_threshold = float(cpu_conf.get("threshold", 85.0))
            cpu_sustained = float(cpu_conf.get("sustained_seconds", 30))
            if cpu_percent >= cpu_threshold:
                if self._cpu_high_since is None:
                    self._cpu_high_since = now
                duration = now - self._cpu_high_since
                if duration >= cpu_sustained:
                    LOG.warning(
                        "[RESOURCE PROTECTION] CPU pressure sustained for %.1fs (%.1f%% >= %.1f%%). Triggering evaluation.",
                        duration,
                        cpu_percent,
                        cpu_threshold,
                    )
                    evs = self._evaluate_candidates("cpu", cpu_percent, cpu_threshold)
                    generated_events.extend(evs)
                    self._cpu_high_since = None  # Reset timer after intervention
            else:
                self._cpu_high_since = None

        # 2. Memory Protection
        mem_conf = config.get("memory", {})
        if mem_conf.get("enabled", True):
            mem_threshold = float(mem_conf.get("threshold", 90.0))
            mem_sustained = float(mem_conf.get("sustained_seconds", 30))
            if memory_percent >= mem_threshold:
                if self._memory_high_since is None:
                    self._memory_high_since = now
                duration = now - self._memory_high_since
                if duration >= mem_sustained:
                    LOG.warning(
                        "[RESOURCE PROTECTION] Memory pressure sustained for %.1fs (%.1f%% >= %.1f%%). Triggering evaluation.",
                        duration,
                        memory_percent,
                        mem_threshold,
                    )
                    evs = self._evaluate_candidates("memory", memory_percent, mem_threshold)
                    generated_events.extend(evs)
                    self._memory_high_since = None  # Reset timer after intervention
            else:
                self._memory_high_since = None

        return generated_events

    def run_loop(self, stop_event: Optional[threading.Event] = None) -> None:
        """Run continuous monitoring loop."""
        stop = stop_event or self._stop_event
        LOG.info("[RESOURCE PROTECTION] Started continuous monitoring loop (interval: %.1fs).", self.scan_interval)
        while not stop.is_set():
            try:
                self.evaluate_and_enforce()
            except Exception as err:
                LOG.exception("[RESOURCE PROTECTION] Unexpected error in loop: %s", err)

            if stop.wait(self.scan_interval):
                break
        LOG.info("[RESOURCE PROTECTION] Stopped monitoring loop.")

    def start(self) -> None:
        """Start background worker thread."""
        if self._worker_thread is not None and self._worker_thread.is_alive():
            return
        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self.run_loop,
            args=(self._stop_event,),
            name="resource-protection-monitor",
            daemon=True,
        )
        self._worker_thread.start()

    def stop(self) -> None:
        """Stop background worker thread."""
        self._stop_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=3.0)

