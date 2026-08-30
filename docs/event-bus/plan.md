# Event Bus Refactor — Implementation Plan (Phases 2–5)

> This plan builds directly on `event-bus-audit-phase1.md`. Citations
> (file names, function names, line numbers) come from that audit.
> Treat them as a starting map, not gospel — if the live code has
> drifted from what's cited (line numbers shifted, a function was
> renamed), verify against the actual file before editing, and note
> the discrepancy in your phase report.

---

## General rules — apply to every phase below

1. **One phase at a time.** Complete a phase's steps, run its
   verification, then report back before starting the next phase.
2. **If verification passes, proceed automatically to the next
   phase.** If any verification step fails or the live code doesn't
   match what a step assumes, **stop immediately** — do not attempt
   your own fix or workaround. Report exactly what failed and what
   you found instead.
3. **Cite file + line for every change you make**, the same way the
   Phase 1 audit did. This is both a safety check and what makes the
   report reviewable.
4. **No drive-by cleanups.** If you notice unrelated issues while
   working (dead code, unrelated bugs, style nits), note them in your
   phase report under "Other observations" — do not fix them inline.
5. **Preserve existing external signatures** (REST endpoints, message
   types, function signatures called from outside the file you're
   editing) unless a step explicitly says to change them.
6. **New background threads follow existing naming/daemon conventions**
   already used in the codebase (e.g. `dhcp-observation-writer`,
   `auto-locate-<client_id>`) — match that style for any new thread
   name.
7. Run any existing tests before and after each phase if a test suite
   exists; note in your report whether one was found and what its
   results were.

---

## Phase 2 — Decouple spatial + ML evaluation from the TCP write path

**Problem being fixed:** `_store_observations()`
(`network_device_storage.py` ~L217–230) synchronously calls
`spatial_engine.evaluate_device_spatial_and_rogue_status()` and
`device_intelligence.classify_device()` inline, on the same TCP thread
and DB connection that just wrote the observation batch. This blocks
the client's message-handling thread for the full duration of
triangulation, rogue scoring, and ML classification for every device
in the batch.

**Confirmed design decisions for this phase:**
- The evaluation queue uses backpressure: if full, **drop the item and
  log a warning** — do not block the TCP thread, do not raise.
  `evaluate_all_devices()` (already exists, `spatial_engine.py` L1035,
  triggered via `POST /api/v1/spatial/evaluate-all`) is the accepted
  catch-up mechanism for anything dropped. No new scheduling/cron is
  being added to auto-trigger it — it remains manually/externally
  triggered as it is today.

**Steps:**
1. Define a new queue, `device_evaluation_queue = queue.Queue(maxsize=1024)`,
   next to the existing `dhcp_observation_queue` definition (near
   `server_lib.py` L105) — same size, same module, same pattern.
2. In `_store_observations()`, after the observation batch commits,
   replace the direct synchronous calls to
   `evaluate_device_spatial_and_rogue_status()` and `classify_device()`
   with: for each updated `dev_id`, call
   `device_evaluation_queue.put_nowait(dev_id)` inside a
   `try/except queue.Full` — on `Full`, log a warning
   (`"evaluation queue full, dropping device_id=%s"`) and continue; do
   not block, do not retry inline.
3. `_store_observations()` should now return immediately after the
   commit — remove the inline evaluation/classification calls
   entirely from this function.
4. Add a new consumer function, `_run_device_evaluation_worker()`
   (mirror `_run_dhcp_observation_writer()`'s structure), started as a
   daemon thread named `device-evaluation-worker` at server startup
   (alongside the other thread starts in `server.py`, near L109–125).
   The worker should:
   - Block on `device_evaluation_queue.get()`.
   - Open its **own fresh DB connection** per item — do not reuse or
     assume the TCP thread's connection is still open (it isn't; that
     connection is closed/returned after the observation commit now).
   - Call `evaluate_device_spatial_and_rogue_status(dev_id, conn=<new connection>)`
     then `classify_device(dev_id, ...)`, commit, close the connection.
   - Wrap the per-item work in try/except so one bad `dev_id` logs and
     continues rather than killing the worker thread.
   - Start with a single worker thread (matching the DHCP writer's
     single-consumer pattern). Do not add concurrency/multiple workers
     in this phase even if it looks easy — that's a separate decision
     for later if profiling shows it's needed.
5. Confirm `evaluate_all_devices()` requires no changes and still works
   standalone as the catch-up path.

**Non-goals for this phase:** alert logic, location assignment logic,
`evaluate_all_devices()` internals, asyncio (there is none in this
codebase — don't introduce it here).

**Verification:**
- Grep confirms no remaining calls to
  `evaluate_device_spatial_and_rogue_status(` or `classify_device(`
  inside `_store_observations()`.
- Send a neighbourhood report with several devices; confirm the TCP
  handler returns quickly (before evaluation/classification would have
  completed), and confirm `device_location_estimates`,
  `rogue_device_assessments`, and `device_classifications` are
  populated shortly after, asynchronously.
- Artificially fill the queue (e.g. temporarily set maxsize=1 and send
  a burst) and confirm items are dropped with a logged warning, and
  that the TCP thread never blocks on a full queue.

---

## Phase 3 — Extract a shared location-write function (breaks the circular dependency)

**Problem being fixed:** `client_localization.try_automatic_client_location_assignment()`
(`client_localization.py` L352, importing/calling into `api_service.py`
L410) calls `api_service.assign_client_location()`, while `api_service`
is also the layer that triggers localization — a circular caller
chain between the two modules.

**This phase is a pure extraction — no behavior change, no
serialization yet (that's Phase 4).**

**Steps:**
1. Confirm the existing file-naming convention for repository/storage
   modules in this codebase (e.g. `network_device_storage.py`,
   `device_classification_storage.py`) and create a new module
   following that convention — e.g. `location_repository.py`.
2. Move the core write logic currently in
   `api_service.assign_client_location()` (`api_service.py` L514–584) —
   the `clients` UPDATE, the occupant guard, the
   `client_location_history` close-previous-row UPDATE, and the new-row
   INSERT — into a new function in `location_repository.py`, e.g.
   `write_client_location_assignment(client_id, location_id, method,
   confidence, ...)` (match parameter names to what
   `assign_client_location()` currently accepts).
3. Update `api_service.assign_client_location()` to become a thin
   wrapper: keep REST-layer concerns (request parsing, any permission
   checks) in `api_service.py`, delegate the actual write to
   `location_repository.write_client_location_assignment(...)`.
4. Update `client_localization.try_automatic_client_location_assignment()`
   to call `location_repository.write_client_location_assignment(...)`
   directly, and **remove the `api_service` import from
   `client_localization.py` entirely**.
5. Evaluate `confirm_client_location()` (`api_service.py` L683–701) and
   `_record_assignment_failure()` (`client_localization.py` L265–289):
   only consolidate these into the shared module if they share
   meaningfully duplicated logic with the main assignment path. If
   they're genuinely distinct operations, leave them where they are —
   don't force a merge that doesn't fit, and note your reasoning
   either way in the report.

**Verification:**
- Confirm `client_localization.py` no longer imports `api_service`
  (check with grep, not just visual scan).
- Trigger a REST-API location assignment and confirm identical DB
  writes to before (same rows, same fields, same
  `client_location_history` behavior).
- Trigger an auto-localization event (new client registration or new
  qualifying neighbour observation) and confirm identical DB writes to
  before.

---

## Phase 4 — Serialize location assignment through a single-consumer queue

**Depends on Phase 3** (needs `location_repository.write_client_location_assignment()`
to exist).

**Problem being fixed:** the occupant-guard TOCTOU race — two
concurrent assignment attempts can both pass the "is this location
free" check before either commits (previously `api_service.py`
L498–505, now living in `location_repository.py` after Phase 3).

**Design principle:** serializing all location-assignment writes
through one single-threaded consumer eliminates the race as a side
effect of the architecture, rather than needing explicit row-level
locking.

**Steps:**
1. Define `location_assignment_queue = queue.Queue(maxsize=256)`
   (smaller than the evaluation queue — assignment events are far less
   frequent than observation batches).
2. Both trigger points — the REST API handler and
   `try_automatic_client_location_assignment()` — should enqueue a
   request (`client_id`, target `location_id` or "auto", requester
   context) instead of calling `write_client_location_assignment()`
   directly.
3. Add a single consumer thread,
   `_run_location_assignment_worker()`, started once at server
   startup, processing the queue strictly one item at a time. This
   single-threaded consumption is the actual fix for the race — do
   not add multiple worker threads here, that would reintroduce the
   same problem.
4. **Queue-full behavior differs from Phase 2 — do not drop silently
   here.** There's no "catch-up" equivalent for a lost location
   assignment. Use a bounded `put(item, timeout=<a few seconds>)` and
   surface a clear "try again" error to the caller if it times out,
   rather than dropping.
5. For the REST API case: block the HTTP handler until the queued
   assignment completes, with a short timeout (this operation is
   low-frequency, so blocking is acceptable for now). Note in your
   report that this is a candidate for the existing async
   action-framework pattern (`PENDING`/`RUNNING`/`COMPLETED`, like
   `actions`/`action_targets`) if it ever becomes a bottleneck — but
   don't build that now, it's out of scope for this phase.

**Verification:**
- Concurrency test: fire two near-simultaneous assignment attempts
  (one REST call + one auto-assignment trigger, or two REST calls)
  targeting the same `location_id` for different clients. Confirm
  exactly one succeeds and the other receives a clear
  "location already occupied" response — not both succeeding.
- Confirm the ordinary single-assignment case still behaves identically
  to before this phase.

---

## Phase 5 — Consolidate alert creation into a shared `create_alert()`

**Problem being fixed:** `alerts` has three write sites
(`create_connection_alert()`, `create_server_alert()`,
`handle_client_alert()`, all in `server_lib.py`) with divergent
validation — connection alerts check working hours, client alerts
cross-check `forbidden_processes`, server alerts do neither.

**Confirmed design decision:** keep all three call sites and their
distinct trigger paths — do not merge *when* each alert type fires.
Only consolidate the *write + validation + notification* logic.

**Steps:**
1. Before writing any code: check whether each of the 3 existing
   functions currently calls `event_broadcaster` to notify the GUI via
   SSE, and whether that happens consistently across all three. The
   Phase 1 audit didn't confirm this either way — verify it directly
   and report what you find before proceeding, since it changes step 4
   below.
2. Create `create_alert(alert_type, severity, client_id, message,
   details=None)` (adjust signature to match what the 3 existing
   functions currently pass) that performs the actual `INSERT` plus
   shared field validation/defaults (severity enum check, timestamp
   handling, any other validation currently duplicated across the 3
   sites).
3. Update `create_connection_alert()`, `create_server_alert()`, and
   `handle_client_alert()` to keep their own type-specific pre-checks
   (working-hours check, forbidden-process cross-check) exactly as
   they are today, but delegate the actual row insert to the new
   `create_alert()` instead of each running its own bare `INSERT`.
4. Based on what step 1 found: if SSE notification isn't already
   consistent across all three, move it into `create_alert()` itself
   so every alert — regardless of which of the 3 paths created it —
   reliably reaches the GUI once.

**Non-goals:** don't change what triggers each alert type or when
each fires — only the write/validation/notify path underneath them.

**Verification:**
- Trigger each of the 3 alert paths (client connect, client
  disconnect, client sends a forbidden-process alert) and confirm each
  still applies its own type-specific validation correctly.
- Confirm all three now produce a consistent SSE notification to the
  GUI (no more, no less than one broadcast per alert).
- Confirm no duplicate or missing alerts compared to pre-change
  behavior.

---

## Deferred — found during the audit, not addressed by this plan

These came up in the Phase 1 audit but aren't in scope here. Flagging
them so they aren't lost, not asking you to fix them now:

- **Disk file write race**: `network_scan_storage.store_network_scan()`
  writes the scan JSON in place with no atomic rename — a concurrent
  reader can see a partial file. Fix would be write-to-temp-then-rename.
- **In-memory-only quarantine/isolation state**: `client_quarantine_status`
  and `device_isolation_status` are Python dicts, not persisted to
  MySQL — a server restart silently loses this state.

Both are independent of the event bus work and can be their own phase
later if wanted.