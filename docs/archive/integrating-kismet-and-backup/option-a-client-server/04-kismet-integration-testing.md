# Kismet Server-Sensor Testing Strategy

## Test levels

### Level 1 — Real Linux Kismet runtime test

Run on the intended Linux server with real radio hardware. A passing test proves the full chain:

```text
Kismet installed -> configured capture source -> monitor-capable adapter -> active frames/devices
-> persisted historical data -> service restart/recovery
```

Record version, service state, capture interface/driver, controlled capture start/end, packet/device growth, known-device MAC visibility, frame/RSSI/frequency availability, output path/files, process/API logs, disk usage, and failures. A process that starts without frames or durable output is a failure.

### Level 2 — Storage and query integration

Against the verified generated source:

- inspect actual schema/API fields and timestamp precision;
- query a known MAC across an exact UTC interval;
- prove records immediately before and after boundaries are excluded while boundary records are included;
- verify source/destination/transmitter matching, noise filtering, ordering, limits, truncation, rotation, active-file read behavior, restart continuity, no-result success, unavailable/corrupt source errors, and storage-permission failure.

Synthetic SQLite fixtures remain valuable for deterministic parser and error tests, but they do not prove the Kismet deployment or schema.

### Level 3 — Application integration

Verify the server-only path:

```text
UI -> REST API -> api_service -> KismetInvestigationService -> server Kismet source -> UI response
```

Cover 15m, 30m, 1h, 4h, 24h, bounded custom windows, invalid MAC/device, invalid/reversed range, empty/future range, missing files, Kismet unavailable, storage unavailable, rotated files, malformed records, max result behavior, alert-derived lookback, and API error mapping.

Assert that no client TCP command is issued for any Kismet investigation and existing client passive discovery/flow behavior remains unchanged.

## Regression suites

- Existing `server/tests/test_kismet_investigation_service.py`: refactor fixtures to the verified server reader contract, keeping synthetic-unit labeling explicit.
- Existing client Kismet listener tests: remove only when client listener removal is implemented and client startup/passive-observation regression tests pass.
- API endpoint and GUI build tests: preserve existing response compatibility.
- Existing client storage retention tests: run separately because client telemetry retention is not Kismet retention.

## Runtime health and failure tests

Health reporting must distinguish:

| Condition | Expected state |
| --- | --- |
| Kismet process stopped | sensor unavailable; history query fails distinctly |
| Adapter/source missing | capture-source failure; no false healthy state |
| Storage unavailable/near capacity | storage health failure; cleanup reserve policy invoked |
| Kismet restart | capture resumes; service reports lifecycle and historical continuity according to verified behavior |
| Server restart | supervisor restarts Kismet if configured; application recovers source access |

## Exit criteria

Production rollout requires: real hardware capture evidence, verified storage/query contract, bounded query tests, health/recovery tests, retention dry-run then controlled cleanup test, application integration pass, and client regression pass after removal of client Kismet code.
