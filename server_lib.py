import datetime
import json
import os
import threading

LOG_FILE = "client_connections.json"

# ============================================================
# SHARED STATE
# ============================================================

clients = {}
clients_lock = threading.Lock()
next_client_id = 1


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

def log_connection(mac, hostname, ip, status):
    """
    Persist a connection event (connected / reconnected / disconnected)
    to a local JSON file, keyed by MAC address.
    """
    log_entry = {
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "hostname":  hostname,
        "ip":        ip,
        "status":    status
    }

    try:
        data = json.load(open(LOG_FILE)) if os.path.exists(LOG_FILE) else {}
    except Exception:
        data = {}

    data.setdefault(mac, []).append(log_entry)
    data[mac] = data[mac][-50:]   # keep last 50 entries per device

    try:
        with open(LOG_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Failed to write connection log: {e}")


def get_connection_logs(mac):
    """Return the stored connection log entries for a given MAC."""
    try:
        if os.path.exists(LOG_FILE):
            data = json.load(open(LOG_FILE))
            return data.get(mac, [])
    except Exception:
        pass
    return []


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
            log_connection(mac, client_info["hostname"], client_info["ip"], "reconnected")
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
        log_connection(mac, client_info["hostname"], client_info["ip"], "connected")
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
        log_connection(mac, client["hostname"], client["ip"], "disconnected")


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


def print_response(command, response):
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
        entries = response.get("data", {}).get("activity", [])
        print(f"\n{'='*66}")
        print(f"  USER ACTIVITY LOG  |  since: {response.get('data', {}).get('since', '?')}")
        print(f"{'='*66}")
        if not entries:
            print("  No activity found.")
        else:
            current_type = None
            for e in entries:
                if e["type"] != current_type:
                    current_type = e["type"]
                    print(f"\n  ── {current_type} ──")
                ts = e["time"] if e["time"] != "Unknown" else "(no timestamp)"
                print(f"  [{ts}]  {e['detail']}")
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

        response = receive_message(conn)

        if response is None:
            print("Client disconnected.")
            remove_client(client["mac"])
            return

        print_response(command, response)

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
