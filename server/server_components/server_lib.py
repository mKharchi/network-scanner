import datetime
import ipaddress
import json
import os
import platform
import queue
import subprocess
import threading
import time

try:
    from database import get_connection
except ImportError:
    from ..database import get_connection

from server_components.log_storage import store_log_file

# ============================================================
# SHARED STATE
# ============================================================

clients = {}
clients_lock = threading.Lock()
next_client_id = 1
pending_disconnect_checks = {}


def _read_positive_float(name, default):
    try:
        return max(0.0, float(os.getenv(name, default)))
    except ValueError:
        return float(default)


def _read_positive_int(name, default):
    try:
        return max(1, int(os.getenv(name, default)))
    except ValueError:
        return int(default)


DISCONNECT_PING_DELAY_SECONDS = _read_positive_float(
    "DISCONNECT_PING_DELAY_SECONDS", "5"
)
DISCONNECT_PING_TIMEOUT_SECONDS = _read_positive_int(
    "DISCONNECT_PING_TIMEOUT_SECONDS", "3"
)

def get_forbidden_processes():
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT process_name, severity, description FROM forbidden_processes WHERE enabled = TRUE")
        return cursor.fetchall()
    except Exception as e:
        print(f"Error fetching forbidden processes: {e}")
        return []
    finally:
        if cursor: cursor.close()
        if conn and conn.is_connected(): conn.close()

ALERT_SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
WORKING_HOURS_DISABLED = "DISABLED"
WORKING_HOURS_WITHIN = "WITHIN"
WORKING_HOURS_OUTSIDE = "OUTSIDE"
WORKING_HOURS_UNKNOWN = "UNKNOWN"


def get_working_hours_status(checked_at=None):
    """Classify a server-local time against the configured working-hours rows.

    ``working_hours.day_of_week`` follows ``datetime.weekday()``: Monday is 0
    and Sunday is 6. A schedule ending at a given time excludes that exact
    end boundary, so 18:00 is outside a 09:30–18:00 workday.
    """
    checked_at = checked_at or datetime.datetime.now()
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT TIME_TO_SEC(start_time), TIME_TO_SEC(end_time)
            FROM working_hours
            WHERE day_of_week = %s AND enabled = TRUE
            """,
            (checked_at.weekday(),),
        )
        schedule = cursor.fetchone()

        if not schedule:
            cursor.execute(
                "SELECT EXISTS(SELECT 1 FROM working_hours WHERE enabled = TRUE)"
            )
            monitoring_enabled = bool(cursor.fetchone()[0])
            return (
                WORKING_HOURS_OUTSIDE
                if monitoring_enabled
                else WORKING_HOURS_DISABLED
            )

        start_seconds, end_seconds = schedule
        current_seconds = (
            checked_at.hour * 3600
            + checked_at.minute * 60
            + checked_at.second
        )

        if start_seconds <= end_seconds:
            is_within = start_seconds <= current_seconds < end_seconds
        else:
            # Supports an overnight schedule such as 22:00–06:00 as well.
            is_within = current_seconds >= start_seconds or current_seconds < end_seconds

        return WORKING_HOURS_WITHIN if is_within else WORKING_HOURS_OUTSIDE
    except Exception as error:
        print(f"Unable to check working hours: {error}")
        return WORKING_HOURS_UNKNOWN
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


def create_connection_alert(client_info, registered_at=None):
    """Persist and display the appropriate server-side registration alert."""
    registered_at = registered_at or datetime.datetime.now()
    working_hours_status = get_working_hours_status(registered_at)

    if working_hours_status == WORKING_HOURS_OUTSIDE:
        alert_type = "CONNECTION_OUTSIDE_WORKING_HOURS"
        severity = "MEDIUM"
        title = "Client connected outside working hours"
        policy_description = "outside configured working hours"
    elif working_hours_status == WORKING_HOURS_DISABLED:
        alert_type = "CLIENT_CONNECTED"
        severity = "LOW"
        title = "Client connected"
        policy_description = "working-hours monitoring is disabled"
    elif working_hours_status == WORKING_HOURS_UNKNOWN:
        alert_type = "CLIENT_CONNECTED"
        severity = "LOW"
        title = "Client connected"
        policy_description = "working-hours status could not be checked"
    else:
        alert_type = "CLIENT_CONNECTED"
        severity = "LOW"
        title = "Client connected"
        policy_description = "during configured working hours"

    hostname = client_info.get("hostname", "Unknown host")
    mac = client_info.get("mac")
    ip = client_info.get("ip", "Unknown IP")
    description = (
        f"{hostname} ({mac}, {ip}) registered at "
        f"{registered_at.strftime('%Y-%m-%d %H:%M:%S')} {policy_description}."
    )

    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM clients WHERE mac = %s", (mac,))
        client = cursor.fetchone()
        if not client:
            print(f"Cannot create registration alert: unknown client {mac}.")
            return False

        cursor.execute(
            """
            INSERT INTO alerts (
                client_id, log_id, alert_type, severity,
                detected_at, activity_time, title, description, status
            ) VALUES (%s, NULL, %s, %s, %s, NULL, %s, %s, 'NEW')
            """,
            (
                client[0],
                alert_type,
                severity,
                registered_at,
                title,
                description,
            ),
        )
        conn.commit()
        print(f"\n[!] ALERT: {title} — {hostname} ({mac})", flush=True)
        return True
    except Exception as error:
        print(f"Error saving registration alert: {error}")
        return False
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


def create_server_alert(mac, alert_type, severity, title, description, detected_at=None):
    """Store and immediately display a server-originated alert."""
    detected_at = detected_at or datetime.datetime.now()
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM clients WHERE mac = %s", (mac,))
        client = cursor.fetchone()
        if not client:
            print(f"Cannot create {alert_type} alert: unknown client {mac}.")
            return False

        cursor.execute(
            """
            INSERT INTO alerts (
                client_id, log_id, alert_type, severity,
                detected_at, activity_time, title, description, status
            ) VALUES (%s, NULL, %s, %s, %s, NULL, %s, %s, 'NEW')
            """,
            (client[0], alert_type, severity, detected_at, title, description),
        )
        conn.commit()
        print(f"\n[!] ALERT: {title} — {mac}", flush=True)
        return True
    except Exception as error:
        print(f"Error saving {alert_type} alert: {error}")
        return False
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


def create_disconnect_alert(client, expected_disconnect):
    hostname = client.get("hostname", "Unknown host")
    ip = client.get("ip", "Unknown IP")
    reason = "at the server's request" if expected_disconnect else "unexpectedly"
    return create_server_alert(
        client["mac"],
        "CLIENT_DISCONNECTED",
        "LOW",
        "Client disconnected",
        f"{hostname} ({client['mac']}, {ip}) disconnected {reason}.",
    )


def create_agent_stopped_alert(client):
    hostname = client.get("hostname", "Unknown host")
    ip = client.get("ip", "Unknown IP")
    return create_server_alert(
        client["mac"],
        "CLIENT_AGENT_STOPPED",
        "HIGH",
        "Client agent stopped",
        (
            f"{hostname} ({client['mac']}, {ip}) remains reachable after its "
            "monitoring-client connection was lost."
        ),
    )


def ping_client(ip):
    """Return whether a client IP responds to one bounded ICMP ping."""
    try:
        address = str(ipaddress.ip_address(ip))
    except ValueError:
        print(f"Cannot ping invalid client IP: {ip!r}")
        return False

    if platform.system() == "Windows":
        command = [
            "ping", "-n", "1", "-w",
            str(DISCONNECT_PING_TIMEOUT_SECONDS * 1000), address,
        ]
    else:
        command = [
            "ping", "-c", "1", "-W",
            str(DISCONNECT_PING_TIMEOUT_SECONDS), address,
        ]

    try:
        return subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=DISCONNECT_PING_TIMEOUT_SECONDS + 1,
            check=False,
        ).returncode == 0
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"Ping check failed for {address}: {error}")
        return False


def verify_client_disconnect(mac, client, check_token):
    """After a grace period, classify an unexpected disconnect once."""
    time.sleep(DISCONNECT_PING_DELAY_SECONDS)

    with clients_lock:
        if pending_disconnect_checks.get(mac) is not check_token:
            return
        if mac in clients:
            pending_disconnect_checks.pop(mac, None)
            return

    reachable = ping_client(client.get("ip", ""))

    with clients_lock:
        # A reconnect may have happened while the ping was running.
        if pending_disconnect_checks.get(mac) is not check_token or mac in clients:
            return
        pending_disconnect_checks.pop(mac, None)

    if reachable:
        create_agent_stopped_alert(client)
    else:
        print(f"Client {mac} is unreachable; keeping disconnect alert informational.")


def _parse_alert_time(value, field_name, *, required=False):
    """Return a database-safe timestamp or raise ValueError."""
    if value is None:
        if required:
            return datetime.datetime.now()
        return None

    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a timestamp string")

    try:
        return datetime.datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError as error:
        raise ValueError(
            f"{field_name} must use YYYY-MM-DD HH:MM:SS"
        ) from error


def handle_client_alert(mac, alert_data):
    """Validate, persist, and display an asynchronous client alert."""
    if not isinstance(alert_data, dict):
        print(f"Rejected malformed alert from {mac}: payload is not an object.")
        return False

    if alert_data.get("alert_type") != "FORBIDDEN_PROCESS":
        print(f"Rejected unsupported alert from {mac}: {alert_data.get('alert_type')!r}")
        return False

    process_name = alert_data.get("process_name")
    if not isinstance(process_name, str) or not process_name.strip():
        print(f"Rejected malformed alert from {mac}: process_name is required.")
        return False

    claimed_severity = alert_data.get("severity")
    if claimed_severity not in ALERT_SEVERITIES:
        print(f"Rejected malformed alert from {mac}: invalid severity.")
        return False

    try:
        detected_at = _parse_alert_time(
            alert_data.get("detected_at"), "detected_at", required=True
        )
        activity_time = _parse_alert_time(
            alert_data.get("activity_time"), "activity_time"
        )
    except ValueError as error:
        print(f"Rejected malformed alert from {mac}: {error}")
        return False

    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT id FROM clients WHERE mac = %s", (mac,))
        row = cursor.fetchone()
        if not row:
            print(f"Rejected alert from unknown client {mac}.")
            return False
        client_db_id = row[0]

        # The database configuration, rather than the client payload, decides
        # whether this process is forbidden and what severity it has.
        cursor.execute(
            """
            SELECT process_name, severity, description
            FROM forbidden_processes
            WHERE process_name = %s AND enabled = TRUE
            """,
            (process_name.strip(),),
        )
        forbidden_process = cursor.fetchone()
        if not forbidden_process:
            print(
                f"Rejected alert from {mac}: {process_name!r} is not an enabled "
                "forbidden process."
            )
            return False

        configured_name, severity, configured_description = forbidden_process
        if severity not in ALERT_SEVERITIES:
            print(f"Rejected alert from {mac}: invalid configured severity {severity!r}.")
            return False

        title = f"Forbidden process detected: {configured_name}"
        description = configured_description or (
            f"Forbidden process '{configured_name}' was detected on the client."
        )
        
        cursor.execute("""
            INSERT INTO alerts (
                client_id, log_id, alert_type, severity, 
                detected_at, activity_time, title, description, status
            ) VALUES (%s, NULL, %s, %s, %s, %s, %s, %s, 'NEW')
        """, (
            client_db_id, 
            "FORBIDDEN_PROCESS",
            severity,
            detected_at,
            activity_time,
            title,
            description,
        ))
        conn.commit()
        print(f"\n[!] ALERT RECEIVED from {mac}: {title}", flush=True)
        return True
    except Exception as e:
        print(f"Error saving alert: {e}")
        return False
    finally:
        if cursor: cursor.close()
        if conn and conn.is_connected(): conn.close()


# ============================================================
# SEND / RECEIVE
# ============================================================

def send_message(conn, message):
    data = json.dumps(message).encode()
    # Prefix with 4-byte big-endian length so the receiver knows exactly how much to read
    conn.sendall(len(data).to_bytes(4, byteorder="big") + data)


def receive_message(conn):
    # Read the 4-byte length header first
    header = b""
    while len(header) < 4:
        chunk = conn.recv(4 - len(header))
        if not chunk:
            return None
        header += chunk

    total = int.from_bytes(header, byteorder="big")

    # Read exactly `total` bytes
    data = b""
    while len(data) < total:
        chunk = conn.recv(min(65536, total - len(data)))
        if not chunk:
            return None
        data += chunk

    return json.loads(data.decode())


# ============================================================
# CONNECTION LOGGING
# ============================================================

def log_connection(mac, status):
    """Log connection or disconnection to the MySQL database."""
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Get client's auto-increment ID
        cursor.execute("SELECT id FROM clients WHERE mac = %s", (mac,))
        row = cursor.fetchone()
        if not row:
            return
        client_db_id = row[0]

        if status in ("connected", "reconnected"):
            cursor.execute('''
                INSERT INTO connections (client_id, connected_at)
                VALUES (%s, CURRENT_TIMESTAMP)
            ''', (client_db_id,))
        elif status == "disconnected":
            # Update the latest open connection for this client
            cursor.execute('''
                UPDATE connections 
                SET disconnected_at = CURRENT_TIMESTAMP 
                WHERE client_id = %s AND disconnected_at IS NULL 
                ORDER BY id DESC LIMIT 1
            ''', (client_db_id,))

        conn.commit()
    except Exception as e:
        print(f"Failed to write connection log: {e}")
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


def update_client_db(mac, client_id, hostname, ip, os_info):
    """Persist/update client metadata in the MySQL database."""
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()

        system = os_info.get("system", str(os_info)) if isinstance(os_info, dict) else str(os_info)
        release = os_info.get("release", "") if isinstance(os_info, dict) else ""
        version = os_info.get("version", "") if isinstance(os_info, dict) else ""
        machine = os_info.get("machine", "") if isinstance(os_info, dict) else ""

        cursor.execute('''
            INSERT INTO clients (client_id, hostname, ip, mac, os_system, os_release, os_version, os_machine)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                client_id=VALUES(client_id),
                hostname=VALUES(hostname),
                ip=VALUES(ip),
                os_system=VALUES(os_system),
                os_release=VALUES(os_release),
                os_version=VALUES(os_version),
                os_machine=VALUES(os_machine),
                updated_at=CURRENT_TIMESTAMP
        ''', (client_id, hostname, ip, mac, system, release, version, machine))

        conn.commit()
    except Exception as e:
        print(f"Failed to update client in DB: {e}")
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


def store_activity_log_file(mac, log_data):
    """
    Store the complete activity log as a JSON file
    and store only its metadata in MySQL.
    """
    if not log_data:
        return

    conn = None
    cursor = None

    try:
        conn = get_connection()
        cursor = conn.cursor()

        # ----------------------------------------------------
        # Find client
        # ----------------------------------------------------
        cursor.execute(
            "SELECT id, client_id FROM clients WHERE mac = %s",
            (mac,)
        )
        row = cursor.fetchone()

        if not row:
            print(f"Cannot store activity log: client {mac} not found.")
            return

        client_db_id = row[0]
        print(f"Storing activity log for client {row[1]} (DB ID: {client_db_id})")
        client_id = row[1]

        # ----------------------------------------------------
        # Store complete log on filesystem
        # ----------------------------------------------------
        file_path = store_log_file(f"client-{client_db_id}", log_data)

        # ----------------------------------------------------
        # Extract metadata
        # ----------------------------------------------------
        period = log_data.get("period")
        generated_at = log_data.get("generated_at")

        # ----------------------------------------------------
        # Store metadata in MySQL
        # ----------------------------------------------------
        cursor.execute(
            """
            INSERT INTO activity_logs (
                client_id,
                file_path,
                period,
                generated_at
            )
            VALUES (%s, %s, %s, %s)
            """,
            (
                client_db_id,
                file_path,
                period,
                generated_at
            )
        )

        conn.commit()

        print(
            f"\nActivity log stored:"
            f"\n  File: {file_path}"
            f"\n  Period: {period}"
        )

    except Exception as error:
        if conn:
            conn.rollback()
        print(f"Failed to store activity log: {error}")

    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


# ============================================================
# CLIENT REGISTRY
# ============================================================

def register_client(client_info, conn):
    global next_client_id

    mac = client_info["mac"]

    with clients_lock:
        # A registration during the grace period cancels the pending agent
        # verification for the previous connection.
        pending_disconnect_checks.pop(mac, None)

        # ---- Reconnecting client ----
        if mac in clients:
            client = clients[mac]
            client["hostname"]   = client_info["hostname"]
            client["ip"]         = client_info["ip"]
            client["os"]         = client_info["os"]
            client["connection"] = conn
            client["responses"]  = queue.Queue()
            client["send_lock"]  = threading.Lock()

            print(f"Client reconnected: {client['client_id']}")
            update_client_db(mac, client["client_id"], client_info["hostname"], client_info["ip"], client_info["os"])
            log_connection(mac, "reconnected")
            create_connection_alert(client_info)
            return client["client_id"]

        # ---- New client ----
        client_id = f"client-{next_client_id}"
        next_client_id += 1

        clients[mac] = {
            "client_id":  client_id,
            "hostname":   client_info["hostname"],
            "ip":         client_info["ip"],
            "mac":        mac,
            "os":         client_info["os"],
            "connection": conn,
            "responses": queue.Queue(),
            "send_lock": threading.Lock(),
        }

        print(f"New client connected: {client_id}")
        update_client_db(mac, client_id, client_info["hostname"], client_info["ip"], client_info["os"])
        log_connection(mac, "connected")
        create_connection_alert(client_info)
        return client_id


def get_client(client_id):
    with clients_lock:
        for client in clients.values():
            if client["client_id"] == client_id:
                return client
    return None


def get_client_by_mac(mac):
    with clients_lock:
        return clients.get(mac)


def remove_client(mac, connection=None):
    with clients_lock:
        client = clients.get(mac)
        if connection is not None and client and client["connection"] is not connection:
            return
        client = clients.pop(mac, None)
        if client:
            expected_disconnect = client.get("disconnect_expected", False)
            check_token = None
            if not expected_disconnect:
                check_token = object()
                pending_disconnect_checks[mac] = check_token

    if client:
        # Wake a command that is waiting for a response before closing the
        # connection.  Queueing this sentinel is safe even when nobody waits.
        client["responses"].put({"type": "DISCONNECTED"})
        try:
            client["connection"].close()
        except OSError:
            pass

        print(f"Removed {client['client_id']}")
        log_connection(mac, "disconnected")
        create_disconnect_alert(client, expected_disconnect)

        if check_token is not None:
            threading.Thread(
                target=verify_client_disconnect,
                args=(mac, client.copy(), check_token),
                daemon=True,
            ).start()


def receive_client_messages(mac, conn):
    """Continuously consume one client's frames after registration.

    A TCP connection can receive alerts at any time.  This is deliberately the
    only post-registration reader for the connection; command handlers consume
    responses from the per-client queue below instead of calling recv().
    """
    try:
        while True:
            message = receive_message(conn)
            if message is None:
                print(f"Client {mac} disconnected.")
                return

            message_type = message.get("type") if isinstance(message, dict) else None
            if message_type == "ALERT":
                handle_client_alert(mac, message.get("alert"))
            elif message_type == "RESPONSE":
                client = get_client_by_mac(mac)
                if client and client["connection"] is conn:
                    client["responses"].put(message)
            else:
                print(f"Unexpected message from {mac}: {message_type!r}")
    except (ConnectionResetError, BrokenPipeError, OSError, json.JSONDecodeError) as error:
        print(f"Connection with client {mac} lost: {error}")
    finally:
        remove_client(mac, conn)


# ============================================================
# DISPLAY HELPERS
# ============================================================

def show_clients():
    print("\n==============================================")
    print("              CONNECTED CLIENTS")
    print("==============================================")

    with clients_lock:
        if not clients:
            print("No clients connected.")
            return

        for client in clients.values():
            print(f"\n{client['client_id']}")
            print(f"  Hostname : {client['hostname']}")
            print(f"  IP       : {client['ip']}")
            print(f"  MAC      : {client['mac']}")

            os_info = client["os"]
            if isinstance(os_info, dict):
                os_display = f"{os_info.get('system', 'Unknown')} {os_info.get('release', '')}".strip()
            else:
                os_display = str(os_info)

            print(f"  OS       : {os_display}")


def print_response(client_id, command, response):
    """Pretty-print a client response depending on the command type."""
    print("\nResponse:")

    if command == "GET_NETWORK_LOG" and response.get("type") == "RESPONSE":
        logs_list = response.get("data", {}).get("logs", [])
        print(f"\n{'='*64}")
        print("  CLIENT NETWORK CONNECTION LOG")
        print(f"{'='*64}")
        for entry in logs_list:
            print(f"  {entry}")
        print(f"{'='*64}")

    elif command == "GET_ACTIVITY_LOG" and response.get("type") == "RESPONSE":
        log_data = response.get("data", {})

        client = get_client(client_id)
        if client:
            store_activity_log_file(
                client["mac"],
                log_data
            )

    else:
        print(json.dumps(response, indent=4))


# ============================================================
# SEND COMMAND TO CLIENT
# ============================================================

def send_command(client_id, command, args=None):
    client = get_client(client_id)

    if not client:
        print("Client not found.")
        return

    conn = client["connection"]

    message = {"type": "COMMAND", "command": command}
    if args is not None:
        message["args"] = args

    try:
        # receive_client_messages() is the sole reader for this socket.  It
        # places command responses in this queue and handles ALERT frames
        # immediately, even while the server is waiting at its menu prompt.
        with client["send_lock"]:
            if command == "DISCONNECT":
                # The client was asked to leave, so its later TCP close must
                # not be interpreted as a stopped/crashed agent.
                with clients_lock:
                    current_client = clients.get(client["mac"])
                    if current_client is client and client["connection"] is conn:
                        client["disconnect_expected"] = True
            send_message(conn, message)

        while True:
            response = client["responses"].get()

            if response.get("type") == "DISCONNECTED":
                print("Client disconnected.")
                return

            # The server menu sends one command at a time, but keeping this
            # check prevents a stale response from being presented as another
            # command's result.
            if response.get("command") != command:
                print(
                    f"Ignoring unexpected response for "
                    f"{response.get('command')!r}."
                )
                continue

            print_response(client_id, command, response)
            break

    except (ConnectionResetError, BrokenPipeError, OSError):
        print("Connection with client lost.")
        remove_client(client["mac"], conn)


# ============================================================
# MENUS
# ============================================================

def client_menu(client_id):
    while True:
        client = get_client(client_id)

        if not client:
            print("Client is no longer connected.")
            return

        print("\n==============================================")
        print(f"              {client_id}")
        print("==============================================")
        print("1.  System information")
        print("2.  Network information")
        print("3.  CPU information")
        print("4.  Memory information")
        print("5.  Disk information")
        print("6.  Processes")
        print("7.  Ping")
        print("8.  Kill process")
        print("9.  Start process")
        print("10. Network connection log")
        print("11. Activity log")
        print("12. Disconnect client")
        print("13. Back")

        choice = input("\nSelect command: ").strip()

        commands = {
            "1":  "GET_SYSTEM_INFO",
            "2":  "GET_NETWORK_INFO",
            "3":  "GET_CPU_INFO",
            "4":  "GET_MEMORY_INFO",
            "5":  "GET_DISK_INFO",
            "6":  "GET_PROCESSES",
            "7":  "PING",
            "8":  "KILL_PROCESS",
            "9":  "START_PROCESS",
            "10": "GET_NETWORK_LOG",
            "11": "GET_ACTIVITY_LOG",
            "12": "DISCONNECT"
        }

        if choice == "13":
            break

        command = commands.get(choice)

        if not command:
            print("Invalid option.")
            continue

        args = None
        if command == "KILL_PROCESS":
            args = input("Enter process name to kill: ").strip()
            if not args:
                print("Process name cannot be empty.")
                continue

        elif command == "GET_ACTIVITY_LOG":
            print("\nTime period:")
            print("  1. Last 24 hours")
            print("  2. Last week")
            print("  3. Last month")
            period_choice = input("Select period: ").strip()
            period_map = {"1": "1d", "2": "1w", "3": "1m"}
            args = period_map.get(period_choice)
            if not args:
                print("Invalid period, defaulting to last 24 hours.")
                args = "1d"

        elif command == "START_PROCESS":
            args = input("Enter absolute path to start: ").strip()
            if not args:
                print("Process path cannot be empty.")
                continue

        send_command(client_id, command, args)

        if command == "DISCONNECT":
            remove_client(client["mac"])
            break


def server_menu():
    while True:
        print("\n==============================================")
        print("                 SERVER")
        print("==============================================")
        print("1. List connected clients")
        print("2. Select client")
        print("3. Exit")

        choice = input("\nSelect option: ").strip()

        if choice == "1":
            show_clients()

        elif choice == "2":
            show_clients()
            client_id = input("\nEnter client ID: ").strip()
            client = get_client(client_id)

            if client:
                client_menu(client_id)
            else:
                print("Client not found.")

        elif choice == "3":
            print("Server shutting down.")
            with clients_lock:
                for client in list(clients.values()):
                    try:
                        client["connection"].close()
                    except Exception:
                        pass
            os._exit(0)

        else:
            print("Invalid option.")
