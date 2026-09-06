"""Standalone client application updater with backup and rollback."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging
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

# Update state machine states (Plan §3.3)
STATE_IDLE = "IDLE"
STATE_PACKAGE_VALIDATING = "PACKAGE_VALIDATING"
STATE_PACKAGE_VALIDATED = "PACKAGE_VALIDATED"
STATE_CLIENT_STOPPING = "CLIENT_STOPPING"
STATE_CLIENT_STOPPED = "CLIENT_STOPPED"
STATE_BACKUP_CREATED = "BACKUP_CREATED"
STATE_FILES_REPLACED = "FILES_REPLACED"
STATE_DEPENDENCIES_INSTALLING = "DEPENDENCIES_INSTALLING"
STATE_CLIENT_STARTING = "CLIENT_STARTING"
STATE_VERSION_VERIFYING = "VERSION_VERIFYING"
STATE_UPDATE_CONFIRMED = "UPDATE_CONFIRMED"

# Failure states
STATE_VALIDATION_FAILED = "VALIDATION_FAILED"
STATE_STOP_FAILED = "STOP_FAILED"
STATE_FILE_REPLACEMENT_FAILED = "FILE_REPLACEMENT_FAILED"
STATE_DEPENDENCY_FAILED = "DEPENDENCY_FAILED"
STATE_START_FAILED = "START_FAILED"
STATE_VERSION_MISMATCH = "VERSION_MISMATCH"
STATE_ROLLBACK_COMPLETED = "ROLLBACK_COMPLETED"
STATE_ROLLBACK_FAILED = "ROLLBACK_FAILED"


def record_update_state(client_root: Path, state: str, details: Optional[Dict[str, Any]] = None) -> None:
    """Persist the current update lifecycle state machine position to disk (Plan §3.3)."""
    try:
        state_dir = client_root / "storage" / "updates"
        state_dir.mkdir(parents=True, exist_ok=True)
        state_file = state_dir / "current_state.json"
        payload = {
            "state": state,
            "timestamp": time.time(),
            "iso_time": datetime.now(timezone.utc).isoformat(),
            **(details or {}),
        }
        temp_file = state_file.with_suffix(".tmp")
        with temp_file.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        os.replace(temp_file, state_file)
    except Exception as err:
        logging.getLogger("updater").debug("Could not record update state %s: %s", state, err)



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


class DependencyInstallError(RuntimeError):
    """Raised when an update cannot prepare its declared dependencies."""


def _resolve_python(client_root: Path) -> Optional[Path]:
    """Resolve the interpreter used for dependency installation and startup."""
    candidates = [
        # Linux / macOS virtualenv paths
        client_root / ".venv" / "bin" / "python",
        client_root / ".venv" / "bin" / "python3",
        client_root / "venv" / "bin" / "python",
        client_root / "venv" / "bin" / "python3",
        # Windows virtualenv paths
        client_root / ".venv" / "Scripts" / "python.exe",
        client_root / "venv" / "Scripts" / "python.exe",
        client_root / ".venv" / "python.exe",
        client_root / "venv" / "python.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate

    current_python = Path(sys.executable)
    if current_python.is_file():
        return current_python
    return None


def _install_dependencies(app_root: Path, python_executable: Optional[Path], runner: Callable[..., Any]) -> None:
    requirements = app_root / "requirements.txt"
    if not requirements.is_file():
        return
    if python_executable is None or not python_executable.is_file():
        raise DependencyInstallError(
            f"requirements.txt exists but no Python interpreter is available: {python_executable}"
        )
    runner(
        [
            str(python_executable),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-r",
            str(requirements),
        ],
        check=True,
    )


def _start_application(
    app_root: Path,
    python_executable: Optional[Path],
    launcher: Callable[..., Any],
    timeout: float,
) -> Any:
    if python_executable is None or not python_executable.is_file():
        raise RuntimeError(f"No Python interpreter is available to start the client: {python_executable}")

    log = logging.getLogger("updater")
    log.info(
        "[UPDATER] Starting client: executable=%s app_root=%s timeout=%.1f",
        python_executable, app_root, timeout,
    )

    process = launcher(
        [str(python_executable), str(app_root / "client.py")],
        cwd=str(app_root),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    if hasattr(process, "poll"):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                if process.returncode != 0:
                    # Genuine crash — the client failed to start.
                    raise RuntimeError(
                        f"client process exited with code {process.returncode} "
                        f"during startup (pid={process.pid})"
                    )
                # Exit code 0 within timeout — the client spawned a child or
                # completed startup normally.  This is NOT a failure.
                log.info(
                    "[UPDATER] Client process exited cleanly (code 0, pid=%d) "
                    "within startup window — treating as successful launch.",
                    process.pid,
                )
                break
            time.sleep(0.1)
        else:
            # Process still running after timeout — also fine: the client is
            # still initialising.
            log.info(
                "[UPDATER] Client process still running after %.1fs "
                "(pid=%d) — treating as successful launch.",
                timeout, process.pid,
            )
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
        record_update_state(root, STATE_PACKAGE_VALIDATING, {"package": str(package_path)})
        safe_extract(package_path, staged_root)
        manifest = _read_json(staged_root / "manifest.json")
        _validate_manifest(manifest)
        staged_app = staged_root / "app"
        if not staged_app.is_dir():
            raise ValueError("package app directory is missing")
        _verify_hashes(staged_app, manifest["file_hashes"])
        record_update_state(root, STATE_PACKAGE_VALIDATED, {"version": manifest["version"]})

        old_version = "unknown"
        version_file = app_root / "version.json"
        if version_file.is_file():
            old_version = str(_read_json(version_file).get("version") or "unknown")
        backup_root = history_root / old_version
        history_root.mkdir(parents=True, exist_ok=True)

        record_update_state(root, STATE_CLIENT_STOPPING)
        stop_client()
        record_update_state(root, STATE_CLIENT_STOPPED)

        _copy_tree(app_root, backup_root)
        record_update_state(root, STATE_BACKUP_CREATED, {"backup_version": old_version})

        _copy_tree(staged_app, app_root)
        record_update_state(root, STATE_FILES_REPLACED)

        python_executable = _resolve_python(root)
        record_update_state(root, STATE_DEPENDENCIES_INSTALLING)
        _install_dependencies(app_root, python_executable, runner)

        record_update_state(root, STATE_CLIENT_STARTING)
        if start_client:
            start_client()
        else:
            _start_application(app_root, python_executable, subprocess.Popen, startup_timeout)

        # Version verification on disk (Plan §3.4)
        record_update_state(root, STATE_VERSION_VERIFYING)
        new_version_file = app_root / "version.json"
        if new_version_file.is_file():
            installed_version = str(_read_json(new_version_file).get("version") or "unknown")
            if installed_version != "unknown" and installed_version != manifest["version"]:
                raise ValueError(
                    f"Installed version {installed_version} does not match manifest version {manifest['version']}"
                )

        record_update_state(root, STATE_UPDATE_CONFIRMED, {"version": manifest["version"], "old_version": old_version})
        return {"status": "COMPLETED", "version": manifest["version"], "old_version": old_version}
    except ValueError as error:
        reason = "VERSION_INVALID" if "version" in str(error).lower() or "updater" in str(error).lower() else "INVALID_PACKAGE"
        record_update_state(root, STATE_VALIDATION_FAILED, {"reason": reason, "error": str(error)})
        return _rollback_result(reason, str(error), app_root, backup_root, start_client, root)
    except (DependencyInstallError, subprocess.CalledProcessError) as error:
        record_update_state(root, STATE_DEPENDENCY_FAILED, {"error": str(error)})
        return _rollback_result("DEPENDENCY_INSTALL_FAILED", str(error), app_root, backup_root, start_client, root)
    except Exception as error:
        record_update_state(root, STATE_START_FAILED, {"error": str(error)})
        return _rollback_result("APPLICATION_START_FAILED", str(error), app_root, backup_root, start_client, root)
    finally:
        shutil.rmtree(staged_root, ignore_errors=True)


def _rollback_result(
    reason: str,
    error: str,
    app_root: Path,
    backup_root: Optional[Path],
    start_client: Optional[Callable[[], Any]],
    client_root: Optional[Path] = None,
) -> Dict[str, Any]:
    if backup_root and backup_root.is_dir():
        try:
            _copy_tree(backup_root, app_root)
            if start_client:
                start_client()
            if client_root:
                record_update_state(client_root, STATE_ROLLBACK_COMPLETED, {"reason": reason, "error": error})
            return {"status": "UPDATE_FAILED", "reason": reason, "error": error, "rolled_back": True}
        except Exception as rollback_error:
            if client_root:
                record_update_state(client_root, STATE_ROLLBACK_FAILED, {"rollback_error": str(rollback_error)})
            return {"status": "UPDATE_FAILED", "reason": "ROLLBACK", "error": f"{error}; rollback failed: {rollback_error}", "rolled_back": False}
    if client_root:
        record_update_state(client_root, STATE_ROLLBACK_FAILED, {"error": error})
    return {"status": "UPDATE_FAILED", "reason": reason, "error": error, "rolled_back": False}


def _persist_update_result(client_root: Path, action_id: Optional[str], result: Dict[str, Any]) -> None:
    """Persist the final result so the restarted client can report it."""
    if not action_id:
        return
    result_dir = client_root / "storage" / "updates" / "results"
    result_dir.mkdir(parents=True, exist_ok=True)
    result_path = result_dir / f"{action_id}.json"
    temporary_path = result_path.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(result), encoding="utf-8")
    os.replace(temporary_path, result_path)


if __name__ == "__main__":
    """Run the updater as a standalone subprocess.

    Usage: python updater.py <staged_package_path> <client_root>

    This entry point is used when spawning the updater from the client
    to apply a staged package after it has been transferred and verified.
    """
    import logging

    log_dir = Path(__file__).parent.parent / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    # Configure minimal logging for standalone operation
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [UPDATER] %(levelname)s: %(message)s",
        handlers=[
            logging.FileHandler(
                log_dir / "updater.log",
                encoding="utf-8",
            )
        ],
    )
    log = logging.getLogger("updater")

    if len(sys.argv) < 3:
        log.error("Usage: python updater.py <staged_package_path> <client_root>")
        raise SystemExit(1)

    staged_pkg = Path(sys.argv[1])
    client_root = Path(sys.argv[2])
    action_id = sys.argv[3] if len(sys.argv) >= 4 else None

    if not staged_pkg.is_file():
        log.error(f"Staged package not found: {staged_pkg}")
        raise SystemExit(1)

    if not (client_root / "app").is_dir():
        log.error(f"Client app directory not found: {client_root / 'app'}")
        raise SystemExit(1)

    log.info(f"Starting update from staged package: {staged_pkg}")

    def _stop_client() -> None:
        """Stop the running client (platform-specific)."""
        import platform

        if platform.system() == "Windows":
            # Kill the Python process running client.py (not a compiled executable)
            os.system("taskkill /F /IM python.exe /FI \"COMMANDLINE eq *client.py*\"")
        else:
            my_pid = os.getpid()
            try:
                import psutil
                for proc in psutil.process_iter(["pid", "cmdline"]):
                    if proc.info["pid"] == my_pid:
                        continue
                    cmdline = " ".join(proc.info.get("cmdline") or [])
                    if "client.py" in cmdline:
                        try:
                            proc.terminate()
                            proc.wait(timeout=2.0)
                        except Exception:
                            try:
                                proc.kill()
                            except Exception:
                                pass
            except Exception:
                os.system("pkill -f 'client\\.py'")
        # Allow time for the process to fully release file locks
        time.sleep(1.0)

    def _start_client() -> Any:
        """Restart the client after a successful update or rollback."""
        python_executable = _resolve_python(client_root)
        return _start_application(
            client_root / "app",
            python_executable,
            subprocess.Popen,
            timeout=10.0,
        )

    result = apply_update(
        staged_pkg,
        client_root=client_root,
        stop_client=_stop_client,
        start_client=_start_client,
    )

    log.info(f"Update result: {result}")
    try:
        _persist_update_result(client_root, action_id, result)
    except Exception as error:
        log.error(f"Could not persist update result: {error}")

    # Exit with status 0 for success, 1 for failure
    sys.exit(0 if result.get("status") == "COMPLETED" else 1)
