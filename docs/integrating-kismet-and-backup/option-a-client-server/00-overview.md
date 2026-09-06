# Kismet Option A: Client-Queried Observations

## Scope

This is an implementation plan only. It describes how the existing wireless investigation API should query the client or sensor that owns the local Kismet capture, using the existing length-prefixed JSON TCP connection and command-response path. It does not implement Python, React, SQL, or protocol changes.

**Prerequisite:** no TCP integration work may begin until [01-kismet-prerequisite-and-deployment.md](01-kismet-prerequisite-and-deployment.md) proves that the supported deployment has a real Kismet runtime, usable capture source, live wireless traffic, known persistence, and historical data accessible to the query component. The current repository does not install or manage Kismet, and a listener that starts without finding a file is not successful capture verification.

## Decision

Use bounded, on-demand request/response:

```text
Wireless Investigation UI
  -> existing REST API
  -> KismetInvestigationService
  -> selected connected client/sensor
  -> existing COMMAND frame
  -> client command dispatcher
  -> KismetListener historical query
  -> actual verified Kismet persistence or API
  -> existing RESPONSE frame
  -> server response queue
  -> KismetInvestigationService normalization
  -> existing REST response
  -> UI
```

The client must never stream all Kismet observations. The server computes an exact UTC interval and sends that interval with each request. The client queries only that interval and returns a bounded result. The prerequisite phase decides whether the historical source is local SQLite, a Kismet API, or a combination; the plan must not assume `.kismet` files until that phase passes.

## Compatibility goals

- Keep the current device wireless-observation REST routes and UI controls.
- Preserve the normalized observation response used by `WirelessInvestigationPanel`.
- Reuse `execute_client_command`, the per-client response queue, `send_message`, `receive_message`, and the existing `RESPONSE` envelope.
- Reuse the client's Kismet SQLite discovery and normalization logic rather than adding a second reader.
- Keep raw Kismet data local; do not add a MySQL row per observation.
- Establish and document Kismet installation, process ownership, capture interface, permissions, storage path/schema/retention, and Linux-sensor versus Windows-client ownership before implementation.
- Remove server filesystem discovery as the normal remote-client path. A server-local lookup may remain only as an explicitly documented fallback during migration, never as an accidental substitute for the requested client.

## Non-goals

- Continuous telemetry.
- Raw `.kismet` file transfer.
- A new socket, framing layer, or authentication mechanism.
- A new wireless-observations MySQL table in Option A.
- UI redesign or new time-range controls.
- Changing the existing Kismet live polling lifecycle except where a shared query helper is needed.
- Installing, configuring, or supervising Kismet as part of this TCP implementation phase.

## Governing invariants

1. `requested client == connected client == authenticated registered client`.
2. Every returned observation satisfies the server-normalized `start <= timestamp <= end` interval.
3. Empty results are successful responses with `observations: []`, not errors.
4. A query failure is represented separately from an empty query.
5. One request has one correlation token, and a response with a different token is not accepted.
6. Option A is blocked until the Kismet prerequisite acceptance gate passes for the actual target deployment.

## Deliverables

The implementation should follow [14-implementation-order.md](14-implementation-order.md) and use [15-implementation-checklist.md](15-implementation-checklist.md) as the gate. The prerequisite evidence is in [01-kismet-prerequisite-and-deployment.md](01-kismet-prerequisite-and-deployment.md). This folder is the complete design record for Option A.
