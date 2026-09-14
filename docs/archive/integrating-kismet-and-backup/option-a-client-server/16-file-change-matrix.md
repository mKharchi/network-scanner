# File Change Matrix

This matrix is the implementation handoff. It names the current anchor, intended responsibility, reuse point, dependency, and test gate for every proposed code change. It is subordinate to the operational acceptance gate in [01-kismet-prerequisite-and-deployment.md](01-kismet-prerequisite-and-deployment.md).

| File                                                       | Class/function                                                         | Current behavior                                                                           | Required change                                                                                             | Reason                                     | Existing pattern to reuse                                        | Dependencies                                             | Tests                                                               |
| ---------------------------------------------------------- | ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------- | ------------------------------------------ | ---------------------------------------------------------------- | -------------------------------------------------------- | ------------------------------------------------------------------- |
| `client/app/kismet_listener.py`                            | `KismetListener`, `poll_new_observations`, new historical query helper | Python poller reads the newest local `.kismet`; it does not manage Kismet or prove capture | After prerequisite approval, adapt to the verified source and add stateless bounded historical query        | Query must use real deployed Kismet data   | Verified source contract plus existing parser/formatter behavior | deployment evidence, protocol schema, limits, UTC parser | `client/tests/test_kismet_listener.py` and operational capture test |
| `client/app/client.py`                                     | connected command loop                                                 | Dispatches existing `COMMAND` frames; no Kismet command branch                             | Add Kismet command branch only after verified source availability and one structured response               | Existing client TCP boundary               | `GET_TELEMETRY_FLOWS`, screenshot worker, socket lock            | verified source, registered ID                           | startup/dispatcher and unavailable-source tests                     |
| `client/app/client_lib.py`                                 | `send_message`, `receive_message`                                      | Four-byte length-prefixed JSON                                                             | No framing change; optional command constant only                                                           | Prevent second TCP architecture            | Existing framing                                                 | protocol naming                                          | serialization fixtures                                              |
| `server/server_components/server_lib.py`                   | `receive_client_messages`                                              | Sole response reader and queue router                                                      | Keep sole reader; add Kismet request wrapper and correlation validation                                     | Transport ownership and identity binding   | `execute_client_command`, flow helper, `DISCONNECTED`            | request ID, canonical client                             | socket/queue/concurrency tests                                      |
| `server/server_components/kismet_service.py`               | `KismetInvestigationService.query_wireless_observations`               | Current production path scans server-visible `.kismet` directories; no remote dispatch     | Dispatch to selected verified client/sensor; validate and normalize remote response; explicit fallback only | Server cannot assume remote Kismet storage | current device/time/result contract                              | verified source, client-owner mapping, server helper     | service routing and fallback tests                                  |
| `server/server_components/api_service.py`                  | wireless and alert functions                                           | Delegates to local Kismet service                                                          | Preserve delegation while using remote service path                                                         | Keep API boundary stable                   | existing functions and alert windows                             | service routing                                          | API/alert tests                                                     |
| `server/api_server.py`                                     | wireless route handler                                                 | Parses existing query and maps errors                                                      | Only adjust status mapping if stable remote errors require it                                               | Preserve UI contract                       | current route/envelope helpers                                   | error code policy                                        | endpoint status tests                                               |
| `server/scripts.sql`                                       | schema                                                                 | No raw Kismet tables                                                                       | No change in Option A                                                                                       | On-demand local storage is sufficient      | existing aggregate telemetry storage decision                    | none                                                     | confirm schema unchanged                                            |
| `server/gui/src/components/WirelessInvestigationPanel.tsx` | fetch/render/export                                                    | Already requests bounded windows and renders normalized result                             | No change expected                                                                                          | UI already expresses requirement           | existing lookback/custom flow                                    | response compatibility                                   | existing GUI build plus contract fixture                            |
| `server/gui/src/api/client.ts`                             | `getDeviceWirelessObservations` and types                              | Sends range/limit/noise and expects result fields                                          | No change expected; fix only demonstrated contract mismatch                                                 | Avoid frontend scope expansion             | current endpoint client                                          | canonical response mapping                               | TypeScript/build                                                    |

## Final architecture diagram

```text
UI: WirelessInvestigationPanel
  |
  v
Existing API route and api_service
  |
  v
KismetInvestigationService
  |  resolve device -> select authenticated client -> normalize UTC window
  v
Existing server TCP COMMAND / execute_client_command
  |
  v
Authenticated client TCP dispatcher
  |
  v
Verified Kismet runtime and capture source
  |
  v
Kismet persistence/API accessible to query component
  |
  v
KismetListener historical query/data layer
  |
  v
Bounded normalized RESPONSE with request_id/client_id
  |
  v
Existing server TCP response reader and per-client queue
  |
  v
KismetInvestigationService validation/response shaping
  |
  v
Existing API envelope
  |
  v
UI
```
