**Completed**
- Files inspected: [Passive Protocol Listener — Implementation Plan.md](/home/adonis/network-scanner/Passive%20Protocol%20Listener%20%E2%80%94%20Implementation%20Plan.md), [codebase_audit_report.md](/home/adonis/network-scanner/codebase_audit_report.md), [README.md](/home/adonis/network-scanner/README.md), [client/client.py](/home/adonis/network-scanner/client/client.py), [client/client_lib.py](/home/adonis/network-scanner/client/client_lib.py), [client/network_neighbour_collector.py](/home/adonis/network-scanner/client/network_neighbour_collector.py), [client/dhcp_listener.py](/home/adonis/network-scanner/client/dhcp_listener.py), [client/neighbourhood.py](/home/adonis/network-scanner/client/neighbourhood.py), [client/user_agent.py](/home/adonis/network-scanner/client/user_agent.py), [client/install_user_logon_task.ps1](/home/adonis/network-scanner/client/install_user_logon_task.ps1), [client/uninstall_user_logon_task.ps1](/home/adonis/network-scanner/client/uninstall_user_logon_task.ps1), [client/stop_windows_client.ps1](/home/adonis/network-scanner/client/stop_windows_client.ps1), [server/server.py](/home/adonis/network-scanner/server/server.py), [server/server_components/server_lib.py](/home/adonis/network-scanner/server/server_components/server_lib.py), [server/api_server.py](/home/adonis/network-scanner/server/api_server.py), [server/gui/src/api/client.ts](/home/adonis/network-scanner/server/gui/src/api/client.ts), [server/gui/src/pages/ClientDetail.tsx](/home/adonis/network-scanner/server/gui/src/pages/ClientDetail.tsx), [server/gui/src/pages/LatestScan.tsx](/home/adonis/network-scanner/server/gui/src/pages/LatestScan.tsx)
- Files changed: none.
- Functions/classes added: none.
- Existing functionality preserved: yes, untouched.
- Tests performed: none yet.

**Current Architecture**
- The Windows startup path is already per-user and non-service based: `client/install_user_logon_task.ps1` creates the scheduled task, `client/user_agent.py` is the logon entry point, and that hands off to `client/client.py`.
- The client already does the right kind of staged startup in `client/client.py`: connect, register, receive `REGISTERED`, sync the stored daily neighbourhood, request forbidden processes, then start background work including `DHCPListener`.
- The existing passive DHCP path is isolated in `client/dhcp_listener.py`, and the daily neighbour snapshot logic is isolated in `client/network_neighbour_collector.py` plus `client/neighbourhood.py`.
- On the server, `server/server_components/server_lib.py` already has the core TCP command queue, response routing, and the existing `GET_NETWORK_NEIGHBOURHOOD` request flow.
- The REST API already exposes client-command dispatch and the current neighbourhood request endpoint in `server/api_server.py`.
- The GUI already has the client-detail action bar in [server/gui/src/pages/ClientDetail.tsx](/home/adonis/network-scanner/server/gui/src/pages/ClientDetail.tsx) and the API wrapper in [server/gui/src/api/client.ts](/home/adonis/network-scanner/server/gui/src/api/client.ts), so a new action can follow the same pattern later.

**Issues / Limitations**
- The repo snapshot here does include `client/`, but the top-level README still shows an older, broader project layout, so some docs are slightly out of sync with the current file tree.
- `GET_PASSIVE_NEIGHBOURHOOD` does not exist yet anywhere in the client, server, or GUI.
- There is no passive protocol observation buffer module yet, so the new feature will need a new client-side component rather than extending the DHCP listener directly.
- I have not changed the Windows tasking/startup mechanism, which matches the plan’s phase-0 constraint.

**Next Step**
- Implement the new client-side `PassiveProtocolListener` skeleton with bounded in-memory observation storage and lifecycle hooks, then wire in `GET_PASSIVE_NEIGHBOURHOOD` as a separate command path without touching the existing `GET_NETWORK_NEIGHBOURHOOD` flow.

If you want, I can start that next phase now.
## Completed

- Phase 2 feature boundary defined.
- Files changed: none.
- New component: `PassiveProtocolListener`, separate from existing ARP/neighbourhood and DHCP paths.
- Existing functionality preserved: yes.
- Tests performed: none; no code changed.

## Current Architecture

`PassiveProtocolListener` will be a new client-only component with one controlled capture worker, bounded in-memory observations, and protocol-specific parsing for mDNS, LLMNR, NBNS, and SSDP. It will not write to daily neighbourhood storage or send observations continuously.

Existing `DHCPListener` remains unchanged and independent.

## Issues / Limitations

- Windows/Npcap capture availability and per-protocol traffic must be validated before implementing capture behavior.
- No protocol parsers or client lifecycle wiring exist yet.

## Next Step

Phase 3: document and validate capture support, privilege requirements, expected metadata, and practical limitations for mDNS, LLMNR, NBNS, SSDP, DHCPv6, and LLDP/CDP.
## Completed

- Phase 3 protocol-support research completed in [protocol-support.md](/home/adonis/network-scanner/docs/passive%20protocol%20listener/protocol-support.md).
- Initial implementation scope: mDNS, LLMNR, NBNS, and SSDP.
- Deferred: DHCPv6, LLDP, and CDP.
- Existing ARP, DHCP, daily-neighbourhood storage, and startup behavior remain untouched.
- Validation: documentation reviewed; `git diff --check` passed.

## Current Architecture

The future listener will use the same Scapy/Npcap capture prerequisite as DHCP, with one bounded capture worker and no active probing. Windows requires Npcap for Scapy capture. [Scapy documentation](https://scapy.readthedocs.io/en/stable/installation.html)

mDNS/DNS-SD can provide names, services, addresses, and TXT metadata; LLMNR is local name resolution; NBNS provides legacy Windows names; SSDP exposes passive UPnP advertisements. [mDNS RFC](https://www.rfc-editor.org/info/rfc6762/), [DNS-SD RFC](https://www.rfc-editor.org/info/rfc6763/), [LLMNR RFC](https://www.rfc-editor.org/info/rfc4795/), [NBNS RFC](https://www.rfc-editor.org/info/rfc1002/)

## Issues / Limitations

- Visibility is limited to traffic delivered to each client interface; switched-network and multicast behavior must be verified on the real center network.
- No live Windows/Npcap validation has occurred yet.
- DHCPv6 is intentionally deferred because it needs separate handling and cannot reliably provide a MAC address.

## Next Step

Phase 4: define the normalized passive-observation contract and bounded deduplication rules before writing the listener module.

## Completed

- Phase 4 observation contract added: [observation-contract.md](/home/adonis/network-scanner/docs/passive%20protocol%20listener/observation-contract.md).
- Defines one schema for mDNS, LLMNR, NBNS, and SSDP.
- Defines validation, metadata limits, 512-entry memory limit, and protocol-specific deduplication keys.
- Existing DHCP, ARP, daily-neighbourhood storage, and `GET_NETWORK_NEIGHBOURHOOD` remain unchanged.
- Validation: `git diff --check` passed.

## Current Architecture

Passive observations will remain independent evidence records, never merged into existing device/neighbourhood records. They are held in memory, deduplicated, and returned only on a later explicit request.

## Issues / Limitations

- The contract is designed but not implemented yet.
- `vendor` and `model` remain optional and only accept directly advertised metadata; no OUI lookup or `LOCATION` fetching will occur.

## Next Step

Phase 5: implement `client/passive_protocol_listener.py` with the bounded buffer, normalization, deduplication, lifecycle methods, and controlled Scapy capture worker.
## Completed

- Phase 5 implemented [passive_protocol_listener.py](/home/adonis/network-scanner/client/passive_protocol_listener.py).
- Added [test_passive_protocol_listener.py](/home/adonis/network-scanner/client/tests/test_passive_protocol_listener.py).
- Added:
  - `PassiveProtocolListener` with one controlled Scapy worker and `start()` / `stop()`.
  - `PassiveObservationBuffer` with a 512-entry default bound, protocol-specific deduplication, and oldest-entry eviction.
  - Safe parsers for mDNS, LLMNR, NBNS, and SSDP.
  - Normalization and bounded `raw_fields` validation.
- Existing DHCP, ARP/neighbourhood storage, socket behavior, and client startup remain untouched.

## Tests

- `python3 -m unittest client/tests/test_passive_protocol_listener.py client/tests/test_dhcp_parser.py client/tests/test_neighbourhood.py`
- Result: `14` tests passed.
- `python3 -m py_compile client/passive_protocol_listener.py`
- `git diff --check` passed.

## Current Architecture

The new listener is fully isolated. It only buffers packets already visible to the selected interface; it does not persist data, send messages, follow SSDP `LOCATION` URLs, or initiate discovery traffic.

## Issues / Limitations

- The listener has not yet been started by `client.py`; that is intentionally reserved for Phase 6.
- Real Windows/Npcap validation is still required.
- DHCPv6, LLDP, and CDP remain deferred.

## Next Step

Phase 6: instantiate and stop `PassiveProtocolListener` alongside the existing DHCP listener in the client session lifecycle, without blocking command handling.
## Completed

- Phase 6 wired `PassiveProtocolListener` into [client.py](/home/adonis/network-scanner/client/client.py:541).
- It starts after `FORBIDDEN_PROCESSES`, beside the existing DHCP listener.
- It reuses the same DHCP-selected interface, including `DHCP_LISTEN_INTERFACE`.
- It stops during normal session cleanup, independently of DHCP.
- Added session lifecycle coverage in [test_client_background_scan.py](/home/adonis/network-scanner/client/tests/test_client_background_scan.py:298).
- Removed test-generated entries from the tracked client log.

## Tests

- `13` client lifecycle/background tests passed.
- `6` passive-listener tests passed.
- `3` DHCP parser tests passed.
- `5` neighbourhood tests passed.
- Syntax compilation and `git diff --check` passed.

## Current Architecture

After client registration and configuration:

```text
Daily neighbour snapshot thread
DHCPListener
PassiveProtocolListener
Background activity scanner
```

The new listener remains in-memory only and does not alter DHCP or neighbourhood reporting.

## Issues / Limitations

- No real Windows/Npcap capture validation yet.
- Protocol startup state is not yet clearly logged per protocol.

## Next Step

Phase 7: add explicit passive-listener startup and availability logging without changing capture behavior.

## Completed

- Phase 7 startup/availability logging added to [passive_protocol_listener.py](/home/adonis/network-scanner/client/passive_protocol_listener.py:582).
- The listener now reports:
  - `Starting...`
  - mDNS, LLMNR, NBNS, and SSDP parser readiness
  - overall `AVAILABLE`, `PARTIALLY_AVAILABLE`, or `UNAVAILABLE` state
  - capture fallback/unavailability reasons
  - capture-worker shutdown
- [client.py](/home/adonis/network-scanner/client/client.py:660) sends these messages through the existing startup log, including `client_service.log`.
- Lifecycle tests no longer write to the real startup log.

## Tests

- `28` tests passed:
  - passive listener: `7`
  - client lifecycle/background: `13`
  - DHCP parser: `3`
  - neighbourhood: `5`
- Syntax compilation and `git diff --check` passed.

## Current Architecture

The passive listener still uses one capture worker, but exposes per-protocol parser availability. A protocol failure can result in `PARTIALLY_AVAILABLE` without stopping the remaining protocol parsers.

## Issues / Limitations

- Shared Scapy/Npcap capture failure makes every UDP protocol unavailable; this is logged per protocol and overall.
- No live Windows/Npcap validation yet.

## Next Step

Phase 8: validate the client-side observation buffer behavior against the contract, including snapshot safety, bounded retention, and deduplication under listener activity.
## Completed

- Phase 8 client-side buffer behavior validated.
- Added regression coverage in [test_passive_protocol_listener.py](/home/adonis/network-scanner/client/tests/test_passive_protocol_listener.py):
  - repeated observations refresh rather than duplicate
  - refreshed observations survive bounded-buffer eviction
  - snapshots are defensive copies and cannot mutate listener memory
- Existing `PassiveObservationBuffer` remains in-memory only, thread-safe, capped at `512` by default, and independent of daily-neighbourhood/DHCP storage.

## Tests

- `30` tests passed:
  - passive listener: `9`
  - client lifecycle/background: `13`
  - DHCP parser: `3`
  - neighbourhood: `5`
- Syntax compilation and `git diff --check` passed.

## Current Architecture

Captured passive evidence enters only `PassiveObservationBuffer`. No packets are persisted or sent to the server during capture. Duplicate protocol evidence updates `observed_at` and `seen_count`; capacity evicts the least recently observed record.

## Issues / Limitations

- Buffer contents remain lost when the client session ends, by design.
- No client command exposes the buffer yet.

## Next Step

Phase 9: add the separate `GET_PASSIVE_NEIGHBOURHOOD` client command path while preserving existing `GET_NETWORK_NEIGHBOURHOOD` behavior exactly.

## Completed

- Phase 9 added `GET_PASSIVE_NEIGHBOURHOOD` in [client.py](/home/adonis/network-scanner/client/client.py).
- The command reads only `PassiveProtocolListener.snapshot()`.
- It does not trigger ARP collection, DHCP handling, daily-neighbourhood file access, persistence, or continuous reporting.
- Existing `GET_NETWORK_NEIGHBOURHOOD` behavior remains unchanged.
- Added request-isolation coverage in [test_client_background_scan.py](/home/adonis/network-scanner/client/tests/test_client_background_scan.py).

## Tests

- `31` tests passed:
  - client lifecycle/background: `14`
  - passive listener: `9`
  - DHCP parser: `3`
  - neighbourhood: `5`
- Syntax compilation and `git diff --check` passed.

## Current Architecture

`GET_NETWORK_NEIGHBOURHOOD` still uses the existing daily ARP/DHCP snapshot path. `GET_PASSIVE_NEIGHBOURHOOD` now uses only the new in-memory passive-observation buffer.

## Issues / Limitations

- The passive command currently returns the raw bounded snapshot through the normal command response mechanism.
- The specified response envelope with `observed_at`, reporter identity, and `observations` is intentionally pending Phase 10.

## Next Step

Phase 10: define and implement the final `GET_PASSIVE_NEIGHBOURHOOD` response payload.
## Completed

- Phase 11: added server command support in [server_lib.py](/home/adonis/network-scanner/server/server_components/server_lib.py:1439).
  - Sends `GET_PASSIVE_NEIGHBOURHOOD` to one connected client.
  - Validates the response envelope and allowed protocols.
  - Does not store, merge, or add passive observations to existing device records.

- Phase 12: added `POST /api/v1/clients/{client_id}/passive-neighbourhood` in [api_server.py](/home/adonis/network-scanner/server/api_server.py:342).
  - Returns the bounded passive snapshot.
  - Maps client timeout to `504`, unavailable client to `409`, and malformed/failed responses to `502`.
  - Added API coverage in [test_api_endpoints.py](/home/adonis/network-scanner/server/tests/test_api_endpoints.py).
  - Added server-command coverage in [test_passive_protocol_requests.py](/home/adonis/network-scanner/server/tests/test_passive_protocol_requests.py).

## Tests

- API suite: `21` passed.
- Passive server-command tests: `3` passed.
- Syntax compilation and `git diff --check` passed.

The API test output includes harmless `ResourceWarning` messages from expected HTTP-error test cases; all tests passed.

## Current Architecture

```text
GUI (pending)
  -> POST /clients/{id}/passive-neighbourhood
  -> server command queue
  -> GET_PASSIVE_NEIGHBOURHOOD
  -> client in-memory snapshot
  -> validated API response
```

No passive data enters existing neighbourhood or `NetworkDevice` storage.

## Next Step

Phase 13: add a GUI API wrapper and client-detail action that requests the passive snapshot and displays its observation/protocol summary.
## Completed

- Phase 13 GUI integration added.
- [client.ts](/home/adonis/network-scanner/server/gui/src/api/client.ts) now exposes `requestClientPassiveNeighbourhood()`.
- [ClientDetail.tsx](/home/adonis/network-scanner/server/gui/src/pages/ClientDetail.tsx) now includes:
  - `Get Passive Network Information` action
  - requesting, success, and error toast states
  - offline/loading protection
  - a result card showing observation count, observed endpoints, detected protocols, latest observation, snapshot time, and reporter

## Validation

- `npm run build` passed: TypeScript compilation and Vite production build succeeded.
- `git diff --check` passed.

The build emitted non-fatal stream-file-descriptor warnings from the restricted environment, but completed successfully.

## Current Architecture

The GUI requests only:

```text
POST /api/v1/clients/{id}/passive-neighbourhood
```

The displayed result is transient client-provided passive evidence. It does not alter device records, daily neighbourhood data, or global collection.

## Next Step

Phase 14: verify feature separation end to end, ensuring passive observations remain independent from ARP, DHCP, `NetworkDevice`, and existing neighbourhood workflows.
## Completed

- Phase 14 separation verification completed.
- Added regression tests proving:
  - [client.py](/home/adonis/network-scanner/client/client.py) passive requests do not read/write daily-neighbourhood storage or send `NETWORK_NEIGHBOURS`.
  - [server_lib.py](/home/adonis/network-scanner/server/server_components/server_lib.py) passive requests do not enter device storage, report ingestion, merging, or global collection.
- Existing ARP/DHCP and `GET_NETWORK_NEIGHBOURHOOD` paths remain independent.

## Tests

- `57` tests passed across client, passive listener, server command, API, DHCP, and neighbourhood suites.
- API suite initially could not bind its loopback test port in the sandbox; it passed when rerun with local socket permission.
- Syntax compilation and `git diff --check` passed.

## Current Architecture

```text
Passive listener buffer
  -> GET_PASSIVE_NEIGHBOURHOOD
  -> server command queue
  -> dedicated REST endpoint
  -> client-detail GUI card
```

This path does not use `NETWORK_NEIGHBOURS`, daily local files, `network_devices`, `network_device_observations`, or global-neighbourhood collection.

## Issues / Limitations

- Passive observations are intentionally transient and disappear when the client session ends.
- The existing [client_service.log](/home/adonis/network-scanner/client/client_service.log) contains real capture-permission failures from prior runtime activity; it was left untouched. Live Windows validation still requires Npcap and appropriate capture permissions.
- The listener can initially report ready before Scapy confirms capture access, then correctly transitions to `UNAVAILABLE` if capture setup fails.

## Next Step

Phase 15: expand protocol, lifecycle, command/API, and GUI validation coverage, then prepare for real-network testing.