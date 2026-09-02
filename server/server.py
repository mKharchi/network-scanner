import json
import os
import socket
import threading

from dotenv import load_dotenv

from server_components.server_lib import (
    clients_lock,
    clients,
    receive_message,
    register_client,
    send_message,
    server_menu,
    get_forbidden_processes,
    get_client_observation_scope,
    receive_client_messages,
)
from database import initiate_db
from server_components.network_discovery import configure_logging


load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
configure_logging()

HOST = os.getenv("SERVER_HOST", "0.0.0.0")
PORT = int(os.getenv("SERVER_PORT", "5000"))


# ============================================================
# ACCEPT CLIENTS
# ============================================================

def accept_clients(server):
    while True:
        try:
            conn, address = server.accept()
            print(f"\nIncoming connection from {address}")

            try:
                registration = receive_message(conn)

                if not registration:
                    conn.close()
                    continue

                print("\nRegistration received:")
                from api_server import DecimalJSONEncoder

                print(json.dumps(registration, indent=4, cls=DecimalJSONEncoder))

                if registration.get("type") != "REGISTER":
                    print("Invalid registration.")
                    conn.close()
                    continue

                client_id = register_client(registration["data"], conn)

                if not client_id:
                    conn.close()
                    continue

                send_message(
                    conn,
                    {
                        "type": "REGISTERED",
                        "client_id": client_id,
                        "observation_scope": get_client_observation_scope(client_id),
                    },
                )
                
                req = receive_message(conn)
                if req and req.get("type") == "REQUEST" and req.get("command") == "GET_FORBIDDEN_PROCESSES":
                    fb_list = get_forbidden_processes()
                    send_message(conn, {"type": "FORBIDDEN_PROCESSES", "data": fb_list})

                # From this point on alerts can arrive independently of a
                # server command, so dedicate one reader to this connection.
                threading.Thread(
                    target=receive_client_messages,
                    # register_client() normalizes MAC addresses for the
                    # client registry. Use the same canonical key here so
                    # command responses reach that client's queue.
                    args=(registration["data"]["mac"].upper().replace("-", ":"), conn),
                    kwargs={
                        "agent_role": registration["data"].get("agent_role", "service")
                    },
                    daemon=True,
                ).start()

            except (ConnectionResetError, BrokenPipeError, json.JSONDecodeError, OSError):
                print("Error while registering client.")
                conn.close()

        except OSError:
            break


def start_server():
    initiate_db()

    server = socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM
    )

    server.setsockopt(
        socket.SOL_SOCKET,
        socket.SO_REUSEADDR,
        1
    )

    server.bind((HOST, PORT))
    server.listen(10)

    print(f"Server listening on {HOST}:{PORT}")

    # Accept clients in background
    threading.Thread(
        target=accept_clients,
        args=(server,),
        daemon=True
    ).start()

    # Start device evaluation worker in background
    try:
        from server_components.server_lib import _run_device_evaluation_worker
        threading.Thread(
            target=_run_device_evaluation_worker,
            daemon=True,
            name="device-evaluation-worker"
        ).start()
    except Exception as e:
        print(f"Note: Device evaluation worker could not start: {e}")

    # Start location assignment worker in background
    try:
        from server_components.location_repository import _run_location_assignment_worker
        threading.Thread(
            target=_run_location_assignment_worker,
            daemon=True,
            name="location-assignment-worker"
        ).start()
    except Exception as e:
        print(f"Note: Location assignment worker could not start: {e}")

    # Start REST API server for GUI in background
    try:
        from api_server import run_api_server, API_HOST, API_PORT
        api_httpd = run_api_server(API_HOST, API_PORT)
        threading.Thread(target=api_httpd.serve_forever, daemon=True).start()
        print(f"REST API server running on http://{API_HOST}:{API_PORT}/api/v1")
    except Exception as e:
        print(f"Note: REST API server could not bind to port: {e}")

    # Keep terminal interaction in main thread
    server_menu()


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    start_server()
