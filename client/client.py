import json
import os
import socket

from client_lib import (
    create_registration_message,
    handle_command,
    receive_message,
    send_message,
    get_activity_log,
)
from process_scanner import scan_for_forbidden_processes
from network_neighbour_collector import NetworkNeighbourCollector
import threading
import time
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

SERVER_IP = os.getenv("SERVER_IP", "127.0.0.1")
SERVER_PORT = int(os.getenv("SERVER_PORT", "5000"))
ALERT_STATE_FILE = os.path.join(os.path.dirname(__file__), "reported_alerts.json")

socket_lock = threading.Lock()
scanner_lock = threading.Lock()
forbidden_processes = []


def load_reported_alerts():
    """Restore a bounded local deduplication state from the previous run."""
    try:
        with open(ALERT_STATE_FILE, "r", encoding="utf-8") as state_file:
            alert_ids = json.load(state_file)
        if isinstance(alert_ids, list):
            return set(alert_id for alert_id in alert_ids if isinstance(alert_id, str))
    except (OSError, json.JSONDecodeError):
        pass
    return set()


def save_reported_alerts(alert_ids):
    """Persist only the recent alert IDs; never retain an unbounded history."""
    try:
        with open(ALERT_STATE_FILE, "w", encoding="utf-8") as state_file:
            json.dump(sorted(alert_ids), state_file)
    except OSError as error:
        print(f"Could not save alert deduplication state: {error}")


reported_alerts = load_reported_alerts()


def send_network_neighbours(client_socket):
    """Report one local neighbour-cache snapshot through the registered socket."""
    neighbours = NetworkNeighbourCollector().collect()
    message = {
        "type": "NETWORK_NEIGHBOURS",
        "data": {
            "observed_at": datetime.now().astimezone().isoformat(),
            "neighbours": neighbours,
        },
    }
    try:
        with socket_lock:
            send_message(client_socket, message)
        print(f"Reported {len(neighbours)} network neighbour entries.")
    except OSError as error:
        print(f"Could not report network neighbours: {error}")


def scan_activity_log(log_data):
    """Create alerts for one collected activity log without duplicating events."""
    global reported_alerts

    with scanner_lock:
        new_alerts, reported_alerts = scan_for_forbidden_processes(
            log_data, forbidden_processes, reported_alerts
        )
        save_reported_alerts(reported_alerts)

    detected_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for alert in new_alerts:
        alert["detected_at"] = detected_at

    return [{"type": "ALERT", "alert": alert} for alert in new_alerts]


def send_alerts(client_socket, alerts, source):
    """Send alert frames before the command response, preserving frame order."""
    if not alerts:
        return

    with socket_lock:
        for alert in alerts:
            try:
                send_message(client_socket, alert)
                print(f"Sent ALERT ({source}): {alert['alert']['title']}")
            except OSError as error:
                print(f"Failed to send alert ({source}): {error}")
                return


def background_scanner(client_socket):
    time.sleep(10)
    
    while True:
        try:
            print("Background scanner running...")
            # Generate 1h activity log
            log_data = get_activity_log("1h")
            with open("hourly_log.json", "w") as f:
                json.dump(log_data, f)
                
            alerts = scan_activity_log(log_data)
            print(f"Background scanner found {len(alerts)} new alerts.")
            send_alerts(client_socket, alerts, "hourly scan")

        except Exception as e:
            print(f"Background scanner error: {e}")
            
        time.sleep(3600)

# ============================================================
# CLIENT
# ============================================================

def start_client():
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    try:
        client.connect((SERVER_IP, SERVER_PORT))
    except OSError as error:
        print(f"Could not connect to server: {error}")
        return

    print(f"Connected to server {SERVER_IP}:{SERVER_PORT}")

    # --------------------------------------------------------
    # Register
    # --------------------------------------------------------
    with socket_lock:
        send_message(client, create_registration_message())
    print("Registration sent.")

    # --------------------------------------------------------
    # Wait for commands
    # --------------------------------------------------------
    while True:
        try:
            message = receive_message(client)

            if message is None:
                print("Server disconnected.")
                break

            msg_type = message.get("type")

            # Silently acknowledge registration confirmation
            if msg_type == "REGISTERED":
                with socket_lock:
                    send_message(client, {"type": "REQUEST", "command": "GET_FORBIDDEN_PROCESSES"})
                continue

            if msg_type == "FORBIDDEN_PROCESSES":
                global forbidden_processes
                forbidden_processes = message.get("data", [])
                print(f"Received {len(forbidden_processes)} forbidden processes.")

                # Milestone 1 sends one authenticated snapshot after initial
                # registration. Periodic reporting is a later scheduling task.
                send_network_neighbours(client)
                
                # Start background scanner
                t = threading.Thread(
                    target=background_scanner,
                    args=(client,),
                    daemon=True,
                )
                t.start()
                continue

            if msg_type != "COMMAND":
                print("Invalid message from server.")
                continue

            command = message.get("command")

            if not command:
                print("Command missing.")
                continue

            print(f"Command received: {command}")

            result = handle_command(message)

            # A server-requested activity log (including the standard 24-hour
            # request) is another detection opportunity.  Send any resulting
            # alerts before the response containing the full log.
            if command == "GET_ACTIVITY_LOG" and isinstance(result, dict):
                alerts = scan_activity_log(result)
                print(
                    f"Activity-log scan ({result.get('period', 'unknown')}) "
                    f"found {len(alerts)} new alerts."
                )
                send_alerts(client, alerts, "server-requested activity log")

            with socket_lock:
                send_message(client, {
                    "type":    "RESPONSE",
                    "command": command,
                    "data":    result
                })

            print("Response sent.")

            if command == "DISCONNECT":
                break

        except json.JSONDecodeError:
            print("Received invalid JSON.")

        except (ConnectionResetError, BrokenPipeError, OSError):
            print("Connection with server lost.")
            break

    client.close()
    print("Client stopped.")


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    start_client()
