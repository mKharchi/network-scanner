"""Phase 2 — Capture file discovery adapter for the standalone probe scanner.

Discovers active and rotated `.kismet` SQLite files using the same
``KISMET_CAPTURE_ROOT`` / ``KISMET_CAPTURE_DIRS`` conventions as the server.
Files are always opened read-only; the active-journal degraded-mode logic
mirrors ``_probe_capture_connection`` from ``kismet_service.py``.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

_SERVER_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "server")
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, os.path.abspath(_SERVER_DIR))

DEFAULT_CAPTURE_ROOT = Path("/home/adonis/kismet")
STALE_JOURNAL_THRESHOLD_SECONDS = 30.0


def _stale_journal_reason(db_path: Path) -> Optional[str]:
    """Return a reason string if a rollback journal is present, else None."""
    journal = Path(f"{db_path}-journal")
    if not journal.exists():
        return None
    try:
        db_mtime = db_path.stat().st_mtime
        journal_mtime = journal.stat().st_mtime
    except OSError:
        return "capture or rollback journal cannot be stat'ed"
    journal_age = time.time() - max(db_mtime, journal_mtime)
    if journal_age > STALE_JOURNAL_THRESHOLD_SECONDS:
        return "stale SQLite rollback journal; restart Kismet to recover it"
    return "active SQLite rollback journal; showing last committed snapshot"


def open_capture_readonly(db_path: Path) -> Tuple[sqlite3.Connection, Optional[str]]:
    """Open a .kismet capture read-only, handling active/stale journals.

    Returns
    -------
    (connection, degraded_reason)
        ``degraded_reason`` is None for a clean read; otherwise a human-readable
        string explaining why the snapshot may lag the live capture.
    """
    journal_reason = _stale_journal_reason(db_path)
    if journal_reason:
        con = sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True, timeout=2.0)
        return con, f"degraded: {journal_reason}"
    con = sqlite3.connect(f"file:{db_path}?mode=ro&nolock=1", uri=True, timeout=2.0)
    return con, None


def discover_capture_files(
    capture_dirs: Optional[List[Path]] = None,
) -> List[Path]:
    """Return .kismet files sorted newest-first by mtime.

    Uses ``KISMET_CAPTURE_DIRS`` (comma-separated) then ``KISMET_CAPTURE_ROOT``
    then the built-in default, mirroring the server service behaviour.
    """
    if capture_dirs is not None:
        dirs = capture_dirs
    else:
        env_dirs = os.getenv("KISMET_CAPTURE_DIRS")
        if env_dirs:
            dirs = [Path(p.strip()) for p in env_dirs.split(",") if p.strip()]
        else:
            root = os.getenv("KISMET_CAPTURE_ROOT")
            dirs = [Path(root) if root else DEFAULT_CAPTURE_ROOT]

    found: List[Path] = []
    for cdir in dirs:
        try:
            if cdir.is_dir():
                for kfile in cdir.glob("*.kismet"):
                    if kfile.is_file() and kfile not in found:
                        found.append(kfile)
        except OSError:
            pass

    found.sort(
        key=lambda path: path.stat().st_mtime if path.exists() else 0,
        reverse=True,
    )
    return found
