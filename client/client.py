import json
import os
import socket
from pathlib import Path

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
from neighbourhood import (
    get_daily_neighbourhood_path,
    load_daily_neighbourhood,
    normalise_dhcp_observation,
    update_daily_neighbourhood,
)
import threading
import time
from datetime import datetime
from dotenv import load_dotenv

CLIENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = CLIENT_DIR.parent


def _load_env_file(path):
    try:
        load_dotenv(path)
    except TypeError:
        load_dotenv()


_load_env_file(REPO_ROOT / ".env")
_load_env_file(CLIENT_DIR / ".env")

SERVER_IP = os.getenv("SERVER_IP", "127.0.0.1")
SERVER_PORT = int(os.getenv("SERVER_PORT", "5000"))
ALERT_STATE_FILE = os.path.join(os.path.dirname(__file__), "reported_alerts.json")
NEIGHBOUR_SNAPSHOT_STATE_FILE = os.path.join(
    os.path.dirname(__file__), "neighbour_snapshot_state.json"
)
STARTUP_LOG_FILE = CLIENT_DIR / "client_service.log"

socket_lock = threading.Lock()
scanner_lock = threading.Lock()
network_scan_lock = threading.Lock()
network_scan_state_lock = threading.Lock()
active_network_scan_global_id = None
forbidden_processes = []


class _StopEventProxy:
    """Combine the global shutdown event with a per-session event."""

    def __init__(self, *events):
        self._events = events

    def is_set(self):
        return any(event is not None and event.is_set() for event in self._events)


def disabled_active_network_scan_result(command):
    """Return the compatibility response for retired on-demand ARP scans.

    The active-scan implementation is intentionally retained below for a
    future feature, but normal client operation must only use passive
    neighbour-table and DHCP collection.
    """
    return {
        "status": "disabled",
        "message": (
            f"Command '{command}' is disabled: active ARP scanning is not part "
            "of the current neighbourhood-collection workflow."
        ),
    }


def _scan_log(message):
    """Emit scan lifecycle telemetry without printing device tables."""
    print(f"[CLIENT NETWORK SCAN] {message}", flush=True)


def _startup_log(message):
    """Persist startup/connectivity messages for Windows service troubleshooting."""
    line = f"{datetime.now().astimezone().isoformat()} {message}\n"
    try:
        with open(STARTUP_LOG_FILE, "a", encoding="utf-8") as log_file:
            log_file.write(line)
    except OSError:
        pass
    print(f"[CLIENT STARTUP] {message}", flush=True)


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


def collect_daily_network_neighbours():
    """Collect one passive snapshot and save it to today's local file.

    This only reads the OS neighbour/ARP table. It neither performs active
    network discovery nor reports a neighbourhood frame to the server.
    """
    snapshot_date = _local_date()
    client_mac = _snapshot_client_mac()
    snapshot_path = get_daily_neighbourhood_path(date=snapshot_date)
    _scan_log(
        f"Daily neighbour snapshot check: client_mac={client_mac or 'unknown'} date={snapshot_date}."
    )
    state = _load_neighbour_snapshot_state()
    if (
        client_mac
        and state.get("last_snapshot_date") == snapshot_date
        and state.get("client_mac") == client_mac
        and snapshot_path.exists()
    ):
        print("Today's local network neighbour snapshot was already collected.")
        return False

    started_at = time.monotonic()
    _scan_log("Daily neighbour snapshot collection started (passive cache only).")
    neighbours = NetworkNeighbourCollector().collect(enrich=True, active_scan=False)
    _scan_log(
        f"Daily neighbour snapshot collection completed: devices={len(neighbours)} "
        f"elapsed={time.monotonic() - started_at:.1f}s."
    )
    try:
        file_path, payload = update_daily_neighbourhood(neighbours, date=snapshot_date)
        _save_neighbour_snapshot_state(snapshot_date, client_mac)
        _scan_log(
            f"Daily snapshot stored: file={file_path} reporter={client_mac or 'unknown'} "
            f"observations={len(payload['observations'])}."
        )
        return True
    except (OSError, ValueError) as error:
        print(f"Could not store local network neighbours: {error}")
        return False


def send_daily_network_neighbours(_client_socket=None):
    """Compatibility wrapper for the former daily-report entry point.

    Normal collection is permanently local-only. Stored observations are sent
    only after registration or when the server explicitly requests them.
    """
    return collect_daily_network_neighbours()


def send_stored_daily_neighbourhood(client_socket):
    """Send today's accumulated local neighbourhood after registration.

    Loading the local file never triggers collection or an active scan.  A
    missing file is represented by an empty, valid daily snapshot so initial
    registration remains safe for new clients.
    """
    snapshot_date = _local_date()
    snapshot_path = get_daily_neighbourhood_path(date=snapshot_date)
    if not snapshot_path.exists():
        _scan_log(
            "Daily neighbourhood file was missing; collecting a passive "
            "snapshot before registration synchronization."
        )
        collect_daily_network_neighbours()
    try:
        payload = load_daily_neighbourhood(date=snapshot_date)
    except (OSError, ValueError) as error:
        print(
            f"Could not load local network neighbourhood for synchronization: {error}"
        )
        return False

    neighbours = payload["observations"]
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
        _scan_log(
            f"Stored daily neighbourhood synchronized: date={snapshot_date} "
            f"observations={len(neighbours)}."
        )
        return True
    except OSError as error:
        print(f"Could not synchronize local network neighbourhood: {error}")
        return False


def send_requested_network_neighbourhood(client_socket):
    """Send today's stored neighbourhood in response to a server command.

    This is intentionally a file read only.  It never performs passive table
    collection or active probing while the server is waiting for a response.
    """
    snapshot_date = _local_date()
    try:
        payload = load_daily_neighbourhood(date=snapshot_date)
    except (OSError, ValueError) as error:
        return {
            "status": "error",
            "message": f"Could not load local network neighbourhood: {error}",
        }

    neighbours = payload["observations"]
    try:
        with socket_lock:
            send_message(
                client_socket,
                {
                    "type": "NETWORK_NEIGHBOURS",
                    "data": {
                        "observation_source": "REQUESTED_NEIGHBOURHOOD",
                        "observed_at": datetime.now().astimezone().isoformat(),
                        "neighbours": neighbours,
                    },
                },
            )
        _scan_log(
            f"Requested daily neighbourhood sent: date={snapshot_date} "
            f"observations={len(neighbours)}."
        )
        return {"status": "ok", "observations_sent": len(neighbours)}
    except OSError as error:
        return {
            "status": "error",
            "message": f"Could not send local network neighbourhood: {error}",
        }


def _complete_requested_neighbourhood_command(client_socket):
    """Send one stored report and its response without blocking the receive loop."""
    result = send_requested_network_neighbourhood(client_socket)
    try:
        with socket_lock:
            send_message(
                client_socket,
                {
                    "type": "RESPONSE",
                    "command": "GET_NETWORK_NEIGHBOURHOOD",
                    "data": result,
                },
            )
        _scan_log("Requested neighbourhood command response sent.")
    except OSError as error:
        _scan_log(f"Requested neighbourhood command response failed: {error}")


def start_requested_neighbourhood_command(client_socket):
    """Run a stored-neighbourhood request in the background."""
    worker = threading.Thread(
        target=_complete_requested_neighbourhood_command,
        args=(client_socket,),
        daemon=True,
        name="requested-neighbourhood-report",
    )
    worker.start()
    return worker


def _lookup_dhcp_vendor(mac_address):
    if not mac_address:
        return None
    try:
        import oui

        oui_db = oui.load_oui_database()
        return oui.get_vendor(mac_address, oui_db)
    except Exception:
        return None


def store_dhcp_neighbourhood_observation(observation):
    """Normalize and save a DHCP discovery without immediately reporting it."""
    if not isinstance(observation, dict):
        return None
    neighbour = normalise_dhcp_observation(
        observation,
        vendor=_lookup_dhcp_vendor(observation.get("mac_address")),
        observed_at=datetime.now().astimezone().isoformat(),
    )
    if not neighbour:
        return None
    try:
        file_path, payload = update_daily_neighbourhood([neighbour])
    except (OSError, ValueError) as error:
        print(f"[DHCP] Could not store local neighbour observation: {error}")
        return None
    print(
        f"Stored DHCP neighbour update locally: {neighbour['mac_address']} "
        f"({neighbour['ip_address']}) in {file_path} "
        f"({len(payload['observations'])} observations)."
    )
    return neighbour


def send_active_network_neighbours(
    client_socket, *, lock_held=False, global_scan_id=None
):
    """Run an active ARP scan without blocking the client command loop."""
    global active_network_scan_global_id
    if not lock_held and not network_scan_lock.acquire(blocking=False):
        _scan_log(
            "Active scan request rejected: another active scan is already running."
        )
        return False

    try:
        started_at = time.monotonic()
        reporter_mac = _snapshot_client_mac()
        _scan_log(
            f"Active scan started: reporter={reporter_mac or 'unknown'} "
            f"global_scan_id={global_scan_id or 'none'}."
        )
        neighbours = NetworkNeighbourCollector().collect(enrich=True, active_scan=True)
        _scan_log(
            f"Active scan collection completed: reporter={reporter_mac or 'unknown'} "
            f"devices={len(neighbours)} elapsed={time.monotonic() - started_at:.1f}s."
        )
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
        _scan_log(
            f"Active scan report sent: reporter={reporter_mac or 'unknown'} devices={len(neighbours)} "
            f"global_scan_id={global_scan_id or 'none'}."
        )
        return True
    except OSError as error:
        _scan_log(f"Active scan report delivery failed: {error}")
        return False
    except Exception as error:
        _scan_log(
            f"Active scan failed: reporter={_snapshot_client_mac() or 'unknown'} error={error}"
        )
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
        _scan_log(
            f"Active scan slot released: global_scan_id={global_scan_id or 'none'}."
        )


def start_active_network_scan(client_socket, *, global_scan_id=None):
    """Start one background ARP scan, returning its status and correlation ID."""
    global active_network_scan_global_id
    if not network_scan_lock.acquire(blocking=False):
        with network_scan_state_lock:
            _scan_log(
                "Active scan request skipped because a scan is already running: "
                f"active_global_scan_id={active_network_scan_global_id or 'none'}."
            )
            return False, active_network_scan_global_id

    with network_scan_state_lock:
        active_network_scan_global_id = global_scan_id

    _scan_log(
        f"Active scan accepted and scheduled: reporter={_snapshot_client_mac() or 'unknown'} "
        f"global_scan_id={global_scan_id or 'none'}."
    )

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


def background_scanner(client_socket, stop_event=None):
    if stop_event:
        if stop_event.wait(10):
            return
    else:
        time.sleep(10)

    while not (stop_event and stop_event.is_set()):
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

        if stop_event:
            if stop_event.wait(3600):
                break
        else:
            time.sleep(3600)


# ============================================================
# CLIENT
# ============================================================


def start_client(stop_event=None):
    if stop_event is None:
        stop_event = threading.Event()

    _startup_log(f"Client starting with server target {SERVER_IP}:{SERVER_PORT}.")

    while not stop_event.is_set():
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        session_stop_event = threading.Event()
        stop_proxy = _StopEventProxy(stop_event, session_stop_event)
        background_thread = None
        dhcp_listener = None

        try:
            try:
                client.settimeout(5)
                client.connect((SERVER_IP, SERVER_PORT))
            except OSError as error:
                _startup_log(
                    f"Could not connect to server {SERVER_IP}:{SERVER_PORT}: {error}"
                )
                if stop_event.wait(5):
                    break
                continue
            finally:
                client.settimeout(None)

            _startup_log(f"Connected to server {SERVER_IP}:{SERVER_PORT}.")

            # --------------------------------------------------------
            # Register
            # --------------------------------------------------------
            with socket_lock:
                send_message(client, create_registration_message(client.getsockname()[0]))
            _startup_log("Registration sent.")

            # --------------------------------------------------------
            # Wait for commands
            # --------------------------------------------------------
            while not stop_proxy.is_set():
                try:
                    message = receive_message(client, stop_event=stop_proxy)

                    if message is None:
                        if stop_proxy.is_set():
                            break
                        _startup_log("Server disconnected.")
                        break

                    msg_type = message.get("type")

                    # Silently acknowledge registration confirmation
                    if msg_type == "REGISTERED":
                        # Send stored snapshot if available.
                        # Do NOT collect synchronously during registration.
                        threading.Thread(
                            target=send_stored_daily_neighbourhood,
                            args=(client,),
                            daemon=True,
                        ).start()

                        # Immediately request forbidden processes.
                        with socket_lock:
                            send_message(
                                client,
                                {
                                    "type": "REQUEST",
                                    "command": "GET_FORBIDDEN_PROCESSES",
                                },
                            )
                        continue

                    if msg_type == "FORBIDDEN_PROCESSES":
                        global forbidden_processes
                        forbidden_processes = message.get("data", [])
                        _startup_log(
                            f"Received {len(forbidden_processes)} forbidden processes."
                        )

                        # Start background daily neighbour snapshot collection so it never blocks command execution
                        threading.Thread(
                            target=collect_daily_network_neighbours,
                            daemon=True,
                        ).start()

                        # Start background scanner
                        if background_thread is None or not background_thread.is_alive():
                            background_thread = threading.Thread(
                                target=background_scanner,
                                args=(client, session_stop_event),
                                daemon=True,
                                name="background-scanner",
                            )
                            background_thread.start()

                        # Start passive DHCP listener (idempotent per session)
                        try:
                            if dhcp_listener is None:

                                def _on_dhcp_obs(obs):
                                    store_dhcp_neighbourhood_observation(obs)

                                # Auto-detect active network interface for sniffing
                                detected_iface = None
                                try:
                                    from network_neighbour_collector import get_local_network

                                    local_net = get_local_network()
                                    if local_net:
                                        detected_iface = local_net.get("interface")
                                except Exception:
                                    pass

                                listen_iface = (
                                    os.getenv("DHCP_LISTEN_INTERFACE") or detected_iface
                                )
                                dhcp_listener = DHCPListener(
                                    _on_dhcp_obs,
                                    interface=listen_iface,
                                )
                                dhcp_listener.start()
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
                        _scan_log(f"Ignored disabled active-scan command: {command}.")
                        result = disabled_active_network_scan_result(command)
                    elif command == "GET_NETWORK_NEIGHBOURHOOD":
                        start_requested_neighbourhood_command(client)
                        continue
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
                        stop_event.set()
                        break

                except json.JSONDecodeError:
                    _startup_log("Received invalid JSON.")

                except (ConnectionResetError, BrokenPipeError, OSError):
                    _startup_log("Connection with server lost.")
                    break

        except KeyboardInterrupt:
            stop_event.set()
        finally:
            session_stop_event.set()
            if dhcp_listener is not None:
                try:
                    dhcp_listener.stop()
                except Exception as error:
                    print(f"[DHCP] Could not stop listener cleanly: {error}")
            if background_thread is not None and background_thread.is_alive():
                background_thread.join(timeout=2)
            try:
                client.close()
            except OSError:
                pass

    print("Client stopped.")


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    start_client()