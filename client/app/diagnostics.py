"""Client diagnostic infrastructure for structured monitoring and debugging.

Provides component-level logging categories, environment capture, storage
permission checks, and startup diagnostics as described in
``docs/client_monitoring/plan.md`` Phase 0.
"""

from __future__ import annotations

import getpass
import json
import logging
import os
import socket
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Component categories (Phase 0.1)
# ---------------------------------------------------------------------------

PERSISTENCE = "PERSISTENCE"
UPDATER = "UPDATER"
EVENT_MONITOR = "EVENT_MONITOR"
SCREENSHOT = "SCREENSHOT"
KISMET = "KISMET"
FLOW_AGGREGATOR = "FLOW_AGGREGATOR"
PASSIVE_LISTENER = "PASSIVE_LISTENER"
PROCESS_MONITOR = "PROCESS_MONITOR"
CLIENT_CORE = "CLIENT_CORE"

_APP_DIR = Path(__file__).resolve().parent
_CLIENT_DIR = _APP_DIR.parent
_VERSION_FILE = _APP_DIR / "version.json"


# ---------------------------------------------------------------------------
# Structured component logging
# ---------------------------------------------------------------------------


def component_log(
    logger: logging.Logger,
    component: str,
    operation: str,
    *,
    level: int = logging.INFO,
    **context: Any,
) -> None:
    """Emit a structured log message tagged with a component category.

    Example::

        component_log(LOG, PERSISTENCE, "flow persisted",
                      flow_id="abc123", target="/path/to/flows.json")
        # => [PERSISTENCE] flow persisted flow_id=abc123 target=/path/to/flows.json
    """
    parts = [f"[{component}] {operation}"]
    for key, value in context.items():
        parts.append(f"{key}={value}")
    logger.log(level, " ".join(parts))


# ---------------------------------------------------------------------------
# Environment capture (Phase 0.2)
# ---------------------------------------------------------------------------


def _read_agent_version() -> str:
    """Read the agent version from version.json, returning 'unknown' on failure."""
    try:
        with _VERSION_FILE.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
            return str(data.get("version", "unknown"))
    except Exception:
        return "unknown"


def _get_current_user() -> str:
    """Best-effort current username."""
    try:
        return os.getlogin()
    except OSError:
        pass
    try:
        return getpass.getuser()
    except Exception:
        return "unknown"


def _get_session_id() -> str:
    """Best-effort Windows session ID (returns 'N/A' on non-Windows)."""
    try:
        import platform
        if platform.system() != "Windows":
            return "N/A"
        import ctypes
        return str(ctypes.windll.kernel32.WTSGetActiveConsoleSessionId())  # type: ignore[attr-defined]
    except Exception:
        return "unknown"


def _is_running_as_service() -> bool:
    """Best-effort detection of Windows service context."""
    try:
        import platform
        if platform.system() != "Windows":
            return False
        # Session 0 is the non-interactive service session on modern Windows.
        import ctypes
        session_id = ctypes.windll.kernel32.WTSGetActiveConsoleSessionId()  # type: ignore[attr-defined]
        # Our own session — if it's 0, we're likely a service.
        import ctypes.wintypes
        pid = os.getpid()
        token_session = ctypes.c_ulong(0)
        # Fallback: check parent process name
        try:
            import psutil
            parent = psutil.Process(pid).parent()
            if parent and parent.name().lower() == "services.exe":
                return True
        except Exception:
            pass
        return False
    except Exception:
        return False


def capture_environment() -> Dict[str, Any]:
    """Collect a diagnostic snapshot of the client's runtime environment.

    Every field degrades gracefully to ``'unknown'`` on failure so that the
    caller never needs to handle exceptions from this function.
    """
    import platform as _platform

    def _safe(fn, default="unknown"):
        try:
            return fn()
        except Exception:
            return default

    return {
        "platform": _safe(lambda: _platform.platform()),
        "python_version": _safe(lambda: sys.version.split()[0]),
        "agent_version": _read_agent_version(),
        "installation_directory": _safe(lambda: str(_CLIENT_DIR)),
        "storage_directory": _safe(lambda: str(_CLIENT_DIR / "storage")),
        "current_user": _get_current_user(),
        "pid": os.getpid(),
        "hostname": _safe(lambda: socket.gethostname()),
        "is_service": _safe(lambda: _is_running_as_service(), default=False),
        "session_id": _get_session_id(),
        "working_directory": _safe(lambda: os.getcwd()),
        "executable_path": _safe(lambda: sys.executable),
    }


# ---------------------------------------------------------------------------
# Startup diagnostics (Phase 0.2)
# ---------------------------------------------------------------------------


def log_startup_diagnostics(logger: logging.Logger) -> None:
    """Log the full environment capture at startup, one field per line."""
    env = capture_environment()
    component_log(logger, CLIENT_CORE, "STARTUP_ENVIRONMENT_BEGIN")
    for key, value in env.items():
        component_log(logger, CLIENT_CORE, f"  {key}={value}")
    component_log(logger, CLIENT_CORE, "STARTUP_ENVIRONMENT_END")


# ---------------------------------------------------------------------------
# Storage permission check (Phase 1.2)
# ---------------------------------------------------------------------------


def check_storage_permissions(
    storage_dir: Path, logger: Optional[logging.Logger] = None
) -> Dict[str, Any]:
    """Inspect the storage directory and report accessibility.

    Returns a dict with ``path``, ``exists``, ``readable``, ``writable``,
    and ``owner`` keys.  Results are also logged if a *logger* is provided.
    """
    result: Dict[str, Any] = {
        "path": str(storage_dir.resolve()),
        "exists": False,
        "readable": False,
        "writable": False,
        "owner": "unknown",
    }

    try:
        result["exists"] = storage_dir.exists()
    except OSError:
        pass

    if result["exists"]:
        try:
            result["readable"] = os.access(storage_dir, os.R_OK)
        except OSError:
            pass
        try:
            result["writable"] = os.access(storage_dir, os.W_OK)
        except OSError:
            pass
        try:
            stat = storage_dir.stat()
            # On Unix, show uid; on Windows this may not be meaningful.
            import platform as _platform
            if _platform.system() != "Windows":
                import pwd
                result["owner"] = pwd.getpwuid(stat.st_uid).pw_name
            else:
                result["owner"] = "N/A (Windows)"
        except Exception:
            pass

    if logger:
        status = "OK" if (result["readable"] and result["writable"]) else "PROBLEM"
        component_log(
            logger,
            PERSISTENCE,
            f"storage_check={status}",
            path=result["path"],
            exists=result["exists"],
            readable=result["readable"],
            writable=result["writable"],
            owner=result["owner"],
        )

    return result
