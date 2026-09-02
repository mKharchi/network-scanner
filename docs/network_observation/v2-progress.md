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

**Integration status:** The storage library is not yet connected to the production
packet observer; V1 still writes `client/storage/passive_packets/<date>.json`.

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

**Integration status:** No production call site currently feeds packets into the
Flow Aggregator, so `flows.json` is not yet produced during normal client runtime.

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

**Integration status:** The filter is not yet invoked between classification and
packet/flow storage, and the server does not yet assign `observation_scope`.

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

**Status:** ⬜ Not started

No delta builder, 15-minute sync scheduler, retry/backoff, ACK/NACK handling, or
`window_id` idempotency implementation exists yet.

---

## Phase 7 — Server Merge Service (v2 §7.7)

**Status:** ⬜ Not started

No v2 server endpoint/service was found for merging `updated_devices`, storing
activity windows, or deduplicating by `(device_mac, window_id)`.

---

## Phase 8 — On-demand Flow API (v2 §7.8, schema §3.6)

**Status:** ⬜ Not started

No server relay endpoint or client flow-serving handler exists for retrieving
records from the local `flows.json` by device and window.

---

## Phase 9 — Initial connection / Network Neighborhood wiring (v2 §7.9)

**Status:** ⏳ Partial — identity stamping is live; v2 neighborhood schema is pending

The existing packet pipeline now supports `observer_client_id`:

- `client/app/packet_extractor.py` accepts and injects the observer identity.
- `client/app/packet_observer.py` passes the identity through with a `CLIENT_ID`
  fallback.
- `client/app/packet_storage.py` preserves/backfills the identity in stored records.
- `client/app/client.py` starts the observer with `CLIENT_ID` at runtime.

The current registration flow still sends the existing V1 neighborhood snapshot;
it does not yet seed the server with the v2 device schema.

---

## Cross-cutting integration (client.py / server.py wiring)

**Status:** ⏳ Partial

Completed:

- V2 libraries and their unit tests exist for storage, flow aggregation, scope
  filtering, device enrichment, and activity windows.
- `observer_client_id` is stamped in the live packet-observation path.
- The current V1 passive observer remains the single capture engine; no second
  sniffer was introduced.

Remaining:

- Connect scope filtering, Flow Aggregator, Device Enrichment Job, and Activity
  Window Aggregator to the production client loop.
- Add per-protocol v2 packet output without replacing the existing V1 storage
  until compatibility is confirmed.
- Implement client-to-server delta sync and server-side merge.
- Add the on-demand flow request/response path.

---

## Test run summary

**Status:** ✅ Client-side v2 unit tests passed — September 2, 2026

Command executed from `client/`:

```text
python -m unittest tests.test_telemetry_storage tests.test_flow_aggregator tests.test_scope_filter tests.test_device_enrichment tests.test_activity_window_aggregator -v
```

Result: **53 tests passed, 0 failures, 0 errors**.

This verifies the standalone v2 client modules only. It is not an end-to-end or
server integration test.

---

## Acceptance criteria checklist (from v2 §8)

- [ ] No raw packets ever leave the client; only §3.5 deltas and §3.6 on-demand flow responses cross the network. Sync/API are not implemented yet.
- [x] Standalone activity aggregation emits a zero-activity record with `active: false` for every known device in a window. Runtime wiring is pending.
- [ ] Killing/restarting the client mid-window does not create duplicate server-side activity records for the same `window_id`. Server idempotency is not implemented.
- [x] Standalone telemetry storage has configurable size-based rotation. Multi-hour soak testing is still pending.
- [x] Standalone scope filter retains traffic when the assigned subnet is on either source or destination side. Production scope assignment/invocation is pending.
- [ ] No location fields, ML/scoring fields, or full-device-base resend appear in a v2 sync payload. The sync payload is not implemented yet.

---

## Known limitations / deferred items

- Phases 1–5 are implemented as standalone, tested client libraries but are not
  connected to the production capture loop.
- V1 packet storage remains active and writes the flat daily passive-packet file;
  v2 per-protocol packet files are currently path/storage scaffolding only.
- Exact per-protocol discovery timestamps are not yet retained by enrichment.
- Server scope assignment, Sync Manager, server merge/deduplication, and the
  on-demand Flow API remain unimplemented.
- No server-side or end-to-end v2 test suite has been added.
