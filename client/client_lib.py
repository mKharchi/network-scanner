import glob
import json
import os
import platform
import re
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import uuid
from datetime import datetime, timedelta

import psutil


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
            if address.family in link_families and mac_address and mac_address != "00:00:00:00:00:00":
                return mac_address.replace("-", ":")

    # Keep a best-effort fallback for unusual platforms, but make it visible
    # to callers that normal interface discovery was not possible.
    mac = uuid.getnode()
    return ":".join(
        f"{(mac >> i) & 0xff:02x}"
        for i in range(40, -1, -8)
    )


def get_hostname():
    return socket.gethostname()


def get_os():
    return {
        "system":  platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine()
    }


def get_system_info(ip_address=None):
    ip_address = ip_address or get_ip()
    return {
        "ip":       ip_address,
        "mac":      get_mac(ip_address),
        "hostname": get_hostname(),
        "os":       get_os()
    }


# ============================================================
# NETWORK INFORMATION
# ============================================================

def get_network_info():
    interfaces = {}
    for name, addresses in psutil.net_if_addrs().items():
        interfaces[name] = []
        for address in addresses:
            interfaces[name].append({
                "family":    str(address.family),
                "address":   address.address,
                "netmask":   address.netmask,
                "broadcast": address.broadcast
            })
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
            return subprocess.check_output(
                ["sysctl", "-n", "machdep.cpu.brand_string"]
            ).decode().strip()
        except Exception:
            pass

    # 4. Windows fallback (wmic)
    elif platform.system() == "Windows":
        try:
            out = subprocess.check_output(
                "wmic cpu get name", shell=True
            ).decode().strip()
            lines = [l.strip() for l in out.splitlines() if l.strip()]
            if len(lines) > 1:
                return lines[1]
        except Exception:
            pass

    return "Unknown Processor"


def get_cpu_info():
    return {
        "processor":      get_cpu_brand(),
        "architecture":   platform.machine(),
        "physical_cores": psutil.cpu_count(logical=False),
        "logical_cores":  psutil.cpu_count(logical=True),
        "usage_percent":  psutil.cpu_percent(interval=1)
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
        "total":         format_size(memory.total),
        "available":     format_size(memory.available),
        "used":          format_size(memory.used),
        "usage_percent": f"{memory.percent:.2f}%"
    }


# ============================================================
# DISK INFORMATION
# ============================================================

def get_disk_info():
    disk = psutil.disk_usage("/")
    return {
        "total":         format_size(disk.total),
        "used":          format_size(disk.used),
        "free":          format_size(disk.free),
        "usage_percent": f"{disk.percent:.2f}%"
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
            "status":  "success",
            "message": f"Terminated {killed_count} process(es) named '{process_name}'",
            "errors":  errors
        }

    return {
        "status":  "error",
        "message": f"No active processes found named '{process_name}'",
        "errors":  errors
    }


def start_process(path):
    try:
        proc = subprocess.Popen(path, shell=True)
        return {
            "status":  "success",
            "message": f"Started process '{path}' with PID {proc.pid}"
        }
    except Exception as e:
        return {
            "status":  "error",
            "message": f"Failed to start process: {e!s}"
        }


# ============================================================
# NETWORK LOG
# ============================================================

def get_network_log():
    system = platform.system()
    logs = []

    if system == "Linux":
        try:
            out = subprocess.check_output(
                ["journalctl", "-u", "NetworkManager", "-n", "30", "--no-pager"],
                stderr=subprocess.DEVNULL
            ).decode("utf-8", errors="ignore")
            logs = [line.strip() for line in out.splitlines() if line.strip()]
        except Exception:
            try:
                for path in ["/var/log/syslog", "/var/log/messages"]:
                    if os.path.exists(path):
                        with open(path, "r") as f:
                            lines = f.readlines()[-150:]
                        for line in lines:
                            if any(k in line.lower() for k in ["dhcp", "networkmanager", "wlan", "eth0", "wlp"]):
                                logs.append(line.strip())
                        break
            except Exception as e:
                logs = [f"Error reading Linux network logs: {e}"]

    elif system == "Windows":
        try:
            cmd = "wevtutil qe Microsoft-Windows-Dhcp-Client/Operational /c:30 /f:text /rd:true"
            out = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode("utf-8", errors="ignore")
            logs = [line.strip() for line in out.splitlines() if line.strip()]
        except Exception as e:
            logs = [f"Error reading Windows event logs: {e}"]

    elif system == "Darwin":
        try:
            out = subprocess.check_output(
                ["log", "show", "--predicate", 'process == "configd"', "--last", "1h", "--style", "syslog"],
                stderr=subprocess.DEVNULL
            ).decode("utf-8", errors="ignore")
            logs = [line.strip() for line in out.splitlines() if line.strip()][-30:]
        except Exception as e:
            logs = [f"Error reading macOS network logs: {e}"]

    if not logs:
        return {"logs": ["No network connection events found in system logs."]}

    # Parse raw logs into a readable timeline
    parsed_logs = []
    for line in logs:
        ts_match = re.match(r"^([A-Z][a-z]{2}\s+\d+\s+\d+:\d+:\d+)", line)
        timestamp = ts_match.group(1) if ts_match else "Recent"

        if "state change:" in line:
            m = re.search(r"state change:\s*(\w+)\s*->\s*(\w+)", line)
            if m:
                parsed_logs.append(f"{timestamp} - Interface State Change: {m.group(1)} -> {m.group(2)}")
                continue

        if "Connected to wireless network" in line:
            m = re.search(r'Connected to wireless network\s+"([^"]+)"', line)
            ssid = m.group(1) if m else "Wi-Fi"
            parsed_logs.append(f'{timestamp} - Connected to Wi-Fi: "{ssid}"')
            continue

        if "new lease, address=" in line:
            m = re.search(r"address=([\d\.]+)", line)
            ip_addr = m.group(1) if m else "IP Address"
            parsed_logs.append(f"{timestamp} - Obtained DHCP Lease IP: {ip_addr}")
            continue

        if "NetworkManager state is now" in line:
            m = re.search(r"state is now\s+(\w+)", line)
            if m:
                parsed_logs.append(f"{timestamp} - Network State: {m.group(1)}")
                continue

        if "deactivated" in line or "disconnected" in line:
            parsed_logs.append(f"{timestamp} - Interface disconnected or deactivated")
            continue

        if "DHCP" in line or "IP address" in line or "lease" in line:
            parsed_logs.append(f"{timestamp} - {re.sub(r'\\s+', ' ', line).strip()}")
            continue

    return {"logs": parsed_logs if parsed_logs else logs}


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
            (chrome_epoch,)
        )
        for row in cur.fetchall():
            add(
                row["visit_time"] or "Unknown",
                f"Browser ({browser_name})",
                f"{row['title'] or '(no title)'} — {row['url']}"
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
            (ff_cutoff,)
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
                f"{row['title'] or '(no title)'} — {row['url']}"
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

                add(
                    ts,
                    "Shell Command",
                    command
                )

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
        os.path.join(
            home,
            ".mozilla",
            "firefox"
        ),

        # Firefox Snap
        os.path.join(
            home,
            "snap",
            "firefox",
            "common",
            ".mozilla",
            "firefox"
        ),

        # Firefox Flatpak
        os.path.join(
            home,
            ".var",
            "app",
            "org.mozilla.firefox",
            ".mozilla",
            "firefox"
        ),
    ]

    profiles = []

    for root in profile_roots:

        if not os.path.isdir(root):
            continue

        profiles.extend(
            glob.glob(
                os.path.join(
                    root,
                    "*",
                    "places.sqlite"
                )
            )
        )

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
                activity_time = datetime.strptime(
                    time_str,
                    "%Y-%m-%d %H:%M:%S"
                )

                if activity_time < cutoff:
                    return

            except (ValueError, TypeError):
                time_str = "Unknown"

        activity.append({
            "time": time_str,
            "type": entry_type,
            "detail": detail,
        })

    # ============================================================
    # LINUX
    # ============================================================

    if system == "Linux":

        # --------------------------------------------------------
        # Browser history
        # --------------------------------------------------------

        browser_roots = {
            "Chrome": os.path.join(
                home,
                ".config/google-chrome"
            ),

            "Chromium": os.path.join(
                home,
                ".config/chromium"
            ),

            "Brave": os.path.join(
                home,
                ".config/BraveSoftware/Brave-Browser"
            ),

            "Edge": os.path.join(
                home,
                ".config/microsoft-edge"
            ),
        }

        for name, profile_root in browser_roots.items():
            _read_chromium_profiles(
                profile_root,
                name,
                add,
                cutoff_epoch
            )

        # --------------------------------------------------------
        # Firefox history
        # --------------------------------------------------------

        ff_profiles = _find_firefox_profiles(home)

        for firefox_db in ff_profiles:
            _read_firefox_history(
                firefox_db,
                add,
                cutoff_epoch
            )

        # --------------------------------------------------------
        # Recently opened files
        # --------------------------------------------------------

        recent_xbel = os.path.join(
            home,
            ".local/share/recently-used.xbel"
        )

        if os.path.exists(recent_xbel):

            try:
                with open(
                    recent_xbel,
                    "r",
                    encoding="utf-8",
                    errors="ignore"
                ) as f:

                    content = f.read()

                for match in re.finditer(
                    r'<bookmark href="([^"]+)"[^>]*modified="([^"]+)"',
                    content
                ):

                    path = (
                        match.group(1)
                        .replace("file://", "")
                        .replace("%20", " ")
                    )

                    ts = (
                        match.group(2)
                        .replace("T", " ")
                        .split(".")[0]
                    )

                    add(
                        ts,
                        "Opened File",
                        path
                    )

            except Exception:
                pass

        # --------------------------------------------------------
        # Shell history
        # --------------------------------------------------------

        bash_history = os.path.join(
            home,
            ".bash_history"
        )

        zsh_history = os.path.join(
            home,
            ".zsh_history"
        )

        if os.path.exists(bash_history):

            _read_shell_history(
                bash_history,
                add,
                cutoff_epoch
            )

        if os.path.exists(zsh_history):

            _read_shell_history(
                zsh_history,
                add,
                cutoff_epoch
            )

    # ============================================================
    # WINDOWS
    # ============================================================

    elif system == "Windows":

        app_data = os.environ.get(
            "LOCALAPPDATA",
            ""
        )

        roaming = os.environ.get(
            "APPDATA",
            ""
        )

        # --------------------------------------------------------
        # Browser history
        # --------------------------------------------------------

        browser_roots = {
            "Chrome": os.path.join(
                app_data,
                r"Google\Chrome\User Data"
            ),

            "Edge": os.path.join(
                app_data,
                r"Microsoft\Edge\User Data"
            ),

            "Brave": os.path.join(
                app_data,
                r"BraveSoftware\Brave-Browser\User Data"
            ),
        }

        for name, profile_root in browser_roots.items():

            _read_chromium_profiles(
                profile_root,
                name,
                add,
                cutoff_epoch
            )

        # --------------------------------------------------------
        # Firefox
        # --------------------------------------------------------

        ff_base = os.path.join(
            roaming,
            r"Mozilla\Firefox\Profiles"
        )

        if os.path.isdir(ff_base):

            for profile in os.listdir(ff_base):

                places = os.path.join(
                    ff_base,
                    profile,
                    "places.sqlite"
                )

                if os.path.exists(places):

                    _read_firefox_history(
                        places,
                        add,
                        cutoff_epoch
                    )

                    break

        # --------------------------------------------------------
        # Recently opened files
        # --------------------------------------------------------

        recent_dir = os.path.join(
            roaming,
            r"Microsoft\Windows\Recent"
        )

        if os.path.isdir(recent_dir):

            for lnk in sorted(
                os.listdir(recent_dir),
                reverse=True
            ):

                full = os.path.join(
                    recent_dir,
                    lnk
                )

                try:
                    mtime = os.path.getmtime(full)
                except OSError:
                    continue

                if mtime >= cutoff_epoch:

                    ts = datetime.fromtimestamp(
                        mtime
                    ).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )

                    add(
                        ts,
                        "Opened File",
                        lnk.replace(".lnk", "")
                    )

    # ============================================================
    # MACOS
    # ============================================================

    elif system == "Darwin":

        # --------------------------------------------------------
        # Browser history
        # --------------------------------------------------------

        browser_roots = {
            "Chrome": os.path.join(
                home,
                "Library/Application Support/Google/Chrome"
            ),

            "Edge": os.path.join(
                home,
                "Library/Application Support/Microsoft Edge"
            ),

            "Brave": os.path.join(
                home,
                "Library/Application Support/BraveSoftware/Brave-Browser"
            ),
        }

        for name, profile_root in browser_roots.items():

            _read_chromium_profiles(
                profile_root,
                name,
                add,
                cutoff_epoch
            )

        # --------------------------------------------------------
        # Firefox
        # --------------------------------------------------------

        ff_profiles = glob.glob(
            os.path.join(
                home,
                "Library/Application Support/Firefox/Profiles/*.default*/places.sqlite"
            )
        )

        if ff_profiles:

            _read_firefox_history(
                ff_profiles[0],
                add,
                cutoff_epoch
            )

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
            ).decode(
                "utf-8",
                errors="ignore"
            )

            for line in out.splitlines()[:50]:

                add(
                    "Recent",
                    "Opened File",
                    line.strip()
                )

        except Exception:
            pass

    # ============================================================
    # SORT
    # ============================================================

    activity.sort(
        key=lambda e: (
            0 if e["time"] == "Unknown" else 1,
            e["time"]
        ),
        reverse=True
    )

    # ============================================================
    # RESULT
    # ============================================================

    return {
        "period": period,
        "since": cutoff_str,
        "generated_at": datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "activity": activity,
    }


# ============================================================
# COMMAND HANDLER (dispatcher)
# ============================================================

def handle_command(message):
    if not isinstance(message, dict):
        return {"error": "Invalid message format"}

    command = message.get("command")

    if command == "GET_SYSTEM_INFO":
        return get_system_info()

    elif command == "GET_NETWORK_INFO":
        return get_network_info()

    elif command == "GET_CPU_INFO":
        return get_cpu_info()

    elif command == "GET_MEMORY_INFO":
        return get_memory_info()

    elif command == "GET_DISK_INFO":
        return get_disk_info()

    elif command == "GET_PROCESSES":
        return get_processes()

    elif command == "KILL_PROCESS":
        process_name = message.get("args")
        if not process_name:
            return {"error": "Process name parameter missing"}
        return kill_process(process_name)

    elif command == "START_PROCESS":
        path = message.get("args")
        if not path:
            return {"error": "Process path parameter missing"}
        return start_process(path)

    elif command == "GET_NETWORK_LOG":
        return get_network_log()

    elif command == "GET_ACTIVITY_LOG":
        period = message.get("args", "1d")
        return get_activity_log(period)

    elif command == "PING":
        return {"status": "ok"}

    elif command == "DISCONNECT":
        return {"status": "OK"}

    return {"error": f"Unknown command: {command}"}


# ============================================================
# REGISTRATION MESSAGE
# ============================================================

def create_registration_message(ip_address=None):
    return {
        "type": "REGISTER",
        "data": get_system_info(ip_address)
    }


# ============================================================
# SEND / RECEIVE
# ============================================================

def send_message(connection, message):
    data = json.dumps(message).encode()
    # Prefix with 4-byte big-endian length so the receiver knows exactly how much to read
    connection.sendall(len(data).to_bytes(4, byteorder="big") + data)


def receive_message(connection):
    # Read the 4-byte length header first
    header = b""
    while len(header) < 4:
        chunk = connection.recv(4 - len(header))
        if not chunk:
            return None
        header += chunk

    total = int.from_bytes(header, byteorder="big")

    # Read exactly `total` bytes
    data = b""
    while len(data) < total:
        chunk = connection.recv(min(65536, total - len(data)))
        if not chunk:
            return None
        data += chunk

    return json.loads(data.decode())
