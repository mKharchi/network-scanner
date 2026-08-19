import json
import os
import socket

from client_lib import (
    create_registration_message,
    handle_command,
    receive_message,
    send_message,
    get_activity_log,
    get_mac,
)
from process_scanner import scan_for_forbidden_processes
from network_neighbour_collector import NetworkNeighbourCollector
from dhcp_listener import DHCPListener
import threading
import time
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

SERVER_IP = os.getenv("SERVER_IP", "127.0.0.1")
SERVER_PORT = int(os.getenv("SERVER_PORT", "5000"))
ALERT_STATE_FILE = os.path.join(os.path.dirname(__file__), "reported_alerts.json")
NEIGHBOUR_SNAPSHOT_STATE_FILE = os.path.join(
    os.path.dirname(__file__), "neighbour_snapshot_state.json"
)

socket_lock = threading.Lock()
scanner_lock = threading.Lock()
network_scan_lock = threading.Lock()
network_scan_state_lock = threading.Lock()
active_network_scan_global_id = None
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


def _local_date():
    return datetime.now().astimezone().date().isoformat()


def _snapshot_client_mac():
    """Return the local client identity used to scope persisted snapshot state."""
    try:
        return get_mac().upper()
    except Exception:
        return None


def _load_neighbour_snapshot_state():
    try:
        with open(NEIGHBOUR_SNAPSHOT_STATE_FILE, "r", encoding="utf-8") as state_file:
            state = json.load(state_file)
        return state if isinstance(state, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_neighbour_snapshot_state(snapshot_date, client_mac):
    try:
        with open(NEIGHBOUR_SNAPSHOT_STATE_FILE, "w", encoding="utf-8") as state_file:
            json.dump(
                {
                    "last_snapshot_date": snapshot_date,
                    "client_mac": client_mac,
                },
                state_file,
            )
    except OSError as error:
        print(f"Could not save neighbour snapshot state: {error}")


def send_daily_network_neighbours(client_socket):
    """Report one full neighbour snapshot at most once per local calendar day.

    This only reads the OS neighbour/ARP table. It does not send ICMP packets
    or cause the server to perform any network discovery.
    """
    snapshot_date = _local_date()
    client_mac = _snapshot_client_mac()
    state = _load_neighbour_snapshot_state()
    if (
        client_mac
        and state.get("last_snapshot_date") == snapshot_date
        and state.get("client_mac") == client_mac
    ):
        print("Today's network neighbour snapshot was already reported.")
        return False

    neighbours = NetworkNeighbourCollector().collect(enrich=True, active_scan=False)
    message = {
        "type": "NETWORK_NEIGHBOURS",
        "data": {
            "observation_source": "DAILY_NEIGHBOUR_SNAPSHOT",
            "observed_at": datetime.now().astimezone().isoformat(),
            "neighbours": neighbours,
        },
    }
    try:
        with socket_lock:
            send_message(client_socket, message)
        _save_neighbour_snapshot_state(snapshot_date, client_mac)
        print(f"Reported {len(neighbours)} network neighbour entries.")
        return True
    except OSError as error:
        print(f"Could not report network neighbours: {error}")
        return False


def send_active_network_neighbours(client_socket, *, lock_held=False, global_scan_id=None):
    """Run an active ARP scan without blocking the client command loop."""
    global active_network_scan_global_id
    if not lock_held and not network_scan_lock.acquire(blocking=False):
        print("Active network scan is already running.")
        return False

    try:
        print("Active network scan started in the background.")
        neighbours = NetworkNeighbourCollector().collect(enrich=True, active_scan=True)
        message = {
            "type": "NETWORK_NEIGHBOURS",
            "data": {
                "observation_source": "ACTIVE_NEIGHBOUR_SCAN",
                "observed_at": datetime.now().astimezone().isoformat(),
                "neighbours": neighbours,
            },
        }
        if global_scan_id:
            message["data"]["global_scan_id"] = global_scan_id
        with socket_lock:
            send_message(client_socket, message)
        print(f"Reported {len(neighbours)} active network neighbour entries.")
        return True
    except OSError as error:
        print(f"Could not report active network neighbours: {error}")
        return False
    except Exception as error:
        print(f"Active network scan failed: {error}")
        if global_scan_id:
            try:
                with socket_lock:
                    send_message(
                        client_socket,
                        {
                            "type": "NETWORK_NEIGHBOURS",
                            "data": {
                                "observation_source": "ACTIVE_NEIGHBOUR_SCAN",
                                "observed_at": datetime.now().astimezone().isoformat(),
                                "global_scan_id": global_scan_id,
                                "scan_status": "failed",
                                "scan_error": str(error)[:255],
                                "neighbours": [],
                            },
                        },
                    )
            except OSError:
                pass
        return False
    finally:
        with network_scan_state_lock:
            active_network_scan_global_id = None
        network_scan_lock.release()


def start_active_network_scan(client_socket, *, global_scan_id=None):
    """Start one background ARP scan, returning its status and correlation ID."""
    global active_network_scan_global_id
    if not network_scan_lock.acquire(blocking=False):
        print("Active network scan is already running.")
        with network_scan_state_lock:
            return False, active_network_scan_global_id

    with network_scan_state_lock:
        active_network_scan_global_id = global_scan_id

    threading.Thread(
        target=send_active_network_neighbours,
        args=(client_socket,),
        kwargs={"lock_held": True, "global_scan_id": global_scan_id},
        daemon=True,
    ).start()
    return True, global_scan_id


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
        send_message(client, create_registration_message(client.getsockname()[0]))
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
                    send_message(
                        client,
                        {"type": "REQUEST", "command": "GET_FORBIDDEN_PROCESSES"},
                    )
                continue

            if msg_type == "FORBIDDEN_PROCESSES":
                global forbidden_processes
                forbidden_processes = message.get("data", [])
                print(f"Received {len(forbidden_processes)} forbidden processes.")

                # Start background daily neighbour snapshot collection so it never blocks command execution
                threading.Thread(
                    target=send_daily_network_neighbours,
                    args=(client,),
                    daemon=True,
                ).start()

                # Start background scanner
                t = threading.Thread(
                    target=background_scanner,
                    args=(client,),
                    daemon=True,
                )
                t.start()

                # Start passive DHCP listener (idempotent)
                try:
                    if (
                        "_dhcp_listener" not in globals()
                        or globals().get("_dhcp_listener") is None
                    ):

                        def _on_dhcp_obs(obs):
                            neighbour = {}
                            if obs.get("requested_ip"):
                                neighbour["ip_address"] = obs.get("requested_ip")
                            if obs.get("mac_address"):
                                neighbour["mac_address"] = obs.get("mac_address")
                                try:
                                    import oui
                                    oui_db = oui.load_oui_database()
                                    vendor_name = oui.get_vendor(obs.get("mac_address"), oui_db)
                                    if vendor_name:
                                        neighbour["vendor"] = vendor_name
                                except Exception:
                                    pass
                            neighbour["entry_type"] = "dynamic"
                            if obs.get("hostname"):
                                neighbour["hostname"] = obs.get("hostname")
                            if obs.get("vendor_class"):
                                neighbour["dhcp_vendor_class"] = obs.get("vendor_class")
                            if obs.get("client_id"):
                                neighbour["dhcp_client_id"] = obs.get("client_id")
                            if obs.get("dhcp_message_type") is not None:
                                neighbour["dhcp_message_type"] = obs.get(
                                    "dhcp_message_type"
                                )

                            if not neighbour.get("mac_address") or not neighbour.get("ip_address"):
                                return

                            # Send the immediate one-device report in the
                            # protocol the server already accepts.
                            msg = {
                                "type": "NETWORK_NEIGHBOURS",
                                "data": {
                                    # Preserve the capture source for the
                                    # server's daily DHCP observation log.
                                    "observation_source": "DHCP",
                                    "observed_at": datetime.now()
                                    .astimezone()
                                    .isoformat(),
                                    "neighbours": [neighbour],
                                    "dhcp": {
                                        "message_type": obs.get(
                                            "dhcp_message_type"
                                        ),
                                        "vendor_class": obs.get("vendor_class"),
                                        "client_id": obs.get("client_id"),
                                    },
                                },
                            }
                            try:
                                with socket_lock:
                                    send_message(client, msg)
                                print(
                                    f"Sent DHCP neighbour update: {neighbour.get('mac_address')} ({neighbour.get('ip_address')})"
                                )
                            except Exception as e:
                                print(f"[DHCP] Failed to send neighbour update: {e}")

                        # Auto-detect active network interface for sniffing
                        detected_iface = None
                        try:
                            from network_neighbour_collector import get_local_network
                            local_net = get_local_network()
                            if local_net:
                                detected_iface = local_net.get("interface")
                        except Exception:
                            pass

                        listen_iface = os.getenv("DHCP_LISTEN_INTERFACE") or detected_iface
                        _dhcp_listener = DHCPListener(
                            _on_dhcp_obs,
                            interface=listen_iface,
                        )
                        _dhcp_listener.start()
                        globals()["_dhcp_listener"] = _dhcp_listener
                except Exception as e:
                    print(f"[DHCP] Could not start listener: {e}")
                continue

            if msg_type != "COMMAND":
                print("Invalid message from server.")
                continue

            command = message.get("command")

            if not command:
                print("Command missing.")
                continue

            print(f"Command received: {command}")

            if command in ("SCAN_NETWORK", "TRIGGER_ARP_SCAN"):
                args = message.get("args")
                global_scan_id = (
                    args.get("global_scan_id")
                    if isinstance(args, dict) and isinstance(args.get("global_scan_id"), str)
                    else None
                )
                started, active_global_scan_id = start_active_network_scan(
                    client, global_scan_id=global_scan_id
                )
                result = {
                    "status": "started" if started else "already_running",
                    "message": (
                        "Active network scan started in the background."
                        if started
                        else "An active network scan is already running."
                    ),
                    "global_scan_id": active_global_scan_id,
                }
            else:
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
                send_message(
                    client, {"type": "RESPONSE", "command": command, "data": result}
                )

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
