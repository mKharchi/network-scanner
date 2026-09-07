# Server Runtime, TCP Registry, REST API, and SSE

## What it does

The server is the coordination point for all managed clients. It accepts
outbound client connections, stores identity and observations, exposes the
operator API, dispatches commands, and broadcasts changes to the GUI.

## Implementation

| Concern | Implementation |
| --- | --- |
| Process entrypoint | `server/server.py` |
| TCP accept/registration | `server/server.py`, `server_components/server_lib.py` |
| Client registry and queues | `server_components/server_lib.py` |
| Database connection/schema initialization | `server/database.py`, `server/scripts.sql` |
| REST and SSE server | `server/api_server.py` |
| Business/API service layer | `server_components/api_service.py` |
| Live event broker | `server_components/event_broadcaster.py` |
| Background action execution | `server_components/action_service.py` |

## Startup sequence

`start_server()` performs these operations:

1. Load `server/.env` with `python-dotenv`.
2. Initialize/verify the MySQL schema.
3. Bind the TCP listener to `SERVER_HOST:SERVER_PORT` (normally `5000`).
4. Start the client accept loop and evaluation/location workers.
5. Bind the REST server to `API_HOST:API_PORT` (approved profile:
   `127.0.0.1:8080`).
6. Enter the interactive operator menu, or wait without stdin when
   `SERVER_INTERACTIVE=false` is set for systemd.

The example unit [network-scanner-server.service.example](../../../network-scanner-server.service.example)
supervises this complete process after boot.

## Client connection lifecycle

The first frame must be a `REGISTER` message. The server normalizes the client
identity, stores the connection, sends initial policy/configuration responses,
and starts a reader for asynchronous client messages. Heartbeats refresh
reachability and version state. Connection failures generate connection
records/events and remove the active socket from the registry.

Commands are matched to the registered client's response queue. A per-client
send lock prevents concurrent action threads from interleaving framed JSON.

## REST behavior

`api_server.py` routes HTTP requests to the service modules. Successful JSON
responses are wrapped as `{"data": ...}`; errors use a stable code/message
envelope. The implementation keeps compatibility aliases such as `/api/...`
alongside the canonical `/api/v1/...` paths.

The API covers clients, devices, scans, DHCP, alerts, policies, actions,
locations, screenshots, packages, bulk updates, wireless investigation, and
health. See [API.md](../API.md) and the detailed
[API contract](../../../server/docs/API_CONTRACT.md).

## Server-Sent Events

`GET /api/v1/events` keeps a streaming HTTP response open. The broadcaster
publishes connection, alert, action, scan, telemetry, health, and spatial
events. The GUI uses these events to invalidate relevant queries and display
toasts instead of requiring a full page refresh.

## Operational notes

- The TCP port must be reachable from client PCs; the REST API can remain
  localhost-only when the GUI runs on the server.
- MySQL credentials belong only in the server environment.
- Start the server with the systemd unit in deployments; use the interactive
  menu only for development or deliberate operator sessions.
- A failed API bind is logged but does not necessarily stop the TCP server;
  check both listeners during troubleshooting.

