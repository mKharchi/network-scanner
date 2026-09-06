# Kismet Client Integration

## Prerequisite boundary

Do not design the historical query against `*.kismet` until the deployment prerequisite proves that the installed Kismet version actually writes those files where the query component can read them. The current code only searches the fixed `client/storage/kismet` directory and selects the newest file; it does not know the real Kismet output path, rotation policy, or external sensor location.

The prerequisite phase must first decide whether the querying component runs on the Linux Kismet sensor, on a supported client host, or against an explicitly secured Kismet API/storage boundary. It must also record whether historical queries use one active file, all retained files, an API, or a combination.

## Recommended query boundary after verification

Add a historical query method beside `poll_new_observations()`, conceptually `query_observations(start_time, end_time, device_mac, limit, include_noise)`, only after extracting shared SQLite discovery and row-normalization helpers. The exact signature should follow the existing server result needs and local naming conventions.

`poll_new_observations()` is stateful live monitoring: it uses `_last_processed_timestamp`, `_processed_hashes`, callback delivery, lifecycle counters, and a five-second loop. It must not be reused for arbitrary historical requests because a request would mutate live cursor state and could omit or duplicate records. The historical method should be stateless per request, use a read-only connection, and never invoke the live callback.

## Query responsibilities on the client

The verified Kismet data layer should own:

- actual Kismet source discovery and unavailable-source detection;
- normalized MAC matching against `sourcemac`, `destmac`, and `transmac`;
- exact `ts_sec`/`ts_usec` filtering and ordering;
- Radiotap/frame decoding needed by the current UI contract, if the verified source exposes the required bytes/fields;
- `include_noise` behavior;
- limit enforcement before response construction;
- normalized observation fields, summary, and query-window metadata.

The server should own device identity resolution, target-client selection, request validation, response validation, API error mapping, and any final contract compatibility mapping.

## Files and changes

### `client/app/kismet_listener.py`

- **Current responsibility:** manages the Python database-poller lifecycle, discovers the newest local `.kismet` file, polls rows, normalizes live observations, and tracks health. It does not manage Kismet itself.
- **Required change:** only after the prerequisite passes, adapt the listener/data layer to the verified persistence or API source and add a bounded historical query operation. Preserve `poll_new_observations()` semantics and do not assume the newest file is sufficient if rotation creates multiple historical files.
- **Reason:** the query must use the real deployed Kismet source; duplicating parsing in the command handler would create divergent behavior.
- **Existing pattern:** current read-only SQLite query, normalized dictionary fields, and server service's frame-decoding behavior.
- **Dependencies:** prerequisite acceptance evidence, source/path/API contract, request validation, maximum result constant, and response schema in `06-tcp-protocol.md`.
- **Tests:** extend `client/tests/test_kismet_listener.py` for exact bounds, MAC roles, noise, limits, missing DB, query failures, and no-result success.

### `client/app/client.py`

- **Current responsibility:** owns the connected client command loop and dispatches commands.
- **Required change:** add one command branch that validates `args`, invokes the Kismet historical query, and sends one `RESPONSE` with the echoed request ID and client identity. For slow queries, use the same non-blocking worker approach already used for screenshot/neighbourhood operations only if profiling shows the receive loop must remain responsive; ensure concurrent sends use `socket_lock`.
- **Reason:** this is the existing dispatcher boundary.
- **Existing pattern:** `GET_TELEMETRY_FLOWS`, `start_screenshot_command`, structured `{status, message}` errors.
- **Dependencies:** `KismetListener` instance lifetime and registration-confirmed canonical ID.
- **Tests:** command dispatch, malformed args, response serialization, Kismet unavailable, and disconnect during response.

### `client/app/client_lib.py`

- **Current responsibility:** framing, action dispatch, registration message construction.
- **Required change:** no framing change. Add a command constant only if the repository's action naming conventions require constants; otherwise keep the Kismet command local to the existing command dispatch convention.
- **Reason:** avoid a second protocol layer.
- **Existing pattern:** length-prefixed JSON and normalized command names.
- **Dependencies:** none beyond shared naming.
- **Tests:** serialization/deserialization can use existing client library tests plus a Kismet payload fixture.

## What must not change

- Do not attach the live `observation_callback` to a continuous TCP sender.
- Do not treat listener startup, directory existence, or a synthetic SQLite fixture as proof that Kismet is installed and capturing.
- Do not make `poll_new_observations()` service historical requests.
- Do not copy raw `.kismet` files to the server.
- Do not let a query change `_last_processed_timestamp` or the live deduplication set.
- Do not let client-provided `client_id` override the registered socket identity.
