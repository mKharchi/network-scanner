"""Standalone client application updater with backup and rollback."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from typing import Any, Callable, Dict, Iterable, Optional

UPDATER_VERSION = "1.0.0"
FAILURE_REASONS = {
    "TRANSFER_FAILED",
    "INVALID_PACKAGE",
    "VERSION_INVALID",
    "DEPENDENCY_INSTALL_FAILED",
    "APPLICATION_START_FAILED",
    "ROLLBACK",
}


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def safe_extract(zip_path: Path | str, destination: Path | str, max_uncompressed_bytes: int = 500 * 1024 * 1024) -> None:
    destination = Path(destination).resolve()
    total_size = 0
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            total_size += info.file_size
            target = (destination / info.filename).resolve()
            if not _inside(target, destination):
                raise ValueError(f"unsafe path in archive: {info.filename}")
        if total_size > max_uncompressed_bytes:
            raise ValueError("archive exceeds uncompressed size limit")
        destination.mkdir(parents=True, exist_ok=True)
        archive.extractall(destination)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path.name}")
    return value


def _version_tuple(value: Any) -> tuple[int, ...]:
    parts = []
    for part in str(value).strip().split("."):
        digits = "".join(character for character in part if character.isdigit())
        parts.append(int(digits or "0"))
    return tuple(parts or [0])


def _validate_manifest(manifest: Dict[str, Any]) -> None:
    required = {"version", "package_type", "minimum_updater_version", "file_hashes"}
    if not required.issubset(manifest):
        raise ValueError("manifest is missing required fields")
    if manifest["package_type"] != "client-update":
        raise ValueError("unsupported package type")
    if not isinstance(manifest["version"], str) or not manifest["version"].strip():
        raise ValueError("invalid application version")
    if not isinstance(manifest["file_hashes"], dict):
        raise ValueError("manifest.file_hashes must be an object")
    if _version_tuple(manifest["minimum_updater_version"]) > _version_tuple(UPDATER_VERSION):
        raise ValueError("package requires a newer updater")


def _verify_hashes(app_root: Path, file_hashes: Dict[str, Any]) -> None:
    for relative_name, expected in file_hashes.items():
        relative = Path(str(relative_name))
        target = (app_root / relative).resolve()
        if not _inside(target, app_root) or not target.is_file():
            raise ValueError(f"manifest file is missing: {relative_name}")
        actual = sha256_file(target)
        if actual.lower() != str(expected).lower():
            raise ValueError(f"hash mismatch for {relative_name}")


def _copy_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def _requirements(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    values = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and not line.startswith("-"):
            values.add(line)
    return values


def _install_dependencies(app_root: Path, venv_python: Optional[Path], runner: Callable[..., Any]) -> None:
    if not venv_python or not venv_python.exists():
        return
    requirements = app_root / "requirements.txt"
    if not requirements.is_file():
        return
    runner([str(venv_python), "-m", "pip", "install", "-r", str(requirements)], check=True)


def _start_application(app_root: Path, venv_python: Optional[Path], runner: Callable[..., Any], timeout: float) -> Any:
    executable = venv_python or Path(sys.executable)
    process = runner([str(executable), str(app_root / "client.py")], cwd=str(app_root), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if hasattr(process, "poll"):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                if process.returncode != 0:
                    raise RuntimeError("client exited during startup")
                break
            time.sleep(0.1)
    return process


def apply_update(
    package_path: Path | str,
    *,
    client_root: Path | str,
    stop_client: Callable[[], None],
    start_client: Optional[Callable[[], Any]] = None,
    runner: Callable[..., Any] = subprocess.run,
    startup_timeout: float = 10.0,
) -> Dict[str, Any]:
    root = Path(client_root).resolve()
    app_root = root / "app"
    config_root = root / "config"
    history_root = root / "storage" / "updates" / "history"
    package_path = Path(package_path).resolve()
    backup_root: Optional[Path] = None
    staging_parent = root / "storage" / "updates" / "staging"
    staging_parent.mkdir(parents=True, exist_ok=True)
    staged_root = Path(tempfile.mkdtemp(prefix="client-update-", dir=str(staging_parent)))
    try:
        if not package_path.is_file() or package_path.suffix.lower() != ".zip":
            raise ValueError("update package must be a zip file")
        safe_extract(package_path, staged_root)
        manifest = _read_json(staged_root / "manifest.json")
        _validate_manifest(manifest)
        staged_app = staged_root / "app"
        if not staged_app.is_dir():
            raise ValueError("package app directory is missing")
        _verify_hashes(staged_app, manifest["file_hashes"])

        old_version = "unknown"
        version_file = app_root / "version.json"
        if version_file.is_file():
            old_version = str(_read_json(version_file).get("version") or "unknown")
        backup_root = history_root / old_version
        history_root.mkdir(parents=True, exist_ok=True)

        stop_client()
        _copy_tree(app_root, backup_root)
        _copy_tree(staged_app, app_root)
        venv_python = root / "venv" / "Scripts" / "python.exe"
        _install_dependencies(app_root, venv_python if venv_python.exists() else None, runner)
        if start_client:
            start_client()
        else:
            _start_application(app_root, venv_python if venv_python.exists() else None, runner, startup_timeout)
        return {"status": "COMPLETED", "version": manifest["version"], "old_version": old_version}
    except ValueError as error:
        reason = "VERSION_INVALID" if "version" in str(error).lower() or "updater" in str(error).lower() else "INVALID_PACKAGE"
        return _rollback_result(reason, str(error), app_root, backup_root, start_client)
    except subprocess.CalledProcessError as error:
        return _rollback_result("DEPENDENCY_INSTALL_FAILED", str(error), app_root, backup_root, start_client)
    except Exception as error:
        return _rollback_result("APPLICATION_START_FAILED", str(error), app_root, backup_root, start_client)
    finally:
        shutil.rmtree(staged_root, ignore_errors=True)


def _rollback_result(reason: str, error: str, app_root: Path, backup_root: Optional[Path], start_client: Optional[Callable[[], Any]]) -> Dict[str, Any]:
    if backup_root and backup_root.is_dir():
        try:
            _copy_tree(backup_root, app_root)
            if start_client:
                start_client()
            return {"status": "UPDATE_FAILED", "reason": reason, "error": error, "rolled_back": True}
        except Exception as rollback_error:
            return {"status": "UPDATE_FAILED", "reason": "ROLLBACK", "error": f"{error}; rollback failed: {rollback_error}", "rolled_back": False}
    return {"status": "UPDATE_FAILED", "reason": reason, "error": error, "rolled_back": False}


if __name__ == "__main__":
     """Run the updater as a standalone subprocess.
     
     Usage: python updater.py <staged_package_path> <client_root>
     
     This entry point is used when spawning the updater from the client
     to apply a staged package after it has been transferred and verified.
     """
     import logging
     
     # Configure minimal logging for standalone operation
     logging.basicConfig(
         level=logging.INFO,
         format="%(asctime)s [UPDATER] %(levelname)s: %(message)s",
         handlers=[
             logging.FileHandler(
                 Path(__file__).parent.parent / "logs" / "updater.log",
                 encoding="utf-8"
             )
         ],
     )
     log = logging.getLogger("updater")
     
     if len(sys.argv) < 3:
         log.error("Usage: python updater.py <staged_package_path> <client_root>")
         raise SystemExit(1)
     
     staged_pkg = Path(sys.argv[1])
     client_root = Path(sys.argv[2])
     
     if not staged_pkg.is_file():
         log.error(f"Staged package not found: {staged_pkg}")
         raise SystemExit(1)
     
     if not (client_root / "app").is_dir():
         log.error(f"Client app directory not found: {client_root / 'app'}")
         raise SystemExit(1)
     
     log.info(f"Starting update from staged package: {staged_pkg}")
     
      def _stop_client():
          """Stop the running client (platform-specific)."""
          import platform
          if platform.system() == "Windows":
              # Kill the Python process running client.py (not a compiled executable)
              os.system("taskkill /F /IM python.exe /FI \"COMMANDLINE eq *client.py*\"")
          else:
              os.system("pkill -f 'python.*client.py'")
          # Allow time for process to fully release file locks
          time.sleep(1.0)
      
      result = apply_update(
         staged_pkg,
         client_root=client_root,
         stop_client=_stop_client,
     )
     
     log.info(f"Update result: {result}")
     
     # Exit with status 0 for success, 1 for failure
     sys.exit(0 if result.get("status") == "COMPLETED" else 1)
