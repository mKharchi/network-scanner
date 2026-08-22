"""Network Quarantine Manager for Endpoint Isolation.

Implements network quarantine enforcement via Windows Firewall (or mock/iptables on Linux)
while keeping the management channel with the central server open for telemetry and recovery.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
import logging
import os
import platform
import subprocess
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

LOG = logging.getLogger("quarantine_manager")

# Standardized rule names
RULE_INBOUND = "AgentQuarantine-Inbound"
RULE_OUTBOUND = "AgentQuarantine-Outbound"
RULE_ALLOW_SERVER_OUT = "AgentQuarantine-Server-Allow-Out"
RULE_ALLOW_SERVER_IN = "AgentQuarantine-Server-Allow-In"
RULE_ALLOW_LOOPBACK_IN = "AgentQuarantine-Loopback-In"
RULE_ALLOW_LOOPBACK_OUT = "AgentQuarantine-Loopback-Out"

ALL_QUARANTINE_RULES = (
    RULE_ALLOW_SERVER_OUT,
    RULE_ALLOW_SERVER_IN,
    RULE_ALLOW_LOOPBACK_IN,
    RULE_ALLOW_LOOPBACK_OUT,
    RULE_INBOUND,
    RULE_OUTBOUND,
)


class QuarantineState:
    NORMAL = "NORMAL"
    QUARANTINE_PENDING = "QUARANTINE_PENDING"
    QUARANTINED = "QUARANTINED"
    QUARANTINE_FAILED = "QUARANTINE_FAILED"
    RESTORE_PENDING = "RESTORE_PENDING"


class NetworkQuarantineManager:
    """Manages endpoint network isolation state and firewall enforcement."""

    def __init__(
        self,
        server_ip: str = "127.0.0.1",
        server_port: int = 5000,
        *,
        default_max_duration_minutes: int = 60,
        event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        dry_run: bool = False,
    ):
        self.server_ip = server_ip
        self.server_port = int(server_port)
        self.default_max_duration_minutes = max(1, default_max_duration_minutes)
        self.event_callback = event_callback
        self.dry_run = dry_run

        self._state = QuarantineState.NORMAL
        self._reason: Optional[str] = None
        self._quarantined_at: Optional[datetime] = None
        self._expires_at: Optional[datetime] = None
        self._command_id: Optional[str] = None

        self._lock = threading.RLock()
        self._timer_thread: Optional[threading.Thread] = None
        self._stop_timer = threading.Event()

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def is_quarantined(self) -> bool:
        with self._lock:
            return self._state == QuarantineState.QUARANTINED

    @staticmethod
    def _enforcement_method() -> str:
        """Describe whether this runtime is applying real firewall controls."""
        if platform.system() == "Windows":
            return "WINDOWS_FIREWALL"
        return "SIMULATED_NO_FIREWALL"

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "state": self._state,
                "is_quarantined": self._state == QuarantineState.QUARANTINED,
                "reason": self._reason,
                "quarantined_at": self._quarantined_at.isoformat() if self._quarantined_at else None,
                "expires_at": self._expires_at.isoformat() if self._expires_at else None,
                "command_id": self._command_id,
                "server_ip": self.server_ip,
                "server_port": self.server_port,
                "enforcement_method": self._enforcement_method(),
            }

    def _run_cmd(self, cmd: list[str]) -> Tuple[int, str]:
        """Execute command safely, returning (exit_code, output)."""
        if self.dry_run:
            LOG.info("[QUARANTINE DRY-RUN] Would execute: %s", " ".join(cmd))
            return 0, "dry-run success"
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            output = (res.stdout or "") + (res.stderr or "")
            return res.returncode, output.strip()
        except Exception as err:
            return -1, str(err)

    def _apply_windows_firewall_rules(self) -> Tuple[bool, str]:
        """Create Windows Firewall rules: whitelist central server & loopback, block all else."""
        # 1. First remove any existing quarantine rules for idempotency
        self._remove_windows_firewall_rules()

        server_target = self.server_ip if self.server_ip not in ("0.0.0.0", "127.0.0.1", "localhost") else None

        # 2. Add whitelist rules first
        if server_target:
            code, out = self._run_cmd([
                "netsh", "advfirewall", "firewall", "add", "rule",
                f"name={RULE_ALLOW_SERVER_OUT}",
                "dir=out", "action=allow",
                f"remoteip={server_target}",
                f"remoteport={self.server_port}",
                "protocol=TCP", "enable=yes",
            ])
            if code != 0:
                return False, f"Failed adding server out rule: {out}"

            code, out = self._run_cmd([
                "netsh", "advfirewall", "firewall", "add", "rule",
                f"name={RULE_ALLOW_SERVER_IN}",
                "dir=in", "action=allow",
                f"remoteip={server_target}",
                "protocol=TCP", "enable=yes",
            ])
            if code != 0:
                return False, f"Failed adding server in rule: {out}"

        # Loopback whitelist
        self._run_cmd([
            "netsh", "advfirewall", "firewall", "add", "rule",
            f"name={RULE_ALLOW_LOOPBACK_IN}",
            "dir=in", "action=allow", "remoteip=127.0.0.1", "enable=yes",
        ])
        self._run_cmd([
            "netsh", "advfirewall", "firewall", "add", "rule",
            f"name={RULE_ALLOW_LOOPBACK_OUT}",
            "dir=out", "action=allow", "remoteip=127.0.0.1", "enable=yes",
        ])

        # 3. Add block rules for everything else
        code, out = self._run_cmd([
            "netsh", "advfirewall", "firewall", "add", "rule",
            f"name={RULE_OUTBOUND}",
            "dir=out", "action=block", "enable=yes",
        ])
        if code != 0:
            return False, f"Failed adding outbound block rule: {out}"

        code, out = self._run_cmd([
            "netsh", "advfirewall", "firewall", "add", "rule",
            f"name={RULE_INBOUND}",
            "dir=in", "action=block", "enable=yes",
        ])
        if code != 0:
            return False, f"Failed adding inbound block rule: {out}"

        return True, "Firewall rules applied successfully."

    def _remove_windows_firewall_rules(self) -> Tuple[bool, str]:
        """Delete only AgentQuarantine-* rules, leaving general firewall intact."""
        errors = []
        for rule_name in ALL_QUARANTINE_RULES:
            code, out = self._run_cmd([
                "netsh", "advfirewall", "firewall", "delete", "rule",
                f"name={rule_name}",
            ])
            # code != 0 with 'No rules match' is normal during cleanups
            if code != 0 and "No rules match" not in out and "0 rule(s) deleted" not in out:
                errors.append(f"{rule_name}: {out}")

        if errors:
            return False, "; ".join(errors)
        return True, "Quarantine rules removed."

    def _apply_rules(self) -> Tuple[bool, str]:
        """Apply firewall rules according to OS."""
        if platform.system() == "Windows" and not self.dry_run:
            return self._apply_windows_firewall_rules()
        # Mock/simulated platform handler
        return True, "Quarantine rules simulated successfully."

    def _remove_rules(self) -> Tuple[bool, str]:
        """Remove firewall rules according to OS."""
        if platform.system() == "Windows" and not self.dry_run:
            return self._remove_windows_firewall_rules()
        # Mock/simulated platform handler
        return True, "Quarantine rules removal simulated successfully."

    def _start_fail_safe_timer(self, duration_minutes: int) -> None:
        """Start background fail-safe timer for automatic quarantine rollback."""
        self._stop_timer.set()
        if self._timer_thread and self._timer_thread.is_alive():
            self._timer_thread.join(timeout=1.0)

        self._stop_timer.clear()
        duration_seconds = max(10, duration_minutes * 60)

        def _timer_worker():
            if self._stop_timer.wait(duration_seconds):
                return
            LOG.warning("[QUARANTINE] Quarantine expired after %d minutes! Executing fail-safe release.", duration_minutes)
            self.release_quarantine(reason="Quarantine duration expired (fail-safe release)")

        self._timer_thread = threading.Thread(
            target=_timer_worker,
            name="quarantine-failsafe-timer",
            daemon=True,
        )
        self._timer_thread.start()

    def quarantine_endpoint(
        self,
        reason: str = "Administrator requested network isolation",
        duration_minutes: Optional[int] = None,
        command_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Place endpoint into network quarantine."""
        with self._lock:
            self._state = QuarantineState.QUARANTINE_PENDING
            dur = duration_minutes or self.default_max_duration_minutes
            now_dt = datetime.now(timezone.utc)
            self._reason = reason
            self._command_id = command_id
            self._quarantined_at = now_dt
            self._expires_at = now_dt + timedelta(minutes=dur)

            success, msg = self._apply_rules()
            if success:
                self._state = QuarantineState.QUARANTINED
                self._start_fail_safe_timer(dur)
                event = {
                    "event_type": "CLIENT_QUARANTINED",
                    "reason": reason,
                    "timestamp": now_dt.isoformat(),
                    "expires_at": self._expires_at.isoformat(),
                    "enforcement_method": self._enforcement_method(),
                    "command_id": command_id,
                }
                if self.event_callback:
                    try:
                        self.event_callback(event)
                    except Exception as err:
                        LOG.warning("[QUARANTINE] Event callback error: %s", err)

                LOG.warning("[QUARANTINE] Endpoint QUARANTINED: reason=%s (expires in %d min)", reason, dur)
                return {
                    "status": "ok",
                    "state": self._state,
                    "message": "Endpoint successfully quarantined.",
                    "expires_at": self._expires_at.isoformat(),
                }
            else:
                self._state = QuarantineState.QUARANTINE_FAILED
                event = {
                    "event_type": "CLIENT_QUARANTINE_FAILED",
                    "reason": f"Firewall rule application failed: {msg}",
                    "timestamp": now_dt.isoformat(),
                    "command_id": command_id,
                }
                if self.event_callback:
                    try:
                        self.event_callback(event)
                    except Exception as err:
                        LOG.warning("[QUARANTINE] Event callback error: %s", err)

                LOG.error("[QUARANTINE] Quarantine FAILED: %s", msg)
                return {
                    "status": "error",
                    "state": self._state,
                    "message": f"Quarantine failed: {msg}",
                }

    def release_quarantine(
        self,
        reason: str = "Administrator released quarantine",
        command_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Release endpoint from network quarantine."""
        with self._lock:
            self._stop_timer.set()
            self._state = QuarantineState.RESTORE_PENDING

            success, msg = self._remove_rules()
            now_dt = datetime.now(timezone.utc)
            if not success:
                # Keep the endpoint marked as quarantined because some or all
                # blocking rules may still be active after a failed cleanup.
                self._state = QuarantineState.QUARANTINED
                event = {
                    "event_type": "CLIENT_QUARANTINE_RELEASE_FAILED",
                    "reason": f"Firewall rule cleanup failed: {msg}",
                    "timestamp": now_dt.isoformat(),
                    "command_id": command_id,
                }
                if self.event_callback:
                    try:
                        self.event_callback(event)
                    except Exception as err:
                        LOG.warning("[QUARANTINE] Event callback error: %s", err)
                LOG.error("[QUARANTINE] Quarantine release FAILED: %s", msg)
                return {
                    "status": "error",
                    "state": self._state,
                    "message": f"Quarantine release failed: {msg}",
                }

            self._state = QuarantineState.NORMAL
            self._reason = None
            self._quarantined_at = None
            self._expires_at = None
            self._command_id = None

            event = {
                "event_type": "CLIENT_QUARANTINE_RELEASED",
                "reason": reason,
                "timestamp": now_dt.isoformat(),
                "command_id": command_id,
            }
            if self.event_callback:
                try:
                    self.event_callback(event)
                except Exception as err:
                    LOG.warning("[QUARANTINE] Event callback error: %s", err)

            LOG.info("[QUARANTINE] Endpoint RESTORED to normal network state: reason=%s", reason)
            return {
                "status": "ok",
                "state": self._state,
                "message": "Quarantine released and normal network access restored.",
            }
