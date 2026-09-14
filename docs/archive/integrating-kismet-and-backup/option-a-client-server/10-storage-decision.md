# Storage Decision

## Recommendation: no new MySQL observation table, pending prerequisite verification

Option A should leave raw Kismet observations in the verified Kismet persistence owned by the sensor/client and query them on demand. The server receives only the bounded normalized result needed by the current investigation request. The exact source is conditional: the prerequisite phase must prove `.kismet` SQLite, Kismet API history, or another supported persistence mechanism before the query design is frozen.

```text
UI -> API -> selected client/sensor -> verified Kismet persistence/API -> selected client/sensor -> API -> UI
```

## Evidence from the repository

- `server/scripts.sql` has no Kismet or raw wireless-observation tables.
- Existing telemetry storage persists device identity and aggregate activity windows, not raw packets.
- The UI already requests a time window and limit and displays a bounded investigation result.
- `KismetInvestigationService` already reads raw captures directly and caps results.
- The client already owns the actual capture files; copying every observation would create unnecessary traffic and retention/storage coupling.
- The repository's pilot proves one Linux host writes `.kismet` SQLite, but this is not yet proven for the target client fleet or for the fixed `client/storage/kismet` path.
- Historical data needs are currently investigative and windowed, not a demonstrated reporting or cross-sensor warehouse requirement.

## Why not synchronize raw observations now

Continuous synchronization would violate the explicit requirement, increase network traffic during capture bursts, require a new durable schema and deduplication policy, and force server retention decisions before usage proves they are needed. MySQL would also duplicate the Kismet source of truth without solving the immediate remote-file access problem.

## When storage may become necessary

Revisit server persistence only if measured requirements show one of these:

- clients are frequently offline when investigations occur;
- cross-client or cross-sensor historical search is required;
- query latency from large local Kismet databases is unacceptable;
- retention must outlive local capture files;
- analytics require server-side aggregation over many sensors;
- audit requirements require immutable server-side copies.

That future design should store normalized aggregates or explicitly selected observations, not automatically every raw packet.

## Kismet API versus local persistence

The Kismet API must be evaluated for runtime health and live data. It should be selected for historical queries only if it exposes the required retained fields and time-window semantics reliably. Local SQLite is preferred for historical queries when the prerequisite proves that the query component is colocated with the sensor, the schema is stable, and retention/rotation are understood. A combination is acceptable: API for health/source status and local persistence for bounded historical reads.

## Current server lookup

The existing server-side lookup should not be treated as a storage solution. It is a local filesystem assumption. During migration it may remain as an explicit opt-in fallback for deployments where the server is itself a sensor, but it must never cause a request for client A to return captures from client B or an unrelated server directory.

## No SQL changes in this phase

Do not modify `server/scripts.sql`, create `wireless_observations`, add migrations, or alter telemetry tables as part of Option A planning or implementation step one.
