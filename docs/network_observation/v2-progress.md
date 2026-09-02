# Network Telemetry & Device Behavior Enrichment (v2) — Implementation Progress

Tracks implementation of `docs/network_observation/v2.md` against its §7 phase order.
This file is updated incrementally as each phase is actually implemented and verified —
entries are only marked ✅ after the corresponding code/tests exist and pass.

## Legend
- ✅ Done  ⏳ In progress  ⬜ Not started

---

## Phase 0 — Audit of existing (V1) implementation

**Status:** ✅ Done — Date: September 2, 2026

The repo already has a V1 passive packet observation feature (see `docs/network_observation/plan.md`
and `docs/network_observation/progress.md`). Relevant existing building blocks to reuse for v2:

| Existing component | File | Reuse plan for v2 |
|---|---|---|
| `extract_metadata_from_scapy()` | `client/app/packet_extractor.py` | Feed per-packet metadata into the new Flow Aggregator instead of re-parsing packets |
| `DailyPacketStorage` | `client/app/packet_storage.py` | Pattern (buffered, atomic, day-rotating JSON) mirrored for `flows.json` |
| `PacketObserver` | `client/app/packet_observer.py` | Existing Scapy `sniff()` loop — extend to also feed the Flow Aggregator, no 2nd sniffer |
| `get_local_network()` | `client/app/network_neighbour_collector.py` | Interface/IP/subnet detection reused for scope filter context |
| `get_mac()` / `CLIENT_ID` env | `client/app/client_lib.py` | `observer_client_id` identity source |
| `neighbourhood.py` atomic JSON write pattern | `client/app/neighbourhood.py` | Reused for `devices.json`, `activity/*.json` atomic writers |
| `device_model.DeviceCorrelator` (in-memory, built by `PassiveProtocolListener`) | `client/app/device_model.py`, `passive_protocol_listener.py` | Discovery signal source for Device Enrichment Job (DHCP/mDNS/LLMNR/NBNS/SSDP) — avoids a second protocol parser |
| Server `server_components/network_device_storage.py` + `database.py` | server | Pattern for upsert/observation-table storage, reused for the new Merge Service |
| `server_components/server_lib.py` request/response pattern (`request_client_passive_neighbourhood`) | server | Pattern reused for the on-demand Flow API relay |

**Decision:** v2 uses a **new storage tree** `client/storage/network_telemetry/<date>/...`
(v2 §2), kept separate from the V1 `client/storage/passive_packets/<date>.json` tree.
V1 is not modified; v2 is purely additive, sharing only the live packet capture stream
(one `PacketObserver`, two consumers: V1 raw storage + v2 Flow Aggregator).

---

## Phase 1 — Schema + storage scaffolding (v2 §7.1)

**Status:** ✅ Done — standalone client library and tests completed September 2, 2026

Implemented in `client/app/telemetry_storage.py`:

- Creates the v2 day-based tree under `client/storage/network_telemetry/<date>/`.
- Provides paths for protocol packet files, `flows.json`, `devices.json`, and
  `activity/<HH-MM>_<HH-MM>.json`.
- Provides atomic JSON read/write helpers.
- Provides `RotatingJSONAppendStore` with configurable size limits and numbered
  rotation (`flows.1.json`, `flows.2.json`, etc.). The default limit is 50 MB and
  can be configured with `TELEMETRY_FILE_MAX_BYTES`.

Tests: `client/tests/test_telemetry_storage.py` — 11 tests passed.

**Integration status:** ✅ Updated September 2, 2026 — `client/app/telemetry_packet_writer.py`
now buffers scope-filtered packet observations and flushes them into
`packets/<protocol>.json` via `RotatingJSONAppendStore`, and `client/app/client.py`
starts/stops it alongside the packet observer. V1 still writes
`client/storage/passive_packets/<date>.json` unchanged and unconditionally, in
parallel — the v2 tree is purely additive per the Phase 0 decision.

---

## Phase 2 — Flow Aggregator (v2 §7.2, schema §3.2)

**Status:** ✅ Done — standalone client library and tests completed September 2, 2026

Implemented in `client/app/flow_aggregator.py`:

- Maintains active flows in memory and merges bidirectional packets into one flow.
- Emits the v2 flow schema, including `flow_id`, observer identity, endpoints,
  protocol, packet/byte counters, duration, TCP flags, direction counters, and
  inter-arrival metrics.
- Finalizes flows after the configurable idle timeout (default 45 seconds).
- Supports manual flush and a background sweep thread.
- Appends finalized flows to the rotating `flows.json` store.

Tests: `client/tests/test_flow_aggregator.py` — 7 tests passed.

**Integration status:** ✅ Updated September 2, 2026 — `client/app/client.py` now
constructs one `FlowAggregator` per session and starts it alongside the packet
observer. `PacketObserver._handle_packet()` forwards every scope-filtered
observation to `flow_aggregator.record_packet()` after it is (unconditionally)
recorded to the existing V1 daily storage, so `flows.json` is now produced
during normal client runtime whenever packet capture is active.

---

## Phase 3 — Scope filtering (v2 §7.3, §6)

**Status:** ✅ Done — standalone client library and tests completed September 2, 2026

Implemented in `client/app/scope_filter.py`:

- Applies the required rule: retain a packet when either source or destination
  IP is inside an assigned CIDR range.
- Supports multiple CIDR ranges, invalid-CIDR handling, persistence to
  `client/storage/scope_config.json`, and `NETWORK_OBSERVATION_SCOPE` override.
- Uses fail-open behavior when no scope is assigned, preserving current capture
  behavior until server scope assignment is wired.

Tests: `client/tests/test_scope_filter.py` — 11 tests passed.

**Integration status:** ✅ Updated September 2, 2026 — `PacketObserver` now
accepts an optional `scope_filter` and applies `keep_observation()` right after
`packet_extractor` classification (v2 §6), before any observation reaches the
Flow Aggregator or the v2 per-protocol packet writer. `client/app/client.py`
builds the filter per session via `ScopeFilter.from_env_or_file()`, which
fails open (keeps everything) until a scope is persisted or the
`NETWORK_OBSERVATION_SCOPE` env var is set — so existing single-client/dev
behavior is unaffected. **Remaining:** the server still does not assign
`observation_scope` to clients at connect time or call `save_scope_config()`
remotely; scope is currently only configurable locally (env var or
`scope_config.json`).

---

## Phase 4 — Device Enrichment Job, 5 min (v2 §7.4, schema §3.3)

**Status:** ✅ Done — standalone client library and tests completed September 2, 2026

Implemented in `client/app/device_enrichment.py`:

- Converts the existing `DeviceCorrelator` snapshot into the v2 identity/presence
  record without adding activity counters.
- Builds discovery blocks for DHCP, mDNS, LLMNR, NBNS, and SSDP with `seen`,
  `last_seen`, mDNS services, and NBNS name where available.
- Preserves devices that are not observed in the current enrichment cycle.
- Provides one-shot execution and a five-minute background job.

Tests: `client/tests/test_device_enrichment.py` — 12 tests passed.

**Known limitation:** Per-protocol `last_seen` currently uses an approximate
value based on the device snapshot; exact protocol timestamps are deferred.

**Integration status:** The job is not yet started by the production client loop,
so `devices.json` is not yet generated during normal runtime.

---

## Phase 5 — Activity Window Aggregator, 15 min (v2 §7.5, schema §3.4)

**Status:** ✅ Done — standalone client library and tests completed September 2, 2026

Implemented in `client/app/activity_window_aggregator.py`:

- Reads finalized flow records from `flows.json`, not raw packet files.
- Groups flow activity by known device MAC and 15-minute window.
- Emits the v2 activity schema, including protocol/port totals and internal vs.
  external connection counts.
- Emits explicit `active: false` records with zero counters for known devices that
  have no flows in the window.
- Writes activity window files and exposes an `on_window_closed` callback for the
  future Sync Manager.

Tests: `client/tests/test_activity_window_aggregator.py` — 9 tests passed.

**Integration status:** The aggregator is not yet started by the production client
loop, and its callback is not connected to a Sync Manager.

---

## Phase 6 — Sync Manager (v2 §7.6, schema §3.5)

**Status:** ✅ Done — standalone client library completed September 2, 2026

Implemented in `client/app/sync_manager.py`:

- **Delta builder:** `build_delta_payload()` whitelists only v2 §3.5 fields (device identity + activity), strips raw packet/flow-level data, enforces `window_id` consistency.
- **Durable persistence:** Pending payloads stored to `sync_pending/<window_hash>.json`; completed window IDs tracked in `sync_pending/completed.json` (last 500 entries kept).
- **Retry/backoff:** Exponential backoff with configurable base (default 5 sec) and max retries (default 3).
- **ACK/NACK handling:** `handle_ack()` receives server ACK/NACK, signals worker thread, auto-marks completed on ACK.
- **`window_id` idempotency:** Skips re-sending and re-marking if the payload is already in `completed.json`.
- **Async send:** One background thread per window, configurable ACK timeout (default 15 sec), graceful shutdown via `stop()`.
- **Reconnect recovery:** `retry_pending()` restarts workers for any durable payloads on client restart/reconnect.

Tests: `client/tests/test_sync_manager.py` — 10 tests passed (delta builder, persistence, ACK/NACK, retry logic, idempotency).

**Integration status:** ✅ Wired into the production client loop in `client/app/client.py`: `ActivityWindowAggregator.on_window_closed` feeds `SyncManager.handle_window_closed`, pending windows retry after registration, and ACK/NACK frames are routed back to `SyncManager.handle_ack`. The Device Enrichment Job also starts from the live `PassiveProtocolListener` snapshot.

---

## Phase 7 — Server Merge Service (v2 §7.7)

**Status:** ✅ Done — implemented and tested September 2, 2026

Implemented in:

- `server/server_components/telemetry_merge.py`
- `server/server_components/server_lib.py` (`TELEMETRY_SYNC` socket dispatch and ACK/NACK)
- `server/api_server.py` (`POST /api/v1/telemetry/sync`)
- `server/scripts.sql` (`telemetry_devices`, `telemetry_activity_windows`)

The merge service now:

- Strictly validates and whitelists v2 §3.5 identity, discovery, and activity fields.
- Rejects raw packet/flow fields, location fields, and ML/scoring fields.
- Upserts the global `network_devices` identity table.
- Stores observer-specific device metadata in `telemetry_devices`.
- Stores activity summaries in `telemetry_activity_windows`.
- Deduplicates repeated deliveries with unique `(device_mac, window_id)` handling.
- Returns idempotent ACK results for duplicate windows and NACKs invalid payloads.
- Enforces registered socket client identity before merging socket payloads.

Tests: `server/tests/test_telemetry_merge.py` — 4 tests passed.


---

## Phase 8 — On-demand Flow API (v2 §7.8, schema §3.6)

**Status:** ✅ Done — implemented and focused-tested September 2, 2026

Implemented in:

- `client/app/flow_query.py`
- `client/app/client.py` (`GET_TELEMETRY_FLOWS` command handling)
- `client/tests/test_flow_query.py`
- `server/server_components/server_lib.py` (`request_client_telemetry_flows` relay)
- `server/api_server.py` (`GET /api/v1/clients/{client_id}/devices/{mac}/flows?window=...`)
- `server/tests/test_telemetry_flow_api.py`

The flow-serving path now:

- Validates a UTC ISO-8601 `<start>_<end>` window and canonicalizes the requested MAC.
- Reads finalized flow records from the requested day and every numbered rotated
  `flows.N.json` sibling, including windows spanning midnight.
- Filters by either flow endpoint MAC and by `last_seen` inside the half-open
  requested window; returns records sorted by `first_seen`.
- Enforces a bounded 10,000-record response limit before data crosses the socket.
- Uses the existing registered client `COMMAND`/`RESPONSE` transport; no second
  connection or packet-serving path was introduced.
- Returns full flow detail only on explicit request. Raw packet files are not read
  or returned by this API.
- Maps client timeout, unavailable, malformed response, and invalid query cases to
  explicit REST error responses.

Verification:

- `client/tests/test_flow_query.py` — 3 tests passed.
- `server/tests/test_telemetry_flow_api.py` — 2 tests passed.
- Regression: `server/tests/test_telemetry_merge.py` — 4 tests passed.
- Initial route placement was caught by the REST test (404); the route was moved
  from the POST handler into `do_GET`, then the focused suite passed.

---

## Phase 9 — Initial connection / Network Neighborhood wiring (v2 §7.9)

**Status:** ✅ Done — registration-time v2 seed and server-assigned scope wired September 2, 2026

The existing packet pipeline continues to stamp `observer_client_id`:

- `client/app/packet_extractor.py` accepts and injects the observer identity.
- `client/app/packet_observer.py` passes the identity through with a `CLIENT_ID`
  fallback.
- `client/app/packet_storage.py` preserves/backfills the identity in stored records.
- `client/app/client.py` starts the observer with `CLIENT_ID` at runtime.

Initial connection now additionally performs the v2-only work through the existing
registered TCP transport, without changing the V1 neighborhood snapshot:

- The server persists per-client CIDR policy in `clients.observation_scope` and
  returns it in the `REGISTERED` frame. `client/app/client.py` persists the policy
  with `save_scope_config()` and hot-applies it to the live `ScopeFilter`.
- `PUT /api/v1/clients/{client_id}/observation-scope` validates CIDRs, persists the
  policy, and pushes a `SCOPE_ASSIGNED` frame to that connected client. `GET` on the
  same endpoint returns the stored assignment. Empty scope remains fail-open.
- After each successful registration, the client sends one `TELEMETRY_SEED` built
  only from the local v2 `devices.json` identity/discovery allowlist. The server
  validates and upserts it through `merge_telemetry_seed()` without creating
  activity-window rows. Raw packet/flow, location, and ML/scoring fields are
  rejected by the same strict boundary used for normal telemetry deltas.
- The existing V1 `NETWORK_NEIGHBOURS` registration snapshot remains active and is
  still sent independently for backward compatibility.

Tests added/updated:

- `client/tests/test_scope_filter.py` — hot scope replacement and fail-open restore.
- `client/tests/test_sync_manager.py` — device-only seed whitelist behavior.
- `server/tests/test_observation_scope.py` — CIDR normalization/persistence,
  malformed-policy fallback, targeted live push, and invalid-CIDR rejection.
- `server/tests/test_registration_scope_delivery.py` — socket-handshake-level
  `REGISTERED` frame contains the persisted observation scope.
- `server/tests/test_telemetry_merge.py` — seed validation/merge without activity
  rows and rejection of activity/raw fields.

---

## Production capture-loop integration (scope filter + Flow Aggregator + per-protocol packets)

**Status:** ✅ Done — implemented and tested September 2, 2026

Closes the previously "not yet connected" gap between the standalone Phase 2/3
libraries and the live capture loop:

- New `client/app/telemetry_packet_writer.py`: `TelemetryPacketWriter` buffers
  normalized observations by `(date, protocol)` and flushes them into
  `packets/<protocol>.json` via the existing `RotatingJSONAppendStore`
  (size-bounded rotation reused from Phase 1), on a size/time threshold and a
  background flush thread — mirroring the `DailyPacketStorage` buffering
  pattern already used for V1.
- `client/app/packet_observer.py`: `PacketObserver` now accepts optional
  `scope_filter`, `flow_aggregator`, and `telemetry_packet_writer` collaborators.
  `_handle_packet()` always records to V1 `DailyPacketStorage` first (unchanged
  behavior), then applies `scope_filter.keep_observation()` (v2 §6) and, only
  for in-scope observations, forwards to `flow_aggregator.record_packet()` and
  `telemetry_packet_writer.record()`. Any collaborator error is caught and
  logged at debug level so a v2-consumer failure can never break V1 capture.
- `client/app/client.py`: builds one `ScopeFilter.from_env_or_file()`,
  `FlowAggregator`, and `TelemetryPacketWriter` per client session alongside
  the existing `PacketObserver` construction, starts them together, and stops
  them (flushing pending data) in the session `finally` block alongside the
  other v2 services.

This means `flows.json` and `packets/<protocol>.json` are now populated during
normal client runtime whenever packet capture is active — no longer standalone
library behavior only. Scope filtering fails open (keeps everything) by
default, so existing single-client/dev deployments without a server-assigned
scope see no behavior change.

Tests:

- `client/tests/test_telemetry_packet_writer.py` — 6 tests passed (buffering,
  per-protocol grouping, unknown-protocol fallback, non-dict inputs ignored,
  threshold-triggered auto-flush, start/stop flushes pending records).
- `client/tests/test_packet_observer.py` — added 3 tests verifying in-scope
  packets are forwarded to both the Flow Aggregator and the per-protocol
  writer, out-of-scope packets are still recorded to V1 storage but not
  forwarded, and packets are forwarded normally when no scope filter is
  configured (fail-open).

**Scope assignment status:** ✅ The server now persists per-client CIDR policy,
delivers it in `REGISTERED`, and can hot-push later changes with `SCOPE_ASSIGNED`.
The environment variable and `scope_config.json` remain supported local overrides
for development and offline clients.

---

## Cross-cutting integration (client.py / server.py wiring)

**Status:** ⏳ Partial

Completed:

- V2 libraries and their unit tests exist for storage, flow aggregation, scope
  filtering, device enrichment, activity windows, sync, server merge, and the
  on-demand Flow API.
- `observer_client_id` is stamped in the live packet-observation path.
- The current V1 passive observer remains the single capture engine; no second
  sniffer was introduced.
- Sync Manager, server merge, and the on-demand flow request/response path are
  wired through the existing registered socket transport and REST API.
- Scope filtering, the Flow Aggregator, and the v2 per-protocol packet writer
  are now all connected to the production packet observer path (see
  "Production capture-loop integration" above) — the client loop feeds
  normalized packet observations into every v2 consumer, not just
  enrichment/activity services.

Remaining:

- Add a complete socket-level integration test that exercises the subsequent
  `TELEMETRY_SEED` acknowledgement exchange against a database-backed server;
  focused handshake coverage already verifies `REGISTERED` scope delivery.
- Add server-side and multi-hour v2 integration/soak coverage.

---

## Test run summary

**Status:** ✅ Focused client/server v2 tests passed — September 2, 2026 (updated)

Client command executed from `client/`:

```text
python -m unittest tests.test_telemetry_storage tests.test_flow_aggregator tests.test_scope_filter tests.test_device_enrichment tests.test_activity_window_aggregator tests.test_sync_manager tests.test_flow_query tests.test_packet_observer tests.test_telemetry_packet_writer -v
```

Result: **69 client tests passed, 0 failures, 0 errors** (61 prior v2-library
tests + 3 new `PacketObserver` scope/forwarding tests + 6 new
`TelemetryPacketWriter` tests, wired into `client/app/client.py`'s production
capture loop and verified against `scapy`/`psutil` after installing
`client/app/requirements.txt`, which were missing from this environment).

Server command executed from `server/`:

```text
python -m unittest tests.test_telemetry_merge tests.test_telemetry_flow_api -v
```

Result: **6 server tests passed, 0 failures, 0 errors** (no server-side changes
in that Phase 8 update; re-run for regression confirmation only).

**Phase 9 focused verification — September 2, 2026:**

```text
client/: python -m unittest tests.test_scope_filter tests.test_sync_manager -v
server/: python -m unittest tests.test_registration_scope_delivery tests.test_observation_scope tests.test_telemetry_merge tests.test_client_registration -v
```

Result: **19 client tests passed** and **15 server tests passed**, with zero
failures or errors. The server suite includes the registration-handshake test
that proves `REGISTERED` carries the persisted `observation_scope`. `py_compile` also succeeded for the changed client and
server modules. The server registration tests emit their existing test-double
logging for unavailable database-backed disconnect alerts; it did not affect
any assertion or result.

The new Phase 8 coverage verifies local rotated flow lookup, day-spanning
windows, query validation/capping, socket relay validation, REST error mapping,
and telemetry-merge regression behavior. This is not yet a full end-to-end or
multi-hour soak test.

Full `client/tests` discovery (`python -m unittest discover -s tests`) was also
run for regression: **214 tests, 2 pre-existing failures + 1 pre-existing error**,
all unrelated to this update and specific to this Windows dev environment
(`socket.AF_PACKET` missing on Windows in `test_client_identity.py`; a Windows
interface-name assertion in `test_network_neighbour_collector.py` expecting a
Linux-style `eth0` label; a Windows-firewall-vs-simulated enforcement-method
mismatch in `test_quarantine_manager.py`). No test outside the v2 telemetry
scope was affected by these changes.

---

## Acceptance criteria checklist (from v2 §8)

- [x] No raw packets ever leave the client; only §3.5 deltas and §3.6 on-demand flow responses cross the network. The Flow API reads local finalized flow files only.
- [x] Standalone activity aggregation emits a zero-activity record with `active: false` for every known device in a window. Now runtime-wired: `flows.json` is populated live via the production `PacketObserver` → `FlowAggregator` path, so the Activity Window Aggregator's own background schedule (already started in `client.py`) now has real flow data to consume.
- [x] Killing/restarting the client mid-window does not create duplicate server-side activity records for the same `window_id` in the implemented sync/merge path. Full restart/end-to-end coverage is still pending.
- [x] Standalone telemetry storage has configurable size-based rotation, now exercised live by both `flows.json` (Flow Aggregator) and `packets/<protocol>.json` (Telemetry Packet Writer) during normal capture. Multi-hour soak testing is still pending.
- [x] Scope filter retains traffic when the assigned subnet is on either source or destination side and is now invoked live in the production packet-observation path (v2 §6). The server persists an admin-configured per-client CIDR policy, delivers it in `REGISTERED`, and can hot-push later changes through `SCOPE_ASSIGNED`; the client persists and applies both forms. Empty/unassigned scope remains intentionally fail-open.
- [x] No location fields, ML/scoring fields, or full-device-base resend appear in a v2 sync payload. The delta builder and server validator enforce this.

---

## Known limitations / deferred items

- Exact per-protocol discovery timestamps are not yet retained by enrichment.
- The v2 registration seed is covered by focused client/server unit tests, but a
  real socket-level registration exchange test is still absent.
- No multi-hour v2 soak suite has been added; current coverage is focused client,
  server, relay, and REST tests.
