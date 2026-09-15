"""Machine-global Kismet capture/config path resolution.

Prefer FHS-style locations that do not depend on a login username:

- captures: ``/var/lib/kismet/captures``
- conf:     ``/etc/kismet``

``~`` must never be used in systemd ``EnvironmentFile`` values — systemd and
the ``kismet`` service user do not expand it to the admin's home directory.
``Path.expanduser()`` is still applied for optional operator overrides so a
manual ``~/...`` path works when the ML tools run as that operator.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional, Sequence

# System defaults — identical on every Linux host once the sensor is installed.
DEFAULT_KISMET_CAPTURE_ROOT = Path("/var/lib/kismet/captures")
DEFAULT_KISMET_CONF_DIR = Path("/etc/kismet")
DEFAULT_KISMET_HOMEDIR = Path("/var/lib/kismet")


def resolve_configured_path(raw: str | Path | None, *, default: Path) -> Path:
    """Expand ``~`` when present, otherwise return an absolute path."""
    if raw is None or str(raw).strip() == "":
        return default
    return Path(str(raw).strip()).expanduser()


def get_capture_dirs(
    capture_dirs: Optional[Sequence[Path | str]] = None,
) -> List[Path]:
    """Resolve capture directories from explicit args or environment.

    Priority:
    1. Explicit ``capture_dirs`` argument
    2. ``KISMET_CAPTURE_DIRS`` (comma-separated)
    3. ``KISMET_CAPTURE_ROOT`` / ``KISMET_CAPTURE_DIR``
    4. ``DEFAULT_KISMET_CAPTURE_ROOT`` (``/var/lib/kismet/captures``)
    """
    if capture_dirs is not None:
        return [resolve_configured_path(path, default=DEFAULT_KISMET_CAPTURE_ROOT) for path in capture_dirs]

    configured_dirs = os.getenv("KISMET_CAPTURE_DIRS")
    if configured_dirs:
        return [
            resolve_configured_path(part, default=DEFAULT_KISMET_CAPTURE_ROOT)
            for part in configured_dirs.split(",")
            if part.strip()
        ]

    configured_root = os.getenv("KISMET_CAPTURE_ROOT") or os.getenv("KISMET_CAPTURE_DIR")
    return [resolve_configured_path(configured_root, default=DEFAULT_KISMET_CAPTURE_ROOT)]


def get_capture_root() -> Path:
    """Return the primary capture directory (first resolved entry)."""
    return get_capture_dirs()[0]


def get_conf_dir() -> Path:
    """Return the Kismet conf directory."""
    return resolve_configured_path(os.getenv("KISMET_CONF_DIR"), default=DEFAULT_KISMET_CONF_DIR)


__all__ = [
    "DEFAULT_KISMET_CAPTURE_ROOT",
    "DEFAULT_KISMET_CONF_DIR",
    "DEFAULT_KISMET_HOMEDIR",
    "get_capture_dirs",
    "get_capture_root",
    "get_conf_dir",
    "resolve_configured_path",
]
