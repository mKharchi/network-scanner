# Phase 0 — Server-Side Architecture Reassessment

**Status:** COMPLETE — architecture decision recorded; target-server runtime evidence is now partially verified in [phase-0-target-server-evidence.md](phase-0-target-server-evidence.md).

**Date:** 2026-09-06

## Decision recorded

The former client-owned Kismet design is abandoned. Kismet is now a Linux-server-owned wireless sensor. Windows clients keep their existing passive discovery, flow, and telemetry duties but have no Kismet process, database, listener, storage, query, transfer, or TCP command.

## Repository findings

- `client/app/kismet_listener.py` is a presumed-local `.kismet` directory poller and does not manage Kismet. Its callback is not wired by `client/app/client.py`.
- `client/app/client.py` imports, starts, and stops that listener; it has no Kismet query command branch.
- `GET_KISMET_OBSERVATIONS` is documentation-only; no code implements it.
- `server/server_components/kismet_service.py` already has the appropriate server ownership and reusable MAC/time/SQLite/Radiotap/noise/normalization logic, but currently includes unverified hard-coded path and pilot assumptions.
- `server/server_components/api_service.py`, the wireless REST routes, and `WirelessInvestigationPanel.tsx` already provide a server-local investigation API/UI boundary and should be preserved where compatible.
- Existing `server_lib.py` TCP command-response machinery is not needed for Kismet under the new design.
- Existing `source_type` conventions include `SERVER_SCAN`, `CLIENT_ARP`, and `CLIENT_DHCP`; Kismet needs independent provenance (`KISMET_SERVER`) rather than a blind merge.
- `client/app/retention_manager.py` is limited to client JSON telemetry artifacts. It is not a Kismet storage cleaner.

## Linux runtime investigation

The current host is an accessible Ubuntu Linux Kismet host. A separate `wlp0s20f3mon` monitor interface successfully captured real packets while the managed `wlp0s20f3` interface remained connected. The short-run evidence and remaining deployment gaps are recorded in [phase-0-target-server-evidence.md](phase-0-target-server-evidence.md).

## Documents created

- `00-kismet-architecture-decision.md`
- `01-kismet-server-deployment.md`
- `02-kismet-storage-and-retention.md`
- `03-kismet-server-investigation.md`
- `04-kismet-integration-testing.md`

## Outcome

No source code, TCP protocol, client behavior, database schema, or UI behavior was changed. Runtime verification has started, but the application implementation gate remains closed until the longer capture, storage lifecycle, service ownership, API hardening, and retention evidence are complete.
