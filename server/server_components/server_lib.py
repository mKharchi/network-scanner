import datetime
import json
import os
import threading

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

def handle_client_alert(mac, alert_data):
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT id FROM clients WHERE mac = %s", (mac,))
        row = cursor.fetchone()
        if not row:
            return
        client_db_id = row[0]
        
        cursor.execute("""
            INSERT INTO alerts (
                client_id, log_id, alert_type, severity, 
                detected_at, activity_time, title, description, status
            ) VALUES (%s, NULL, %s, %s, %s, %s, %s, %s, 'NEW')
        """, (
            client_db_id, 
            alert_data.get("alert_type"), 
            alert_data.get("severity", "MEDIUM"), 
            alert_data.get("detected_at"), 
            alert_data.get("activity_time"), 
            alert_data.get("title"), 
            alert_data.get("description")
        ))
        conn.commit()
        print(f"\n[!] ALERT RECEIVED from {mac}: {alert_data.get('title')}")
    except Exception as e:
        print(f"Error saving alert: {e}")
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
        # ---- Reconnecting client ----
        if mac in clients:
            client = clients[mac]
            client["hostname"]   = client_info["hostname"]
            client["ip"]         = client_info["ip"]
            client["os"]         = client_info["os"]
            client["connection"] = conn

            print(f"Client reconnected: {client['client_id']}")
            update_client_db(mac, client["client_id"], client_info["hostname"], client_info["ip"], client_info["os"])
            log_connection(mac, "reconnected")
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
            "connection": conn
        }

        print(f"New client connected: {client_id}")
        update_client_db(mac, client_id, client_info["hostname"], client_info["ip"], client_info["os"])
        log_connection(mac, "connected")
        return client_id


def get_client(client_id):
    with clients_lock:
        for client in clients.values():
            if client["client_id"] == client_id:
                return client
    return None


def remove_client(mac):
    with clients_lock:
        client = clients.pop(mac, None)

    if client:
        try:
            client["connection"].close()
        except OSError:
            pass

        print(f"Removed {client['client_id']}")
        log_connection(mac, "disconnected")


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

        entries = log_data.get("activity", [])

        print(f"\n{'='*66}")
        print(f"  USER ACTIVITY LOG  |  since: {log_data.get('since', '?')}")
        print(f"{'='*66}")

        if not entries:
            print("  No activity found.")
        else:
            current_type = None
            for entry in entries:
                if entry["type"] != current_type:
                    current_type = entry["type"]
                    print(f"\n  ── {current_type} ──")

                timestamp = (
                    entry["time"]
                    if entry["time"] != "Unknown"
                    else "(no timestamp)"
                )
                print(f"  [{timestamp}]  {entry['detail']}")

        print(f"{'='*66}")

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
        send_message(conn, message)

        while True:
            response = receive_message(conn)

            if response is None:
                print("Client disconnected.")
                remove_client(client["mac"])
                return
                
            if response.get("type") == "ALERT":
                handle_client_alert(client["mac"], response.get("alert", {}))
            else:
                break

        print_response(client_id, command, response)

    except (ConnectionResetError, BrokenPipeError, OSError):
        print("Connection with client lost.")
        remove_client(client["mac"])


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
