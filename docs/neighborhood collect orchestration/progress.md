## PHASE 1 

### What I inspected

- Read [codebase_audit_report.md](/home/adonis/network-scanner/codebase_audit_report.md) completely.
- Traced the client collector, DHCP listener, client protocol, server ingestion, database storage, JSON storage, merging, global-scan orchestration, REST API, GUI, and relevant tests.
- No code was changed. The pre-existing change to `client/hourly_log.json` was not touched.

### Current discovery flow

```text
Client connects and registers
  ↓
Client receives FORBIDDEN_PROCESSES
  ├─ starts daily passive ARP/neighbour snapshot thread
  └─ starts passive DHCP listener
        ↓
NETWORK_NEIGHBOURS TCP frames
        ↓
server_lib.receive_client_messages()
        ↓
handle_network_neighbour_report()
        ↓
MySQL observations + daily JSON audit/scan file
        ↓
run_manual_scan() merges recent observations by MAC
        ↓
classified device snapshot in server/storage/network_scans/network_scan_YYYY-MM-DD.json
```

The startup snapshot is passive: `send_daily_network_neighbours()` calls `NetworkNeighbourCollector.collect(enrich=True, active_scan=False)`.

### ARP-table data flow

```text
Linux: ip -j neigh show
Windows: arp -a
macOS: arp -an
  ↓
NetworkNeighbourCollector.collect(active_scan=False)
  ↓
Optional DNS/mDNS + OUI enrichment
  ↓
NETWORK_NEIGHBOURS
  source=DAILY_NEIGHBOUR_SNAPSHOT
  ↓
handle_network_neighbour_report()
  ↓
store_client_neighbour_observations()
  ↓
network_devices upsert + CLIENT_ARP observation insert
  ↓
record_daily_neighbour_snapshot()
  ↓
daily server JSON file
```

The client only persists a `last_snapshot_date`/client-MAC marker in `client/neighbour_snapshot_state.json`; it does not yet maintain the required local accumulated daily neighborhood dataset.

### DHCP data flow

```text
Scapy DHCP packet capture
(or limited UDP/68 fallback)
  ↓
DHCPListener.parse_dhcp_packet()
  ↓
client._on_dhcp_obs()
  ↓
NETWORK_NEIGHBOURS
  source=DHCP
  ↓
handle_network_neighbour_report()
  ├─ store_client_dhcp_observations()
  │    └─ network_devices + CLIENT_DHCP observations
  └─ append_daily_dhcp_observation()
       └─ daily server JSON audit file
```

DHCP reports are sent immediately. They are not accumulated locally with ARP-table entries before transmission.

### Current persistence and merging

| Component | File | Function/Class | Responsibility |
|---|---|---|---|
| Passive ARP/neighbour collection | [network_neighbour_collector.py](/home/adonis/network-scanner/client/network_neighbour_collector.py) | `NetworkNeighbourCollector.collect()` | Reads OS neighbour cache and enriches records. |
| Active client ARP scan | [network_neighbour_collector.py](/home/adonis/network-scanner/client/network_neighbour_collector.py) | `discover_active_arp()`, `merge_neighbours_by_mac()` | Scapy ARP sweep and MAC-based merge with passive results. |
| Daily client reporting | [client.py](/home/adonis/network-scanner/client/client.py) | `send_daily_network_neighbours()` | Sends one passive snapshot per calendar day after registration setup. |
| DHCP capture | [dhcp_listener.py](/home/adonis/network-scanner/client/dhcp_listener.py) | `DHCPListener` | Captures and parses DHCP presence information. |
| DHCP transmission | [client.py](/home/adonis/network-scanner/client/client.py) | `_on_dhcp_obs()` | Sends immediate DHCP `NETWORK_NEIGHBOURS` reports. |
| Client reception | [client.py](/home/adonis/network-scanner/client/client.py) | `start_client()` command loop | Handles server commands, including active scan commands. |
| Server reception | [server_lib.py](/home/adonis/network-scanner/server/server_components/server_lib.py) | `receive_client_messages()`, `handle_network_neighbour_report()` | Validates and routes reports based on their source. |
| Database persistence | [network_device_storage.py](/home/adonis/network-scanner/server/server_components/network_device_storage.py) | `_store_observations()`, `store_client_neighbour_observations()`, `store_client_dhcp_observations()` | Upserts device identity and appends source-attributed observations. |
| Daily JSON persistence | [network_scan_storage.py](/home/adonis/network-scanner/server/server_components/network_scan_storage.py) | `record_daily_neighbour_snapshot()`, `append_daily_dhcp_observation()`, `store_network_scan()` | Maintains `network_scan_YYYY-MM-DD.json`. |
| Server merging/deduplication | [network_discovery.py](/home/adonis/network-scanner/server/server_components/network_discovery.py) | `get_recent_client_neighbour_observations()`, `merge_discovery_sources()`, `run_manual_scan()` | Loads fresh `CLIENT_ARP`/`CLIENT_DHCP` observations and deduplicates merged devices by MAC. |
| Current global active orchestration | [global_network_scan.py](/home/adonis/network-scanner/server/server_components/global_network_scan.py) | `GlobalNetworkScanManager` | Batches active ARP requests with bounded concurrency and per-client command/report timeouts. |
| REST/UI triggers | [api_server.py](/home/adonis/network-scanner/server/api_server.py), [LatestScan.tsx](/home/adonis/network-scanner/server/gui/src/pages/LatestScan.tsx), [ClientDetail.tsx](/home/adonis/network-scanner/server/gui/src/pages/ClientDetail.tsx) | global-active endpoints and scan buttons | Exposes and triggers active single-client/global scans. |

### Active ARP scan flow

```text
GUI/API/CLI
  ↓
SCAN_NETWORK or TRIGGER_ARP_SCAN command
  ↓
client.start_active_network_scan()
  ↓
send_active_network_neighbours()
  ↓
NetworkNeighbourCollector.collect(active_scan=True)
  ↓
discover_active_arp() via Scapy srp(Ether/ARP)
  ↓
NETWORK_NEIGHBOURS source=ACTIVE_NEIGHBOUR_SCAN
  ↓
server_lib.handle_network_neighbour_report()
  ↓
CLIENT_ARP persistence + run_manual_scan()
```

The global version is:

```text
POST /api/v1/network/scans/global-active
  ↓
run_global_active_scan()
  ↓
GlobalNetworkScanManager
  ↓
bounded client buckets (default 5)
  ↓
each client receives SCAN_NETWORK with a per-client command timeout
  ↓
each active report has a per-client report timeout
  ↓
results are persisted and merged by MAC
```

There is also a separate server-local active ARP endpoint: `POST /api/v1/network/scans/active` → `run_active_scan()` → `discover_devices()`.

### Problems identified

- The current global “bucketed” orchestration is structurally useful, but it requests active ARP sweeps. It must be repurposed to request already-stored client neighborhood data.
- No unified client-side daily neighborhood file exists. ARP snapshots are collected transiently; DHCP discoveries are transmitted transiently.
- The client sends its daily snapshot after the `FORBIDDEN_PROCESSES` handshake, not immediately on TCP connect.
- The server currently triggers `run_manual_scan()` after every accepted DHCP, daily snapshot, and active-scan report. A bucketed collection should instead merge at controlled orchestration points.
- Server persistence contains both source observations and a daily JSON file. This is appropriate, but the audit report’s older description of timestamped scan files is stale: current `store_network_scan()` updates the daily `network_scan_YYYY-MM-DD.json` file.
- `merge_discovery_sources()` deduplicates output by MAC. Raw historical DB observations intentionally remain append-only; daily snapshots are deduplicated only per reporting client/day.

### Proposed modification

```text
Client
  ├─ passive ARP/neighbour cache collection
  └─ DHCP listener discoveries
          ↓
merge/deduplicate locally by MAC
          ↓
persist one daily local neighborhood file
          ↓
on connection or GET_NEIGHBOURHOOD command
          ↓
send stored neighborhood to server
```

```text
Server global collection
  ↓
create collection job
  ↓
Bucket 1 → GET_NEIGHBOURHOOD to each client → individual timeout
  ↓
persist accepted reports → merge once → update job
  ↓
Bucket 2 → repeat
  ↓
final MAC-deduplicated merge and persisted scan
```

Active ARP functions and endpoints will be retained for future use but removed from the normal client and global-neighborhood workflow.

### What was verified

- Read-only source trace completed for every required path.
- `git diff --check` passed.
- No tests were run because Phase 1 explicitly prohibits code modification; the next phase will add/adjust tests before behavior changes.

### Next step

Phase 2 will disable client active scanning from the normal workflow while retaining its implementation and compatibility surface. It will update the active-scan command entry points so normal neighborhood collection continues only through passive ARP-table and DHCP sources, then run focused client tests.

**WAITING FOR APPROVAL**

## Phase 2 

### What changed

- Disabled all normal active-ARP entry points:
  - Client `SCAN_NETWORK` / `TRIGGER_ARP_SCAN` commands now return `status: "disabled"` without starting a scan.
  - REST active-scan routes return `409 ACTIVE_NETWORK_SCAN_DISABLED`.
  - Removed active scan controls from the GUI and server CLI.
  - Removed `SCAN_NETWORK` from the advertised client command list.
- Retained active-scan implementation for future use:
  - `discover_active_arp()`, `send_active_network_neighbours()`, global scan manager, and server active-scan functions remain in code.
- Added regression tests for passive daily collection and disabled API routes.
- Updated the API contract’s global-active endpoint status.

Modified files: [client.py](/home/adonis/network-scanner/client/client.py), [api_server.py](/home/adonis/network-scanner/server/api_server.py), [server_lib.py](/home/adonis/network-scanner/server/server_components/server_lib.py), GUI scan pages, API contract, and tests.

### What was verified

- Client passive snapshot test confirms `collect(enrich=True, active_scan=False)`.
- DHCP parser tests: passed (3).
- Client collector tests: passed (10).
- Client background scan tests: passed (3).
- Server storage tests: passed (11).
- API integration tests: passed (16), including all disabled active-scan routes.
- GUI production build: passed.
- `git diff --check`: passed.

Known limitation: `server/tests/test_network_discovery.py` could not run in this environment because the `mysql` Python package is unavailable. No code change caused that import failure.

### Current architecture

```text
Passive ARP/neighbour table + DHCP listener
  ↓
existing client daily snapshot / DHCP reporting
  ↓
server validation and storage
  ↓
server-side merge by MAC
```

Active scanning cannot be triggered through the client, REST API, GUI, or CLI. Its code remains dormant for future use.

### Next step

Phase 3 will inspect and stabilize the common client neighborhood representation so ARP and DHCP discoveries can feed the same normalized local model, without yet changing server-side merging or adding local persistence.

**WAITING FOR APPROVAL**

## Phase 3 — Step 3 

### What changed

No files changed. This step was inspection-only.

### What was verified

- ARP/neighbour entries are normalized in `normalise_neighbour()` as:
  `ip_address`, `mac_address`, `entry_type`, optional `interface`.
- `NetworkNeighbourCollector.enrich()` optionally adds `hostname` and `vendor`.
- DHCP parsing produces:
  `mac_address`, `requested_ip`, `hostname`, `vendor_class`, `client_id`, and `dhcp_message_type`.
- The client DHCP callback adapts DHCP data into a neighbour-shaped record and adds DHCP-specific fields before reporting it.
- Existing ARP collector tests and DHCP parser tests cover these source formats.

### Current architecture

```text
ARP/neighbour table
  ↓
{ ip_address, mac_address, entry_type, interface? }
  ↓
optional { hostname, vendor }

DHCP listener
  ↓
{ mac_address, requested_ip, hostname, vendor_class,
  client_id, dhcp_message_type }
  ↓
client callback adapts it to a neighbour record
```

The two sources already overlap on IP, MAC, hostname, and vendor, but they do not yet share one explicit normalized client-neighborhood record or a common local aggregation path.

### Next step

Step 4 will define and implement one normalized client-side neighborhood record, preserving source-specific DHCP metadata and useful enrichment while avoiding duplicate device records. It will not yet introduce local daily-file persistence or server-side merging.

**WAITING FOR APPROVAL**

## Phase 3 complete

### What changed

Added a shared client neighborhood representation.

- Added [neighbourhood.py](/home/adonis/network-scanner/client/neighbourhood.py):
  - `normalise_neighbourhood_observation()`
  - `normalise_dhcp_observation()`
  - `merge_neighbourhood_observations()`
- Updated [network_neighbour_collector.py](/home/adonis/network-scanner/client/network_neighbour_collector.py) so passive ARP-table results use the shared representation.
- Updated [client.py](/home/adonis/network-scanner/client/client.py) so DHCP callbacks use the same representation.
- Added focused normalization tests in [test_neighbourhood.py](/home/adonis/network-scanner/client/tests/test_neighbourhood.py), plus collector integration coverage.

Normalized records now contain:

```text
ip_address, mac_address, hostname, vendor, os,
entry_type, interface, source, sources, observed_at
```

DHCP records additionally preserve `dhcp_message_type`, `dhcp_vendor_class`, and `dhcp_client_id`.

Same MAC+IP observations merge locally while retaining useful ARP/DHCP metadata and their source list.

### What was verified

- New neighborhood normalization tests: passed (3).
- Client neighbor collector tests: passed (11).
- DHCP parser tests: passed (3).
- Python syntax compilation: passed.
- `git diff --check`: passed.

Compatibility: added client-side fields are safely ignored by the existing server validator. No server-side merge or persistence behavior changed.

### Current architecture

```text
Passive ARP table ─┐
                   ├─ normalize → common neighborhood record
DHCP listener ─────┘
                   ↓
             existing immediate reporting
```

The common representation is ready, but daily local storage and local accumulation have not yet been added.

### Next step

Phase 4, Step 5 will add the client’s daily neighborhood file and MAC+IP deduplication for observations collected during the current day.

**WAITING FOR APPROVAL**

## Phase 4 — Step 5 

### What changed

Added daily neighborhood-file storage in [neighbourhood.py](/home/adonis/network-scanner/client/neighbourhood.py):

- `get_daily_neighbourhood_path()`
- `load_daily_neighbourhood()`
- `update_daily_neighbourhood()`

Daily files will use:

```text
client/storage/network_neighbourhood/YYYY-MM-DD.json
```

Writes are atomic. Updates merge observations by MAC+IP, preserving useful ARP/DHCP fields and source metadata.

Added storage coverage in [test_neighbourhood.py](/home/adonis/network-scanner/client/tests/test_neighbourhood.py).

### What was verified

- Daily-file creation, reload, and ARP/DHCP deduplication: passed.
- Neighborhood tests: passed (4).
- Client collector tests: passed (11).
- DHCP parser tests: passed (3).
- Client background tests: passed (3).
- Python syntax compilation and `git diff --check`: passed.

No real client storage file was created during validation; tests use a temporary directory.

### Current architecture

```text
ARP / DHCP
  ↓
normalized neighborhood observation
  ↓
daily-file storage API (ready, not yet invoked)
```

Collection still follows the existing reporting behavior. Step 5 intentionally does not make callbacks persist observations yet.

### Next step

Phase 5, Step 6 will route passive ARP and DHCP discoveries into the daily local file and stop sending a network message for each newly discovered device.

**WAITING FOR APPROVAL**

## Phase 5 — Step 6 complete

### What changed

Updated [client.py](/home/adonis/network-scanner/client/client.py) so normal collection is local-only:

- Added `collect_daily_network_neighbours()`:
  - collects passive ARP/neighbour-table data;
  - writes it to today’s local neighborhood file;
  - does not send a `NETWORK_NEIGHBOURS` frame.
- Preserved `send_daily_network_neighbours()` as a compatibility wrapper; it now only performs local collection.
- Added `store_dhcp_neighbourhood_observation()`:
  - normalizes DHCP data;
  - enriches vendor information where available;
  - writes it to the daily local file;
  - does not transmit immediately.
- DHCP listener callbacks and the background daily collection thread now use these local-storage paths.
- Expanded client tests to assert that daily ARP and DHCP collection do not call `send_message()`.

### What was verified

- Client background tests: passed (4).
- Neighborhood storage/merge tests: passed (4).
- Client collector tests: passed (11).
- DHCP parser tests: passed (3).
- Python syntax compilation and `git diff --check`: passed.

### Current architecture

```text
Passive ARP table ─┐
                   ├─ normalize → update today’s local neighborhood file
DHCP listener ─────┘

No immediate client → server neighborhood transmission
```

The server will not receive newly collected normal ARP/DHCP observations until synchronization is added in the next phase. Disabled active-scan code remains unchanged.

### Next step

Phase 6, Step 7 will load today’s local neighborhood file after successful client registration and send that accumulated snapshot to the server without initiating a scan.

**WAITING FOR APPROVAL**

## Phase 6 — Step 7 complete

### What changed

Added `send_stored_daily_neighbourhood()` in [client.py](/home/adonis/network-scanner/client/client.py).

After `REGISTERED`, the client now:

```text
loads today’s local neighborhood file
  ↓
sends DAILY_NEIGHBOUR_SNAPSHOT to the server
  ↓
requests forbidden-process settings
```

- No ARP collection or active scan is triggered during synchronization.
- If today’s file does not exist, the client sends a valid empty snapshot.
- Existing server-side daily-snapshot validation/persistence remains compatible.

### What was verified

- Client background/synchronization tests: passed (6).
- Neighborhood storage tests: passed (4).
- Client collector tests: passed (11).
- DHCP parser tests: passed (3).
- Server daily-neighbor ingestion tests: passed (11).
- Python syntax compilation and `git diff --check`: passed.

### Current architecture

```text
Client registers
  ↓
send accumulated local daily neighborhood snapshot
  ↓
server validates, stores, and merges it
  ↓
client continues passive ARP/DHCP collection into local storage
```

Known limitation: the current server accepts only one daily snapshot per reporting client/day. If the local file changes after this initial upload, those new observations wait for a later synchronization mechanism—the next phase’s server-request command will address that path.

A generated local file now exists at [2026-08-20.json](/home/adonis/network-scanner/client/storage/network_neighbourhood/2026-08-20.json); I left it untouched.

### Next step

Phase 7, Step 8 will implement `GET_NETWORK_NEIGHBOURHOOD`: the server asks one client to read and transmit today’s local neighborhood file without performing an active scan.

**WAITING FOR APPROVAL**

## Phase 7 — Step 8 complete

### What changed

Added `GET_NETWORK_NEIGHBOURHOOD` support.

- [client.py](/home/adonis/network-scanner/client/client.py) now handles the command by:
  - reading today’s local neighborhood file;
  - sending a `NETWORK_NEIGHBOURS` report with `source=REQUESTED_NEIGHBOURHOOD`;
  - returning promptly with `{status: "ok", observations_sent: N}`;
  - never collecting ARP data or performing active scanning.
- [server_lib.py](/home/adonis/network-scanner/server/server_components/server_lib.py) now persists requested-neighborhood reports without the once-per-day snapshot deduplication.
- Added client and server regression coverage.

### What was verified

- Client command/storage tests: passed (7).
- Neighborhood storage tests: passed (4).
- Client collector tests: passed (11).
- DHCP parser tests: passed (3).
- Server network-device storage tests: passed (12).
- Python syntax compilation and `git diff --check`: passed.

### Current architecture

```text
Server command: GET_NETWORK_NEIGHBOURHOOD
  ↓
Client reads today’s local neighborhood file
  ↓
REQUESTED_NEIGHBOURHOOD report
  ↓
Server validates and persists observations
  ↓
Client command response confirms sent count
```

The command can now be dispatched through the existing low-level server command mechanism. The direct REST/API operation and controlled per-client timeout are intentionally deferred to the next relevant phases.

### Next step

Phase 8, Step 9 will centralize server-side neighborhood merging so reports from multiple clients resolve to one device per MAC while preserving useful IP, hostname, vendor, source, and reporting-client data.

**WAITING FOR APPROVAL**

## Phase 8 — Step 9 complete

### What changed

Centralized server-side neighborhood merging and preserved local source provenance.

- Added `merge_and_persist_client_neighbourhood()` in [network_discovery.py](/home/adonis/network-scanner/server/server_components/network_discovery.py). `run_manual_scan()` remains as its compatibility wrapper.
- Added `merge_and_broadcast_neighbourhood()` in [server_lib.py](/home/adonis/network-scanner/server/server_components/server_lib.py), used by normal daily and requested-neighborhood reports.
- Requested reports now persist and trigger the shared merge path.
- [network_device_storage.py](/home/adonis/network-scanner/server/server_components/network_device_storage.py) now preserves client `arp`/`dhcp` provenance:
  - ARP-only observations → `CLIENT_ARP`
  - DHCP-only observations → `CLIENT_DHCP`
  - observations learned through both → one device with both source-attributed observation rows.
- Merged snapshot devices now retain all observed addresses in `ip_addresses`, while remaining one device per MAC.

No database schema changes were required.

### What was verified

- Server storage/report tests: passed (14).
- Server discovery/merge tests: passed (23), including:
  - two reporting clients with one MAC and two IPs merge into one device;
  - both IPs and sources are retained.
- Client tests remain passing:
  - command/sync tests (7);
  - local storage tests (4);
  - collector tests (11);
  - DHCP parser tests (3).
- Python syntax compilation and `git diff --check`: passed.

Known limitation: one test’s automatic snapshot write could not update `server/storage/network_scans` because that directory is owned by the service account (`nobody:nogroup`) in this workspace. The report was still persisted through the mocked storage path, and the merge failure is handled as nonfatal. The deployment user must have write access to that scan directory.

### Current architecture

```text
Client report
  ↓
validate and preserve arp/dhcp source data
  ↓
network_devices upsert + immutable source observations
  ↓
shared merge-and-persist operation
  ↓
one merged device per MAC
  ├─ primary IP
  ├─ ip_addresses
  └─ observation_sources / reporting clients
```

### Next step

Phase 9, Step 10 will expose a server operation/API to request `GET_NETWORK_NEIGHBOURHOOD` from one connected client, wait for its bounded response, and return a controlled `client_timeout` when necessary.

**WAITING FOR APPROVAL**

## Phase 9 — Step 10 complete

Added the direct client-neighbourhood collection operation:

- `POST /api/v1/clients/{client_id}/network-neighbourhood`
- Sends `GET_NETWORK_NEIGHBOURHOOD` without initiating a scan.
- Uses `NETWORK_NEIGHBOURHOOD_REQUEST_TIMEOUT` (default 12 seconds).
- Returns controlled outcomes: success (200), client timeout (504), unavailable (409), or request failure (502).
- Documented the endpoint in [API_CONTRACT.md](/home/adonis/network-scanner/server/docs/API_CONTRACT.md).
- Added unit and API integration coverage.

Verified successfully:

- 15 server storage/operation tests
- 23 discovery tests
- 18 API integration tests
- Python compilation and `git diff --check`

The known server-storage permission warning remains non-fatal and is handled without interrupting client report processing.

Ready for approval to begin Phase 10: bucket-based collection design.

## Phase 10 — Step 11 complete

### What changed

Documented the bucket-based passive neighbourhood-collection design. No runtime
code, endpoint, database schema, or client behaviour changed in this step.

The implementation boundary is intentionally separate from the dormant active
ARP-scan implementation:

- Retain `GlobalNetworkScanManager` and `run_global_active_scan()` unchanged as
  legacy active-scan code.
- Add a new `GlobalNeighbourhoodCollectionManager` in
  `server/server_components/global_network_scan.py` (the module will be
  renamed only if that becomes necessary for clarity in a later, compatible
  change).
- Add a passive start function alongside `run_global_active_scan()` in
  `server/server_components/network_discovery.py`.
- Add a new explicit passive REST operation, rather than re-enabling the
  legacy `/network/scans/global-active` active-scan route. The exact API
  response and status resource are deferred to the global-result phase.

### Bucket design

```text
online-client snapshot
  ↓
deduplicate targets by reporter MAC and preserve client ID
  ↓
partition stable target order into configurable buckets
  ↓
bucket 1: issue GET_NETWORK_NEIGHBOURHOOD concurrently to at most N clients
  ↓
wait until every request in bucket 1 has a terminal result
  ↓
record per-client results; merge/persist the accepted reports
  ↓
bucket 2 … repeat until no targets remain
  ↓
produce one partial-success collection summary
```

- `GLOBAL_NEIGHBOURHOOD_COLLECTION_BUCKET_SIZE` will configure the maximum
  clients in one bucket (default `5`; invalid values fall back safely).
- A collection uses an online-client snapshot captured under
  `server_lib.clients_lock`; clients connecting later belong to the next
  collection, which keeps the job deterministic.
- Each target retains `client_id`, client MAC, bucket number, dispatch/start/
  completion times, terminal status, observations sent, and a bounded error.
- A bucket is sequential relative to other buckets. Requests *within* a
  bucket run concurrently through a bounded `ThreadPoolExecutor`.
- The worker calls the existing
  `server_lib.request_client_network_neighbourhood(client_id, timeout=...)`.
  It therefore sends `GET_NETWORK_NEIGHBOURHOOD`, never `SCAN_NETWORK`, and
  uses the already-established client request/response protocol.
- Per-client timeout policy will be implemented in Phase 12. The planned
  initial value is the existing `NETWORK_NEIGHBOURHOOD_REQUEST_TIMEOUT`
  default (`12` seconds), captured at collection start so a job is internally
  consistent.
- `completed`, `client_timeout`, `client_unavailable`, and `client_error` are
  terminal results. One non-completed target never prevents the current or a
  later bucket from executing.
- Accepted reports continue to be validated, persisted, and merged by the
  existing report receiver before the successful command response returns.
  The global manager will aggregate result metadata only; it will not invent a
  second observation-storage path.

### Current architecture

```text
Direct request
  server_lib.request_client_network_neighbourhood(client_id)
  ↓
  GET_NETWORK_NEIGHBOURHOOD
  ↓
  client sends stored REQUESTED_NEIGHBOURHOOD report
  ↓
  existing validation → source-attributed persistence → MAC merge

Planned global request
  GlobalNeighbourhoodCollectionManager
  ↓
  Bucket 1 (≤ configured size; concurrent direct requests)
  ↓
  record terminal outcomes; existing receiver persists/merges reports
  ↓
  Bucket 2 (only after Bucket 1 is terminal)
  ↓
  partial-success result
```

### What was verified

- Read `GlobalNetworkScanManager`, `run_global_active_scan()`, the direct
  request operation, current API contract, and the active-manager regression
  test to confirm the new design will not reactivate an ARP flow.
- Confirmed the existing direct request operation returns the terminal states
  required by the proposed manager.
- `git diff --check` had already passed after Phase 9. No code changed in this
  design-only step, so no additional runtime test was required.

### Compatibility and limitations

- Existing active global scan endpoints and manager stay disabled/dormant; no
  legacy client receives an active scan command.
- The direct client endpoint remains available and is the single request
  primitive used by the planned global manager.
- This design does not yet start collections, execute buckets, add timeout
  bookkeeping, expose a global result, or add structured orchestration logs.

### Next step

Phase 11, Step 12 will implement the new passive manager’s first execution
loop: partition the online snapshot, execute one bucket at a time, and issue
concurrent `GET_NETWORK_NEIGHBOURHOOD` requests within each bucket. It will
add focused tests proving that bucket two cannot start before every target in
bucket one reaches a terminal state.

**WAITING FOR APPROVAL**

## Phase 11 — Step 12 complete

### What changed

Implemented the passive bucket executor without re-enabling any active scan.

- Added `GlobalNeighbourhoodCollectionManager` in
  [global_network_scan.py](/home/adonis/network-scanner/server/server_components/global_network_scan.py):
  stable MAC-deduplicated targets, a configurable bucket size (default `5`),
  one collection at a time, sequential buckets, concurrent requests within a
  bucket, and in-memory per-client terminal metadata.
- Added `run_global_neighbourhood_collection()` in
  [network_discovery.py](/home/adonis/network-scanner/server/server_components/network_discovery.py),
  which captures online clients under `server_lib.clients_lock` and starts the
  passive manager.
- Added a regression test proving bucket two cannot dispatch until every
  first-bucket client completes.

Workers call `server_lib.request_client_network_neighbourhood()`, so they use
`GET_NETWORK_NEIGHBOURHOOD` and existing validation, persistence, and
MAC-based merging. They never send `SCAN_NETWORK` or start ARP discovery.

### What was verified

- Python compilation: passed.
- Discovery tests: passed (24), including bucket ordering/concurrency.
- Server storage/direct-request tests: passed (15).
- `git diff --check`: passed.

The existing service-owned scan-directory warning in one test remains nonfatal
and unchanged.

### Current architecture

```text
online-client snapshot
  ↓
GlobalNeighbourhoodCollectionManager
  ↓
Bucket 1: concurrent GET_NETWORK_NEIGHBOURHOOD requests
  ↓ (all terminal)
Bucket 2: concurrent requests
  ↓
… until complete
```

### Compatibility and limitations

- Legacy active manager and disabled active routes remain dormant.
- The passive manager currently uses the direct request operation’s existing
  timeout behaviour. Explicit collection-level timeout policy and resilience
  testing are next.
- No public global passive API route or final global result response exists
  yet; those are intentionally deferred.

### Next step

Phase 12, Step 13 will make per-client timeout policy explicit and prove that
a timeout is recorded while the rest of the bucket and later buckets proceed.

**WAITING FOR APPROVAL**

## Phase 12 — Step 13 complete

Implemented isolated per-client timeouts for passive global collection.

- Added `GLOBAL_NEIGHBOURHOOD_COLLECTION_CLIENT_TIMEOUT`.
- Defaults to `NETWORK_NEIGHBOURHOOD_REQUEST_TIMEOUT` (12 seconds).
- The timeout is captured once when a collection starts and passed separately to each client request.
- A timeout is recorded as `TIMED_OUT`; other clients and later buckets still proceed.
- Collection summaries now expose `request_timeout` and `timed_out`.

Verified:

- Discovery tests: 25 passed, including timeout isolation across buckets.
- Server storage/direct-request tests: 15 passed.
- Python compilation and `git diff --check` passed.

As requested, I did not modify `progress.md`.

Next: Phase 13 — return the global partial-success result.

## Phase 13 — Global result complete

The passive collection summary now returns partial-success metrics:

- `clients_requested`
- `clients_succeeded`
- `clients_failed` (includes unavailable clients)
- `clients_timed_out`
- `devices_discovered` from a final MAC-deduplicated merge
- `buckets_completed`
- `merge_error` when final snapshot persistence fails

A single timeout or unavailable client produces `partial`; it does not stop collection. The final merge runs once after successful requests, preserving the shared persistence and deduplication path.

Verified:

- Discovery tests: 26 passed, including partial success (success + timeout + unavailable).
- Server storage/direct-request tests: 15 passed.
- Python compilation and `git diff --check` passed.

I did not modify `progress.md`.

Next: Phase 14 — structured orchestration logging.

## Phase 14 — Structured logging complete

Added distinct passive-collection lifecycle logs:

- Collection start: target count, bucket size, request timeout.
- Each bucket start and completion.
- Per-client success with observation count.
- Per-client timeout as a warning; unavailable/error outcomes recorded.
- Final partial/completed summary with client counts, devices, and bucket count.

Verified:

- Discovery tests: 27 passed, including lifecycle-log coverage.
- Server storage/direct-request tests: 15 passed.
- Python compilation and `git diff --check` passed.

I did not modify `progress.md`.

Next: Phase 15 — disable/remove the remaining immediate normal neighborhood transmissions, leaving only connection and explicit-request synchronization.

## Phase 15 — Final transmission model complete

Normal discovery is now guarded as local-only:

- Passive ARP collection writes to today’s local neighborhood file.
- DHCP discoveries write to the same file.
- Neither path may send `NETWORK_NEIGHBOURS` immediately.
- Permitted sends remain:
  - after successful registration (`DAILY_NEIGHBOUR_SNAPSHOT`);
  - on `GET_NETWORK_NEIGHBOURHOOD` (`REQUESTED_NEIGHBOURHOOD`).
- Dormant active-scan reporting remains retained for future compatibility and stays disabled in normal workflows.

Added a regression test that performs both passive ARP and DHCP collection and verifies zero network sends.

Verified:

- Client background/transmission tests: 8 passed.
- Neighborhood storage tests: 4 passed.
- Network collector tests: 11 passed.
- DHCP parser tests: 3 passed.
- Python compilation and `git diff --check` passed.

I did not modify `progress.md`.

All steps in the approved neighborhood collection plan are now implemented.