# Kismet Server-Sensor Implementation Plan and Final Architecture Report

## Supersession notice

This document and `00-kismet-architecture-decision.md` supersede the client-query design documents numbered `00-overview.md` through `16-file-change-matrix.md` and the earlier `progress/phase-0.md` within this directory. Those files are retained as historical evidence and must not be used as the implementation specification. The active phase records are `progress/phase-0-server-architecture.md` and `progress/phase-1.md` through `progress/phase-10.md`.

## A. Current architecture

The repository already has two observation streams. Windows clients collect existing passive protocol, DHCP, ARP/neighbour, packet, flow, and telemetry information. The server persists/merges device information and exposes API/UI views. Separately, the server already contains `KismetInvestigationService`, wireless API helpers, routes, UI types, and a wireless investigation panel.

Current Kismet code is incomplete as deployment architecture: the server service searches configured and hard-coded filesystem directories, while `client/app/kismet_listener.py` polls a presumed client-local database. Neither component launches or manages Kismet. The repository contains no capture database artifact and no implementation of a Kismet TCP command.

## B. Previous Kismet architecture

The former Option A documentation planned remote on-demand retrieval:

```text
UI -> server -> client TCP command -> client KismetListener/local capture -> client response -> server -> UI
```

That plan required client ownership mapping, request IDs, Kismet response queues, and `GET_KISMET_OBSERVATIONS`. It is superseded and must not guide implementation.

## C. New architecture

```text
Windows clients -> existing passive observations -> server
Linux server Wi-Fi adapter -> Kismet -> server persistent capture -> KismetInvestigationService -> API/UI
```

Kismet is one central, server-owned RF observation source. The server queries its own verified Kismet persistence or local authenticated API. Clients remain lightweight and are not a Kismet transport/storage/execution boundary.

## D. Components to keep

- `server/server_components/kismet_service.py` parsing foundations: MAC normalization, device resolution, time parsing, MAC-role matching, frame parsing, noise filtering, channel conversion, and summaries.
- `server/server_components/api_service.py` wireless/alert service integration.
- Existing REST routes and `server/gui/src/components/WirelessInvestigationPanel.tsx` bounded investigation controls.
- Existing client passive discovery, telemetry, flow aggregation, device enrichment, storage, and sync pipeline.
- Existing `observation_sources`/`source_type` conventions, location assignment, and device inventory.
- Existing Kismet pilot, MAC-correlation, storage-pipeline, and coverage documents as historical evidence/reference.

## E. Components to modify

| Component | Required future change |
| --- | --- |
| `server/server_components/kismet_service.py` | Replace hard-coded/development directory discovery with a configured, verified server source; enforce bounded windows and actual source schema/API contract; tag output as `KISMET_SERVER`; add source/health errors. |
| `server/server_components/api_service.py` | Preserve delegation; map stable server-sensor failures to API statuses after service errors are defined. |
| `server/api_server.py` | Adjust only error/status mapping or validated query limits if required. |
| Server configuration/deployment assets | Add verified capture-root, retention, health, and service configuration only after target server evidence. |
| Server tests | Separate synthetic parser fixtures from real Kismet integration tests and cover server-source failures/rotation/boundaries. |
| Existing architecture docs | Mark client-query Option A as superseded and link to this plan without deleting history. |

## F. Components to remove

Removal is deferred until the server reader is operational and tested:

- `client/app/kismet_listener.py`;
- its import, construction, and cleanup in `client/app/client.py`;
- client Kismet listener tests and any client-only diagnostics/event-monitor exclusions that become unused;
- client storage assumptions for `storage/kismet`.

Before removal, preserve any compatible parsing code in a server utility only if the target Kismet source confirms it is needed. Do not move client lifecycle behavior to the server application; external Kismet supervision remains an operating-system/service responsibility.

## G. Components to create

Potential components are deliberately conditional on target-server verification:

- a small server-local Kismet source adapter or repository abstraction inside/alongside `kismet_service.py`;
- server Kismet health reader (service/process/source/storage state) if the verified service/API permits it;
- dedicated server Kismet retention/cleanup job with dry-run and free-space guard;
- deployment service/unit/container configuration managed outside Windows clients;
- server integration tests against a fixture representing the verified target schema.

No new MySQL raw-observation table is planned.

## H. Protocol changes

**No Kismet-specific client/server TCP protocol is required.** `GET_KISMET_OBSERVATIONS` was never implemented and must not be added. Generic TCP improvements remain separate work only if another feature needs them.

## I. Storage architecture

Kismet writes to a target-server verified, high-capacity Linux mount corresponding to the project’s intended `D:` capacity. The actual mount path, filesystem capacity, permissions, and configuration are unknown until target-server inspection. Kismet data stays there; MySQL retains application/device/alert context. Retention is server-controlled, measured from real capture growth, and never deletes an active/journaled file. Existing client JSON retention remains separate.

## J. Query architecture

```text
device ID/MAC + UTC range -> KismetInvestigationService -> canonical MAC + bounded interval
-> verified server Kismet source -> source/destination/transmitter match -> normalized metadata -> API/UI
```

The service returns a successful empty result for no observations and distinct errors for Kismet process/source/storage/query failures. It must not return raw packet payloads or query a client.

## K. Deployment architecture

The Linux server owns Kismet through a documented service manager or approved container supervisor. Prefer wired management plus a dedicated monitor-capable Wi-Fi adapter. Kismet writes to a verified persistent mount; the application has read-only access. Kismet management/API binding stays local/private and authenticated if enabled. Server health checks report Kismet process, capture source, storage, and free-space state.

## L. Testing plan

1. **Real runtime:** target Linux Kismet, adapter, monitor source, traffic, storage, restart, and capacity evidence.
2. **Synthetic/unit:** deterministic source adapter/parser, MAC roles, microsecond time bounds, normalization, limits, errors, and rotation behavior.
3. **Application integration:** UI/API/service/server storage flow; no client TCP activity; alert path, failure/status, and client regressions.

## M. Risks

- Adapter chipset/driver/monitor-mode suitability may require dedicated hardware.
- Kismet versions can change persistence schema/API capabilities.
- Active SQLite/journal/rotation access needs verified safe-read behavior.
- Central single-sensor coverage and RSSI are location-specific; no single-sensor multilateration claim.
- Disk growth and low-space conditions require measured retention and reserve controls.
- Large historical queries need strict range/limit/pagination policy.
- Capture metadata is sensitive; secure filesystem/API access and authorized retention/deletion controls are required.
- Server Kismet failure must not be reported as an empty observation result.

## N. Recommended implementation order

| Phase | Status | Deliverable / exit criterion |
| --- | --- | --- |
| 0 — Linux runtime verification | In progress, blocked by host access | Target server Kismet/service/radio/storage evidence. |
| 1 — Capture-source validation | Pending | Controlled real capture proves active 802.11 observations. |
| 2 — Persistence/storage configuration | Pending | Verified source format/path/schema, mount, growth, rotation/read safety. |
| 3 — Server-side data-access contract | Pending | Source adapter contract and deterministic server query fixtures. |
| 4 — Investigation service | Pending | Refactored server-local bounded query implementation and unit tests. |
| 5 — REST/API integration | Pending | Stable errors and compatible endpoint behavior. |
| 6 — UI integration | Pending | UI validates server-source status/truncation only if needed; existing flow preserved. |
| 7 — Server retention/cleanup | Pending | Measured policy, dry-run, safety reserve, controlled cleanup. |
| 8 — Runtime health monitoring | Pending | Process/source/storage health and recovery behavior. |
| 9 — Integration/regression testing | Pending | Real, synthetic, and application test evidence. |
| 10 — Production deployment | Pending | Supervised startup, access controls, monitoring, rollback plan, and acceptance sign-off. |

Do not implement a later phase before the preceding phase’s acceptance evidence is recorded in `progress/phase-x.md`.
