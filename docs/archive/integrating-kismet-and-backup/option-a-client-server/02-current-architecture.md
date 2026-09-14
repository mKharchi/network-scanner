# Current Architecture

## Client Kismet path

`client/app/kismet_listener.py` owns the local database-poller lifecycle and SQLite access. It does not own the Kismet daemon lifecycle.

- `KismetListener.__init__` selects `client/storage/kismet` by default.
- `find_latest_database()` selects the newest `*.kismet` by file modification time.
- `start()` creates an idempotent background poller.
- `_run_loop()` reconnects when a database appears or changes.
- `poll_new_observations()` reads `packets` in ascending `ts_sec`, `ts_usec` order, uses a bounded `LIMIT 500`, deduplicates by packet hash, and emits normalized dictionaries through the optional callback.
- Existing normalized fields include `timestamp`, `epoch_sec`, source/destination/BSSID, signal, frequency, packet length, datasource, and sensor ID.
- The live poller is currently created without an observation callback in `client/app/client.py`, so it is not a server telemetry stream.

The repository contains no code that installs Kismet, starts `kismet`/`kismet_server`/`kismet_cap`, generates Kismet configuration, sets monitor mode, verifies a capture interface, calls Kismet's REST API, or supervises a Kismet process. The current listener can therefore report its own thread state while no real Kismet process or capture exists.

The historical investigation implementation on the server currently contains richer parsing: MAC matching across source, destination, and transmitter, timestamp microseconds, Radiotap frame decoding, noise filtering, channel calculation, summary aggregation, and a 2,000-result service cap. Option A must move or share that logic with the client instead of making the client return the reduced live-poller shape and asking the server to reopen the remote file.

## Client connection

`client/app/client_lib.py` frames JSON as a four-byte big-endian payload length followed by UTF-8 JSON. `send_message()` uses `sendall()` and `receive_message()` reads exactly the declared frame. The client connection loop in `client/app/client.py` handles registration confirmation, configuration messages, and `COMMAND` frames on the same socket.

The client receives its authoritative `client_id` in `REGISTERED`. The server derives the identity from the registered MAC as `client-<lowercase MAC without separators>` and stores the socket in the server registry.

## Server connection

`server/server_components/server_lib.py` has one post-registration reader, `receive_client_messages()`. It routes unsolicited client messages and places `RESPONSE` frames on the registered client's `responses` queue. `execute_client_command()` sends a `COMMAND`, waits for a response, ignores responses for other command names, returns a structured error on timeout, and recognizes the `DISCONNECTED` sentinel.

The registry stores connection, canonical client ID, MAC, send lock, role, and response queue. `get_client(client_id)` selects by canonical client ID; `get_client_by_mac()` selects the live connection by MAC and role.

## Server wireless path today

`server/server_components/kismet_service.py` resolves the device and scans configured server-side directories for `*.kismet`. It queries SQLite directly, applies time bounds, decodes frames, filters noise, aggregates summaries, and returns the UI-shaped result. `server/server_components/api_service.py` instantiates this service for the device and alert investigation functions. `server/api_server.py` passes `lookback`, `start`, `end`, `limit`, and `include_noise` from the existing routes.

This works only when captures are visible on the server filesystem. It does not identify a remote capture owner or use the TCP client connection. The existing server search is the current implementation, not proof that the remote client has Kismet data.

## Deployment reality

The client installation and packaging are Windows-oriented, while the repository's Kismet pilot documents a separately managed Linux sensor using `wlp0s20f3mon`. The client requirements and package specification contain no Kismet dependency or executable. The actual deployment must therefore resolve whether Kismet runs on a Linux sensor, on a supported client OS, or through another supported sensor boundary before Option A assigns a query component or capture directory.

See [01-kismet-prerequisite-and-deployment.md](01-kismet-prerequisite-and-deployment.md) for the required installation, interface, runtime, persistence, API, and acceptance checks.

## UI contract today

`server/gui/src/components/WirelessInvestigationPanel.tsx` defaults to `15m`, supports `all`, `15m`, `30m`, `1h`, `4h`, `24h`, and custom UTC/ISO start and end, and sends the selected window plus `include_noise` and a limit. The API client calls `/devices/{id}/wireless-observations`. The component expects `device`, `query_window`, `summary`, and `observations`; it performs presentation filtering and exports JSON/CSV.

Option A should preserve this contract. The server, not the browser, should resolve a preset into concrete UTC `start` and `end` values before contacting the client.
