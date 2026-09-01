# Remote Package Deployment — Implementation Plan

> Scope note: this entire document covers **Feature Phase 1 only** —
> sending a package to clients and extracting it. Feature Phase 2
> (restructuring the client so it can self-update) is intentionally
> out of scope here and will be its own plan once this is proven.
>
> Internally this is broken into Milest>ones A–D so "Phase" always
> refers to the overall feature, never gets confused with a step below.

---

## General rules — apply to every milestone below

1. **One milestone at a time.** Complete it, run its verification,
   report back before starting the next.
2. **If verification passes, proceed automatically. If any
   verification step fails or the live code doesn't match what a step
   assumes, stop immediately** — report what failed rather than
   improvising a fix.
3. **Cite file + line for every finding and every change.**
4. **No drive-by cleanups.** Note unrelated issues you notice under
   "Other observations" in your report — don't fix them inline.
5. This feature writes files to every managed client and will
   eventually run as whatever privilege level the client agent runs
   under. Treat every safety check below (hash verification, path
   validation, size limits) as required, not optional — do not skip
   or simplify any of them even for a "just testing" version.

---

## Milestone A — Audit: action framework & screenshot pipeline

**Read-only. No code changes.** Produce a findings report before any
implementation work starts.

**Scope:** the action framework (server + client dispatch), the
screenshot capture/transfer feature end to end (both sides), and the
underlying TCP message framing.

**Questions to answer, each cited with file/function/line:**

1. **Action framework structure**
   - How is an action represented server-side (data model: id, type,
     target(s), params, status)?
   - What does the wire message look like when an action is dispatched
     to a client (message type, payload shape)?
   - How does the client route an incoming action to the right handler
     (a dispatch table keyed by action type, or something else)?
   - What does the client's completion/failure report back to the
     server look like (message type, payload shape) — does it support
     arbitrary binary data, or just status + error string?
   - Does multi-target dispatch (one action → many clients) already
     work generically, or is it custom per action type? The original
     feature doc claims actions can target "individual clients, groups
     of devices, or entire network zones" — confirm whether that's
     real today or aspirational.

2. **Screenshot transfer mechanism (the binary-payload precedent)**
   - Exactly how is the image encoded for transport (base64 in JSON?
     length-prefixed raw bytes? something else)?
   - Is it sent as a single frame, or chunked? If single-frame, what's
     the largest payload actually tested — this matters because a zip
     package could be far bigger than any screenshot.
   - What does the **client-side send path** look like (this is what
     we invert for receiving)?
   - What does the **server-side receive path** look like
     (`_persist_screenshot_metadata` and whatever reads the raw bytes
     before it) — this is what we invert for sending.
   - **Critical question: does the client currently have ANY code path
     for receiving a large binary payload FROM the server**, as opposed
     to parsing small JSON control messages? This is the most likely
     gap — flag clearly whether it exists or needs to be built new.

3. **Message framing / protocol**
   - How does the TCP layer delimit messages (newline-delimited JSON?
     length-prefixed frames? something else)?
   - Any existing size limits or fixed-size `recv()` buffer assumptions
     that would silently truncate or corrupt a multi-MB payload?

4. **Client-side filesystem conventions**
   - Where does the client agent currently write local files (daily
     scan snapshots, logs, etc.)? What directory and permission
     conventions are used? This informs where the new package staging
     folder should live.

5. **Other observations** — anything relevant that doesn't fit above.

**Stop condition:** produce the report, then wait — do not proceed to
Milestone B until reviewed.

---

## Milestone B — Send one package to one client, into a dedicated folder

**Goal:** prove the transfer mechanism end to end for a single client.
**No extraction yet** — the package just needs to land intact.

### B.1 — Make long-running actions non-blocking (scoped narrowly)

The audit confirmed `POST /api/v1/actions` blocks the HTTP handler
until `execute_action()` fully returns (`api_server.py:717-731`), and
the action row skips straight from `PENDING` to a terminal status
without ever passing through `RUNNING`. A multi-minute transfer cannot
go through this path as-is. Two fixes, kept separate since they carry
different risk:

1. **Set `RUNNING` at the start of `execute_action()`**
   (`action_service.py`), before dispatching to any target. Safe to
   apply universally — it only adds a status transition that today
   never gets observed because every existing action finishes in
   seconds. No external behavior change for any action type.
2. **Make dispatch asynchronous, but only for long-running action
   types.** Do not change the blocking behavior of the 20+ existing
   fast action types (`GET_PROCESSES`, `SCREENSHOT`, etc.) — other
   code may depend on the current synchronous response containing the
   final result. Add a small allowlist the `POST /api/v1/actions`
   handler checks, e.g. `LONG_RUNNING_ACTION_TYPES = {"DEPLOY_PACKAGE"}`:
   for these types, spawn `execute_action()` in a background daemon
   thread and return HTTP 201 immediately with `status: PENDING`; for
   every other type, keep today's exact blocking behavior unchanged.

### B.2 — Wire protocol: three message types, not one

This doesn't fit the existing single-command/single-response pattern
`execute_client_command()` uses (audit: `server_lib.py:1416-1419` only
forwards `type == "RESPONSE"` frames to a synchronously-waiting
caller). Use three distinct message types instead:

- **`DEPLOY_PACKAGE_INIT`** (server → client, a normal `COMMAND`
  through the existing dispatch table) — carries `action_id`,
  `package_id`, `sha256`, `total_size`, `chunk_size`, `total_chunks`.
  Client responds `"ready"` or `"error"` via the existing `RESPONSE`
  pattern — this is just an acknowledgment, so it fits comfortably
  within the existing 10–12s timeout.
- **`PACKAGE_CHUNK`** (server → client, **new message type**, sent
  _outside_ the `ActionManager`/`execute_client_command()`
  wait-for-response mechanism entirely) — carries `action_id`, `seq`,
  `data` (base64, ≤128–256KB decoded). The client's main receive loop
  needs a new branch recognizing `type == "PACKAGE_CHUNK"`, routed to
  a stream-to-disk handler instead of the `COMMAND` dispatch table.
- **`PACKAGE_RESULT`** (client → server, **new message type**, sent
  asynchronously after the last chunk) — carries `action_id`, `status`
  (`SUCCESS`/`FAILED`), computed hash, error detail if any. Route this
  the same way `handle_client_alert()` already handles incoming
  `ALERT` messages — a dedicated handler that writes directly to
  `actions`/`action_targets` and pushes to `event_broadcaster`,
  **not** through the `client["responses"]` queue built for a
  synchronously-waiting caller, since nothing waits synchronously
  anymore after B.1.

### B.3 — Client-side implementation

1. On `DEPLOY_PACKAGE_INIT`: create/clear the staging folder
   (`CLIENT_DIR / "updates" / "incoming"`, per Milestone A), open
   `<package_id>.zip.part` for writing. If this fails (disk full,
   permission error), respond `"error"` and stop — never proceed to
   accept chunks for a target that can't be prepared.
2. Add the new `PACKAGE_CHUNK` branch to the client's main receive
   loop, alongside existing `COMMAND`/`RESPONSE` handling. Each chunk
   is decoded and **appended directly to the open `.part` file** —
   never accumulated in memory.
3. On the final expected chunk (`seq == total_chunks`): close the
   file, compute its SHA-256, compare against the hash from
   `DEPLOY_PACKAGE_INIT`.
   - Match: rename `.part` → final filename via `os.replace()`
     (matching the atomic-rename pattern already used in
     `screenshot_manager.py:143-148`), send `PACKAGE_RESULT` with
     `SUCCESS`.
   - Mismatch: delete the `.part` file, send `PACKAGE_RESULT` with
     `FAILED` and reason `"hash mismatch"`.

### B.4 — Server-side implementation

1. Implement `DEPLOY_PACKAGE` action creation: read a source zip from
   disk, compute its hash, chunk it.
2. In the background thread from B.1: send `DEPLOY_PACKAGE_INIT`, wait
   for the existing-pattern ack. On `"error"` or timeout, mark the
   target `FAILED` and stop — don't send chunks to a client that isn't
   ready.
3. On `"ready"`: send `PACKAGE_CHUNK` frames sequentially over the
   client's socket. **Acquire whatever per-client socket-write lock
   already protects concurrent writes to that connection** (the audit
   notes the client acquires `socket_lock` when sending — confirm the
   server has an equivalent, so this background thread's chunk stream
   can't interleave with, e.g., a heartbeat being sent to the same
   client concurrently).
4. No per-chunk acknowledgment/flow-control protocol for this
   milestone — rely on TCP's own backpressure (a blocking `send()`
   naturally stalls if the client isn't reading fast enough) for a
   single target. Revisit only if Milestone D's bulk testing shows
   it's actually needed.
5. When `PACKAGE_RESULT` arrives (routed per B.2), update
   `actions`/`action_targets` to the final status and broadcast via
   `event_broadcaster`, matching the pattern used for alerts.
6. Add an overall transfer timeout/watchdog: if no `PACKAGE_RESULT`
   arrives within a reasonable window after the last chunk was sent,
   or the client disconnects mid-transfer, mark the target `FAILED`
   with reason `"timeout"` rather than leaving it `RUNNING` forever.

**Non-goals:** no extraction (Milestone C). No multi-client targeting
(Milestone D). No package-build/versioning workflow — point the server
at a manually-prepared test zip for now. No general async refactor of
the action framework beyond the narrow `LONG_RUNNING_ACTION_TYPES`
allowlist in B.1 — every other existing action type keeps its current
synchronous behavior unchanged.

**Verification:**

- Confirm `POST /api/v1/actions` for a `DEPLOY_PACKAGE` action returns
  HTTP 201 immediately (not after the transfer completes), and the
  action visibly passes through `PENDING → RUNNING → SUCCESS`/`FAILED`
  when polled or observed via SSE.
- Confirm no existing action type's behavior changed — spot-check one
  fast action type (e.g. `GET_PROCESSES`) still blocks and returns its
  full result synchronously exactly as before.
- Send a small test zip (a few KB) to one test client. Confirm the
  received file is byte-identical to the source (compare hashes
  independently — don't just trust the client's self-report).
- Send a larger test zip (tens of MB) to confirm the chunked
  streaming approach handles it without memory spikes or truncation.
- Interrupt the transfer mid-way (kill the connection). Confirm the
  client never treats a partial file as valid, and the server-side
  target eventually reflects `FAILED` rather than hanging indefinitely
  (this is what step B.4.6's watchdog is for).
- Confirm concurrent access to the client's socket (e.g. a heartbeat
  arriving mid-transfer) doesn't corrupt the chunk stream or the
  heartbeat message.

**Stop condition:** report results — exact wire protocol used, chunk
size, staging folder path, and confirmation the async-dispatch fix is
scoped only to `DEPLOY_PACKAGE` — before proceeding to Milestone C.

---

## Milestone C — Safe extraction

**Goal:** once a hash-verified zip is sitting in the staging folder
(from Milestone B), extract it safely.

**Steps:**

1. After hash verification succeeds, extract into a **new temporary
   staging subdirectory**, separate from both the raw zip and the
   final deployed location (e.g. `updates/staging/<package_id>/`).
2. **Zip-slip guard — validate every entry before extracting any of
   them.** Fail closed: if even one entry is unsafe, abort the whole
   archive, extract nothing. Reference implementation (adapt to match
   codebase conventions, but keep the validate-before-extract order):

   ```python
   import os
   import zipfile

   def safe_extract(zip_path: str, dest_dir: str,
                     max_uncompressed_bytes: int = 500 * 1024 * 1024) -> None:
       dest_dir = os.path.realpath(dest_dir)
       with zipfile.ZipFile(zip_path) as zf:
           total_uncompressed = sum(info.file_size for info in zf.infolist())
           if total_uncompressed > max_uncompressed_bytes:
               raise ValueError(
                   f"archive too large: {total_uncompressed} bytes uncompressed"
               )
           for info in zf.infolist():
               target_path = os.path.realpath(os.path.join(dest_dir, info.filename))
               if not (target_path == dest_dir
                       or target_path.startswith(dest_dir + os.sep)):
                   raise ValueError(f"unsafe path in archive: {info.filename}")
           # every entry validated -- now actually extract
           zf.extractall(dest_dir)
   ```

3. Enforce the uncompressed-size guard shown above (or an
   equivalent per-entry compression-ratio check) to reject zip-bomb
   style archives before they fill the disk.
4. Once staging extraction fully succeeds, **atomically swap** it into
   the "current" deployed location (directory rename — atomic on the
   same filesystem on both Linux and Windows) only after every file
   extracted without error. On any failure, clean up the staging
   directory and leave the previous "current" deployment untouched.
5. Report `COMPLETED` with the new package version, or `FAILED` with a
   specific reason (`hash mismatch` / `unsafe archive` / `disk full` /
   etc.) back to the server.

**Non-goals:** this milestone does not make the extracted package
"live" in the sense of the agent actually using/restarting into it —
that's Feature Phase 2. This just gets files safely onto disk.

**Verification:**

- Extract a legitimate test zip; confirm files land correctly via the
  atomic swap.
- Craft a malicious test zip with a path-traversal entry (e.g.
  `../../evil.txt` or an absolute path). Confirm the client refuses
  the **entire** archive with a clear "unsafe archive" failure and
  writes zero files anywhere.
- Craft an oversized/zip-bomb-style archive; confirm the size guard
  rejects it before extraction starts writing to disk.
- Kill the client process mid-extraction; confirm on restart there's
  no partially-extracted directory being treated as the current valid
  deployment — the previous good state must be untouched.

**Stop condition:** report results, including the exact path-validation
logic used, before proceeding to Milestone D.

---

## Milestone D — Bulk / multi-client targeting

**Goal:** extend the now-proven single-client `DEPLOY_PACKAGE` flow to
multiple clients at once.

**Steps:**

1. Based on Milestone A's findings: if generic multi-target dispatch
   already exists and is genuinely used (not just claimed), use it as-is.
   If it turns out to be single-target only in practice, extend it —
   but confirm which situation you're actually in before writing code.
2. Allow `DEPLOY_PACKAGE` actions to be created with a list of target
   `client_id`s (or a group/zone reference), relying on per-target
   status tracking (the `action_targets`-style table, if that's what
   Milestone A finds) so each client's `COMPLETED`/`FAILED` status is
   independent.
3. **Throttle concurrency deliberately.** Sending a package to the
   full fleet simultaneously means that many concurrent chunked
   transfers at once — check whether this risks starving the TCP
   server's other duties (heartbeats to unrelated clients). If the
   codebase already has a concurrency-limiting pattern (e.g. a
   `ThreadPoolExecutor` with a max-concurrent-clients setting used
   elsewhere for bulk operations), reuse it rather than inventing a
   new one.
4. Surface aggregate progress through the existing action-tracking
   API/UI (e.g. "18/25 completed, 2 failed, 5 in progress") — check
   whether this rollup already exists generically for other
   multi-target actions or needs to be added.

**Non-goals:** no automatic retry-on-failure logic yet — a failed
client can be manually re-targeted later. This milestone is about
fan-out mechanics, not resilience policy.

**Verification:**

- Deploy a test package to 3–5 test clients at once. Confirm each is
  tracked independently.
- Force one client to fail on purpose (e.g. corrupt its expected hash)
  and confirm it doesn't affect the others' success.
- Confirm bulk deployment doesn't delay heartbeat processing for
  clients not involved in the deployment — the ingest path for
  unrelated clients must stay responsive throughout.

**Stop condition:** report results. At this point, Feature Phase 1
(package transfer + extraction) is complete and ready for real-world
testing before Feature Phase 2 (client self-update) is even scoped.
