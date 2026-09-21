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
    replace: bool = True,
) -> Dict[str, Any]:
    """Stream an upload to disk, compute SHA-256, and persist metadata.

    By default ``replace=True`` so retrying the same package id (same version
    zip after a failed client update) overwrites the on-disk archive and
    upserts the MySQL row. Set ``replace=False`` to keep the old reject-if-exists
    behaviour.
    """
    resolved_id = normalize_package_id(package_id)
    safe_name = _safe_filename(filename)
    if not safe_name.lower().endswith(".zip"):
        raise ValueError("Package must be a .zip archive.")

    PACKAGE_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    storage_path = PACKAGE_STORAGE_DIR / f"{resolved_id}.zip"
    existing = get_package(resolved_id)
    had_file = storage_path.exists()
    if (had_file or existing) and not replace:
        raise ValueError(f"Package '{resolved_id}' already exists.")

    # Write to a temp sibling first so a failed upload never leaves a half-written
    # zip under the final package id.
    temp_path = PACKAGE_STORAGE_DIR / f".{resolved_id}.{uuid.uuid4().hex}.part"
    digest = hashlib.sha256()
    size_bytes = 0
    try:
        with temp_path.open("wb") as dest:
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

        if size_bytes <= 0:
            raise ValueError("Package file is empty.")

        temp_path.replace(storage_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

    sha256 = digest.hexdigest().lower()
    record = {
        "package_id": resolved_id,
        "filename": safe_name,
        "size_bytes": size_bytes,
        "sha256": sha256,
        "storage_path": str(storage_path),
        "uploaded_by": uploaded_by,
        "created_at": _now(),
        "replaced": existing is not None or had_file,
    }
    _upsert_package_record(record)
    created_at = record.get("created_at")
    if created_at is not None and hasattr(created_at, "isoformat"):
        record["created_at"] = created_at.isoformat()
    return record


def _upsert_package_record(record: Dict[str, Any]) -> None:
    """Insert a package row, or refresh it when package_id already exists."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """INSERT INTO packages
               (package_id, filename, size_bytes, sha256, storage_path, uploaded_by, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE
                   filename = VALUES(filename),
                   size_bytes = VALUES(size_bytes),
                   sha256 = VALUES(sha256),
                   storage_path = VALUES(storage_path),
                   uploaded_by = VALUES(uploaded_by),
                   created_at = VALUES(created_at)""",
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


# Backwards-compatible alias used by older call sites / tests.
def _insert_package_record(record: Dict[str, Any]) -> None:
    _upsert_package_record(record)

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


def list_packages(limit: int = 100) -> list[Dict[str, Any]]:
    """List all available packages in the repository."""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """SELECT package_id, filename, size_bytes, sha256, storage_path,
                      uploaded_by, created_at
               FROM packages
               ORDER BY created_at DESC
               LIMIT %s""",
            (max(1, min(limit, 500)),),
        )
        rows = cursor.fetchall() or []
        for row in rows:
            created_at = row.get("created_at")
            if created_at is not None and hasattr(created_at, "isoformat"):
                row["created_at"] = created_at.isoformat()
        return rows
    finally:
        cursor.close()
        conn.close()


def build_client_update_package(
    version: str,
    *,
    release_notes: Optional[str] = None,
    base_app_dir: Optional[Path | str] = None,
    uploaded_by: Optional[str] = None,
) -> Dict[str, Any]:
    """Build an update package (.zip with manifest.json and app/) from client/app."""
    import json
    import shutil
    import tempfile
    import zipfile

    ver = str(version or "").strip()
    if not ver or not re.match(r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?$", ver):
        raise ValueError(f"Invalid semantic version '{version}'. Expected format like '2.0.0'.")

    if base_app_dir is None:
        source_dir = Path(__file__).resolve().parents[2] / "client" / "app"
    else:
        source_dir = Path(base_app_dir).resolve()

    if not source_dir.is_dir():
        raise FileNotFoundError(f"Source client app directory does not exist: {source_dir}")

    resolved_id = f"client-update-{ver}"
    filename = f"client-update-{ver}.zip"

    PACKAGE_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    storage_path = PACKAGE_STORAGE_DIR / filename

    with tempfile.TemporaryDirectory(prefix="pkg_build_") as tmp_str:
        tmp_dir = Path(tmp_str)
        app_target = tmp_dir / "app"

        # Ignore python cache files, git files, and temporary outputs
        def _ignore_patterns(_path: str, names: list[str]) -> set[str]:
            ignored = set()
            for name in names:
                if name == "__pycache__" or name.startswith(".git") or name.endswith((".pyc", ".pyo", ".tmp", ".part")):
                    ignored.add(name)
            return ignored

        shutil.copytree(source_dir, app_target, ignore=_ignore_patterns)

        # Bundle the standalone updater so clients can self-heal stop/start bugs.
        # It lives outside app/ on disk (client/updater) and is applied by apply_update
        # when present in the zip.
        updater_source = source_dir.parent / "updater"
        if updater_source.is_dir():
            updater_target = tmp_dir / "updater"
            shutil.copytree(updater_source, updater_target, ignore=_ignore_patterns)

        # Write version.json inside app/
        version_data = {
            "version": ver,
            "release_date": _now().isoformat() + "Z",
            "updater_version": "1.0.0",
        }
        with (app_target / "version.json").open("w", encoding="utf-8") as vf:
            json.dump(version_data, vf, indent=2)

        # Calculate file hashes for all files in app/
        file_hashes: Dict[str, str] = {}
        for item in sorted(app_target.rglob("*")):
            if item.is_file():
                rel_path = item.relative_to(app_target).as_posix()
                file_hashes[rel_path] = calculate_sha256_file(item)

        # Write manifest.json
        manifest = {
            "version": ver,
            "package_type": "client-update",
            "minimum_updater_version": "1.0.0",
            "file_hashes": file_hashes,
            "release_notes": release_notes or f"Client update package v{ver}",
            "build_timestamp": _now().isoformat() + "Z",
            "includes_updater": bool(updater_source.is_dir()),
        }
        with (tmp_dir / "manifest.json").open("w", encoding="utf-8") as mf:
            json.dump(manifest, mf, indent=2)

        # Build zip archive into a temp file, then atomically replace the stored package
        # so rebuilding the same version after a failed deploy is safe to retry.
        tmp_zip = tmp_dir / "temp_package.zip"
        with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for root_path, _, file_names in os.walk(tmp_dir):
                for fname in file_names:
                    full_file = Path(root_path) / fname
                    if full_file == tmp_zip:
                        continue
                    arcname = full_file.relative_to(tmp_dir).as_posix()
                    zf.write(full_file, arcname)

        staging_path = PACKAGE_STORAGE_DIR / f".{resolved_id}.{uuid.uuid4().hex}.part"
        try:
            shutil.copy2(tmp_zip, staging_path)
            staging_path.replace(storage_path)
        except Exception:
            staging_path.unlink(missing_ok=True)
            raise

    # Compute digest and size
    size_bytes = storage_path.stat().st_size
    sha256 = calculate_sha256_file(storage_path)

    record = {
        "package_id": resolved_id,
        "filename": filename,
        "size_bytes": size_bytes,
        "sha256": sha256,
        "storage_path": str(storage_path),
        "uploaded_by": uploaded_by or "system-builder",
        "created_at": _now(),
    }
    _upsert_package_record(record)

    created_at = record.get("created_at")
    if created_at is not None and hasattr(created_at, "isoformat"):
        record["created_at"] = created_at.isoformat()
    return record


def delete_package(package_id: str) -> bool:
    """Remove package metadata and delete the zip from disk.

    Also cleans up the canonical ``{package_id}.zip`` path so a manual file
    delete + orphaned DB row cannot leave the store inconsistent.
    """
    resolved_id = str(package_id).strip()
    record = get_package(resolved_id)
    paths_to_remove = set()
    if record and record.get("storage_path"):
        paths_to_remove.add(Path(record["storage_path"]))
    paths_to_remove.add(PACKAGE_STORAGE_DIR / f"{resolved_id}.zip")

    for path in paths_to_remove:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM packages WHERE package_id = %s", (resolved_id,))
        conn.commit()
        return cursor.rowcount > 0 or record is not None
    finally:
        cursor.close()
        conn.close()
