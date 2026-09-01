import base64
import glob
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import select
import sqlite3
import subprocess
import tempfile
import threading
import uuid
import zipfile
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import psutil

from action_framework import (
    ActionManager,
    ActionType,
    DEPLOY_PACKAGE_INIT_COMMAND,
    normalize_action_name,
)

# ============================================================
# SYSTEM INFORMATION
# ============================================================


def get_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
    except OSError:
        ip = "Unknown"
    finally:
        sock.close()
    return ip


def get_mac(active_ip=None):
    """Return the MAC for the interface carrying the active IPv4 address.

    ``uuid.getnode()`` can select a virtual, disconnected, or otherwise
    unrelated adapter on multi-interface machines (especially Windows).  The
    registration identity must instead be the adapter whose IPv4 address is
    actually used to reach the server.
    """
    active_ip = active_ip or get_ip()
    link_families = {
        getattr(psutil, "AF_LINK", None),
        getattr(socket, "AF_PACKET", None),
    }
    link_families.discard(None)

    for addresses in psutil.net_if_addrs().values():
        has_active_ip = any(
            address.family == socket.AF_INET and address.address == active_ip
            for address in addresses
        )
        if not has_active_ip:
            continue
        for address in addresses:
            mac_address = address.address.strip().lower()
            if (
                address.family in link_families
                and mac_address
                and mac_address != "00:00:00:00:00:00"
            ):
                return mac_address.replace("-", ":")

    # Keep a best-effort fallback for unusual platforms, but make it visible
    # to callers that normal interface discovery was not possible.
    mac = uuid.getnode()
    return ":".join(f"{(mac >> i) & 0xff:02x}" for i in range(40, -1, -8))


def get_hostname():
    return socket.gethostname()


def get_os():
    return {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
    }


CLIENT_VERSION_PATH = Path(__file__).resolve().parent / "version.json"
DEFAULT_CLIENT_VERSION = "0.0.0"
HEARTBEAT_INTERVAL_SECONDS = 30.0


def get_client_version() -> str:
    try:
        with CLIENT_VERSION_PATH.open("r", encoding="utf-8") as version_file:
            value = json.load(version_file).get("version")
        return str(value or DEFAULT_CLIENT_VERSION)
    except (OSError, ValueError, TypeError):
        return DEFAULT_CLIENT_VERSION


def send_pending_update_results(connection) -> int:
    """Report durable updater results after the client reconnects."""
    results_dir = Path(__file__).resolve().parent.parent / "storage" / "updates" / "results"
    if not results_dir.is_dir():
        return 0

    sent = 0
    for result_path in sorted(results_dir.glob("*.json")):
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
            action_id = result.get("action_id") or result_path.stem
            update_status = result.get("status")
            message = {
                "type": "PACKAGE_RESULT",
                "action_id": action_id,
                "status": "SUCCESS" if update_status == "COMPLETED" else "FAILED",
                "update_status": update_status,
                **result,
            }
            with socket_lock:
                send_message(connection, message)
            result_path.unlink()
            sent += 1
        except (OSError, ValueError, TypeError):
            continue
    return sent




def get_system_info(ip_address=None):
    ip_address = ip_address or get_ip()
    return {
        "ip": ip_address,
        "mac": get_mac(ip_address),
        "hostname": get_hostname(),
        "os": get_os(),
        "client_version": get_client_version(),
        "platform": platform.system(),
    }


# ============================================================
# NETWORK INFORMATION
# ============================================================


def get_network_info():
    interfaces = {}
    for name, addresses in psutil.net_if_addrs().items():
        interfaces[name] = []
        for address in addresses:
            interfaces[name].append(
                {
                    "family": str(address.family),
                    "address": address.address,
                    "netmask": address.netmask,
                    "broadcast": address.broadcast,
                }
            )
    return interfaces


# ============================================================
# CPU INFORMATION
# ============================================================


def get_cpu_brand():
    # 1. Try platform.processor() first
    brand = platform.processor()
    if brand and not brand.isspace():
        return brand

    # 2. Linux fallback (/proc/cpuinfo)
    if platform.system() == "Linux":
        try:
            with open("/proc/cpuinfo", "r") as f:
                for line in f:
                    if "model name" in line:
                        return re.sub(r".*:\s*", "", line, 1).strip()
        except Exception:
            pass

    # 3. macOS fallback (sysctl)
    elif platform.system() == "Darwin":
        try:
            return (
                subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"])
                .decode()
                .strip()
            )
        except Exception:
            pass

    # 4. Windows fallback (wmic)
    elif platform.system() == "Windows":
        try:
            out = (
                subprocess.check_output("wmic cpu get name", shell=True)
                .decode()
                .strip()
            )
            lines = [l.strip() for l in out.splitlines() if l.strip()]
            if len(lines) > 1:
                return lines[1]
        except Exception:
            pass

    return "Unknown Processor"


def get_cpu_info():
    return {
        "processor": get_cpu_brand(),
        "architecture": platform.machine(),
        "physical_cores": psutil.cpu_count(logical=False),
        "logical_cores": psutil.cpu_count(logical=True),
        "usage_percent": psutil.cpu_percent(interval=1),
    }


# ============================================================
# MEMORY INFORMATION
# ============================================================


def format_size(bytes_size):
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_size < 1024:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024
    return f"{bytes_size:.2f} PB"


def get_memory_info():
    memory = psutil.virtual_memory()
    return {
        "total": format_size(memory.total),
        "available": format_size(memory.available),
        "used": format_size(memory.used),
        "usage_percent": f"{memory.percent:.2f}%",
    }


# ============================================================
# DISK INFORMATION
# ============================================================


def get_disk_info():
    disk = psutil.disk_usage("/")
    return {
        "total": format_size(disk.total),
        "used": format_size(disk.used),
        "free": format_size(disk.free),
        "usage_percent": f"{disk.percent:.2f}%",
    }


# ============================================================
# PROCESS INFORMATION
# ============================================================


def get_processes():
    processes = []
    for process in psutil.process_iter(["pid", "name", "username", "status"]):
        try:
            if process.info["status"] == psutil.STATUS_ZOMBIE:
                continue
            processes.append(process.info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return processes


def kill_process(process_name):
    killed_count = 0
    errors = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if proc.info["name"] == process_name:
                proc.terminate()
                killed_count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as e:
            errors.append(f"PID {proc.pid if proc else 'unknown'}: {e!s}")

    if killed_count > 0:
        return {
            "status": "success",
            "message": f"Terminated {killed_count} process(es) named '{process_name}'",
            "errors": errors,
        }

    return {
        "status": "error",
        "message": f"No active processes found named '{process_name}'",
        "errors": errors,
    }


def start_process(path):
    try:
        proc = subprocess.Popen(path, shell=True)
        return {
            "status": "success",
            "message": f"Started process '{path}' with PID {proc.pid}",
        }
    except Exception as e:
        return {"status": "error", "message": f"Failed to start process: {e!s}"}


# ============================================================
# ACTIVITY LOG
# ============================================================


def _read_chrome_history(db_path, browser_name, add, cutoff_epoch):
    if not os.path.exists(db_path):
        return
    tmp = tempfile.mktemp(suffix=".db")
    try:
        shutil.copy2(db_path, tmp)
        conn = sqlite3.connect(tmp)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        # Chrome stores time as microseconds since 1601-01-01; convert cutoff to that
        chrome_epoch = int((cutoff_epoch + 11644473600) * 1_000_000)
        cur.execute(
            "SELECT title, url, "
            "datetime((last_visit_time/1000000)-11644473600, 'unixepoch', 'localtime') as visit_time "
            "FROM urls WHERE last_visit_time >= ? ORDER BY last_visit_time DESC LIMIT 200",
            (chrome_epoch,),
        )
        for row in cur.fetchall():
            add(
                row["visit_time"] or "Unknown",
                f"Browser ({browser_name})",
                f"{row['title'] or '(no title)'} — {row['url']}",
            )
        conn.close()
    except Exception:
        pass
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass


def _read_firefox_history(db_path, add, cutoff_epoch):
    """
    Read Firefox browsing history from places.sqlite.

    Firefox stores visit_date as microseconds since Unix epoch.
    A temporary copy is used because Firefox may have the database open.
    """
    if not os.path.isfile(db_path):
        return

    tmp = tempfile.mktemp(suffix=".sqlite")

    try:
        shutil.copy2(db_path, tmp)

        conn = sqlite3.connect(tmp)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        ff_cutoff = int(cutoff_epoch * 1_000_000)

        cur.execute(
            """
            SELECT
                p.title,
                p.url,
                h.visit_date
            FROM moz_historyvisits h
            JOIN moz_places p
                ON h.place_id = p.id
            WHERE h.visit_date >= ?
              AND h.visit_date IS NOT NULL
            ORDER BY h.visit_date DESC
            LIMIT 500
            """,
            (ff_cutoff,),
        )

        rows = cur.fetchall()

        for row in rows:
            try:
                visit_time = datetime.fromtimestamp(
                    row["visit_date"] / 1_000_000
                ).strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError, OSError):
                visit_time = "Unknown"

            add(
                visit_time,
                "Browser (Firefox)",
                f"{row['title'] or '(no title)'} — {row['url']}",
            )

        conn.close()

    except (sqlite3.Error, OSError, shutil.Error) as e:
        print(f"Failed to read Firefox history: {e}")

    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _read_safari_history(db_path, add, cutoff_epoch):
    """Read macOS Safari history from its History.db SQLite database."""
    if not os.path.isfile(db_path):
        return

    tmp = tempfile.mktemp(suffix=".db")
    try:
        shutil.copy2(db_path, tmp)
        conn = sqlite3.connect(tmp)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Safari records seconds since 2001-01-01, unlike Unix timestamps.
        safari_epoch_offset = 978307200
        safari_cutoff = cutoff_epoch - safari_epoch_offset
        cursor.execute(
            """
            SELECT
                i.url,
                v.title,
                datetime(v.visit_time + ?, 'unixepoch', 'localtime') AS visit_time
            FROM history_visits AS v
            JOIN history_items AS i ON i.id = v.history_item
            WHERE v.visit_time >= ?
            ORDER BY v.visit_time DESC
            LIMIT 500
            """,
            (safari_epoch_offset, safari_cutoff),
        )

        for row in cursor.fetchall():
            add(
                row["visit_time"] or "Unknown",
                "Browser (Safari)",
                f"{row['title'] or '(no title)'} — {row['url']}",
            )
        conn.close()
    except (sqlite3.Error, OSError, shutil.Error):
        # History collection is optional; a locked or unavailable browser
        # database must not prevent the rest of the activity log.
        pass
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _read_chromium_profiles(profile_root, browser_name, add, cutoff_epoch):
    """Read Default and named profiles for a Chromium-family browser."""
    if not os.path.isdir(profile_root):
        return

    history_files = glob.glob(os.path.join(profile_root, "*", "History"))
    for history_file in sorted(set(history_files)):
        _read_chrome_history(history_file, browser_name, add, cutoff_epoch)


def _read_shell_history(path, add, cutoff_epoch):
    """
    Read Bash/Zsh shell history.

    Bash history with timestamps looks like:

        #1786880318
        export HISTTIMEFORMAT='%Y-%m-%d %H:%M:%S '

        #1786880320
        echo "$HISTTIMEFORMAT"

    The #<epoch> line belongs to the command immediately following it.
    """

    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except (OSError, IOError):
        return

    current_timestamp = None
    current_command = []

    def flush_command():
        nonlocal current_timestamp, current_command

        if not current_command:
            return

        command = "\n".join(current_command).strip()

        if not command:
            current_command = []
            return

        # We only add commands for which we have a timestamp.
        if current_timestamp is not None:
            if current_timestamp >= cutoff_epoch:
                ts = datetime.fromtimestamp(current_timestamp).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

                add(ts, "Shell Command", command)

        current_command = []

    for raw_line in lines:
        line = raw_line.rstrip("\n")

        # Bash timestamp marker: #<unix_timestamp>
        timestamp_match = re.fullmatch(r"#(\d+)", line.strip())

        if timestamp_match:
            # Finish the previous command first.
            flush_command()

            try:
                current_timestamp = int(timestamp_match.group(1))
            except ValueError:
                current_timestamp = None

            continue

        # Ignore empty lines unless they are part of a command.
        if not line.strip():
            if current_command:
                current_command.append("")
            continue

        current_command.append(line)

    # Flush the final command.
    flush_command()


def _find_firefox_profiles(home):
    """
    Find Firefox places.sqlite databases across common Linux
    installation types.
    """

    profile_roots = [
        # Native Firefox
        os.path.join(home, ".mozilla", "firefox"),
        # Firefox Snap
        os.path.join(home, "snap", "firefox", "common", ".mozilla", "firefox"),
        # Firefox Flatpak
        os.path.join(home, ".var", "app", "org.mozilla.firefox", ".mozilla", "firefox"),
    ]

    profiles = []

    for root in profile_roots:

        if not os.path.isdir(root):
            continue

        profiles.extend(glob.glob(os.path.join(root, "*", "places.sqlite")))

    # Remove duplicates while preserving order
    return list(dict.fromkeys(profiles))


def get_activity_log(period="1d"):
    """
    Collect user activity and filter to the requested period.

    period:
        '1h' = last hour
        '1d' = last 24 hours
        '1w' = last 7 days
        '1m' = last 30 days
    """

    periods = {
        "1h": timedelta(hours=1),
        "1d": timedelta(days=1),
        "1w": timedelta(days=7),
        "1m": timedelta(days=30),
    }

    delta = periods.get(period, timedelta(days=1))

    now = datetime.now()
    cutoff = now - delta

    cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
    cutoff_epoch = cutoff.timestamp()

    system = platform.system()

    activity = []

    home = os.path.expanduser("~")

    # ------------------------------------------------------------
    # Helper used by every activity source
    # ------------------------------------------------------------

    def add(time_str, entry_type, detail):

        if time_str not in ("Unknown", "Recent"):

            try:
                activity_time = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")

                if activity_time < cutoff:
                    return

            except (ValueError, TypeError):
                time_str = "Unknown"

        activity.append(
            {
                "time": time_str,
                "type": entry_type,
                "detail": detail,
            }
        )

    # ============================================================
    # LINUX
    # ============================================================

    if system == "Linux":

        # --------------------------------------------------------
        # Browser history
        # --------------------------------------------------------

        browser_roots = {
            "Chrome": os.path.join(home, ".config/google-chrome"),
            "Chromium": os.path.join(home, ".config/chromium"),
            "Brave": os.path.join(home, ".config/BraveSoftware/Brave-Browser"),
            "Edge": os.path.join(home, ".config/microsoft-edge"),
        }

        for name, profile_root in browser_roots.items():
            _read_chromium_profiles(profile_root, name, add, cutoff_epoch)

        # --------------------------------------------------------
        # Firefox history
        # --------------------------------------------------------

        ff_profiles = _find_firefox_profiles(home)

        for firefox_db in ff_profiles:
            _read_firefox_history(firefox_db, add, cutoff_epoch)

        # --------------------------------------------------------
        # Recently opened files
        # --------------------------------------------------------

        recent_xbel = os.path.join(home, ".local/share/recently-used.xbel")

        if os.path.exists(recent_xbel):

            try:
                with open(recent_xbel, "r", encoding="utf-8", errors="ignore") as f:

                    content = f.read()

                for match in re.finditer(
                    r'<bookmark href="([^"]+)"[^>]*modified="([^"]+)"', content
                ):

                    path = match.group(1).replace("file://", "").replace("%20", " ")

                    ts = match.group(2).replace("T", " ").split(".")[0]

                    add(ts, "Opened File", path)

            except Exception:
                pass

        # --------------------------------------------------------
        # Shell history
        # --------------------------------------------------------

        bash_history = os.path.join(home, ".bash_history")

        zsh_history = os.path.join(home, ".zsh_history")

        if os.path.exists(bash_history):

            _read_shell_history(bash_history, add, cutoff_epoch)

        if os.path.exists(zsh_history):

            _read_shell_history(zsh_history, add, cutoff_epoch)

    # ============================================================
    # WINDOWS
    # ============================================================

    elif system == "Windows":

        app_data = os.environ.get("LOCALAPPDATA", "")

        roaming = os.environ.get("APPDATA", "")

        # --------------------------------------------------------
        # Browser history
        # --------------------------------------------------------

        browser_roots = {
            "Chrome": os.path.join(app_data, r"Google\Chrome\User Data"),
            "Edge": os.path.join(app_data, r"Microsoft\Edge\User Data"),
            "Brave": os.path.join(app_data, r"BraveSoftware\Brave-Browser\User Data"),
        }

        for name, profile_root in browser_roots.items():

            _read_chromium_profiles(profile_root, name, add, cutoff_epoch)

        # --------------------------------------------------------
        # Firefox
        # --------------------------------------------------------

        ff_base = os.path.join(roaming, r"Mozilla\Firefox\Profiles")

        if os.path.isdir(ff_base):

            for profile in os.listdir(ff_base):

                places = os.path.join(ff_base, profile, "places.sqlite")

                if os.path.exists(places):

                    _read_firefox_history(places, add, cutoff_epoch)

                    break

        # --------------------------------------------------------
        # Recently opened files
        # --------------------------------------------------------

        recent_dir = os.path.join(roaming, r"Microsoft\Windows\Recent")

        if os.path.isdir(recent_dir):

            for lnk in sorted(os.listdir(recent_dir), reverse=True):

                full = os.path.join(recent_dir, lnk)

                try:
                    mtime = os.path.getmtime(full)
                except OSError:
                    continue

                if mtime >= cutoff_epoch:

                    ts = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")

                    add(ts, "Opened File", lnk.replace(".lnk", ""))

    # ============================================================
    # MACOS
    # ============================================================

    elif system == "Darwin":

        # --------------------------------------------------------
        # Browser history
        # --------------------------------------------------------

        browser_roots = {
            "Chrome": os.path.join(home, "Library/Application Support/Google/Chrome"),
            "Edge": os.path.join(home, "Library/Application Support/Microsoft Edge"),
            "Brave": os.path.join(
                home, "Library/Application Support/BraveSoftware/Brave-Browser"
            ),
        }

        for name, profile_root in browser_roots.items():

            _read_chromium_profiles(profile_root, name, add, cutoff_epoch)

        # --------------------------------------------------------
        # Firefox
        # --------------------------------------------------------

        ff_profiles = glob.glob(
            os.path.join(
                home,
                "Library/Application Support/Firefox/Profiles/*.default*/places.sqlite",
            )
        )

        if ff_profiles:

            _read_firefox_history(ff_profiles[0], add, cutoff_epoch)

        _read_safari_history(
            os.path.join(home, "Library", "Safari", "History.db"),
            add,
            cutoff_epoch,
        )

        # --------------------------------------------------------
        # macOS recently used files
        # --------------------------------------------------------

        try:

            out = subprocess.check_output(
                [
                    "mdfind",
                    "-onlyin",
                    home,
                    "kMDItemLastUsedDate != ''",
                    "-attr",
                    "kMDItemDisplayName",
                    "-attr",
                    "kMDItemLastUsedDate",
                ],
                timeout=5,
                stderr=subprocess.DEVNULL,
            ).decode("utf-8", errors="ignore")

            for line in out.splitlines()[:50]:

                add("Recent", "Opened File", line.strip())

        except Exception:
            pass

    # ============================================================
    # SORT
    # ============================================================

    activity.sort(
        key=lambda e: (0 if e["time"] == "Unknown" else 1, e["time"]), reverse=True
    )

    # ============================================================
    # RESULT
    # ============================================================

    return {
        "period": period,
        "since": cutoff_str,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "activity": activity,
    }


# ============================================================
# COMMAND HANDLER (dispatcher)
# ============================================================


def _handle_get_system_info(_message, **_context):
    return get_system_info()


def _handle_get_network_info(_message, **_context):
    return get_network_info()


def _handle_get_cpu_info(_message, **_context):
    return get_cpu_info()


def _handle_get_memory_info(_message, **_context):
    return get_memory_info()


def _handle_get_disk_info(_message, **_context):
    return get_disk_info()


def _handle_get_processes(_message, **_context):
    return get_processes()


def _handle_kill_process(message, **_context):
    process_name = message.get("args")
    if not process_name:
        return {"error": "Process name parameter missing"}
    return kill_process(process_name)


def _handle_start_process(message, **_context):
    path = message.get("args")
    if not path:
        return {"error": "Process path parameter missing"}
    return start_process(path)


def _handle_power_action(message, *, action_type, **_context):
    """Schedule a power action after its acknowledgement can be sent."""
    args = message.get("args") or {}
    if not isinstance(args, dict):
        args = {}
    try:
        delay = max(1, min(int(args.get("delay_seconds", 5)), 60))
    except (TypeError, ValueError):
        return {"status": "error", "message": "delay_seconds must be an integer between 1 and 60."}

    system = platform.system()
    if system == "Windows":
        command = ["shutdown", "/s" if action_type == ActionType.SHUTDOWN.value else "/r", "/t", str(delay)]
    elif system in {"Linux", "Darwin"}:
        command = ["shutdown", "-h" if action_type == ActionType.SHUTDOWN.value else "-r", f"+{max(1, delay // 60)}"]
    else:
        return {"status": "error", "message": f"Power actions are not supported on {system}."}

    def run_power_command():
        try:
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, ValueError) as error:
            print(f"[ACTION] Could not schedule {action_type}: {error}")

    timer = threading.Timer(0.25, run_power_command)
    timer.daemon = True
    timer.start()
    return {
        "status": "ok",
        "action": action_type,
        "state": "scheduled",
        "delay_seconds": delay,
    }


def _handle_shutdown(message, **context):
    return _handle_power_action(message, action_type=ActionType.SHUTDOWN.value, **context)


def _handle_restart(message, **context):
    return _handle_power_action(message, action_type=ActionType.RESTART.value, **context)


def _handle_refresh_health(_message, **_context):
    payload = {
        "status": "ok",
        "health": {
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_percent": psutil.disk_usage("/").percent,
        },
    }
    location = load_client_location()
    if location:
        payload["location"] = location
    return payload


def _handle_collect_diagnostics(_message, **_context):
    return {
        "status": "ok",
        "system": get_system_info(),
        "health": _handle_refresh_health(_message)["health"],
        "process_count": len(get_processes()),
    }


def _handle_update_location(message, **_context):
    location = message.get("args")
    if not isinstance(location, dict) or not location.get("id") or not location.get("label"):
        return {"status": "error", "message": "A valid location object is required."}
    location_path = Path(__file__).resolve().parent.parent / "storage" / "client_location.json"
    temporary_path = f"{location_path}.tmp"
    try:
        with open(temporary_path, "w", encoding="utf-8") as location_file:
            json.dump(location, location_file, ensure_ascii=False, sort_keys=True)
        os.replace(temporary_path, location_path)
    except OSError as error:
        return {"status": "error", "message": f"Could not persist location: {error}"}
    return {"status": "ok", "location": location}


def _handle_get_activity_log(message, **_context):
    period = message.get("args", "1d")
    return get_activity_log(period)


def _handle_quarantine_client(message, *, quarantine_manager=None, **_context):
    args = message.get("args") or {}
    reason = (
        args.get("reason", "Administrator requested network isolation")
        if isinstance(args, dict)
        else str(args)
    )
    duration = args.get("duration_minutes") if isinstance(args, dict) else None
    cmd_id = args.get("command_id") if isinstance(args, dict) else None
    if quarantine_manager:
        return quarantine_manager.quarantine_endpoint(
            reason=reason, duration_minutes=duration, command_id=cmd_id
        )
    return {"status": "error", "message": "Quarantine manager is not initialized"}


def _handle_release_client(message, *, quarantine_manager=None, **_context):
    args = message.get("args") or {}
    reason = (
        args.get("reason", "Administrator released network isolation")
        if isinstance(args, dict)
        else str(args)
    )
    cmd_id = args.get("command_id") if isinstance(args, dict) else None
    if quarantine_manager:
        return quarantine_manager.release_quarantine(reason=reason, command_id=cmd_id)
    return {"status": "error", "message": "Quarantine manager is not initialized"}


def _handle_get_quarantine_status(_message, *, quarantine_manager=None, **_context):
    if quarantine_manager:
        return quarantine_manager.get_status()
    return {"status": "error", "message": "Quarantine manager is not initialized"}


def _handle_isolate_device(message, *, network_state_manager=None, **_context):
    args = message.get("args") or {}
    reason = (
        args.get("reason", "Administrator requested static device isolation")
        if isinstance(args, dict)
        else str(args)
    )
    if network_state_manager:
        # The command intentionally removes the active route and may prevent
        # this response from reaching the server.
        return network_state_manager.isolate_static_ip(reason=reason, enabled=True)
    return {"status": "error", "message": "Network state manager is not initialized"}


def _handle_get_device_isolation_status(_message, *, network_state_manager=None, **_context):
    if network_state_manager:
        return {"status": "ok", "data": network_state_manager.get_lifecycle_state()}
    return {"status": "error", "message": "Network state manager is not initialized"}


def _handle_update_forbidden_process_policy(message, *, process_monitor=None, **_context):
    rules = message.get("args", [])
    if process_monitor and isinstance(rules, list):
        process_monitor.set_rules(rules)
        return {"status": "ok", "rules_loaded": len(rules)}
    return {"status": "error", "message": "Process monitor not initialized or invalid rules format"}


def _handle_ping(_message, **_context):
    return {"status": "ok"}


def _handle_disconnect(_message, **_context):
    return {"status": "OK"}


def _handle_flush_neighbourhood_storage(_message, **_context):
    from neighbourhood import flush_neighbourhood_storage

    return flush_neighbourhood_storage()


CLIENT_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_INCOMING_DIR = CLIENT_ROOT / "storage" / "updates" / "incoming"
PACKAGE_STAGING_DIR = CLIENT_ROOT / "storage" / "updates" / "staging"
PACKAGE_CURRENT_DIR = CLIENT_ROOT / "storage" / "updates" / "current"
DEFAULT_MAX_UNCOMPRESSED_BYTES = 500 * 1024 * 1024  # 500 MB

_PACKAGE_THREAD = threading.local()
_ALL_PACKAGE_STATES = []
_ALL_PACKAGE_STATES_LOCK = threading.Lock()
_PACKAGE_SESSION_LOCK = threading.Lock()


def _default_package_paths() -> Dict[str, Path]:
    base = Path(__file__).resolve().parent.parent / "storage" / "updates"
    return {
        "incoming": base / "incoming",
        "staging": base / "staging",
        "current": base / "current",
        "sent_files": Path(__file__).resolve().parent.parent / "storage" / "sent-files",
        "sessions": {},
    }


def _package_state() -> Dict[str, Any]:
    state = getattr(_PACKAGE_THREAD, "state", None)
    if state is None:
        defaults = _default_package_paths()
        state = {
            "incoming": defaults["incoming"],
            "staging": defaults["staging"],
            "current": defaults["current"],
            "sent_files": defaults["sent_files"],
            "sessions": {},
        }
        _PACKAGE_THREAD.state = state
        with _ALL_PACKAGE_STATES_LOCK:
            _ALL_PACKAGE_STATES.append(state)
    return state


def configure_package_paths(
    incoming: Path | str | None = None,
    staging: Path | str | None = None,
    current: Path | str | None = None,
    sent_files: Path | str | None = None,
) -> None:
    """Override package directories for the current thread (used by tests)."""
    state = _package_state()
    if incoming is not None:
        state["incoming"] = Path(incoming)
    if staging is not None:
        state["staging"] = Path(staging)
    if current is not None:
        state["current"] = Path(current)
    if sent_files is not None:
        state["sent_files"] = Path(sent_files)


def reset_all_package_states() -> None:
    """Close and clear package sessions/paths created in any thread (testing helper)."""
    with _ALL_PACKAGE_STATES_LOCK:
        for state in _ALL_PACKAGE_STATES:
            for session in list(state["sessions"].values()):
                file_handle = session.get("file_handle")
                if file_handle and not file_handle.closed:
                    try:
                        file_handle.close()
                    except Exception:
                        pass
            state["sessions"].clear()
        _ALL_PACKAGE_STATES.clear()
    if hasattr(_PACKAGE_THREAD, "state"):
        delattr(_PACKAGE_THREAD, "state")


class _ActivePackageSessionsProxy:
    def _sessions(self):
        return _package_state()["sessions"]

    def get(self, key, default=None):
        return self._sessions().get(key, default)

    def __contains__(self, key):
        return key in self._sessions()

    def __setitem__(self, key, value):
        self._sessions()[key] = value

    def pop(self, key, default=None):
        return self._sessions().pop(key, default)

    def clear(self):
        self._sessions().clear()

    def values(self):
        return self._sessions().values()


ACTIVE_PACKAGE_SESSIONS = _ActivePackageSessionsProxy()


def safe_extract(
    zip_path: Path | str,
    dest_dir: Path | str,
    max_uncompressed_bytes: int = DEFAULT_MAX_UNCOMPRESSED_BYTES,
) -> None:
    """Safely extract a zip archive after validating size limits and zip-slip path traversals."""
    dest_dir_str = os.path.realpath(str(dest_dir))
    with zipfile.ZipFile(str(zip_path), "r") as zf:
        total_uncompressed = sum(info.file_size for info in zf.infolist())
        if total_uncompressed > max_uncompressed_bytes:
            raise ValueError(
                f"archive too large: {total_uncompressed} bytes uncompressed exceeds limit of {max_uncompressed_bytes} bytes"
            )
        for info in zf.infolist():
            target_path = os.path.realpath(os.path.join(dest_dir_str, info.filename))
            if not (
                target_path == dest_dir_str
                or target_path.startswith(dest_dir_str + os.sep)
            ):
                raise ValueError(f"unsafe path in archive: {info.filename}")
        # Every entry validated -- now actually extract
        os.makedirs(dest_dir_str, exist_ok=True)
        zf.extractall(dest_dir_str)


def atomic_swap_directory(source_dir: Path | str, target_dir: Path | str) -> None:
    """Atomically swap source_dir into target_dir on the same filesystem."""
    src = Path(source_dir).resolve()
    dst = Path(target_dir).resolve()
    dst.parent.mkdir(parents=True, exist_ok=True)

    if not dst.exists():
        os.replace(str(src), str(dst))
        return

    # If destination exists, move it aside, replace with new source, then clean up old
    backup = dst.with_name(f"{dst.name}_old_{uuid.uuid4().hex[:8]}")
    os.replace(str(dst), str(backup))
    try:
        os.replace(str(src), str(dst))
        shutil.rmtree(str(backup), ignore_errors=True)
    except Exception:
        # Rollback if replacing with new directory failed
        try:
            os.replace(str(backup), str(dst))
        except Exception:
            pass
        raise


def _safe_file_name(value: Any, fallback: str) -> str:
    raw_value = str(value or fallback).strip()
    candidate = Path(raw_value).name
    if (
        not raw_value
        or candidate in {"", ".", ".."}
        or candidate != raw_value
        or "/" in raw_value
        or "\\\\" in raw_value
        or Path(raw_value).is_absolute()
    ):
        raise ValueError("destination name must be a single relative filename")
    return candidate


def _handle_deploy_package_init(message, **_context):
    args = message.get("args") if isinstance(message.get("args"), dict) else {}
    action_id = message.get("action_id") or args.get("action_id")
    package_id = _safe_file_name(args.get("package_id") or action_id, str(action_id or "package"))
    operation = str(args.get("operation") or "DEPLOY_PACKAGE").strip().upper()
    if operation not in {"DEPLOY_PACKAGE", "SEND_FILE", "UPDATE_CLIENT"}:
        return {"status": "error", "message": f"Unsupported package operation: {operation}"}
    sha256 = args.get("sha256")
    total_size = args.get("total_size", 0)
    chunk_size = args.get("chunk_size", 131072)
    total_chunks = args.get("total_chunks", 1)

    if not action_id or not package_id or not sha256:
        return {
            "status": "error",
            "message": "Missing required package parameters (action_id, package_id, sha256).",
        }

    try:
        staging_dir = _package_state()["incoming"]
        destination_dir = (
            _package_state()["sent_files"]
            if operation == "SEND_FILE"
            else _package_state()["incoming"]
        )
        staging_dir.mkdir(parents=True, exist_ok=True)
        destination_dir.mkdir(parents=True, exist_ok=True)
        part_path = staging_dir / f"{package_id}.part"
        requested_name = args.get("filename") or args.get("file_name")
        final_name = _safe_file_name(requested_name, f"{package_id}.zip")
        final_path = (
            destination_dir / final_name
            if operation == "SEND_FILE"
            else staging_dir / f"{package_id}.zip"
        )
        final_root = destination_dir.resolve()
        if final_path.resolve().parent != final_root:
            return {"status": "error", "message": "Invalid destination filename."}

        try:
            if part_path.exists():
                part_path.unlink()
        except OSError as err:
            return {
                "status": "error",
                "message": f"Could not clear stale partial package file: {err}",
            }

        file_handle = open(part_path, "wb")

        with _PACKAGE_SESSION_LOCK:
            sessions = _package_state()["sessions"]
            old_session = sessions.get(action_id)
            if old_session and old_session.get("file_handle"):
                try:
                    old_session["file_handle"].close()
                except Exception:
                    pass

            sessions[action_id] = {
                "action_id": action_id,
                "package_id": package_id,
                "operation": operation,
                "sha256": str(sha256).strip().lower(),
                "total_size": int(total_size),
                "chunk_size": int(chunk_size),
                "total_chunks": int(total_chunks),
                "part_path": part_path,
                "final_path": final_path,
                "file_handle": file_handle,
                "received_chunks": 0,
                "hasher": hashlib.sha256(),
                "bytes_written": 0,
            }

        return {
            "status": "ready",
            "action_id": action_id,
            "package_id": package_id,
            "operation": operation,
            "filename": final_name,
            "total_chunks": total_chunks,
        }
    except Exception as exc:
        return {
            "status": "error",
            "message": f"Failed to initialize package staging: {exc}",
        }


def process_package_chunk(message):
    """Process an incoming PACKAGE_CHUNK frame, write directly to disk, and extract safely."""
    if not isinstance(message, dict):
        return {"type": "PACKAGE_RESULT", "status": "FAILED", "error": "Invalid message format"}

    action_id = message.get("action_id")
    seq = message.get("seq")
    data_b64 = message.get("data")

    with _PACKAGE_SESSION_LOCK:
        sessions = _package_state()["sessions"]
        session = sessions.get(action_id)
        if not session:
            return {
                "type": "PACKAGE_RESULT",
                "action_id": action_id,
                "status": "FAILED",
                "error": f"No active package session found for action_id={action_id}",
            }

        file_handle = session["file_handle"]
        part_path = session["part_path"]
        final_path = session["final_path"]
        expected_hash = session["sha256"]
        package_id = session["package_id"]

        try:
            chunk_bytes = base64.b64decode(data_b64, validate=True)
            file_handle.write(chunk_bytes)
            file_handle.flush()
            session["hasher"].update(chunk_bytes)
            session["bytes_written"] += len(chunk_bytes)
            session["received_chunks"] += 1

            if seq == session["total_chunks"]:
                file_handle.close()
                sessions.pop(action_id, None)

                computed_hash = session["hasher"].hexdigest().lower()
                if computed_hash == expected_hash:
                    os.replace(part_path, final_path)
                    if session.get("operation") == "UPDATE_CLIENT":
                        result = {
                            "type": "PACKAGE_RESULT",
                            "action_id": action_id,
                            "package_id": package_id,
                            "status": "STAGED",
                            "sha256": computed_hash,
                            "file_path": str(final_path),
                            "destination": "updates/incoming",
                            "total_bytes": session["bytes_written"],
                        }
                        # Spawn the updater subprocess in the background
                        # Get client_root from the final_path (which is storage/updates/incoming)
                        # Navigate: pkg.zip -> incoming -> updates -> storage -> client
                        client_root = final_path.parent.parent.parent.parent  # Go up 4 levels to client root
                        spawn_result = _spawn_updater_subprocess(final_path, client_root, action_id)
                        result["updater_spawn_status"] = spawn_result.get("status")
                        if spawn_result.get("status") == "ok":
                            result["updater_pid"] = spawn_result.get("updater_pid")
                        else:
                            result["updater_error"] = spawn_result.get("message")
                        return result
                    if session.get("operation") == "SEND_FILE":
                        return {
                            "type": "PACKAGE_RESULT",
                            "action_id": action_id,
                            "package_id": package_id,
                            "status": "SUCCESS",
                            "sha256": computed_hash,
                            "file_path": str(final_path),
                            "destination": "sent-files",
                            "total_bytes": session["bytes_written"],
                        }

                    # Deploy packages are extracted into staging and atomically swapped.
                    staging_extract_dir = _package_state()["staging"] / f"{package_id}_{uuid.uuid4().hex[:8]}"
                    shutil.rmtree(staging_extract_dir, ignore_errors=True)
                    staging_extract_dir.mkdir(parents=True, exist_ok=True)
                    try:
                        safe_extract(final_path, staging_extract_dir)
                        atomic_swap_directory(staging_extract_dir, _package_state()["current"])
                        return {
                            "type": "PACKAGE_RESULT",
                            "action_id": action_id,
                            "package_id": package_id,
                            "status": "SUCCESS",
                            "sha256": computed_hash,
                            "file_path": str(final_path),
                            "extracted_path": str(_package_state()["current"]),
                            "total_bytes": session["bytes_written"],
                        }
                    except Exception as extract_error:
                        shutil.rmtree(staging_extract_dir, ignore_errors=True)
                        return {
                            "type": "PACKAGE_RESULT",
                            "action_id": action_id,
                            "package_id": package_id,
                            "status": "FAILED",
                            "sha256": computed_hash,
                            "error": f"safe extraction failed: {extract_error}",
                        }
                else:
                    try:
                        part_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                    return {
                        "type": "PACKAGE_RESULT",
                        "action_id": action_id,
                        "package_id": package_id,
                        "status": "FAILED",
                        "sha256": computed_hash,
                        "error": f"hash mismatch: expected {expected_hash}, got {computed_hash}",
                    }
            return None
        except Exception as error:
            try:
                file_handle.close()
            except Exception:
                pass
            try:
                part_path.unlink(missing_ok=True)
            except OSError:
                pass
            sessions.pop(action_id, None)
            return {
                "type": "PACKAGE_RESULT",
                "action_id": action_id,
                "package_id": package_id,
                "status": "FAILED",
                "error": f"chunk write failed: {error}",
            }


def _spawn_updater_subprocess(
    staged_package_path: Path | str,
    client_root: Path | str,
    action_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Spawn the updater as a subprocess to apply a staged package.
    
    This runs asynchronously; the subprocess continues even if the main client
    exits or is stopped. Returns immediately with status 'UPDATER_SPAWNED' or an error.
    """
    import subprocess
    import sys
    
    try:
        staged_path = Path(staged_package_path).resolve()
        client_root_path = Path(client_root).resolve()
        updater_path = client_root_path / "updater" / "updater.py"
        
        if not staged_path.is_file():
            return {
                "status": "error",
                "message": f"Staged package not found: {staged_path}",
            }
        
        if not updater_path.is_file():
            return {
                "status": "error",
                "message": f"Updater not found: {updater_path}",
            }
        
        # Use subprocess.Popen to spawn the updater in the background.
        # The updater will handle stopping the client, replacing app/, and restarting.
        # We pass the staged package path and client_root as arguments.
        python_exe = sys.executable
        proc = subprocess.Popen(
            [
                python_exe,
                str(updater_path),
                str(staged_path),
                str(client_root_path),
                *( [str(action_id)] if action_id else [] ),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # Detach from parent on Unix; on Windows this is ignored
        )
        
        return {
            "status": "ok",
            "message": "Updater spawned successfully",
            "updater_pid": proc.pid,
        }
    except Exception as error:
        return {
            "status": "error",
            "message": f"Failed to spawn updater: {error}",
        }


ACTION_MANAGER = ActionManager()
ACTION_MANAGER.register(ActionType.GET_SYSTEM_INFO.value, _handle_get_system_info)
ACTION_MANAGER.register(ActionType.GET_NETWORK_INFO.value, _handle_get_network_info)
ACTION_MANAGER.register(ActionType.GET_CPU_INFO.value, _handle_get_cpu_info)
ACTION_MANAGER.register(ActionType.GET_MEMORY_INFO.value, _handle_get_memory_info)
ACTION_MANAGER.register(ActionType.GET_DISK_INFO.value, _handle_get_disk_info)
ACTION_MANAGER.register(ActionType.GET_PROCESSES.value, _handle_get_processes)
ACTION_MANAGER.register(ActionType.KILL_PROCESS.value, _handle_kill_process)
ACTION_MANAGER.register(ActionType.START_PROCESS.value, _handle_start_process)
ACTION_MANAGER.register(ActionType.SHUTDOWN.value, _handle_shutdown)
ACTION_MANAGER.register(ActionType.RESTART.value, _handle_restart)
ACTION_MANAGER.register(ActionType.REFRESH_HEALTH.value, _handle_refresh_health)
ACTION_MANAGER.register(ActionType.COLLECT_DIAGNOSTICS.value, _handle_collect_diagnostics)
ACTION_MANAGER.register(ActionType.GET_ACTIVITY_LOG.value, _handle_get_activity_log)
ACTION_MANAGER.register(ActionType.QUARANTINE_CLIENT.value, _handle_quarantine_client)
ACTION_MANAGER.register(ActionType.RELEASE_CLIENT.value, _handle_release_client)
ACTION_MANAGER.register(ActionType.GET_QUARANTINE_STATUS.value, _handle_get_quarantine_status)
ACTION_MANAGER.register(ActionType.ISOLATE_DEVICE.value, _handle_isolate_device)
ACTION_MANAGER.register(
    ActionType.GET_DEVICE_ISOLATION_STATUS.value,
    _handle_get_device_isolation_status,
)
ACTION_MANAGER.register(
    ActionType.UPDATE_FORBIDDEN_PROCESS_POLICY.value,
    _handle_update_forbidden_process_policy,
)
ACTION_MANAGER.register(ActionType.PING.value, _handle_ping)
ACTION_MANAGER.register(ActionType.DISCONNECT.value, _handle_disconnect)
ACTION_MANAGER.register(ActionType.UPDATE_LOCATION.value, _handle_update_location)
ACTION_MANAGER.register(
    ActionType.FLUSH_NEIGHBOURHOOD_STORAGE.value,
    _handle_flush_neighbourhood_storage,
)
ACTION_MANAGER.register(
    DEPLOY_PACKAGE_INIT_COMMAND,
    _handle_deploy_package_init,
)
ACTION_MANAGER.register(
    ActionType.DEPLOY_PACKAGE.value,
    _handle_deploy_package_init,
)
ACTION_MANAGER.register(
    ActionType.SEND_FILE.value,
    _handle_deploy_package_init,
)
ACTION_MANAGER.register(
    ActionType.UPDATE_CLIENT.value,
    _handle_deploy_package_init,
)


def handle_command(
    message,
    *,
    quarantine_manager=None,
    process_monitor=None,
    network_state_manager=None,
):
    if not isinstance(message, dict):
        return {"error": "Invalid message format"}

    command = normalize_action_name(message.get("command"))
    return ACTION_MANAGER.dispatch(
        {**message, "command": command},
        quarantine_manager=quarantine_manager,
        process_monitor=process_monitor,
        network_state_manager=network_state_manager,
    )


# ============================================================
# REGISTRATION MESSAGE
# ============================================================


def load_client_location():
    """Load the last server-assigned physical location, if one is cached."""
    location_path = Path(__file__).resolve().parent.parent / "storage" / "client_location.json"
    try:
        with open(location_path, "r", encoding="utf-8") as location_file:
            location = json.load(location_file)
        return location if isinstance(location, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def create_registration_message(ip_address=None, *, agent_role="service"):
    """Create a client registration frame with the process role.

    The same device can run the Session 0 service and an interactive user-session
    agent.  The role lets the server route desktop-specific requests only to the
    interactive connection while retaining the existing MAC-derived device ID.
    """
    data = get_system_info(ip_address)
    data["agent_role"] = agent_role
    location = load_client_location()
    if location:
        data["location"] = location
    return {"type": "REGISTER", "data": data}


# ============================================================
# SEND / RECEIVE
# ============================================================


def send_message(connection, message):
    data = json.dumps(message).encode()
    # Prefix with 4-byte big-endian length so the receiver knows exactly how much to read
    connection.sendall(len(data).to_bytes(4, byteorder="big") + data)


def receive_message(connection, stop_event=None, poll_interval=0.5):
    def wait_for_readable():
        while True:
            if stop_event and stop_event.is_set():
                return False
            try:
                readable, _, _ = select.select([connection], [], [], poll_interval)
            except (OSError, ValueError):
                return False
            if readable:
                return True

    # Read the 4-byte length header first.
    header = b""
    while len(header) < 4:
        if not wait_for_readable():
            return None
        chunk = connection.recv(4 - len(header))
        if not chunk:
            return None
        header += chunk

    total = int.from_bytes(header, byteorder="big")

    # Read exactly `total` bytes.
    data = b""
    while len(data) < total:
        if not wait_for_readable():
            return None
        chunk = connection.recv(min(65536, total - len(data)))
        if not chunk:
            return None
        data += chunk

    return json.loads(data.decode())
