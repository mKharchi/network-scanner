# Milestone A — Audit Report: Action Framework & Screenshot Pipeline

Status: Completed (Read-only audit. No code changes made.)  
 Scope: Action framework (server + client dispatch), screenshot capture/transfer pipeline, TCP message framing, and client-side filesystem conventions.  
 ──────

## 1. Action Framework Structure

### Server-Side Representation (Data Model)

• Database Schema:  
 • actions table (scripts.sql:126-142): Stores primary action records with columns: id (BIGINT PK), action_id (VARCHAR(100) UNIQUE), action_type  
 (VARCHAR(64)), requested_by (VARCHAR(255)), created_at (DATETIME), started_at (DATETIME), completed_at (DATETIME), expires_at (DATETIME), status  
 (VARCHAR(32)), parameters (LONGTEXT JSON), result (LONGTEXT JSON), error (LONGTEXT JSON).  
 • action_targets table (scripts.sql:144-166): Stores per-target execution records linked by action_id (FK to actions.id) and client_id (FK to clients.
id), with columns: status, sent_at, acknowledged_at, started_at, completed_at, result, error, target_order.  
 • In-Memory Models & Vocabulary:  
 • Action Types & States defined in action_framework.py:15-56 via ActionType (SHUTDOWN, RESTART, SCREENSHOT, KILL_PROCESS, etc.) and ActionState  
 (PENDING, DISPATCHED, ACKNOWLEDGED, RUNNING, SUCCESS, PARTIAL_SUCCESS, FAILED, EXPIRED, CANCELLED).  
 • Dataclasses ActionRecord and ActionTargetRecord in action_framework.py:110-136.  
 • Orchestration / Persistence:  
 • create_action() in action_service.py:66-116 validates action_type and non-empty targets, inserts rows into actions and action_targets, and returns  
 the created record.  
 • get_action() in action_service.py:219-239 queries actions joined with action_targets.

### Wire Message Format (Server → Client)

• When an action is dispatched to a connected client via execute_client_command() (server_lib.py:1504-1523), the TCP frame payload is:  
 {  
 "type": "COMMAND",  
 "command": "<ACTION_NAME_OR_COMMAND>",  
 "args": {  
 "command_id": "<action_id>",  
 ...  
 }  
 }  
 (e.g., {"type": "COMMAND", "command": "REQUEST_SCREENSHOT", "args": {"command_id": "screenshot-1725100000000"}})

### Client-Side Action Routing

• Main Loop Dispatch:  
 • In start_client() (client.py:958-995), incoming messages with msg_type == "COMMAND" have their command normalized via normalize_action_name(message.
get("command")) (action_framework.py:67-72).  
 • High-overhead or non-blocking commands are handled directly in client.py:  
 • SCREENSHOT (client.py:976-984) → calls start_screenshot_command() in a dedicated daemon worker thread.  
 • GET_NETWORK_NEIGHBOURHOOD (client.py:973-975) → calls start_requested_neighbourhood_command().  
 • GET_PASSIVE_NEIGHBOURHOOD (client.py:985-988) → calls get_requested_passive_neighbourhood().  
 • Standard commands route to handle_command() in client_lib.py:1060-1077.  
 • Registry / Dispatch Table:  
 • ActionManager in action_framework.py:112-146 implements register(action_type, handler) and dispatch(message, \*\*context).  
 • ACTION_MANAGER instance is populated in client_lib.py:1025-1058 with handlers for GET_SYSTEM_INFO, GET_NETWORK_INFO, GET_CPU_INFO, GET_MEMORY_INFO,
GET_DISK_INFO, GET_PROCESSES, KILL_PROCESS, START_PROCESS, SHUTDOWN, RESTART, REFRESH_HEALTH, COLLECT_DIAGNOSTICS, GET_ACTIVITY_LOG, QUARANTINE_CLIENT,
RELEASE_CLIENT, GET_QUARANTINE_STATUS, ISOLATE_DEVICE, GET_DEVICE_ISOLATION_STATUS, UPDATE_FORBIDDEN_PROCESS_POLICY, PING, DISCONNECT, UPDATE_LOCATION,
and FLUSH_NEIGHBOURHOOD_STORAGE.

### Client Completion / Failure Reporting (Client → Server)

• The client reports back through send_message() (client.py:1008-1012, client.py:394-398):  
 {  
 "type": "RESPONSE",  
 "command": "<COMMAND_NAME>",  
 "data": {  
 "status": "ok" | "error",  
 ...  
 }  
 }

• Data Support: It supports JSON data only (dictionaries, lists, strings, status, error messages). Raw binary bytes cannot be sent directly; binary data  
 must be base64-encoded strings within JSON.

### Multi-Target Dispatch Status

• Current State: Single-client loop in practice.  
 • In create_action() (action_service.py:76-77), targets must be a list of explicit client ID strings.  
 • In execute_action() (action_service.py:131-189), multi-target execution executes targets sequentially (synchronously in series) within a single thread.
• Group/Zone Resolution: Aspirational only. There is currently no logic resolving device groups or network zones into client lists in action_service.py or
api_server.py.  
 ──────

## 2. Screenshot Transfer Mechanism (Binary-Payload Precedent)

### Encoding & Transport

• Encoding: Base64-encoded string within JSON ("image_base64": base64.b64encode(image_bytes).decode("ascii")) in client.py:385.  
 • Transport: Single frame over TCP with a 4-byte length prefix enclosing the entire JSON message (client_lib.py:1115-1118).

### Frame Size & Limits

• Framing: Sent as a single unchunked frame.  
 • Size Limits:  
 • Client response limit: SCREENSHOT_MAX_RESPONSE_BYTES = 8MB raw (client/client.py:L76-78, client/client.py:L372).  
 • Server storage limit: MAX_SCREENSHOT_BYTES = 8MB raw (server_components/screenshot_storage.py:L55).  
 • Largest payload tested: Unit test in test_screenshot_storage.py:50-58 tests a 1x1 pixel PNG (~70 bytes) and verifies rejection of a 9MB payload.

### Client Send Path

1. Client receives COMMAND for SCREENSHOT / REQUEST_SCREENSHOT in start_client() (client.py:976-984).
2. Worker thread executes \_complete_screenshot_command() (client.py:363-407).
3. Calls ScreenshotManager.capture() (screenshot_manager.py:124-163) which grabs screen, writes to temp file (tempfile.gettempdir()/network-  
   scanner/screenshots/\*.partial), renames atomically to .png.
4. Reads raw bytes, checks size <= 8MB, base64 encodes image, builds response dictionary (client.py:371-386).
5. Acquires socket_lock and calls send_message(client_socket, {"type": "RESPONSE", "command": "REQUEST_SCREENSHOT", "data": response}) (client.py:394-398).
6. Unlinks local temporary PNG file after transmission (client.py:403-406).  


### Server Receive Path

1. receive_client_messages() (server_lib.py:1394-1431) reads frame via receive_message(conn) (server_lib.py:809-828) and puts RESPONSE message into  
   client["responses"] queue (server_lib.py:1416-1419).
2. execute_client_command() dequeues the response (server_lib.py:1529).
3. request_client_screenshot() (server_lib.py:1658-1707) passes data to store_screenshot(client_id, data) (screenshot_storage.py:77-106).
4. store_screenshot calls decode_and_validate_png() (screenshot_storage.py:63-75), which decodes base64, checks PNG headers/CRCs  
   (screenshot_storage.py:17-51), and writes to server/storage/screenshots/<client_id>/<filename>.png.
5. \_persist_screenshot_metadata() (server_lib.py:1615-1656) inserts record into screenshots table.  


### Critical Gap: Client Binary Ingest Path

• Does the client currently have ANY code path for receiving a large binary payload FROM the server?  
 NO. The client only has receive_message() (client_lib.py:1121-1155), which unconditionally decodes entire frames as UTF-8 text and executes json.loads().
• Conclusion: A chunked streaming transfer protocol (where chunks stream directly from incoming socket frames to disk) must be built new.  
 ──────

## 3. Message Framing & Protocol

### Delimitation

• Framing: 4-byte big-endian length prefix followed by UTF-8 encoded JSON bytes (server_lib.py:801-828, client_lib.py:1115-1155).  
 • Header: len(data).to_bytes(4, byteorder="big").  
 • Payload read loop: chunk = sock.recv(min(65536, total - len(data))) accumulating in data until len(data) == total.

### Size Limits & Buffer Observations

• The 4-byte header mathematically allows up to 4GB frames.  
 • However, receive_message() loads the entire payload into RAM as bytes, decodes it to str (2x RAM), and parses JSON (further RAM expansion).  
 • Sending a 50MB–100MB zip in a single JSON frame would lead to substantial memory spikes and risks hitting socket timeouts or OOM on small client devices.
• Command timeouts on the server (timeout=10.0 or 12.0s in action_service.py:177) would expire long transfers if attempted as a single synchronous command.
Chunked transfer with per-chunk progress or dedicated chunk streaming is required.  
 ──────

## 4. Client-Side Filesystem Conventions

### Directory Layout & Storage

• Base directory: CLIENT_DIR = Path(**file**).resolve().parent (client.py:41).  
 • Existing persistent client files:  
 • Startup / Service Log: CLIENT_DIR / "client_service.log" (client.py:61).  
 • State JSON files: CLIENT_DIR / "reported_alerts.json" (client.py:57), CLIENT_DIR / "neighbour_snapshot_state.json" (client.py:58-60), CLIENT_DIR /  
 "forbidden_process_scan.json" (client.py:67), CLIENT_DIR / "client_location.json" (client_lib.py:1086).  
 • Persistent observations: CLIENT_DIR / "storage" / "network_neighbourhood" (neighbourhood.py:17-19).  
 • Ephemeral / Temp storage: Path(tempfile.gettempdir()) / "network-scanner" / "screenshots" (screenshot_manager.py:93-94).

### File & Folder Conventions for Package Staging

• Recommended Staging Location: Dedicated folder under client directory: CLIENT_DIR / "updates" / "incoming" (and CLIENT_DIR / "updates" / "staging" for  
 extraction in Milestone C).
• Atomic Operations: In-flight downloads use .part or .partial extensions and are atomically renamed via os.replace upon SHA-256 verification, matching  
 the pattern in screenshot_manager.py:143-148.
──────

## 5. Other Observations

1. Synchronous Serial Execution: execute_action() in action_service.py:131-189 loops through targets sequentially. If one target times out (12s),  
   subsequent clients are blocked for that duration. Multi-client dispatch (Milestone D) will require concurrency management.
2. Server Message Ingest Routing: In server_lib.py:1416-1419, receive_client_messages() forwards incoming client frames to client["responses"] only if  
   type == "RESPONSE". Any action response must use type: "RESPONSE" to be picked up by the waiting command dispatcher.
3. Client Idempotency Cache: ActionManager.dispatch() in action_framework.py:133-145 caches results by action_id in self.\_seen_actions. If a re-dispatch  
   occurs with the same action_id, the cached result is returned without re-running the handler.
   ──────
   Stop Condition Met: In accordance with the rules of docs/package-send/plan.md, Milestone A is complete and submitted for review before proceeding to  
   Milestone B.
