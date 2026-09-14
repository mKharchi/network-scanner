# Neighborhood Collection & Server Orchestration Plan

## Objective
Refactor the current network-neighborhood collection flow so that:
- Clients do not perform active ARP scans on demand anymore.
- Existing active-scan functions remain in the codebase but are disabled/not used for now.
- Clients continuously build a daily local neighborhood file from the information they already collect.
- Neighborhood data includes both:
  - ARP/neighbour-table discoveries.
  - DHCP listener discoveries.
- Clients send their accumulated neighborhood data:
  - When they connect to the server.
  - When the server explicitly requests it.
- The server becomes responsible for orchestrating collection from multiple clients.
- Global collection is performed in buckets rather than querying all clients simultaneously.
- Each client request has its own timeout.
- The server merges the returned data and handles deduplication.

Every step must be validated before proceeding to the next step.

## Development Rules
The IDE AI must work strictly one step at a time.
After completing each step, **STOP**.
Do not automatically continue to the next step.

At the end of every step provide:
1. **What was changed**
   List:
   - files modified
   - functions modified
   - functions added/removed
   - behavioral changes
   - compatibility considerations
2. **What was verified**
   List:
   - tests executed
   - manual tests performed
   - expected vs actual behavior
   - any known limitations
3. **Current architecture**
   Briefly explain how the relevant flow works after the changes.
4. **Next step**
   Explain exactly what the next step will modify and why.

Then wait for explicit approval before continuing.

## Phase 1 — Inspect Before Modifying
Before making any code changes, inspect the existing implementation and understand how neighborhood discovery currently works.

The following document is a required reference:
`network-scanner/codebase_audit_report.md`

Read this file completely before proceeding. It contains the existing analysis of:
- Network Discovery & Architecture
- Current discovery sources
- How devices/neighbors are discovered
- The device discovery flow
- The existing architecture diagram
- Scan-related files and their responsibilities
- How ARP-table discovery currently works
- How DHCP discovery/results currently work
- How neighborhood data is represented
- How neighborhood data currently moves from client → server
- Existing scan files and storage mechanisms

### Required Phase 1 Workflow
The IDE AI must:
1. Read `network-scanner/codebase_audit_report.md` completely.
2. Inspect the actual source code referenced by the report.
3. Identify every component involved in neighborhood discovery.
4. Identify the exact code paths for:
   - ARP/neighbour-table collection
   - DHCP discovery/listening
   - neighborhood aggregation
   - neighborhood persistence on the client
   - neighborhood transmission to the server
   - server-side reception
   - server-side persistence
   - server-side merging/deduplication
5. Identify the existing active ARP scan implementation and all places where it is invoked.
6. Determine which existing functionality should be:
   - removed from the normal workflow,
   - disabled,
   - retained but unused,
   - or preserved for possible future use.

Do not modify anything yet.

### Phase 1 Deliverable
When the inspection is complete, stop and report back with:

1. **Current Discovery Flow**
   Show the actual current flow, for example:
   ```
   ARP / DHCP
       ↓
   Client neighborhood collector
       ↓
   Client storage
       ↓
   Client → Server
       ↓
   Server processing
       ↓
   Database / scan storage
   ```
   Use the actual project implementation, not assumptions.

2. **Active ARP Scan Flow**
   Show exactly how the current active scan works:
   ```
   Server
     ↓
   client command
     ↓
   client active scan
     ↓
   result
     ↓
   server
   ```
   Identify the relevant files/functions.

3. **Neighborhood Data Flow**
   Explain separately how:
   - ARP-table results are collected
   - DHCP results are collected
   - both are combined, if they are
   - data is stored
   - data is transmitted
   - data is merged on the server

4. **Files and Functions**
   Provide a table:
   | Component | File | Function/Class | Responsibility |
   | --- | --- | --- | --- |
   | ARP discovery | ... | ... | ... |
   | DHCP discovery | ... | ... | ... |
   | Neighborhood storage | ... | ... | ... |
   | Client transmission | ... | ... | ... |
   | Server reception | ... | ... | ... |
   | Server merging | ... | ... | ... |
   | Active scan | ... | ... | ... |

5. **Proposed Modification**
   Explain precisely what will change to implement the new architecture:
   ```
   Client
     ↓
   continuously gather neighborhood
     ↓
   store daily neighborhood locally
     ↓
   server connection
     ↓
   send stored neighborhood
   ```
   and:
   ```
   Server requests one client
           ↓
   client sends neighborhood
           ↓
   server stores/merges it
   ```
   and:
   ```
   Server requests global neighborhood
           ↓
           ├── Bucket 1 → clients → collect
           ├── merge results
           ├── persist results
           │
           ├── Bucket 2 → clients → collect
           ├── merge results
           ├── persist results
           │
           └── ...
   ```

Do not implement this yet.

### Validation Gate
At the end of Phase 1, provide:
```
PHASE 1 COMPLETE

What I inspected:
...

Current architecture:
...

Active ARP scan:
...

Neighborhood discovery:
...

ARP data flow:
...

DHCP data flow:
...

Current persistence:
...

Current client → server flow:
...

Files/functions involved:
...

Problems identified:
...

Proposed changes:
...

Phase 2 will:
...

WAITING FOR APPROVAL
```
Do not proceed to Phase 2 until I explicitly approve it.

## Phase 2 — Disable Client Active Scans
### Step 2 — Remove Active Scan From the Normal Workflow
Modify the client workflow so that:
- Active ARP scanning is no longer triggered.
- Existing active-scan implementation remains available in the codebase.
- Existing functions should not be deleted unless proven unnecessary.
- Existing APIs should not be unnecessarily removed.

The goal is:
```
OLD
Server
  ↓
SCAN_NETWORK
  ↓
Client performs active ARP scan
  ↓
Client reports result

NEW
Client
  ↓
Existing neighbourhood collection
  ↓
Local daily storage
```
The server should no longer depend on `SCAN_NETWORK` for neighborhood discovery.

### Verify
Test that:
- client starts normally
- client still collects neighborhood data
- DHCP collection still works
- ARP/neighbour-table collection still works
- no active ARP scan is automatically triggered

**STOP**
Wait for approval.

## Phase 3 — Understand and Stabilize Local Collection
### Step 3 — Verify How Neighborhoods Are Gathered
Inspect the existing collection implementation.
The client should gather neighborhood information from:
- **ARP / neighbour table**
  For example: IP, MAC, interface, entry type
- **DHCP**
  For example: MAC, requested IP, hostname, vendor class, client ID, timestamp
- **Enrichment**
  Where available: hostname, vendor, OS

Do not redesign enrichment yet.
The objective is simply to make sure both sources feed the same neighborhood representation.

### Step 4 — Define the Normalized Neighborhood Record
Establish one internal representation for a neighborhood device.
For example:
```json
{
    "ip_address": "172.16.0.102",
    "mac_address": "E4:FD:45:BA:8B:96",
    "hostname": "DESKTOP-DJP05CM",
    "vendor": "Microsoft",
    "os": null,
    "source": "arp",
    "observed_at": "..."
}
```
DHCP information can populate additional fields:
```json
{
    "source": "dhcp",
    "hostname": "DESKTOP-DJP05CM"
}
```
If the same device is discovered through multiple mechanisms, preserve the useful information instead of creating unnecessary duplicate devices.

**Important:** Do not implement server-side merging yet. This phase only establishes the client's collection representation.

**STOP**
Wait for approval.

## Phase 4 — Daily Client Neighborhood Storage
### Step 5 — Implement Daily Neighborhood File
The client should maintain a local file for the current day.
Conceptually:
```
client/
└── storage/
    └── network_neighbourhood/
        └── 2026-08-20.json
```
The exact location should follow the project's existing storage conventions.
The file represents:
Everything this client has learned about its network neighborhood during the current day.
Every new observation should be added to the daily file.
Example:
```json
{
    "date": "2026-08-20",
    "observations": [
        {
            "ip_address": "172.16.0.102",
            "mac_address": "E4:FD:45:BA:8B:96",
            "hostname": "DESKTOP-DJP05CM",
            "source": "dhcp",
            "observed_at": "..."
        }
    ]
}
```

### Deduplication
The client should avoid blindly appending the exact same observation repeatedly.
At minimum, identify records using:
- MAC + IP
while preserving timestamps when useful.
Do not over-engineer historical storage yet.

**STOP**
Wait for approval.

## Phase 5 — Add Observations Locally
### Step 6 — Change Collection From "Send Immediately" to "Store Locally"
Currently the client may behave like:
```
Device detected → Send to server
```
Change this to:
```
Device detected → Normalize → Enrich → Save/update today's neighborhood file
```
The DHCP listener should follow the same principle:
```
DHCP request detected → Normalize → Save/update today's neighborhood file
```
The client should not send a network message for every discovery.
This is the key architectural change.

### Verify
Generate:
- ARP discoveries
- DHCP discoveries
and verify that both appear in the daily local file.

**STOP**
Wait for approval.

## Phase 6 — Send Neighborhood on Client Connection
### Step 7 — Initial Neighborhood Synchronization
When the client successfully connects and registers with the server:
```
Client connects → Register → Load today's neighborhood file → Send neighborhood snapshot → Server stores it
```
This should happen after successful registration, not before.
If the file does not exist:
- send empty neighborhood
- or an explicit result.
The client should not crash because no neighborhood has been collected yet.

**Important:** The connection-time transmission should represent the accumulated local state, not trigger a new active ARP scan.

**STOP**
Wait for approval.

## Phase 7 — Direct Client Neighborhood Request
### Step 8 — Server → One Client
Implement a server command allowing the server to ask a specific client:
`GET_NETWORK_NEIGHBOURHOOD`

Flow:
```
Server
  │
  │ GET_NETWORK_NEIGHBOURHOOD
  ▼
Client
  │
  │ Read today's neighborhood file
  ▼
Client
  │
  │ Send neighborhood
  ▼
Server
  │
  │ Persist / merge
  ▼
Storage
```
The client should:
- not perform an active scan
- read its accumulated local data
- send the result
- return promptly

### Timeout
Use a reasonable per-client timeout.
A client that does not respond must not block the server indefinitely.

**STOP**
Wait for approval.

## Phase 8 — Server-Side Merge
### Step 9 — Centralize Neighborhood Merging
Before implementing global orchestration, ensure the server has one reliable merge operation.
The merge must handle:
- Client A reports: MAC X → IP 1
- Client B reports: MAC X → IP 1
Result: one device

It must also handle:
- Client A: MAC X → IP 1
- Client B: MAC X → IP 2
without incorrectly creating two physical devices solely because the IP changed.
The merge should preserve useful information from different reports.
For example: MAC, IPs observed, Hostnames observed, Vendors, Sources, First seen, Last seen, Reporting clients.

Do not redesign the existing database schema unless necessary.
Reuse existing network-device storage where possible.

**STOP**
Wait for approval.

## Phase 9 — Direct Request API
### Step 10 — Add Server Operation for One Client
Expose a server-side operation such as:
`Request neighborhood from client X`

The implementation should:
- locate the client
- send `GET_NETWORK_NEIGHBOURHOOD`
- wait up to the configured timeout
- receive the neighborhood
- validate it
- merge it
- persist it
- return the result

A timeout should produce a controlled failure (`client_timeout`) and not crash the server.

**STOP**
Wait for approval.

## Phase 10 — Global Collection Orchestration
### Step 11 — Design Bucket-Based Collection
Only after the direct-client flow works should global collection be implemented.
For example, with 25 clients:
```
25 clients
   ↓
Bucket 1 → clients 1–5
Bucket 2 → clients 6–10
Bucket 3 → clients 11–15
Bucket 4 → clients 16–20
Bucket 5 → clients 21–25
```
The exact bucket size should be configurable.

## Phase 11 — Execute One Bucket at a Time
### Step 12 — Bucket Execution
For each bucket:
```
Take bucket
     ↓
Send GET_NETWORK_NEIGHBOURHOOD to all clients in bucket
     ↓
Wait concurrently
     ↓
Each client has individual timeout
     ↓
Collect successful responses
     ↓
Record failed/timed-out clients
     ↓
Merge successful results
     ↓
Persist merged results
     ↓
Move to next bucket
```
Important: Clients inside a bucket should still be queried concurrently.
The goal is not serial querying, but bucketed concurrency:
```
       ┌→ client 1
       ├→ client 2
Server ├→ client 3
       ├→ client 4
       └→ client 5
             ↓
        collect results
             ↓
           merge
```
Then move to the next bucket.
This prevents 25 clients from creating one enormous uncontrolled request burst.

## Phase 12 — Per-Client Timeout
### Step 13 — Isolate Client Failures
Every client request must have its own timeout.
Example:
```
Bucket 1
Client 1 → success
Client 2 → success
Client 3 → timeout
Client 4 → success
Client 5 → success
             ↓
Merge 1, 2, 4, 5
Record client 3 as timeout
             ↓
Continue to Bucket 2
```
A single problematic client must never prevent the global collection from completing.

## Phase 13 — Global Scan Result
### Step 14 — Produce a Global Collection Result
The server should return something similar to:
```json
{
    "status": "completed",
    "clients_requested": 25,
    "clients_succeeded": 22,
    "clients_failed": 1,
    "clients_timed_out": 2,
    "devices_discovered": 37,
    "buckets_completed": 5
}
```
This makes the operation observable.
Do not report global failure simply because one client failed.
Use a partial-success model.

## Phase 14 — Observability
### Step 15 — Add Structured Logging
Log:
```
[INFO] Global neighborhood collection started: 25 clients
[INFO] Bucket 1/5 started: 5 clients
[INFO] Client A responded: 14 observations
[WARNING] Client B timed out
[INFO] Bucket 1 completed
...
[INFO] Global neighborhood collection completed
```
This will make diagnosing the current "everything times out" problem much easier.

**STOP**
Wait for approval.

## Phase 15 — Remove Immediate Neighborhood Reporting
### Step 16 — Finalize the New Transmission Model
Once all previous phases work, remove/disable the old behavior where every newly detected device causes an immediate server transmission.
Final client behavior should be:
```
                    ┌───────────────┐
                    │ ARP/neighbour │
                    │    table      │
                    └───────┬───────┘
                            │
                            ▼
                    ┌───────────────┐
                    │ DHCP listener │
                    └───────┬───────┘
                            │
                            ▼
                    ┌───────────────┐
                    │ Normalize +   │
                    │ enrich        │
                    └───────┬───────┘
                            │
                            ▼
                 ┌─────────────────────┐
                 │ Today's neighborhood│
                 │       file          │
                 └──────────┬──────────┘
                            │
                ┌───────────┴───────────┐
                │                       │
          Client connects        Server requests
                │                       │
                └───────────┬───────────┘
                            ▼
                         Server
```

## Final Architecture
The target architecture should be:
```
CLIENT 1 ─┐
CLIENT 2 ─┤
CLIENT 3 ─┤
CLIENT 4 ─┤
...       ├── local daily neighborhood files
CLIENT 25 ┘
                 │
                 │ on connection
                 │ or explicit request
                 ▼
        ┌──────────────────────┐
        │       SERVER         │
        │                      │
        │  Bucket orchestrator │
        │          ↓           │
        │   Receive results    │
        │          ↓           │
        │      Merge           │
        │          ↓           │
        │      Deduplicate     │
        │          ↓           │
        │       Persist        │
        └──────────────────────┘
```

## Final Implementation Order
The IDE AI must implement in this exact order:
1. Map current neighborhood pipeline
2. Disable active ARP scans from normal client workflow
3. Verify ARP + DHCP neighborhood collection
4. Define normalized neighborhood record
5. Implement daily client neighborhood storage
6. Change discovery from immediate-send → local storage
7. Send neighborhood when client connects
8. Implement direct server → client neighborhood request
9. Centralize server-side merge/deduplication
10. Implement direct-client request operation
11. Design bucket-based global collection
12. Execute buckets concurrently internally
13. Add per-client timeouts
14. Return global partial-success results
15. Add structured orchestration logging
16. Remove/disable immediate neighborhood transmission

## Critical Constraint
**DO NOT IMPLEMENT THE WHOLE PLAN IN ONE PASS.**
After every single step, stop and provide:

```
STEP COMPLETED
──────────────

Changes:
...

Files modified:
...

Tests / verification:
...

Current behavior:
...

Potential issues:
...

NEXT STEP
─────────
...

Waiting for approval.
```
The developer will manually review and approve each step before the IDE AI proceeds.
