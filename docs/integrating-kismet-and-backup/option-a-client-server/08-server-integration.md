# Server Integration

## Ownership

`KismetInvestigationService` should remain the owner of the investigation use case and response contract. `server_lib` remains the transport/connection owner. `api_service` remains the API-facing delegation layer. This keeps TCP details out of the HTTP handler and avoids making the database module a transport client.

## Proposed flow

1. `server/api_server.py` continues parsing the existing route parameters.
2. `api_service.get_device_wireless_observations()` calls `KismetInvestigationService`.
3. The service resolves the device using the existing MySQL/network-scan/direct-MAC logic.
4. It determines the capture owner using the repository's device-to-client identity mapping. The implementation must identify the authoritative `client_id`/MAC, not guess from the server filesystem.
5. It normalizes the UI range and validates the limit/noise flag.
6. It checks the selected client is connected through `server_lib.get_client()`.
7. It sends `GET_KISMET_OBSERVATIONS` through a new narrow server helper wrapping `execute_client_command()`.
8. It validates request ID, client ID, query window, status, result types, bounds, and summary consistency.
9. It returns the existing UI response shape or a structured API error.

## File change records

### `server/server_components/kismet_service.py`

- **Current behavior:** scans configured local/server paths and queries all discovered `.kismet` databases.
- **Required change:** add remote-client dispatch and response validation; move or share query normalization/frame formatting with the client; make server filesystem lookup an explicit migration fallback only if retained.
- **Reason:** server cannot read a client machine's local capture.
- **Existing pattern to reuse:** current device resolution, time parsing, result contract, MAC/frame/noise logic, and configured limit.
- **Dependencies:** `server_lib` command helper and a defined capture-owner mapping.
- **Tests:** remote success, offline client, identity mismatch, exact window, empty result, malformed response, fallback policy.

### `server/server_components/server_lib.py`

- **Current behavior:** owns registries, post-registration socket reader, response queues, command send, timeout, and disconnect handling.
- **Required change:** add `request_client_kismet_observations()` beside the telemetry-flow request helper, using `execute_client_command()` and request-ID validation. Keep `receive_client_messages()` as the only reader.
- **Reason:** transport behavior belongs here and must be reused by services.
- **Existing pattern to reuse:** `execute_client_command`, `get_client`, `send_lock`, response queue, `DISCONNECTED`, timeout.
- **Dependencies:** protocol schema and client identity validation.
- **Tests:** selected connection, request serialization, response correlation, concurrency, timeout, disconnect, and wrong client response.

### `server/server_components/api_service.py`

- **Current behavior:** delegates the wireless endpoint and alert investigation to a newly instantiated local Kismet service.
- **Required change:** keep delegation but let the service choose remote dispatch; ensure alert windows and all route arguments pass through unchanged.
- **Reason:** preserve the API boundary and avoid HTTP/TCP coupling.
- **Existing pattern to reuse:** current `get_device_wireless_observations()` and alert helper.
- **Dependencies:** service routing and error mapping.
- **Tests:** API route contract, alert window, offline/error status mapping.

### `server/api_server.py`

- **Current behavior:** parses query parameters and maps `ValueError` to 404 and other errors to 500.
- **Required change:** only adjust mappings if new stable service errors require a 400/409/503 distinction; do not change route names or parameters.
- **Reason:** clients already depend on this endpoint.
- **Existing pattern to reuse:** current `send_data`/`send_error_response` wrapper.
- **Dependencies:** documented error codes.
- **Tests:** status and envelope for invalid range, offline client, unavailable Kismet, and empty success.

## Local fallback policy

The current server scan should not remain the default merely because it exists. Recommended policy: remote client is authoritative whenever a selected client is known; server-local lookup is retained only behind an explicit configuration flag for migration/backward compatibility, with response metadata identifying `source: server-local-fallback`. If the requested client is offline, return a client-unavailable error rather than silently querying another client's or the server's capture.
