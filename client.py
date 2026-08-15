from client_lib import (
    create_registration_message,
    handle_command,
    receive_message,
    send_message,
)
import json
import socket

SERVER_IP   = "172.16.1.238"
SERVER_PORT = 5000


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