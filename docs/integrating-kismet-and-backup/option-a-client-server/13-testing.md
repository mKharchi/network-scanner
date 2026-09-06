# Testing Strategy

## Unit tests

## Kismet deployment verification

Before TCP integration tests, run an operational verification on each supported deployment class. Record installation/version, process/service state, effective configuration, capture interface and permissions, Kismet logs/API status, real packet activity, persistence path/format/schema, timestamps, rotation, retention, and historical readability. A synthetic `.kismet` fixture does not satisfy this phase.

Cover at least:

- missing Kismet executable or package;
- Kismet fails to start or exits unexpectedly;
- invalid or inaccessible capture interface;
- monitor-mode/driver/permission failure;
- no wireless activity;
- Kismet process active but no records persisted;
- missing, corrupt, incomplete, locked, or rotating database;
- multiple retained capture files;
- Linux sensor versus Windows client ownership;
- Kismet API available/unavailable and authenticated/unauthenticated behavior.

### Time and validation

- preset calculations for 15 minutes, one hour, and 24 hours;
- custom UTC ISO and epoch parsing;
- naive/offset timestamp normalization according to existing conventions;
- inclusive start/end behavior, including microsecond tie cases;
- invalid reversed, malformed, future, and over-maximum ranges;
- limit minimum/default/maximum and boolean noise parsing.

### Client Kismet query

Extend `client/tests/test_kismet_listener.py` with temporary fixtures matching the verified source schema, containing rows before, inside, and after the window. Verify source/destination/transmitter matching, field normalization, frame decoding, noise filtering, deterministic ordering, limit/truncation, missing source, SQL/API failure, and successful empty results. Verify historical queries do not mutate live poller timestamp or hash state.

### Protocol

Test JSON payload serialization through the existing four-byte framing functions. Validate required fields, request ID echo, response schema, error schema, bounds, and rejection of identity mismatch. Test malformed JSON/schema without changing framing code.

### Server command helper

Test selected client lookup, command arguments, response ID matching, response client identity matching, timeout, disconnect sentinel, wrong-command queue entries, and concurrent requests. Use fake registered client/socket/queue fixtures rather than a real network unless existing tests require sockets.

### API/service

Mock the client request helper and assert the service passes the exact normalized start/end, device MAC, limit, and noise flag. Assert existing response shape and error mapping. Test alert-derived windows use the same path.

## Integration tests

Exercise the full bounded path:

```text
HTTP/API request
 -> KismetInvestigationService
 -> server execute_client_command
 -> framed TCP socket
 -> client command dispatcher
 -> local temporary Kismet SQLite
 -> framed RESPONSE
 -> server response queue/validator
 -> HTTP response
```

Use at least two fake clients with distinct databases and identities. Request client A and prove only A's rows are returned. Send a forged response from client B and prove it is rejected.

## Functional matrix

| Scenario            | Expected assertion                                      |
| ------------------- | ------------------------------------------------------- |
| Last 10 minutes     | only rows in exact ten-minute UTC window                |
| Last hour           | exact one-hour bounds echoed and enforced               |
| Last 24 hours       | bounded result and maximum-range policy enforced        |
| Custom range        | exact custom start/end, inclusive boundaries            |
| Empty range         | HTTP success with empty observations and zero summary   |
| Multiple clients    | target client database only                             |
| Concurrent requests | request IDs keep responses paired                       |
| Client disconnect   | structured transport error, no empty success            |
| Kismet unavailable  | `KISMET_UNAVAILABLE`, distinct from empty               |
| Invalid request     | validation error before SQLite query                    |
| Large result        | bounded limit and explicit truncation/error policy      |
| Noise flag          | ACK/CTS/RTS filtering matches existing service behavior |
| Alert investigation | alert interval reaches the target client unchanged      |

## Critical invariant test

Insert records at `T - 10m`, `T - 10m - 1us`, `T`, and `T + 1s`. Query “last 10 minutes” with concrete bounds and assert the outside records never appear. Repeat through the full TCP/API integration test, not only the local query unit test.

## Regression checks

Run existing client Kismet tests, client startup/registration tests, server Kismet service tests, telemetry/seed socket tests, server API tests, and the GUI TypeScript/build checks. Do not modify unrelated failing tests; record pre-existing failures separately.
