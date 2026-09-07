"""Client Activity and Event Monitoring Layer (Plan Phase 2).

Provides:
- Standardized event taxonomy (Application, File, Client events).
- Windows registry-based application install/uninstall/update detection.
- Monitored directory filesystem change detection (creation, modification, deletion).
- Event noise filtering, deduplication, and rate limiting to prevent event storms.
- Local event persistence in ``client/storage/events/``.
- Integration callbacks to forward events to the server as alerts.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import socket
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

LOG = logging.getLogger("event_monitor")

# ---------------------------------------------------------------------------
# Standard Event Taxonomy (Plan §2.1)
# ---------------------------------------------------------------------------

# Application events
APP_INSTALLED = "APP_INSTALLED"
APP_UNINSTALLED = "APP_UNINSTALLED"
APP_UPDATED = "APP_UPDATED"
APP_STARTED = "APP_STARTED"
APP_STOPPED = "APP_STOPPED"

# File events
FILE_CREATED = "FILE_CREATED"
FILE_MODIFIED = "FILE_MODIFIED"
FILE_DELETED = "FILE_DELETED"
FILE_RENAMED = "FILE_RENAMED"

# Client events
CLIENT_STARTED = "CLIENT_STARTED"
CLIENT_STOPPED = "CLIENT_STOPPED"
CLIENT_UPDATED = "CLIENT_UPDATED"
CLIENT_UPDATE_FAILED = "CLIENT_UPDATE_FAILED"
CLIENT_CONFIG_CHANGED = "CLIENT_CONFIG_CHANGED"

ALL_EVENT_TYPES = frozenset({
    APP_INSTALLED,
    APP_UNINSTALLED,
    APP_UPDATED,
    APP_STARTED,
    APP_STOPPED,
    FILE_CREATED,
    FILE_MODIFIED,
    FILE_DELETED,
    FILE_RENAMED,
    CLIENT_STARTED,
    CLIENT_STOPPED,
    CLIENT_UPDATED,
    CLIENT_UPDATE_FAILED,
    CLIENT_CONFIG_CHANGED,
})

# Patterns to ignore to prevent event storms and filter passive monitoring/internal files (Plan §9-§13)
DEFAULT_IGNORE_PATTERNS = [
    # Temporary, cache, and editor swap files
    re.compile(r".*\.tmp$", re.IGNORECASE),
    re.compile(r".*\.temp$", re.IGNORECASE),
    re.compile(r".*\.partial$", re.IGNORECASE),
    re.compile(r".*\.lock$", re.IGNORECASE),
    re.compile(r".*~.*"),
    re.compile(r".*\.swp$", re.IGNORECASE),
    re.compile(r".*\.log$", re.IGNORECASE),
    re.compile(r".*\.pyc$", re.IGNORECASE),
    re.compile(r".*__pycache__.*"),
    re.compile(r".*\.pytest_cache.*"),
    re.compile(r".*(\.git|\.venv)(/|\\).*", re.IGNORECASE),
    re.compile(r".*AppData[/\\]Local[/\\]Temp.*", re.IGNORECASE),
    re.compile(r".*logs([/\\].*)?$", re.IGNORECASE),
    # Passive packet, neighbourhood, and telemetry storage (Plan §9-§12)
    re.compile(r".*storage[/\\]network_neighbourhood.*", re.IGNORECASE),
    re.compile(r".*storage[/\\]network_telemetry.*", re.IGNORECASE),
    re.compile(r".*storage[/\\]passive_packets.*", re.IGNORECASE),
    # Event monitor persistence & internal client state files
    re.compile(r".*storage[/\\]events.*", re.IGNORECASE),
    re.compile(r".*storage[/\\]sent-files.*", re.IGNORECASE),
    re.compile(r".*storage[/\\]neighbour_snapshot_state\.json.*", re.IGNORECASE),
    re.compile(r".*storage[/\\]forbidden_process.*", re.IGNORECASE),
    re.compile(r".*storage[/\\]reported_alerts\.json.*", re.IGNORECASE),
]


def is_excluded_path(
    path: Path | str,
    ignore_patterns: Optional[List[re.Pattern]] = None,
) -> bool:
    """Centralized check for excluded filesystem paths (Plan §10)."""
    if not path:
        return False
    path_str = str(Path(path).resolve()) if isinstance(path, Path) else str(path)
    patterns = ignore_patterns if ignore_patterns is not None else DEFAULT_IGNORE_PATTERNS
    return any(p.search(path_str) or p.match(path_str) for p in patterns)


@dataclass
class ClientEvent:
    """Standardized client event record (Plan §2.5)."""

    event_type: str
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    client_id: str = "unknown"
    path: Optional[str] = None
    application: Optional[str] = None
    version: Optional[str] = None
    user: Optional[str] = None
    process: Optional[str] = None
    source: str = "event_monitor"
    details: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        # Drop None fields for concise serialization
        return {k: v for k, v in data.items() if v is not None}


# ---------------------------------------------------------------------------
# Rate Limiting & Deduplication (Plan §2.4)
# ---------------------------------------------------------------------------


class EventRateLimiter:
    """Sliding-window rate limiter to guard against event storms."""

    def __init__(self, max_events: int = 50, window_seconds: float = 10.0) -> None:
        self.max_events = max_events
        self.window_seconds = window_seconds
        self._timestamps: List[float] = []
        self._lock = threading.Lock()

    def allow(self, now: Optional[float] = None) -> bool:
        current_time = now if now is not None else time.monotonic()
        with self._lock:
            cutoff = current_time - self.window_seconds
            self._timestamps = [t for t in self._timestamps if t > cutoff]
            if len(self._timestamps) >= self.max_events:
                return False
            self._timestamps.append(current_time)
            return True


class EventDeduplicator:
    """Debounces identical events occurring within a suppression window."""

    def __init__(self, debounce_seconds: float = 3.0) -> None:
        self.debounce_seconds = debounce_seconds
        self._recent: Dict[Tuple[str, str], float] = {}
        self._lock = threading.Lock()

    def is_duplicate(
        self, event_type: str, key: str, now: Optional[float] = None
    ) -> bool:
        current_time = now if now is not None else time.monotonic()
        with self._lock:
            # Purge expired
            cutoff = current_time - (self.debounce_seconds * 2)
            self._recent = {k: v for k, v in self._recent.items() if v > cutoff}

            cache_key = (event_type, key)
            last_time = self._recent.get(cache_key)
            if last_time is not None and (current_time - last_time) < self.debounce_seconds:
                return True
            self._recent[cache_key] = current_time
            return False


# ---------------------------------------------------------------------------
# Windows Registry Application Inventory Reader (Plan §2.2)
# ---------------------------------------------------------------------------


def get_installed_applications_windows() -> Dict[str, str]:
    """Read installed applications from the Windows Registry.

    Inspects:
    - HKLM\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall
    - HKLM\\Software\\Wow6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall
    - HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall

    Returns a dict mapping DisplayName -> DisplayVersion.
    """
    apps: Dict[str, str] = {}
    if platform.system() != "Windows":
        return apps

    try:
        import winreg
    except ImportError:
        return apps

    hives = [
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]

    for root_hive, subkey_path in hives:
        try:
            with winreg.OpenKey(root_hive, subkey_path) as key:
                num_subkeys = winreg.QueryInfoKey(key)[0]
                for i in range(num_subkeys):
                    try:
                        subkey_name = winreg.EnumKey(key, i)
                        with winreg.OpenKey(key, subkey_name) as app_key:
                            try:
                                name, _ = winreg.QueryValueEx(app_key, "DisplayName")
                                if not name or not str(name).strip():
                                    continue
                                name = str(name).strip()
                                version = ""
                                try:
                                    ver, _ = winreg.QueryValueEx(app_key, "DisplayVersion")
                                    version = str(ver).strip() if ver else ""
                                except OSError:
                                    pass
                                apps[name] = version or "unknown"
                            except OSError:
                                continue
                    except OSError:
                        continue
        except OSError:
            continue

    return apps


# ---------------------------------------------------------------------------
# Directory Filesystem Snapshot & Diff (Plan §2.3)
# ---------------------------------------------------------------------------


def _scan_directory_state(
    directory: Path,
    ignore_patterns: Optional[List[re.Pattern]] = None,
    max_files: int = 1000,
) -> Dict[str, float]:
    """Return a mapping of str(file_path) -> mtime for files in directory."""
    patterns = ignore_patterns if ignore_patterns is not None else DEFAULT_IGNORE_PATTERNS
    state: Dict[str, float] = {}
    if not directory.exists() or not directory.is_dir():
        return state

    try:
        count = 0
        for entry in directory.rglob("*"):
            if count >= max_files:
                break
            if not entry.is_file():
                continue
            path_str = str(entry.resolve())
            if is_excluded_path(path_str, patterns):
                continue
            try:
                state[path_str] = entry.stat().st_mtime
                count += 1
            except OSError:
                continue
    except OSError as err:
        LOG.debug("[EVENT_MONITOR] Error scanning %s: %s", directory, err)

    return state


# ---------------------------------------------------------------------------
# Event Monitor Manager
# ---------------------------------------------------------------------------


class EventMonitor:
    """Coordinates application and filesystem event detection."""

    def __init__(
        self,
        *,
        client_id: Optional[str] = None,
        monitored_directories: Optional[List[Path | str]] = None,
        storage_root: Optional[Path | str] = None,
        event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        scan_interval_seconds: float = 10.0,
        app_scan_interval_seconds: float = 60.0,
        ignore_patterns: Optional[List[re.Pattern]] = None,
        apps_provider: Optional[Callable[[], Dict[str, str]]] = None,
    ) -> None:
        self.client_id = client_id or "unknown-client"
        self.monitored_directories = [
            Path(d).resolve() for d in (monitored_directories or [])
        ]
        client_root = Path(__file__).resolve().parent.parent
        self.storage_root = (
            Path(storage_root) if storage_root else (client_root / "storage" / "events")
        )
        self.event_callback = event_callback
        self.scan_interval = scan_interval_seconds
        self.app_scan_interval = app_scan_interval_seconds
        self.ignore_patterns = ignore_patterns or DEFAULT_IGNORE_PATTERNS
        self._apps_provider = apps_provider or get_installed_applications_windows

        self._rate_limiter = EventRateLimiter(max_events=30, window_seconds=10.0)
        self._deduplicator = EventDeduplicator(debounce_seconds=3.0)

        self._file_states: Dict[str, Dict[str, float]] = {}
        self._installed_apps: Dict[str, str] = {}
        self._has_scanned_apps = False
        self._lock = threading.RLock()

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def initialize_baselines(self) -> None:
        """Capture initial baseline of applications and files to avoid startup flood."""
        with self._lock:
            # File state baseline
            for d in self.monitored_directories:
                if d.exists():
                    self._file_states[str(d)] = _scan_directory_state(
                        d, self.ignore_patterns
                    )

            # Application baseline
            try:
                self._installed_apps = self._apps_provider()
                self._has_scanned_apps = True
            except Exception as err:
                LOG.warning("[EVENT_MONITOR] Could not initialize app baseline: %s", err)

    def check_application_changes(self) -> List[ClientEvent]:
        """Detect installed, uninstalled, or updated applications."""
        events: List[ClientEvent] = []
        try:
            current_apps = self._apps_provider()
        except Exception as err:
            LOG.warning("[EVENT_MONITOR] App scan error: %s", err)
            return events

        with self._lock:
            if not self._has_scanned_apps:
                self._installed_apps = current_apps
                self._has_scanned_apps = True
                return events

            old_names = set(self._installed_apps.keys())
            new_names = set(current_apps.keys())

            # Uninstalled applications (Plan §2.2)
            for removed in old_names - new_names:
                version = self._installed_apps.get(removed)
                events.append(
                    ClientEvent(
                        event_type=APP_UNINSTALLED,
                        client_id=self.client_id,
                        application=removed,
                        version=version,
                        source="windows_registry_monitor",
                    )
                )

            # Installed applications
            for added in new_names - old_names:
                version = current_apps.get(added)
                events.append(
                    ClientEvent(
                        event_type=APP_INSTALLED,
                        client_id=self.client_id,
                        application=added,
                        version=version,
                        source="windows_registry_monitor",
                    )
                )

            # Updated applications
            for common in old_names & new_names:
                old_v = self._installed_apps.get(common)
                new_v = current_apps.get(common)
                if old_v and new_v and old_v != new_v and old_v != "unknown":
                    events.append(
                        ClientEvent(
                            event_type=APP_UPDATED,
                            client_id=self.client_id,
                            application=common,
                            version=f"{old_v} -> {new_v}",
                            source="windows_registry_monitor",
                        )
                    )

            self._installed_apps = current_apps

        return events

    def check_file_changes(self) -> List[ClientEvent]:
        """Detect created, modified, or deleted files in monitored directories."""
        events: List[ClientEvent] = []

        with self._lock:
            for directory in self.monitored_directories:
                dir_key = str(directory)
                previous_files = self._file_states.get(dir_key, {})
                current_files = _scan_directory_state(directory, self.ignore_patterns)

                old_paths = set(previous_files.keys())
                new_paths = set(current_files.keys())

                # Deleted files (Plan §2.3)
                for deleted_path in old_paths - new_paths:
                    if is_excluded_path(deleted_path, self.ignore_patterns):
                        continue
                    events.append(
                        ClientEvent(
                            event_type=FILE_DELETED,
                            client_id=self.client_id,
                            path=deleted_path,
                            source="filesystem_monitor",
                        )
                    )

                # Created files
                for created_path in new_paths - old_paths:
                    if is_excluded_path(created_path, self.ignore_patterns):
                        continue
                    events.append(
                        ClientEvent(
                            event_type=FILE_CREATED,
                            client_id=self.client_id,
                            path=created_path,
                            source="filesystem_monitor",
                        )
                    )

                # Modified files
                for common_path in old_paths & new_paths:
                    if is_excluded_path(common_path, self.ignore_patterns):
                        continue
                    if abs(current_files[common_path] - previous_files[common_path]) > 0.001:
                        events.append(
                            ClientEvent(
                                event_type=FILE_MODIFIED,
                                client_id=self.client_id,
                                path=common_path,
                                source="filesystem_monitor",
                            )
                        )

                self._file_states[dir_key] = current_files

        return events

    def emit_event(self, event: ClientEvent) -> bool:
        """Process, filter, persist, and dispatch a client event."""
        # 0. Path exclusion check (Plan §10-§13)
        if event.path and is_excluded_path(event.path, self.ignore_patterns):
            LOG.debug("[EVENT_MONITOR] Excluded path event dropped: %s", event.path)
            return False

        # 1. Deduplication check
        dedup_key = event.path or event.application or event.event_type
        if self._deduplicator.is_duplicate(event.event_type, dedup_key):
            LOG.debug(
                "[EVENT_MONITOR] Debounced duplicate event: %s (%s)",
                event.event_type,
                dedup_key,
            )
            return False

        # 2. Rate limiting check
        if not self._rate_limiter.allow():
            LOG.warning(
                "[EVENT_MONITOR] Rate limit exceeded, dropping event: %s (%s)",
                event.event_type,
                dedup_key,
            )
            return False

        # 3. Log event
        LOG.info(
            "[EVENT_MONITOR] %s: app=%s path=%s version=%s",
            event.event_type,
            event.application or "none",
            event.path or "none",
            event.version or "none",
        )

        # 4. Local persistence
        event_dict = event.to_dict()
        self._persist_event(event_dict)

        # 5. Delivery callback
        if self.event_callback:
            try:
                self.event_callback(event_dict)
            except Exception as err:
                LOG.warning("[EVENT_MONITOR] Event callback failed: %s", err)

        return True

    def _persist_event(self, event_dict: Dict[str, Any]) -> None:
        """Append event to day-scoped storage."""
        try:
            today_str = datetime.now().astimezone().date().isoformat()
            day_file = self.storage_root / f"{today_str}.json"
            self.storage_root.mkdir(parents=True, exist_ok=True)

            existing: List[Dict[str, Any]] = []
            if day_file.exists():
                try:
                    with day_file.open("r", encoding="utf-8") as fh:
                        data = json.load(fh)
                        if isinstance(data, list):
                            existing = data
                except Exception:
                    existing = []

            existing.append(event_dict)

            # Atomic write
            temp_file = day_file.with_suffix(".tmp")
            with temp_file.open("w", encoding="utf-8") as fh:
                json.dump(existing, fh, indent=2, ensure_ascii=False)
                fh.write("\n")
            os.replace(temp_file, day_file)
        except Exception as err:
            LOG.warning("[EVENT_MONITOR] Could not persist event: %s", err)

    def poll_once(self) -> int:
        """Perform a single check pass and emit detected events. Returns event count."""
        app_events = self.check_application_changes()
        file_events = self.check_file_changes()
        all_events = app_events + file_events
        emitted = 0
        for ev in all_events:
            if self.emit_event(ev):
                emitted += 1
        return emitted

    def start(self) -> None:
        """Start background polling thread."""
        if self._thread and self._thread.is_alive():
            return
        self.initialize_baselines()
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="event-monitor-loop",
        )
        self._thread.start()
        LOG.info("[EVENT_MONITOR] Event monitor started.")

    def stop(self) -> None:
        """Stop background polling thread."""
        if self._thread:
            self._stop_event.set()
            self._thread.join(timeout=3.0)
            self._thread = None
            LOG.info("[EVENT_MONITOR] Event monitor stopped.")

    def _run_loop(self) -> None:
        last_app_scan = 0.0
        while not self._stop_event.wait(self.scan_interval):
            try:
                now = time.monotonic()
                if now - last_app_scan >= self.app_scan_interval:
                    for ev in self.check_application_changes():
                        self.emit_event(ev)
                    last_app_scan = now

                for ev in self.check_file_changes():
                    self.emit_event(ev)
            except Exception as err:
                LOG.debug("[EVENT_MONITOR] Polling loop error: %s", err)
