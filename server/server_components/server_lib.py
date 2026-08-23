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
pending_disconnect_checks = {}
device_isolation_status = {}
DHCP_OBSERVATION_QUEUE_SIZE = 1024
dhcp_observation_queue = queue.Queue(maxsize=DHCP_OBSERVATION_QUEUE_SIZE)
dhcp_observation_worker_lock = threading.Lock()
dhcp_observation_worker_started = False


def merge_and_broadcast_neighbourhood(*, context_overrides=None):
    """Create and announce one MAC-deduplicated client-neighbourhood snapshot."""
    from server_components.network_discovery import (
        merge_and_persist_client_neighbourhood,
    )
    from server_components import event_broadcaster

    _, devices, scan_path = merge_and_persist_client_neighbourhood(
        context_overrides=context_overrides
    )
    scan_id = os.path.splitext(os.path.basename(scan_path))[0]
    event_broadcaster.broadcast_network_update(scan_id, len(devices))
    return devices, scan_path


def _run_dhcp_observation_writer():
    """Persist DHCP audit events away from the TCP connection reader."""
    while True:
        reporter_mac, neighbours, dhcp = dhcp_observation_queue.get()
        try:
            from server_components.network_scan_storage import (
                append_daily_dhcp_observation,
            )

            append_daily_dhcp_observation(reporter_mac, neighbours, dhcp)

            # Notify the frontend over SSE so the DHCP page updates live
            try:
                from server_components import event_broadcaster

                event_broadcaster.broadcast_dhcp_update(
                    {
                        "reporting_client_mac": reporter_mac,
                        "neighbours": neighbours,
                        "dhcp": dhcp or {},
                    }
                )
            except Exception as broadcast_error:
                print(
                    f"[DHCP] broadcast_dhcp_update failed (non-fatal): {broadcast_error}"
                )
        except Exception as error:
            print(f"Could not append DHCP observation log: {error}")
        finally:
            dhcp_observation_queue.task_done()


def queue_dhcp_observation(reporter_mac, neighbours, dhcp):
    """Queue a DHCP event without delaying the client command-response path."""
    global dhcp_observation_worker_started
    with dhcp_observation_worker_lock:
        if not dhcp_observation_worker_started:
            threading.Thread(
                target=_run_dhcp_observation_writer,
                daemon=True,
                name="dhcp-observation-writer",
            ).start()
            dhcp_observation_worker_started = True
    try:
        dhcp_observation_queue.put_nowait((reporter_mac, neighbours, dhcp))
    except queue.Full:
        print(
            "Dropped DHCP observation because the audit queue is full "
            f"({DHCP_OBSERVATION_QUEUE_SIZE} pending events)."
        )


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
        cursor.execute(
            "SELECT process_name, severity, description FROM forbidden_processes WHERE enabled = TRUE"
        )
        return cursor.fetchall()
    except Exception as e:
        print(f"Error fetching forbidden processes: {e}")
        return []
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


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
                WORKING_HOURS_OUTSIDE if monitoring_enabled else WORKING_HOURS_DISABLED
            )

        start_seconds, end_seconds = schedule
        current_seconds = (
            checked_at.hour * 3600 + checked_at.minute * 60 + checked_at.second
        )

        if start_seconds <= end_seconds:
            is_within = start_seconds <= current_seconds < end_seconds
        else:
            # Supports an overnight schedule such as 22:00–06:00 as well.
            is_within = (
                current_seconds >= start_seconds or current_seconds < end_seconds
            )

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
        alert_id = getattr(cursor, "lastrowid", None)
        print(f"\n[!] ALERT: {title} — {hostname} ({mac})", flush=True)

        try:
            from server_components import event_broadcaster

            event_broadcaster.broadcast_alert(
                {
                    "id": alert_id,
                    "client": {
                        "id": client_info.get("client_id"),
                        "hostname": hostname,
                    },
                    "type": alert_type,
                    "severity": severity,
                    "status": "NEW",
                    "title": title,
                    "description": description,
                    "detected_at": registered_at.isoformat(),
                }
            )
            event_broadcaster.broadcast_client_status(
                client_id=client_info.get("client_id", ""),
                mac=mac,
                hostname=hostname,
                state="ONLINE",
                ip=ip,
            )
        except Exception:
            pass

        return True
    except Exception as error:
        print(f"Error saving registration alert: {error}")
        return False
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


def create_server_alert(
    mac, alert_type, severity, title, description, detected_at=None
):
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
        alert_id = cursor.lastrowid
        print(f"\n[!] ALERT: {title} — {mac}", flush=True)

        try:
            from server_components import event_broadcaster

            event_broadcaster.broadcast_alert(
                {
                    "id": alert_id,
                    "client": {"mac": mac},
                    "type": alert_type,
                    "severity": severity,
                    "status": "NEW",
                    "title": title,
                    "description": description,
                    "detected_at": (
                        detected_at.isoformat()
                        if hasattr(detected_at, "isoformat")
                        else str(detected_at)
                    ),
                }
            )
        except Exception:
            pass

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
    """Return whether a client IP responds to a bounded two-packet ICMP ping."""
    try:
        address = str(ipaddress.ip_address(ip))
    except ValueError:
        print(f"Cannot ping invalid client IP: {ip!r}")
        return False

    if platform.system() == "Windows":
        command = [
            "ping",
            "-n",
            "2",
            "-w",
            str(DISCONNECT_PING_TIMEOUT_SECONDS * 1000),
            address,
        ]
    else:
        command = [
            "ping",
            "-c",
            "2",
            "-W",
            str(DISCONNECT_PING_TIMEOUT_SECONDS),
            address,
        ]

    try:
        return (
            subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=(DISCONNECT_PING_TIMEOUT_SECONDS * 2) + 1,
                check=False,
            ).returncode
            == 0
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"Ping check failed for {address}: {error}")
        return False


def has_arp_neighbour(ip):
    """Return whether the local neighbour table confirms a LAN host is alive.

    Endpoint firewalls can block ICMP while the machine is still online. A
    failed ping is therefore followed by this ARP-level check before an
    unexpected disconnect is treated as informational.
    """
    try:
        address = str(ipaddress.ip_address(ip))
    except ValueError:
        return False

    if platform.system() == "Windows":
        command = ["arp", "-a", address]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            return result.returncode == 0 and address in result.stdout
        except (OSError, subprocess.TimeoutExpired) as error:
            print(f"ARP reachability check failed for {address}: {error}")
            return False

    try:
        result = subprocess.run(
            ["ip", "-j", "neigh", "show", "to", address],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if result.returncode != 0:
            return False
        neighbours = json.loads(result.stdout)
        return any(
            neighbour.get("dst") == address
            and neighbour.get("lladdr")
            and neighbour.get("state") not in {"FAILED", "INCOMPLETE", "NOARP"}
            for neighbour in neighbours
            if isinstance(neighbour, dict)
        )
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
        print(f"ARP reachability check failed for {address}: {error}")
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
    if not reachable:
        reachable = has_arp_neighbour(client.get("ip", ""))

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
        raise ValueError(f"{field_name} must use YYYY-MM-DD HH:MM:SS") from error


def handle_client_alert(mac, alert_data):
    """Validate, persist, and display an asynchronous client alert."""
    if not isinstance(alert_data, dict):
        print(f"Rejected malformed alert from {mac}: payload is not an object.")
        return False

    if alert_data.get("alert_type") != "FORBIDDEN_PROCESS":
        print(
            f"Rejected unsupported alert from {mac}: {alert_data.get('alert_type')!r}"
        )
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
            print(
                f"Rejected alert from {mac}: invalid configured severity {severity!r}."
            )
            return False

        title = f"Forbidden process detected: {configured_name}"
        description = configured_description or (
            f"Forbidden process '{configured_name}' was detected on the client."
        )

        cursor.execute(
            """
            INSERT INTO alerts (
                client_id, log_id, alert_type, severity, 
                detected_at, activity_time, title, description, status
            ) VALUES (%s, NULL, %s, %s, %s, %s, %s, %s, 'NEW')
        """,
            (
                client_db_id,
                "FORBIDDEN_PROCESS",
                severity,
                detected_at,
                activity_time,
                title,
                description,
            ),
        )
        conn.commit()
        print(f"\n[!] ALERT RECEIVED from {mac}: {title}", flush=True)
        return True
    except Exception as e:
        print(f"Error saving alert: {e}")
        return False
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


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
            cursor.execute(
                """
                INSERT INTO connections (client_id, connected_at)
                VALUES (%s, CURRENT_TIMESTAMP)
            """,
                (client_db_id,),
            )
        elif status == "disconnected":
            # Update the latest open connection for this client
            cursor.execute(
                """
                UPDATE connections 
                SET disconnected_at = CURRENT_TIMESTAMP 
                WHERE client_id = %s AND disconnected_at IS NULL 
                ORDER BY id DESC LIMIT 1
            """,
                (client_db_id,),
            )

        conn.commit()
    except Exception as e:
        print(f"Failed to write connection log: {e}")
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


def _client_id_for_mac(mac):
    """Return a restart-safe client identifier derived from its local identity."""
    return f"client-{mac.replace(':', '').replace('-', '').lower()}"


def update_client_db(mac, client_id, hostname, ip, os_info):
    """Persist/update client metadata in the MySQL database."""
    conn = None
    cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()

        system = (
            os_info.get("system", str(os_info))
            if isinstance(os_info, dict)
            else str(os_info)
        )
        release = os_info.get("release", "") if isinstance(os_info, dict) else ""
        version = os_info.get("version", "") if isinstance(os_info, dict) else ""
        machine = os_info.get("machine", "") if isinstance(os_info, dict) else ""

        cursor.execute(
            """
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
        """,
            (client_id, hostname, ip, mac, system, release, version, machine),
        )

        conn.commit()
        return True
    except Exception as e:
        print(f"Failed to update client in DB: {e}")
        return False
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
        cursor.execute("SELECT id, client_id FROM clients WHERE mac = %s", (mac,))
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
            (client_db_id, file_path, period, generated_at),
        )

        conn.commit()

        print(
            f"\nActivity log stored:" f"\n  File: {file_path}" f"\n  Period: {period}"
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
    mac = client_info["mac"].upper().replace("-", ":")
    client_info = dict(client_info)
    client_info["mac"] = mac
    client_id = _client_id_for_mac(mac)

    with clients_lock:
        # A registration during the grace period cancels the pending agent
        # verification for the previous connection.
        pending_disconnect_checks.pop(mac, None)

        # ---- Reconnecting client ----
        if mac in clients:
            client = clients[mac]

            if not update_client_db(
                mac,
                client_id,
                client_info["hostname"],
                client_info["ip"],
                client_info["os"],
            ):
                print(
                    f"Client registration rejected because {mac} could not be saved to MySQL."
                )
                return None

            client["hostname"] = client_info["hostname"]
            client["ip"] = client_info["ip"]
            client["os"] = client_info["os"]
            client["client_id"] = client_id
            client["connection"] = conn
            client["responses"] = queue.Queue()
            client["send_lock"] = threading.Lock()

            print(f"Client reconnected: {client['client_id']}")
            log_connection(mac, "reconnected")
            create_connection_alert(client_info)
            return client["client_id"]

        # ---- New client ----
        if not update_client_db(
            mac,
            client_id,
            client_info["hostname"],
            client_info["ip"],
            client_info["os"],
        ):
            print(
                f"Client registration rejected because {mac} could not be saved to MySQL."
            )
            return None

        clients[mac] = {
            "client_id": client_id,
            "hostname": client_info["hostname"],
            "ip": client_info["ip"],
            "mac": mac,
            "os": client_info["os"],
            "connection": conn,
            "responses": queue.Queue(),
            "send_lock": threading.Lock(),
        }

        print(f"New client connected: {client_id}")
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
            disconnect_reason = client.get("disconnect_reason")
            if disconnect_reason == "DEVICE_ISOLATION":
                existing = device_isolation_status.get(client["client_id"], {})
                device_isolation_status[client["client_id"]] = {
                    **existing,
                    "status": "CONNECTION_LOST_AFTER_ISOLATION",
                    "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                }
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


def handle_network_neighbour_report(
    reporter_mac,
    payload,
    *,
    report_validator=None,
    observation_storer=None,
    dhcp_observation_storer=None,
    daily_snapshot_exists=None,
    daily_snapshot_storer=None,
    daily_scan_reference_storer=None,
):
    """Ingest one report using the MAC bound to the registered TCP session.

    ``reporter_mac`` is supplied by the server connection registry, never by
    the client message. Optional dependencies keep validation and persistence
    independently testable without a database.
    """
    if report_validator is None:
        from server_components.network_device_storage import validate_neighbour_report

        report_validator = validate_neighbour_report

    source = payload.get("observation_source") if isinstance(payload, dict) else None
    global_scan_id = (
        payload.get("global_scan_id") if isinstance(payload, dict) else None
    )
    scan_status = payload.get("scan_status") if isinstance(payload, dict) else None
    reported_count = (
        len(payload.get("neighbours", []))
        if isinstance(payload, dict) and isinstance(payload.get("neighbours"), list)
        else "invalid"
    )
    print(
        "[NETWORK REPORT] Received: "
        f"reporter={reporter_mac} source={source or 'unknown'} "
        f"global_scan_id={global_scan_id or 'none'} entries={reported_count} "
        f"scan_status={scan_status or 'completed'}.",
        flush=True,
    )
    try:
        neighbours = report_validator(payload)
        if source == "DHCP":
            if not neighbours:
                print(f"Ignored empty DHCP observation from {reporter_mac}.")
                return True
            try:
                storer = observation_storer
                if storer is None:
                    from server_components.network_device_storage import (
                        store_client_dhcp_observations,
                    )

                    storer = store_client_dhcp_observations
                stored = storer(reporter_mac, neighbours)
                print(f"Stored {stored} DHCP observation(s) from {reporter_mac}.")
            except Exception as error:
                print(f"Could not store DHCP observation in database: {error}")

            if dhcp_observation_storer is not None:
                # Dependency injection keeps the synchronous path available
                # for focused unit tests.
                dhcp_observation_storer(reporter_mac, neighbours, payload.get("dhcp"))
            else:
                queue_dhcp_observation(reporter_mac, neighbours, payload.get("dhcp"))

            # Automatically trigger a fresh scan merge & SSE broadcast so the UI updates
            try:
                merge_and_broadcast_neighbourhood()
            except Exception as auto_err:
                pass

            return True

        if observation_storer is None:
            from server_components.network_device_storage import (
                store_client_neighbourhood_observations,
            )

            observation_storer = store_client_neighbourhood_observations

        if source == "DAILY_NEIGHBOUR_SNAPSHOT":
            if daily_snapshot_exists is None or daily_snapshot_storer is None:
                from server_components.network_scan_storage import (
                    has_daily_neighbour_snapshot,
                    record_daily_neighbour_snapshot,
                )

                daily_snapshot_exists = (
                    daily_snapshot_exists or has_daily_neighbour_snapshot
                )
                daily_snapshot_storer = (
                    daily_snapshot_storer or record_daily_neighbour_snapshot
                )
            if daily_snapshot_exists(reporter_mac):
                print(f"Daily neighbour snapshot already recorded for {reporter_mac}.")
                return True

            stored = observation_storer(reporter_mac, neighbours)
            print(
                f"Stored {stored} daily neighbour observation(s) from {reporter_mac}."
            )
            try:
                daily_log_path, created = daily_snapshot_storer(
                    reporter_mac, neighbours
                )
                if created:
                    print(f"Added daily neighbour snapshot to {daily_log_path}.")
                    if daily_scan_reference_storer is None:
                        from server_components.network_device_storage import (
                            store_daily_network_scan_reference,
                        )

                        daily_scan_reference_storer = store_daily_network_scan_reference
                    daily_scan_reference_storer(daily_log_path)
                    print(
                        f"Stored daily network-scan file reference: {daily_log_path}."
                    )

                # Automatically trigger a fresh scan merge & SSE broadcast so the UI updates
                try:
                    merge_and_broadcast_neighbourhood()
                except Exception as auto_err:
                    pass
            except Exception as error:
                # Database storage remains valid even if its readable mirror
                # cannot be updated on this attempt.
                print(f"Could not append daily neighbour snapshot: {error}")
            return True

        if source == "REQUESTED_NEIGHBOURHOOD":
            stored = observation_storer(reporter_mac, neighbours)
            print(
                f"Stored {stored} requested neighbourhood observation(s) from {reporter_mac}."
            )
            try:
                merge_and_broadcast_neighbourhood(
                    context_overrides={"scan_type": "REQUESTED_NEIGHBOURHOOD"}
                )
            except Exception as error:
                print(f"Could not merge requested neighbourhood report: {error}")
            return True

        if source == "ACTIVE_NEIGHBOUR_SCAN":
            global_scan_manager = None
            if global_scan_id:
                from server_components.global_network_scan import (
                    global_network_scan_manager,
                )

                global_scan_manager = global_network_scan_manager
                if global_scan_manager.is_duplicate_report(
                    global_scan_id, reporter_mac
                ):
                    print(
                        f"Ignored duplicate active scan report from {reporter_mac} "
                        f"for global scan {global_scan_id}."
                    )
                    return True

            if scan_status == "failed":
                if global_scan_manager:
                    global_scan_manager.record_report(
                        global_scan_id,
                        reporter_mac,
                        neighbours,
                        failed=True,
                        error=payload.get("scan_error"),
                    )
                print(f"Client {reporter_mac} reported an active scan failure.")
                return True

            stored = observation_storer(reporter_mac, neighbours)
            print(
                "[NETWORK REPORT] Persisted active scan observations: "
                f"reporter={reporter_mac} stored={stored} global_scan_id={global_scan_id or 'none'}."
            )
            if global_scan_manager:
                global_scan_manager.record_report(
                    global_scan_id, reporter_mac, neighbours
                )
            try:
                from server_components.network_discovery import run_manual_scan
                from server_components import event_broadcaster
                import os

                _, devices, scan_path = run_manual_scan(
                    context_overrides={"scan_type": "CLIENT_ACTIVE"}
                )
                scan_id = os.path.splitext(os.path.basename(scan_path))[0]
                event_broadcaster.broadcast_network_update(scan_id, len(devices))
                print(
                    "[NETWORK REPORT] Active scan merge completed: "
                    f"reporter={reporter_mac} merged_devices={len(devices)} scan_id={scan_id}.",
                    flush=True,
                )
            except Exception as error:
                print(f"Could not merge active neighbour report: {error}")
            return True

        # Preserve the legacy protocol for older clients until they are
        # upgraded to label their snapshots explicitly.
        stored = observation_storer(reporter_mac, neighbours)
        print(f"Stored {stored} network neighbour observation(s) from {reporter_mac}.")
        return True
    except ValueError as error:
        print(f"Rejected network neighbours from {reporter_mac}: {error}")
    except Exception as error:
        print(f"Failed to store network neighbours from {reporter_mac}: {error}")
    return False


def receive_client_messages(mac, conn):
    """Continuously consume one client's frames after registration.

    A TCP connection can receive alerts at any time.  This is deliberately the
    only post-registration reader for the connection; command handlers consume
    responses from the per-client queue below instead of calling recv().
    """
    # The registry is keyed by canonical uppercase colon-separated MACs.
    # Normalizing here keeps response routing correct even for older callers.
    mac = mac.upper().replace("-", ":") if isinstance(mac, str) else mac
    try:
        while True:
            message = receive_message(conn)
            if message is None:
                print(f"Client {mac} disconnected.")
                return

            message_type = message.get("type") if isinstance(message, dict) else None
            if message_type == "ALERT":
                handle_client_alert(mac, message.get("alert"))
            elif message_type == "NETWORK_NEIGHBOURS":
                handle_network_neighbour_report(mac, message.get("data"))
            elif message_type == "RESPONSE":
                client = get_client_by_mac(mac)
                if client and client["connection"] is conn:
                    client["responses"].put(message)
            else:
                print(f"Unexpected message from {mac}: {message_type!r}")
    except (
        ConnectionResetError,
        BrokenPipeError,
        OSError,
        json.JSONDecodeError,
    ) as error:
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

    if command == "GET_ACTIVITY_LOG" and response.get("type") == "RESPONSE":
        log_data = response.get("data", {})

        client = get_client(client_id)
        if client:
            store_activity_log_file(client["mac"], log_data)

    else:
        print(json.dumps(response, indent=4))


# ============================================================
# SEND / EXECUTE COMMAND TO CLIENT
# ============================================================


def execute_client_command(
    client_id, command, args=None, timeout=10.0, *, process_network_scan=True
):
    """Send a command to a connected client and return the structured response payload."""
    client = get_client(client_id)
    if not client:
        return {"status": "error", "message": f"Client '{client_id}' is not connected."}

    conn = client["connection"]
    message = {"type": "COMMAND", "command": command}
    if command in ("SCAN_NETWORK", "TRIGGER_ARP_SCAN"):
        global_scan_id = args.get("global_scan_id") if isinstance(args, dict) else None
        print(
            "[NETWORK COMMAND] Dispatching active scan: "
            f"client_id={client_id} hostname={client['hostname']} mac={client['mac']} "
            f"global_scan_id={global_scan_id or 'none'} acknowledgement_timeout={timeout}s.",
            flush=True,
        )
    if args is not None:
        message["args"] = args

    try:
        with client["send_lock"]:
            if command == "DISCONNECT":
                with clients_lock:
                    current_client = clients.get(client["mac"])
                    if current_client is client and client["connection"] is conn:
                        client["disconnect_expected"] = True
            send_message(conn, message)

        start_t = time.time()
        while (time.time() - start_t) < timeout:
            remaining = max(0.1, timeout - (time.time() - start_t))
            try:
                response = client["responses"].get(timeout=remaining)
            except queue.Empty:
                print(
                    "[NETWORK COMMAND] Acknowledgement timed out: "
                    f"client_id={client_id} command={command} timeout={timeout}s.",
                    flush=True,
                )
                return {
                    "status": "error",
                    "message": f"Command '{command}' timed out after {timeout}s.",
                }

            if response.get("type") == "DISCONNECTED":
                return {
                    "status": "error",
                    "message": "Client disconnected while waiting for command response.",
                }

            if response.get("command") != command:
                continue

            if command in ("SCAN_NETWORK", "TRIGGER_ARP_SCAN"):
                response_data = response.get("data")
                print(
                    "[NETWORK COMMAND] Active-scan acknowledgement received: "
                    f"client_id={client_id} status="
                    f"{response_data.get('status') if isinstance(response_data, dict) else 'invalid'} "
                    f"global_scan_id="
                    f"{response_data.get('global_scan_id') if isinstance(response_data, dict) else 'none'}.",
                    flush=True,
                )

            # Store activity log file if activity log was fetched
            if command == "GET_ACTIVITY_LOG" and response.get("type") == "RESPONSE":
                log_data = response.get("data", {})
                store_activity_log_file(client["mac"], log_data)

            # Legacy synchronous scan responses may include observations. New
            # clients acknowledge the command immediately and report their
            # results separately as ACTIVE_NEIGHBOUR_SCAN messages.
            if (
                process_network_scan
                and command in ("SCAN_NETWORK", "TRIGGER_ARP_SCAN")
                and response.get("type") == "RESPONSE"
            ):
                data = response.get("data", {})
                if isinstance(data, dict) and data.get("status") == "ok":
                    devs = data.get("devices", [])
                    if devs:
                        try:
                            print(
                                f"Storing ARP_SCAN_NETWORK observations from {client['mac']} done in {int(datetime.now().timestamp())} ."
                            )
                            from server_components.network_device_storage import (
                                store_client_neighbour_observations,
                            )

                            store_client_neighbour_observations(client["mac"], devs)
                            from server_components.network_discovery import (
                                run_manual_scan,
                            )
                            from server_components import event_broadcaster
                            import os

                            _, all_devs, scan_path = run_manual_scan()
                            scan_id = os.path.splitext(os.path.basename(scan_path))[0]
                            event_broadcaster.broadcast_network_update(
                                scan_id, len(all_devs)
                            )
                        except Exception as e:
                            print(f"Failed to store SCAN_NETWORK observations: {e}")

            return {
                "status": "ok",
                "command": command,
                "data": response.get("data"),
                "raw": response,
                "client_id": client_id,
            }

        return {"status": "error", "message": f"Command '{command}' timed out."}
    except (ConnectionResetError, BrokenPipeError, OSError) as e:
        remove_client(client["mac"], conn)
        return {"status": "error", "message": f"Connection lost: {e}"}


def request_client_network_neighbourhood(client_id, *, timeout=None):
    """Request one connected client's stored daily neighbourhood.

    The client sends its local report before its command response. A timeout
    is isolated to this client and returned as structured state for the REST
    layer and the later bucket orchestrator.
    """
    if timeout is None:
        try:
            timeout = max(
                0.1,
                float(os.getenv("NETWORK_NEIGHBOURHOOD_REQUEST_TIMEOUT", "12")),
            )
        except ValueError:
            timeout = 12.0

    result = execute_client_command(
        client_id,
        "GET_NETWORK_NEIGHBOURHOOD",
        timeout=timeout,
        process_network_scan=False,
    )
    if result.get("status") != "ok":
        message = result.get("message", "Client neighbourhood request failed.")
        if "timed out" in message.lower():
            return {
                "status": "client_timeout",
                "client_id": client_id,
                "timeout_seconds": timeout,
                "message": message,
            }
        if "not connected" in message.lower():
            return {
                "status": "client_unavailable",
                "client_id": client_id,
                "message": message,
            }
        return {"status": "client_error", "client_id": client_id, "message": message}

    data = result.get("data")
    if not isinstance(data, dict) or data.get("status") != "ok":
        message = data.get("message") if isinstance(data, dict) else None
        return {
            "status": "client_error",
            "client_id": client_id,
            "message": message or "Client could not provide its stored neighbourhood.",
        }

    return {
        "status": "completed",
        "client_id": client_id,
        "observations_sent": data.get("observations_sent", 0),
        "timeout_seconds": timeout,
    }


def request_client_passive_neighbourhood(client_id, *, timeout=None):
    """Request one connected client's bounded passive-protocol snapshot.

    Passive observations stay separate from the existing neighbourhood/device
    pipeline. This helper only dispatches the client command and validates the
    response contract for the REST layer added in the next phase.
    """
    if timeout is None:
        try:
            timeout = max(
                0.1,
                float(os.getenv("PASSIVE_NEIGHBOURHOOD_REQUEST_TIMEOUT", "10")),
            )
        except ValueError:
            timeout = 10.0

    result = execute_client_command(
        client_id,
        "GET_PASSIVE_NEIGHBOURHOOD",
        timeout=timeout,
        process_network_scan=False,
    )
    if result.get("status") != "ok":
        message = result.get("message", "Client passive neighbourhood request failed.")
        if "timed out" in message.lower():
            return {
                "status": "client_timeout",
                "client_id": client_id,
                "timeout_seconds": timeout,
                "message": message,
            }
        if "not connected" in message.lower():
            return {
                "status": "client_unavailable",
                "client_id": client_id,
                "message": message,
            }
        return {"status": "client_error", "client_id": client_id, "message": message}

    data = result.get("data")
    observations = data.get("observations") if isinstance(data, dict) else None
    valid_observations = isinstance(observations, list) and all(
        isinstance(observation, dict)
        and observation.get("protocol") in {"dhcp", "mdns", "llmnr", "nbns", "ssdp"}
        for observation in observations
    )
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("observed_at"), str)
        or not isinstance(data.get("reporter"), str)
        or not valid_observations
    ):
        return {
            "status": "client_error",
            "client_id": client_id,
            "message": "Client returned an invalid passive neighbourhood response.",
        }
    from .passive_neighbourhood_storage import (
        append_passive_neighbourhood_snapshot,
    )
    try:
        storage_path = append_passive_neighbourhood_snapshot(
        client_id=client_id,
        reporter=data["reporter"],
        observed_at=data["observed_at"],
        observations=observations,
    )
    except Exception:
        return {
                    "status": "storage_error",
                    "client_id": client_id,
                    "message": "Failed to store passive neighbourhood snapshot.",
                }
        storage_path = None
    return {
        "status": "completed",
        "client_id": client_id,
        "timeout_seconds": timeout,
        "observed_at": data["observed_at"],
        "reporter": data["reporter"],
        "observations": observations,
        "observation_count": len(observations),
    }


def quarantine_client(client_id, reason="Administrator requested network quarantine", duration_minutes=60, timeout=10.0):
    """Dispatch QUARANTINE_CLIENT command to a connected client."""
    cmd_id = f"cmd-quarantine-{int(time.time())}"
    args = {
        "reason": reason,
        "duration_minutes": duration_minutes,
        "command_id": cmd_id,
    }
    return execute_client_command(client_id, "QUARANTINE_CLIENT", args=args, timeout=timeout)


def release_client_quarantine(client_id, reason="Administrator released network quarantine", timeout=10.0):
    """Dispatch RELEASE_CLIENT command to a connected client."""
    cmd_id = f"cmd-release-{int(time.time())}"
    args = {
        "reason": reason,
        "command_id": cmd_id,
    }
    return execute_client_command(client_id, "RELEASE_CLIENT", args=args, timeout=timeout)


def get_client_quarantine_status(client_id, timeout=10.0):
    """Dispatch GET_QUARANTINE_STATUS command to a connected client."""
    return execute_client_command(client_id, "GET_QUARANTINE_STATUS", timeout=timeout)


def isolate_client(
    client_id,
    reason="Administrator requested static device isolation",
    timeout=10.0,
):
    """Request static-IP isolation and classify the expected disconnect.

    The client removes its production route, so a missing response after the
    command is sent is a successful transport outcome, not a normal agent-loss
    alert. Network restoration intentionally remains a local admin action.
    """
    client = get_client(client_id)
    if not client:
        return {"status": "error", "message": f"Client '{client_id}' is not connected."}

    sent_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with clients_lock:
        current_client = clients.get(client["mac"])
        if current_client is not client:
            return {"status": "error", "message": f"Client '{client_id}' is not connected."}
        client["disconnect_expected"] = True
        client["disconnect_reason"] = "DEVICE_ISOLATION"
        device_isolation_status[client_id] = {
            "status": "SENT",
            "reason": reason,
            "sent_at": sent_at,
            "updated_at": sent_at,
        }

    result = execute_client_command(
        client_id,
        "ISOLATE_DEVICE",
        args={"reason": reason},
        timeout=timeout,
    )
    if result.get("status") == "ok":
        with clients_lock:
            existing = device_isolation_status.get(client_id, {})
            device_isolation_status[client_id] = {
                **existing,
                "status": "ACKNOWLEDGED",
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
        return {**result, "isolation_status": "ACKNOWLEDGED"}

    message = result.get("message", "Device isolation command failed.")
    if "disconnected" in message.lower() or "connection lost" in message.lower():
        with clients_lock:
            existing = device_isolation_status.get(client_id, {})
            device_isolation_status[client_id] = {
                **existing,
                "status": "CONNECTION_LOST_AFTER_ISOLATION",
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
        return {
            "status": "ok",
            "client_id": client_id,
            "isolation_status": "CONNECTION_LOST_AFTER_ISOLATION",
            "message": "Isolation command was sent and the client disconnected as expected.",
        }

    with clients_lock:
        current_client = clients.get(client["mac"])
        if current_client is client:
            client.pop("disconnect_expected", None)
            client.pop("disconnect_reason", None)
        existing = device_isolation_status.get(client_id, {})
        device_isolation_status[client_id] = {
            **existing,
            "status": "FAILED",
            "message": message,
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
    return result


def get_device_isolation_status(client_id):
    """Return the latest server-side isolation dispatch state for a client."""
    with clients_lock:
        status = device_isolation_status.get(client_id)
        if status:
            return {"status": "ok", "data": status.copy()}
    return {
        "status": "ok",
        "data": {"status": "NOT_REQUESTED", "client_connected": get_client(client_id) is not None},
    }


def send_command(client_id, command, args=None):
    res = execute_client_command(client_id, command, args, timeout=25.0)
    if res.get("status") == "ok":
        print_response(client_id, command, res.get("raw", {}))
    else:
        print(f"Command failed: {res.get('message')}")


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
        print("10. Activity log")
        print("11. Disconnect client")
        print("12. Back")

        choice = input("\nSelect command: ").strip()

        commands = {
            "1": "GET_SYSTEM_INFO",
            "2": "GET_NETWORK_INFO",
            "3": "GET_CPU_INFO",
            "4": "GET_MEMORY_INFO",
            "5": "GET_DISK_INFO",
            "6": "GET_PROCESSES",
            "7": "PING",
            "8": "KILL_PROCESS",
            "9": "START_PROCESS",
            "10": "GET_ACTIVITY_LOG",
            "11": "DISCONNECT",
        }

        if choice == "12":
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
        print("3. Merge client network-discovery reports")
        print("4. Exit")

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
            try:
                from server_components.network_discovery import (
                    NetworkDiscoveryError,
                    run_manual_scan,
                )

                context, devices, result_path = run_manual_scan()
                print(
                    f"\nClient network reports merged: {len(devices)} device(s) found."
                )
                print(f"Saved result: {result_path}")
            except NetworkDiscoveryError as error:
                print(f"Network discovery failed: {error}")

        elif choice == "4":
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
