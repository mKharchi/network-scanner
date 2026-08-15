import json
import socket
import threading

from server_lib import (
    clients_lock,
    clients,
    receive_message,
    register_client,
    send_message,
    server_menu,
)

HOST = "0.0.0.0"
PORT = 5000


# ============================================================
# ACCEPT CLIENTS
# ============================================================

def start_server():

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(10)

    print(f"Server listening on {HOST}:{PORT}")

    # Start interactive console in a background thread
    threading.Thread(target=server_menu, daemon=True).start()

    # Accept incoming client connections
    while True:

        conn, address = server.accept()
        print(f"\nIncoming connection from {address}")

        try:
            registration = receive_message(conn)

            if not registration:
                conn.close()
                continue

            print("\nRegistration received:")
            print(json.dumps(registration, indent=4))

            if registration.get("type") != "REGISTER":
                print("Invalid registration.")
                conn.close()
                continue

            client_id = register_client(registration["data"], conn)

            send_message(conn, {"type": "REGISTERED", "client_id": client_id})

        except (ConnectionResetError, BrokenPipeError, json.JSONDecodeError, OSError):
            print("Error while registering client.")
            conn.close()


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    start_server()