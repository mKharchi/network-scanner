# Kismet Option A Plan Summary

## Purpose

Correct the current architecture so the server no longer assumes that client Kismet capture files are available on the server filesystem. Kismet observations remain on the client that captured them and are queried only when the UI requests an investigation.

This summary is implementation planning only. It does not authorize or include Python, React, SQL, TCP, API, or UI changes.

**New prerequisite:** Option A is blocked until [01-kismet-prerequisite-and-deployment.md](01-kismet-prerequisite-and-deployment.md) proves that Kismet is installed, running, capturing from a valid source, persisting real observations, and making the requested historical data accessible. The current repository does not install or manage Kismet.

## Target Architecture

```text
UI
  -> existing REST API
  -> KismetInvestigationService
  -> selected authenticated client/sensor
  -> existing TCP COMMAND frame
  -> client command dispatcher
  -> verified Kismet runtime and capture source
  -> verified Kismet persistence/API
  -> KismetListener historical query
  -> bounded TCP RESPONSE
  -> server response queue and validator
  -> KismetInvestigationService
  -> existing API response envelope
  -> UI
```

The client must not continuously send Kismet observations. Each UI request produces one bounded query for one exact time interval. The verified deployment phase decides whether historical data comes from local `.kismet` SQLite, the Kismet API, or both; the summary must not assume `.kismet` files exist.

## Deployment Finding

The repository's pilot report documents one successful Linux Kismet sensor using `wlp0s20f3mon` and a `.kismet` SQLite database, including 81,969 packets over 41.23 minutes. The managed client installation and packaging are Windows-oriented and contain no Kismet executable, configuration, capture-source setup, or API integration. A current development-host check found Kismet binaries but no running Kismet process or repository capture files. Therefore the pilot is evidence of feasibility, not proof that target clients are deployed.

The first phase must resolve Linux sensor versus Windows client ownership, installation and startup, capture-interface capability, permissions, storage path/schema/rotation/retention, Kismet API availability, and the secure boundary through which the query component accesses historical data.

## Existing Architecture Being Reused

- TCP uses four-byte big-endian length-prefixed JSON frames.
- The server has one post-registration reader, `receive_client_messages()`.
- Server commands use `execute_client_command()` and a per-client response queue.
- Client commands are dispatched in the existing `client/app/client.py` connection loop.
- `GET_TELEMETRY_FLOWS` is the closest existing server-to-client request/response pattern.
- Client identity is established during registration and represented by the canonical MAC-derived `client_id`.
- The current UI already supports `15m`, `30m`, `1h`, `4h`, `24h`, custom UTC/ISO ranges, limits, noise filtering, and the normalized observation response.

No new socket, framing system, authentication mechanism, or continuous telemetry channel is needed.

## Proposed Protocol

Use the existing envelopes with a new command such as `GET_KISMET_OBSERVATIONS`.

Request data should include:

- unique `request_id`;
- expected `client_id`;
- normalized device MAC;
- UTC `start_time` and `end_time`;
- bounded `limit`;
- `include_noise`.

The client returns one `RESPONSE` containing:

- `status`;
- echoed `request_id` and registered `client_id`;
- exact `query_window`;
- normalized observations;
- summary values;
- `truncated` and optional cursor metadata.

The server accepts a response only when command, request ID, client ID, query window, status, and observation structure all validate. A response from another client or another concurrent request is rejected.

## Time-Range Rules

The server resolves UI presets into concrete UTC bounds before dispatching:

- `15m`, `1h`, and `24h` become `end = current UTC time` and `start = end - duration`;
- custom ranges use the existing ISO/epoch conventions;
- alert investigations preserve their existing `[detected_at - lookback, detected_at]` window;
- bounds are inclusive and echoed in the response;
- timestamps retain Kismet seconds and microseconds;
- invalid, reversed, ambiguous, or over-maximum ranges fail validation;
- default and maximum result limits remain bounded, initially matching the existing 500 default and 2,000 service cap.

The critical invariant is:

> A request for the last 10 minutes must never return an observation outside that exact interval.

## Client Changes Planned

### `client/app/kismet_listener.py`

Add a stateless historical query operation alongside, but separate from, `poll_new_observations()`. Reuse local database discovery, SQLite access, MAC matching, timestamp handling, frame decoding, noise filtering, normalization, and summary logic. Historical queries must not mutate the live poller's timestamp or deduplication state.

### `client/app/client.py`

Add one command-dispatch branch for the Kismet request. Validate arguments, call the existing listener/data layer, and send one structured response. Return distinct errors for invalid input, unavailable Kismet, query failure, and empty success. Do not attach the live observation callback to a continuous TCP sender.

### `client/app/client_lib.py`

Keep framing unchanged. Add a command constant only if required by local naming conventions.

## Server Changes Planned

### `server/server_components/server_lib.py`

Add a Kismet-specific request helper beside the existing flow request pattern. Reuse client lookup, send locks, `execute_client_command()`, response queues, timeout handling, disconnect sentinels, and the single socket reader. Add request-ID and registered-client validation for concurrent safety.

### `server/server_components/kismet_service.py`

Keep ownership of the investigation use case and normalized API response. Resolve the device, select its authoritative client, normalize the time window, dispatch the remote request, validate the result, and return the existing UI-shaped response.

The current server-side `.kismet` scan must not remain the normal remote path. It may remain only as an explicit, documented server-local fallback for migration or deployments where the server is itself a sensor. It must never silently query another client's data.

### `server/server_components/api_service.py` and `server/api_server.py`

Preserve the existing API delegation, routes, parameters, response envelope, and alert investigation flow. Adjust error mappings only when stable remote error codes require distinct HTTP statuses.

### SQL and frontend

Do not modify `server/scripts.sql` for Option A. Do not modify the existing UI or API client unless a contract regression is demonstrated. The UI already expresses the required bounded-query behavior.

## Storage Decision

Do not create a `wireless_observations` MySQL table. Raw observations remain in the verified Kismet persistence owned by the sensor/client and are fetched on demand. Local `.kismet` SQLite remains the preferred historical source only if Phase 0 proves that the deployed Kismet version writes it where the query component can read it; otherwise the plan must use the actual discovered API/storage source.

This fits the repository because:

- the client owns the capture files;
- existing MySQL tables store device identity and aggregate telemetry, not raw packets;
- the UI requests bounded investigation windows;
- synchronization of every packet would increase traffic, storage, deduplication, and retention complexity;
- no current requirement demonstrates a need for server-side raw-observation search.

Reconsider server persistence only if offline investigations, cross-sensor analytics, retention, or audit requirements justify it later.

## Error Semantics

Empty results are successful:

```text
status = ok
observations = []
summary.observation_count = 0
```

Failures remain distinct and use stable codes such as:

- `CLIENT_OFFLINE`;
- `CLIENT_TIMEOUT`;
- `KISMET_UNAVAILABLE`;
- `KISMET_QUERY_FAILED`;
- `INVALID_REQUEST`;
- `INVALID_TIME_RANGE`;
- `RESULT_TOO_LARGE` or explicit truncation;
- `MALFORMED_RESPONSE`;
- `IDENTITY_MISMATCH`.

Never convert a transport, identity, database, or protocol failure into an empty observation result. Do not automatically retry the first implementation; preserve the same normalized time window if bounded retries are added later.

## Testing Requirements

Unit tests should cover time normalization, exact inclusive bounds, MAC matching, frame/noise handling, limits, serialization, request validation, response validation, identity checks, timeout, disconnect, and historical-query isolation from live polling.

Integration tests should exercise:

```text
HTTP -> service -> server TCP -> client dispatcher -> verified Kismet source
  -> client TCP response -> server queue/validator -> HTTP
```

Use at least two clients with separate databases. Verify that the requested client is the only data source and that a forged or mismatched response is rejected.

Functional coverage must include:

- last 10 minutes;
- last hour;
- last 24 hours;
- custom ranges;
- empty results;
- multiple clients;
- concurrent requests;
- client disconnect;
- Kismet unavailable;
- invalid requests;
- large results;
- alert-derived ranges;
- noise filtering.

The boundary test must include records just before, exactly at, and just after the requested interval, and must be executed through the full TCP/API path.

## Implementation Order

1. Prove Kismet installation, runtime, capture source, real packet activity, persistence, API/storage access, and Linux/Windows ownership.
2. Freeze the verified Kismet source contract and block TCP work if the gate fails.
3. Freeze current API, UI, timestamp, identity, and Kismet service fixtures.
4. Define the command, request/response schema, error codes, limits, and request-ID policy.
5. Adapt and unit-test the client historical query against the verified source.
6. Add and test the client command-dispatch branch.
7. Add and test the server request helper and correlation validation.
8. Route `KismetInvestigationService` to the selected client/sensor.
9. Preserve API and alert behavior while adding precise error mappings.
10. Run operational capture verification plus two-client end-to-end and ten-minute boundary tests.
11. Run existing client, server, telemetry, API, and GUI regression checks.
12. Add pagination/chunking only if measured payloads require it, then roll out with explicit fallback configuration.

## Detailed Plan Documents

- [00-overview.md](00-overview.md): scope, decision, invariants, and non-goals.
- [01-kismet-prerequisite-and-deployment.md](01-kismet-prerequisite-and-deployment.md): actual Kismet installation, capture, persistence, API, deployment models, verification procedure, and acceptance gate.
- [02-current-architecture.md](02-current-architecture.md): current client, server, database, API, and UI behavior.
- [03-existing-tcp-flow.md](03-existing-tcp-flow.md): reusable TCP request/response path and correlation limits.
- [04-kismet-runtime-and-storage.md](04-kismet-runtime-and-storage.md): verified runtime, persistence, API decision, and deployment evidence contract.
- [05-kismet-client-integration.md](05-kismet-client-integration.md): client query boundary and file-level responsibilities.
- [06-tcp-protocol.md](06-tcp-protocol.md): proposed payloads, validation, correlation, and size strategy.
- [07-time-range-query.md](07-time-range-query.md): UTC normalization, inclusivity, limits, and pagination policy.
- [08-server-integration.md](08-server-integration.md): service ownership, routing, fallback, and server file changes.
- [09-client-integration.md](09-client-integration.md): dispatcher, validation, concurrency, and client test anchors.
- [10-storage-decision.md](10-storage-decision.md): rationale for keeping observations in verified local Kismet storage.
- [11-api-ui-flow.md](11-api-ui-flow.md): preserved API/UI contract and alert flow.
- [12-error-handling.md](12-error-handling.md): error matrix, retry policy, and observability.
- [13-testing.md](13-testing.md): deployment, unit, integration, functional, and regression strategy.
- [14-implementation-order.md](14-implementation-order.md): staged implementation sequence.
- [15-implementation-checklist.md](15-implementation-checklist.md): implementation and verification gates.
- [16-file-change-matrix.md](16-file-change-matrix.md): complete file/class/function handoff and architecture diagram.
