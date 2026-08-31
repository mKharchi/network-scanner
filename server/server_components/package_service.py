"""Disk-backed deployment package storage with MySQL metadata references."""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, IO, Optional

from database import get_connection

DEFAULT_STORAGE_DIR = Path(__file__).resolve().parents[1] / "storage" / "packages"
PACKAGE_STORAGE_DIR = Path(os.getenv("PACKAGE_STORAGE_DIR", str(DEFAULT_STORAGE_DIR)))
MAX_PACKAGE_SIZE_BYTES = max(1, int(os.getenv("MAX_PACKAGE_SIZE_MB", "200"))) * 1024 * 1024

_PACKAGE_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,99}$")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _safe_filename(value: str) -> str:
    name = Path(str(value or "package.zip")).name
    cleaned = "".join(character for character in name if character.isalnum() or character in "._- ")
    return (cleaned or "package.zip").strip()[:255]


def normalize_package_id(value: Optional[str]) -> str:
    candidate = str(value or "").strip()
    if candidate and _PACKAGE_ID_RE.match(candidate):
        return candidate
    return f"pkg-{uuid.uuid4().hex[:12]}"


def calculate_sha256_file(path: Path, chunk_size: int = 131072) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest().lower()


def stream_to_storage(
    source: IO[bytes],
    *,
    filename: str,
    package_id: Optional[str] = None,
    uploaded_by: Optional[str] = None,
    max_bytes: int = MAX_PACKAGE_SIZE_BYTES,
) -> Dict[str, Any]:
    """Stream an upload to disk, compute SHA-256, and persist metadata."""
    resolved_id = normalize_package_id(package_id)
    safe_name = _safe_filename(filename)
    if not safe_name.lower().endswith(".zip"):
        raise ValueError("Package must be a .zip archive.")

    PACKAGE_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    storage_path = PACKAGE_STORAGE_DIR / f"{resolved_id}.zip"
    if storage_path.exists():
        raise ValueError(f"Package '{resolved_id}' already exists.")

    digest = hashlib.sha256()
    size_bytes = 0
    try:
        with storage_path.open("wb") as dest:
            while True:
                chunk = source.read(131072)
                if not chunk:
                    break
                size_bytes += len(chunk)
                if size_bytes > max_bytes:
                    raise ValueError(
                        f"Package exceeds the {max_bytes // (1024 * 1024)} MB size limit."
                    )
                digest.update(chunk)
                dest.write(chunk)
    except Exception:
        storage_path.unlink(missing_ok=True)
        raise

    if size_bytes <= 0:
        storage_path.unlink(missing_ok=True)
        raise ValueError("Package file is empty.")

    sha256 = digest.hexdigest().lower()
    record = {
        "package_id": resolved_id,
        "filename": safe_name,
        "size_bytes": size_bytes,
        "sha256": sha256,
        "storage_path": str(storage_path),
        "uploaded_by": uploaded_by,
        "created_at": _now(),
    }
    _insert_package_record(record)
    created_at = record.get("created_at")
    if created_at is not None and hasattr(created_at, "isoformat"):
        record["created_at"] = created_at.isoformat()
    return record


def _insert_package_record(record: Dict[str, Any]) -> None:
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """INSERT INTO packages
               (package_id, filename, size_bytes, sha256, storage_path, uploaded_by, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (
                record["package_id"],
                record["filename"],
                record["size_bytes"],
                record["sha256"],
                record["storage_path"],
                record.get("uploaded_by"),
                record.get("created_at") or _now(),
            ),
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def get_package(package_id: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """SELECT package_id, filename, size_bytes, sha256, storage_path,
                      uploaded_by, created_at
               FROM packages WHERE package_id = %s""",
            (str(package_id).strip(),),
        )
        row = cursor.fetchone()
        if not row:
            return None
        created_at = row.get("created_at")
        if created_at is not None and hasattr(created_at, "isoformat"):
            row["created_at"] = created_at.isoformat()
        return row
    finally:
        cursor.close()
        conn.close()


def package_exists(package_id: str) -> bool:
    return get_package(package_id) is not None


def get_package_path(package_id: str) -> Optional[Path]:
    record = get_package(package_id)
    if not record:
        return None
    path = Path(record["storage_path"])
    return path if path.is_file() else None


def delete_package(package_id: str) -> bool:
    record = get_package(package_id)
    if not record:
        return False
    Path(record["storage_path"]).unlink(missing_ok=True)
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM packages WHERE package_id = %s", (package_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        cursor.close()
        conn.close()
