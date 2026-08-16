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


def get_mac():
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


def get_system_info():
    return {
        "ip":       get_ip(),
        "mac":      get_mac(),
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
        "total":         disk.total,
        "used":          disk.used,
        "free":          disk.free,
        "usage_percent": disk.percent
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
    if not os.path.exists(db_path):
        return
    tmp = tempfile.mktemp(suffix=".db")
    try:
        shutil.copy2(db_path, tmp)
        conn = sqlite3.connect(tmp)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        # Firefox stores visit_date as microseconds since Unix epoch
        ff_cutoff = int(cutoff_epoch * 1_000_000)
        cur.execute(
            "SELECT p.title, p.url, "
            "datetime(h.visit_date/1000000, 'unixepoch', 'localtime') as visit_time "
            "FROM moz_historyvisits h JOIN moz_places p ON h.place_id = p.id "
            "WHERE h.visit_date >= ? ORDER BY h.visit_date DESC LIMIT 200",
            (ff_cutoff,)
        )
        for row in cur.fetchall():
            add(
                row["visit_time"] or "Unknown",
                "Browser (Firefox)",
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


def get_activity_log(period="1d"):
    """
    Collect user activity and filter to the requested period.
    period: '1d' = last 24 h, '1w' = last 7 days, '1m' = last 30 days.
    """
    periods = {"1h": timedelta(hours=1), "1d": timedelta(days=1), "1w": timedelta(days=7), "1m": timedelta(days=30)}
    delta = periods.get(period, timedelta(days=1))
    cutoff = datetime.now() - delta
    cutoff_str   = cutoff.strftime("%Y-%m-%d %H:%M:%S")
    cutoff_epoch = cutoff.timestamp()

    system = platform.system()
    activity = []
    home = os.path.expanduser("~")

    def add(time_str, entry_type, detail):
        if time_str not in ("Unknown", "Recent"):
            try:
                if datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S") < cutoff:
                    return
            except ValueError:
                pass
        activity.append({"time": time_str, "type": entry_type, "detail": detail})

    if system == "Linux":
        browser_paths = {
            "Chrome":   os.path.join(home, ".config/google-chrome/Default/History"),
            "Chromium": os.path.join(home, ".config/chromium/Default/History"),
            "Brave":    os.path.join(home, ".config/BraveSoftware/Brave-Browser/Default/History"),
            "Edge":     os.path.join(home, ".config/microsoft-edge/Default/History"),
        }
        for name, path in browser_paths.items():
            _read_chrome_history(path, name, add, cutoff_epoch)

        ff_profiles = (
            glob.glob(os.path.join(home, ".mozilla/firefox/*.default*/places.sqlite")) +
            glob.glob(os.path.join(home, ".mozilla/firefox/*.default/places.sqlite"))
        )
        if ff_profiles:
            _read_firefox_history(ff_profiles[0], add, cutoff_epoch)

        recent_xbel = os.path.join(home, ".local/share/recently-used.xbel")
        if os.path.exists(recent_xbel):
            try:
                with open(recent_xbel, "r", errors="ignore") as f:
                    content = f.read()
                for m in re.finditer(r'<bookmark href="([^"]+)"[^>]*modified="([^"]+)"', content):
                    path = m.group(1).replace("file://", "").replace("%20", " ")
                    ts = m.group(2).replace("T", " ").split(".")[0]
                    add(ts, "Opened File", path)
            except Exception:
                pass

        for history_file in [".bash_history", ".zsh_history"]:
            hpath = os.path.join(home, history_file)
            if os.path.exists(hpath):
                try:
                    with open(hpath, "r", errors="ignore") as f:
                        lines = f.readlines()
                    for line in lines[-500:]:
                        line = line.strip()
                        m = re.match(r"^:\s*(\d+):\d+;(.+)$", line)
                        if m:
                            ts = datetime.fromtimestamp(int(m.group(1))).strftime("%Y-%m-%d %H:%M:%S")
                            add(ts, "Shell Command", m.group(2))
                        elif line and not line.startswith(":"):
                            add("Unknown", "Shell Command", line)
                except Exception:
                    pass
                break

    elif system == "Windows":
        app_data = os.environ.get("LOCALAPPDATA", "")
        roaming   = os.environ.get("APPDATA", "")

        browser_paths = {
            "Chrome": os.path.join(app_data, r"Google\Chrome\User Data\Default\History"),
            "Edge":   os.path.join(app_data, r"Microsoft\Edge\User Data\Default\History"),
            "Brave":  os.path.join(app_data, r"BraveSoftware\Brave-Browser\User Data\Default\History"),
        }
        for name, path in browser_paths.items():
            _read_chrome_history(path, name, add, cutoff_epoch)

        ff_base = os.path.join(roaming, r"Mozilla\Firefox\Profiles")
        if os.path.isdir(ff_base):
            for profile in os.listdir(ff_base):
                places = os.path.join(ff_base, profile, "places.sqlite")
                if os.path.exists(places):
                    _read_firefox_history(places, add, cutoff_epoch)
                    break

        recent_dir = os.path.join(roaming, r"Microsoft\Windows\Recent")
        if os.path.isdir(recent_dir):
            for lnk in sorted(os.listdir(recent_dir), reverse=True):
                full = os.path.join(recent_dir, lnk)
                mtime = os.path.getmtime(full)
                if mtime >= cutoff_epoch:
                    ts = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
                    add(ts, "Opened File", lnk.replace(".lnk", ""))

    elif system == "Darwin":
        browser_paths = {
            "Chrome": os.path.join(home, "Library/Application Support/Google/Chrome/Default/History"),
            "Edge":   os.path.join(home, "Library/Application Support/Microsoft Edge/Default/History"),
            "Brave":  os.path.join(home, "Library/Application Support/BraveSoftware/Brave-Browser/Default/History"),
        }
        for name, path in browser_paths.items():
            _read_chrome_history(path, name, add, cutoff_epoch)

        ff_profiles = glob.glob(
            os.path.join(home, "Library/Application Support/Firefox/Profiles/*.default*/places.sqlite")
        )
        if ff_profiles:
            _read_firefox_history(ff_profiles[0], add, cutoff_epoch)

        try:
            out = subprocess.check_output(
                ["mdfind", "-onlyin", home, "kMDItemLastUsedDate != ''",
                 "-attr", "kMDItemDisplayName", "-attr", "kMDItemLastUsedDate"],
                timeout=5, stderr=subprocess.DEVNULL
            ).decode("utf-8", errors="ignore")
            for line in out.splitlines()[:50]:
                add("Recent", "Opened File", line.strip())
        except Exception:
            pass

    activity.sort(
        key=lambda e: (0 if e["time"] == "Unknown" else 1, e["time"]),
        reverse=True
    )

    return {
        "period": period,
        "since": cutoff_str,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "activity": activity
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

def create_registration_message():
    return {
        "type": "REGISTER",
        "data": get_system_info()
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
