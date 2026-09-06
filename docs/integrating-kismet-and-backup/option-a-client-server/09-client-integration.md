# Client Integration Details

## Deployment prerequisite

This phase assumes that [01-kismet-prerequisite-and-deployment.md](01-kismet-prerequisite-and-deployment.md) has passed. The client command must query the verified Kismet data source; it must not start an unconfigured daemon, invent a capture path, or return success merely because `KismetListener` is running.

The current client receives no Kismet installation, executable, configuration, or capture interface from its package. If the approved deployment is a separate Linux sensor, document how the query component is colocated with or securely reaches that sensor before implementing this dispatcher.

## Dispatcher design

The intended client path is:

```text
COMMAND GET_KISMET_OBSERVATIONS
  -> existing client command loop
  -> validate args and registered identity
  -> verified Kismet historical data source query
  -> normalized result
  -> RESPONSE with request_id/client_id
```

The listener should be initialized once as it is today in `_ensure_background_services()`. The command handler may use the existing listener/data object only after the verified source is configured. If the source is unavailable, Kismet is not running, the capture interface is invalid, or persistence is not readable, return `KISMET_UNAVAILABLE` rather than constructing a second listener or opening a separate uncontrolled reader.

## Validation at the client

Validate before opening SQLite:

- args is an object;
- request ID is present and bounded;
- `device_mac` normalizes to a valid MAC;
- `client_id`, when present, equals the registration-confirmed ID held by the client;
- start/end parse as UTC and satisfy `start < end`;
- range does not exceed configured maximum;
- limit is an integer within the protocol bounds;
- `include_noise` is boolean.

The server's target selection remains authoritative; this validation is defense in depth.

## Concurrency

A historical query must not mutate the live poller's cursor/deduplication state. Use a read-only SQLite connection per query, close it in all paths, and serialize writes only through the existing socket lock. If concurrent queries are allowed, bound them with a small executor/semaphore so a busy client cannot create unlimited SQLite work.

Do not block the main receive loop with an unbounded operation. The existing screenshot/neighbourhood worker pattern is available if a query may exceed the socket read cadence. The worker must send exactly one response and preserve request ID correlation.

## Response construction

Return normalized observations compatible with the server's current service/UI response. Include `status`, `request_id`, `client_id`, exact `query_window`, observations, summary, and truncation metadata. Distinguish:

- no database: `KISMET_UNAVAILABLE`;
- database opens but SQL fails: `KISMET_QUERY_FAILED`;
- verified Kismet process/source is absent: `KISMET_UNAVAILABLE`;
- valid query with zero rows: `status: ok`, empty list and zero summary;
- invalid input: `INVALID_REQUEST` or `INVALID_TIME_RANGE`.

## What should not be modified

- Registration/authentication semantics.
- Length-prefixed framing.
- The live poll interval and callback behavior.
- Existing telemetry, flow, neighbourhood, screenshot, package, or quarantine commands.
- The client-to-server continuous telemetry architecture.

## Tests

Use the existing temporary SQLite setup in `client/tests/test_kismet_listener.py` for deterministic unit tests, but add a separate operational verification against a real supported Kismet deployment. Test missing executable/service, invalid source, missing/corrupt/incomplete persistence, file rotation, and API/storage availability. Verify that a query for the last ten minutes cannot return a row at eleven minutes ago, including rows sharing the same second but outside the microsecond bound.
