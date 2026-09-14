# Implementation Checklist

## Architecture and contract

- [ ] Complete the Kismet prerequisite acceptance gate before TCP work.
- [ ] Record supported OS/deployment class, Kismet version, installation source, process owner, and startup mechanism.
- [ ] Verify a real capture interface, driver, monitor-mode capability, permissions, and normal-connectivity impact.
- [ ] Run a controlled capture and prove new wireless records are generated.
- [ ] Record the actual Kismet API/persistence source, path, schema, timestamps, rotation, retention, and historical availability.
- [ ] Resolve Linux sensor versus Windows managed-client ownership and the secure data-access boundary.
- [ ] Decide whether Kismet API, local persistence, or both serve health/live/history needs.
- [ ] Confirm the target client mapping for every supported device identifier.
- [ ] Confirm canonical client ID derivation and registration-confirmed identity.
- [ ] Record the exact command, request ID, error codes, and response schema.
- [ ] Preserve the existing REST routes, query parameters, response envelope, and UI fields.
- [ ] Decide and document the finite maximum for `all`/custom ranges.

## Client

- [ ] Do not treat `KismetListener.start()` or directory existence as proof of Kismet operation.
- [ ] Query the verified Kismet source rather than assuming `client/storage/kismet` or the newest file.
- [ ] Add a stateless historical Kismet query path separate from live polling.
- [ ] Reuse local database discovery and shared parsing/normalization logic.
- [ ] Enforce exact UTC start/end bounds and limit before transport.
- [ ] Preserve timestamp microseconds and deterministic ordering.
- [ ] Validate request identity and input types.
- [ ] Return empty success separately from unavailable/query failure.
- [ ] Echo request ID and registered client ID.
- [ ] Bound concurrent query work and close SQLite resources.
- [ ] Add unit and dispatcher tests.

## Server transport

- [ ] Keep `receive_client_messages()` as the only socket reader.
- [ ] Reuse `execute_client_command`, response queue, send lock, timeout, and disconnect sentinel.
- [ ] Match both command and request ID.
- [ ] Validate response client ID against the socket registry.
- [ ] Reject malformed, stale, wrong-client, and out-of-window responses.
- [ ] Add timeout, disconnect, and concurrency tests.

## Server service/API

- [ ] Normalize presets/custom ranges once on the server.
- [ ] Select the requested client without fallback to another client.
- [ ] Replace server filesystem lookup as the normal remote path.
- [ ] Keep local lookup only behind explicit fallback configuration, if needed.
- [ ] Preserve summary/observation fields required by the UI.
- [ ] Route alert investigations through the same remote path.
- [ ] Map stable service errors to appropriate API statuses.

## Storage and performance

- [ ] Do not create a Kismet MySQL table for Option A.
- [ ] Verify actual Kismet persistence before freezing the local-storage design.
- [ ] Document file rotation, retention, sidecar/WAL behavior, and safe historical reads.
- [ ] Measure response size and query latency with realistic captures.
- [ ] Enforce maximum result size and explicit truncation behavior.
- [ ] Add cursor/chunking only if measurement requires it.
- [ ] Verify no continuous Kismet telemetry sender exists.

## Verification

- [ ] Verify Kismet installation, process health, capture source, real packet activity, persistence, and historical queries operationally.
- [ ] Test missing executable, stopped process, invalid interface, permission failure, no activity, missing/corrupt/rotating storage, and API failure.
- [ ] Run last 10-minute, last-hour, last-24-hour, and custom-range tests.
- [ ] Verify outside-window observations never appear.
- [ ] Verify empty result is not reported as retrieval error.
- [ ] Verify offline client, disconnect, timeout, missing database, SQL failure, invalid range, malformed response, identity mismatch, and oversized result.
- [ ] Verify two clients return isolated data.
- [ ] Verify concurrent requests correlate correctly.
- [ ] Run existing client/server Kismet, telemetry, API, and GUI regression checks.
- [ ] Update deployment/operations documentation after implementation, not during this plan-only phase.
