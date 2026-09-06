# Kismet Architecture Decision — Server-Side Wireless Sensor

**Status:** Accepted architecture; implementation is gated on Linux-server verification.

## Decision

Kismet is a **server-owned wireless sensor**. It runs on the Linux server alongside the server application, captures using a server-attached Wi-Fi adapter, and writes its historical data to server-side persistent storage.

```text
Windows clients -> existing passive discovery, flows, and telemetry -> server
Linux server    -> Kismet capture and storage -> KismetInvestigationService -> API/UI
```

Clients do **not** install, launch, supervise, query, or store Kismet. They send no Kismet observations and receive no Kismet-specific commands.

## Superseded design

The earlier `option-a-client-server` documents describe a client/sensor query path (`server -> TCP COMMAND -> client -> KismetListener -> RESPONSE`). That design is superseded by this decision. The documents remain as historical evidence; they must not be used as an implementation specification.

The existing `progress/phase-0.md` is also superseded: its client/sensor ownership gate no longer applies. The new deployment gate is verification of the server's Linux runtime, adapter, capture source, persistence, and storage mount.

## Current repository assessment

| Component | Status under this decision | Action later |
| --- | --- | --- |
| `client/app/kismet_listener.py` | Obsolete client-side poller | Do not delete in planning phase; extract any reusable parsing only after server query contract is verified, then remove listener and tests/imports in a dedicated change. |
| `client/app/client.py` Kismet creation/cleanup | Obsolete | Remove only with client regression coverage. |
| `client/app/event_monitor.py` Kismet exclusions | Obsolete once client Kismet paths are removed | Review in the same cleanup change. |
| `server/server_components/kismet_service.py` | Conceptually correct location | Refactor to a configured server-owned source; retain reusable MAC, time, radiotap, noise-filter, normalization, and summary logic. |
| API/UI investigation flow | Useful | Preserve its existing REST route, time controls, and response shape unless a verified source contract forces a compatible extension. |
| `server_lib.py` TCP request/response machinery | Unrelated but useful infrastructure | No Kismet protocol work is required. Do not add Kismet request IDs, queues, commands, or response validation. |
| Client passive discovery/flows | Separate observation source | Keep unchanged. |

## Target flow

```text
WirelessInvestigationPanel
  -> existing REST API
  -> api_service
  -> KismetInvestigationService
  -> configured server-local Kismet repository or verified Kismet history API
  -> bounded normalized results
  -> existing API envelope
  -> UI
```

The service receives a device identifier, resolves the application MAC using existing rules, normalizes the requested UTC interval on the server, queries only matching server-owned Kismet records, applies limits/noise filtering, and returns observations tagged `KISMET_SERVER`.

## Observation-source boundary

Client and Kismet data remain separate:

| Source | Owner | Meaning |
| --- | --- | --- |
| `CLIENT_ARP`, `CLIENT_DHCP`, existing client telemetry types | Windows client agent | Distributed endpoint/network observations; retain their existing `observation_sources` handling. |
| `KISMET_SERVER` | Linux server Kismet sensor | RF observation from the physical location and radio coverage of the server sensor. |

The existing network-discovery model already retains `source_type` values such as `SERVER_SCAN`, `CLIENT_ARP`, and `CLIENT_DHCP`; any future Kismet source representation should extend that convention rather than merge records blindly or create a packet-per-row MySQL table.

## Localization implication

One centralized Kismet sensor adds RSSI and wireless-presence evidence at **one physical observation point**. It can complement endpoint location and client observations, but it cannot provide multilateration by itself. Multi-sensor localization is a future expansion requiring separately placed, time-synchronized sensors and calibrated measurements.

## Non-goals

- No client Kismet installation or storage.
- No `GET_KISMET_OBSERVATIONS` client command; repository audit found no implementation of it.
- No raw Kismet packet copy into MySQL.
- No exposure of raw Kismet storage or management API to clients.
- No claim that pilot storage/schema/interface facts are verified for the target Linux server.
