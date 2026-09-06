"""Request-driven screenshot capture for the interactive Windows client.

This module deliberately has no scheduler, socket, or HTTP code.  A caller must
invoke :meth:`ScreenshotManager.capture` in response to a validated server
command after the server can reliably address the interactive user-session
agent.
"""

from __future__ import annotations

import getpass
import logging
import os
import platform
import re
import socket
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

LOG = logging.getLogger("screenshot")

SAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
DEFAULT_MAX_TEMP_FILES = 10
DEFAULT_MAX_TEMP_AGE_SECONDS = 3_600
USER_SESSION_AGENT_ROLES = ("interactive", "combined")


@dataclass(frozen=True)
class SessionTopology:
    """Windows session topology diagnostics (Plan §4.1)."""

    agent_user: str
    agent_session_id: Optional[int]
    active_session_id: Optional[int]
    interactive_user: str
    window_station: str
    desktop_name: str
    is_active_session: bool
    can_capture: bool
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_user": self.agent_user,
            "agent_session_id": self.agent_session_id,
            "active_session_id": self.active_session_id,
            "interactive_user": self.interactive_user,
            "window_station": self.window_station,
            "desktop_name": self.desktop_name,
            "is_active_session": self.is_active_session,
            "can_capture": self.can_capture,
            "reason": self.reason,
        }


def get_session_topology() -> SessionTopology:
    """Detect current process session vs active interactive console session (Plan §4.1)."""
    agent_user = "unknown"
    try:
        agent_user = os.getlogin()
    except OSError:
        try:
            agent_user = getpass.getuser()
        except Exception:
            pass

    if platform.system() != "Windows":
        return SessionTopology(
            agent_user=agent_user,
            agent_session_id=None,
            active_session_id=None,
            interactive_user=agent_user,
            window_station="N/A (Linux)",
            desktop_name="N/A (Linux)",
            is_active_session=True,
            can_capture=True,
            reason="Non-Windows OS - session isolation does not apply",
        )

    agent_session_id: Optional[int] = None
    active_session_id: Optional[int] = None
    window_station = "unknown"
    desktop_name = "unknown"
    interactive_user = "unknown"

    try:
        import ctypes
        import ctypes.wintypes

        # 1. Active Console Session
        active_session_id = ctypes.windll.kernel32.WTSGetActiveConsoleSessionId()  # type: ignore[attr-defined]
        if active_session_id == 0xFFFFFFFF:
            active_session_id = None

        # 2. Agent Process Session ID
        dw_session_id = ctypes.wintypes.DWORD()
        if ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(dw_session_id)):  # type: ignore[attr-defined]
            agent_session_id = dw_session_id.value

        # 3. Window Station
        hwinsta = ctypes.windll.user32.GetProcessWindowStation()  # type: ignore[attr-defined]
        if hwinsta:
            buf = ctypes.create_unicode_buffer(256)
            needed = ctypes.wintypes.DWORD()
            if ctypes.windll.user32.GetUserObjectInformationW(hwinsta, 2, buf, 512, ctypes.byref(needed)):  # type: ignore[attr-defined]
                window_station = buf.value

        # 4. Desktop Name
        hdesk = ctypes.windll.user32.GetThreadDesktop(ctypes.windll.kernel32.GetCurrentThreadId())  # type: ignore[attr-defined]
        if hdesk:
            buf = ctypes.create_unicode_buffer(256)
            needed = ctypes.wintypes.DWORD()
            if ctypes.windll.user32.GetUserObjectInformationW(hdesk, 2, buf, 512, ctypes.byref(needed)):  # type: ignore[attr-defined]
                desktop_name = buf.value

        # 5. Interactive User via WTSQuerySessionInformation
        if active_session_id is not None:
            buf_ptr = ctypes.c_void_p()
            bytes_ret = ctypes.wintypes.DWORD()
            if ctypes.windll.wtsapi32.WTSQuerySessionInformationW(0, active_session_id, 5, ctypes.byref(buf_ptr), ctypes.byref(bytes_ret)):  # type: ignore[attr-defined]
                if buf_ptr.value:
                    interactive_user = ctypes.wstring_at(buf_ptr.value)
                    ctypes.windll.wtsapi32.WTSFreeMemory(buf_ptr)  # type: ignore[attr-defined]
    except Exception as err:
        LOG.debug("[SCREENSHOT] Session detection error: %s", err)

    is_active = (
        agent_session_id is not None
        and active_session_id is not None
        and agent_session_id == active_session_id
    )
    if agent_session_id == 0:
        can_capture = False
        reason = (
            f"Agent running in Session 0 (service); active console is Session {active_session_id} "
            f"({interactive_user}). Desktop capture requires an interactive user-session agent."
        )
    elif active_session_id is None:
        can_capture = False
        reason = "No interactive console session currently active on Windows."
    elif not is_active:
        can_capture = False
        reason = (
            f"Agent session ({agent_session_id}) does not match active console session ({active_session_id})."
        )
    else:
        can_capture = True
        reason = "Session matches active console desktop."

    return SessionTopology(
        agent_user=agent_user,
        agent_session_id=agent_session_id,
        active_session_id=active_session_id,
        interactive_user=interactive_user,
        window_station=window_station,
        desktop_name=desktop_name,
        is_active_session=is_active,
        can_capture=can_capture,
        reason=reason,
    )


def screenshot_capture_enabled(agent_role: Optional[str]) -> bool:
    """Desktop capture is available to user-session agents, including combined mode."""
    return agent_role in USER_SESSION_AGENT_ROLES


@dataclass(frozen=True)
class ScreenshotResult:
    """Metadata for a locally captured, temporary screenshot."""

    path: Path
    filename: str
    device_name: str
    captured_at: str
    mime_type: str
    image_format: str


def sanitize_device_name(device_name: str) -> str:
    """Produce a non-empty, filesystem-safe component for a screenshot name."""

    sanitized = SAFE_FILENAME_CHARS.sub("_", str(device_name).strip())
    sanitized = sanitized.strip("._-")
    return sanitized[:80] or "unknown-device"


def build_screenshot_filename(
    device_name: str,
    captured_at: datetime,
    command_id: Optional[str] = None,
    extension: str = "png",
) -> str:
    """Create a UTC filename that is safe and collision resistant."""

    if captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=timezone.utc)
    timestamp = captured_at.astimezone(timezone.utc).strftime("%Y%m%d-%H%M%S")
    suffix_source = command_id or uuid.uuid4().hex
    suffix = SAFE_FILENAME_CHARS.sub("", str(suffix_source))[:12] or uuid.uuid4().hex[:12]
    safe_extension = SAFE_FILENAME_CHARS.sub("", extension.lower()) or "png"
    return f"{sanitize_device_name(device_name)}-{timestamp}-{suffix}.{safe_extension}"


class ScreenshotManager:
    """Capture the interactive user's virtual desktop into a bounded temp area.

    Pillow is imported only at capture time so non-interactive service code and
    unit tests can import this module without loading GUI capture support.
    """

    def __init__(
        self,
        temp_dir: Optional[Path | str] = None,
        *,
        include_all_screens: bool = True,
        max_temp_files: int = DEFAULT_MAX_TEMP_FILES,
        max_temp_age_seconds: int = DEFAULT_MAX_TEMP_AGE_SECONDS,
        image_grabber: Optional[Callable[..., object]] = None,
        hostname_provider: Callable[[], str] = socket.gethostname,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        topology_provider: Optional[Callable[[], SessionTopology]] = None,
    ) -> None:
        if max_temp_files < 1:
            raise ValueError("max_temp_files must be at least 1")
        if max_temp_age_seconds < 0:
            raise ValueError("max_temp_age_seconds cannot be negative")

        default_temp_dir = Path(tempfile.gettempdir()) / "network-scanner" / "screenshots"
        self.temp_dir = Path(temp_dir) if temp_dir is not None else default_temp_dir
        self.include_all_screens = include_all_screens
        self.max_temp_files = max_temp_files
        self.max_temp_age_seconds = max_temp_age_seconds
        self._image_grabber = image_grabber
        self._hostname_provider = hostname_provider
        self._clock = clock
        self._topology_provider = topology_provider or get_session_topology

    def cleanup_stale_files(self, now: Optional[datetime] = None) -> None:
        """Remove expired files and cap retained screenshots after failed uploads."""

        if not self.temp_dir.exists():
            return

        now_timestamp = (now or self._clock()).timestamp()
        files = sorted(
            (path for path in self.temp_dir.glob("*.png") if path.is_file()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for index, path in enumerate(files):
            is_expired = now_timestamp - path.stat().st_mtime > self.max_temp_age_seconds
            exceeds_limit = index >= self.max_temp_files
            if is_expired or exceeds_limit:
                try:
                    path.unlink()
                except OSError:
                    # Capture callers should receive capture errors, not cleanup noise.
                    pass

    def capture(
        self,
        *,
        command_id: Optional[str] = None,
        device_name: Optional[str] = None,
    ) -> ScreenshotResult:
        """Capture a PNG of the virtual desktop in a temporary local directory.

        Diagnoses session topology first (Plan §4.1, §4.3) to ensure desktop
        isolation issues are reported with actionable diagnostic context.
        """
        topology = self._topology_provider()
        LOG.info(
            "[SCREENSHOT] Session check: agent_user=%s agent_session=%s "
            "active_session=%s interactive_user=%s station=%s desktop=%s can_capture=%s",
            topology.agent_user,
            topology.agent_session_id,
            topology.active_session_id,
            topology.interactive_user,
            topology.window_station,
            topology.desktop_name,
            topology.can_capture,
        )

        if not topology.can_capture:
            raise RuntimeError(
                f"Screenshot capture blocked: {topology.reason} "
                f"[Session topology: agent_user={topology.agent_user}, agent_session={topology.agent_session_id}, "
                f"active_session={topology.active_session_id}, interactive_user={topology.interactive_user}]"
            )

        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.cleanup_stale_files()

        captured_at = self._clock()
        device_name = sanitize_device_name(device_name or self._hostname_provider())
        filename = build_screenshot_filename(device_name, captured_at, command_id)
        final_path = self.temp_dir / filename
        temporary_path = final_path.with_suffix(".partial")

        try:
            image = self._grab_image()
            image.save(temporary_path, format="PNG")
            os.replace(temporary_path, final_path)
        except Exception as error:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise RuntimeError(
                f"Screenshot capture failed: {error} "
                f"[Session topology: agent_user={topology.agent_user}, agent_session={topology.agent_session_id}, "
                f"active_session={topology.active_session_id}, interactive_user={topology.interactive_user}]"
            ) from error

        return ScreenshotResult(
            path=final_path,
            filename=filename,
            device_name=device_name,
            captured_at=captured_at.astimezone(timezone.utc).isoformat(),
            mime_type="image/png",
            image_format="PNG",
        )

    def _grab_image(self) -> object:
        if self._image_grabber is not None:
            return self._image_grabber(all_screens=self.include_all_screens)

        try:
            from PIL import ImageGrab
        except ImportError as error:
            raise RuntimeError(
                "Pillow is required for screenshot capture. Install the client dependencies."
            ) from error
        return ImageGrab.grab(all_screens=self.include_all_screens)
