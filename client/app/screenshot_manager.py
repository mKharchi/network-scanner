"""Request-driven screenshot capture for the interactive Windows client.

This module deliberately has no scheduler, socket, or HTTP code.  A caller must
invoke :meth:`ScreenshotManager.capture` in response to a validated server
command after the server can reliably address the interactive user-session
agent.
"""

from __future__ import annotations

import os
import re
import socket
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional


SAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
DEFAULT_MAX_TEMP_FILES = 10
DEFAULT_MAX_TEMP_AGE_SECONDS = 3_600
USER_SESSION_AGENT_ROLES = ("interactive", "combined")


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

        This function must be called from the interactive user-session agent;
        a Windows Session 0 service cannot be relied on to capture that desktop.
        """

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
            raise RuntimeError(f"Screenshot capture failed: {error}") from error

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
