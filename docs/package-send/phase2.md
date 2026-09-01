# Phase 2 Implementation Plan: Client Deployment & Update System

**Context for the IDE AI:** This project is a network-monitoring client/server system used in an internship at a workshop center. Phase 1 (pushing zip packages to clients and extracting them, over an existing action-dispatch framework) is complete. Phase 2 builds a proper update/deployment system on top of that transport. Work through the milestones below **in order**. Do not skip ahead to a later milestone until the current one has a working, verified result. At the start of each milestone, re-read the current state of the codebase — don't assume anything from a previous milestone's plan still matches the code exactly.

---

## Ground rules for every milestone

- Don't touch `config/.env` (or wherever machine-specific config lives) as part of any update package logic — it must never be overwritten by an update.
- Every new piece of wire protocol (message types, statuses) should reuse the existing action framework's state machine (`PENDING → RUNNING → COMPLETED/FAILED` or equivalent) rather than inventing a parallel one.
- Every file-write operation coming from the network must validate the destination path stays inside the intended directory (zip-slip protection) and must verify a checksum before being trusted.
- Prefer extending existing modules over duplicating logic between `SEND_FILE` and `UPDATE_CLIENT` — they should share the transport layer but not the storage/execution logic.
- After each milestone, produce a short written summary of what changed and what was tested, before moving to the next milestone.

---

## Milestone A — Architecture Audit (no code changes)

**Goal:** Fully map the existing system before touching it.

1. Inspect and document:
   - The current client installation folder structure and the installation guide included in the client.
   - The action framework: how actions are created, dispatched, and how state transitions are tracked/reported to the server.
   - The current package transfer implementation from Phase 1 (chunking, `incoming/`, `staging/`, `current/` folders, checksum verification, extraction logic).
   - The client startup/agent mechanism (how it's registered to start at logon, how it's stopped/restarted).
   - Current registration message format and any existing version fields.
   - Current heartbeat/telemetry message format.
   - Requirements/dependency handling (how the venv is created, how `requirements.txt` is currently installed).
2. Deliverable: a short written summary (a markdown doc is fine) listing each of the above with file/module references, plus a list of open questions or gaps (e.g., "no version.json exists yet", "heartbeat has no version field").

**Do not write feature code in this milestone.**

---

## Milestone B — Separate File Transfer from Update Storage

**Goal:** Split the general-purpose file transfer feature from anything update-related, storage-wise, before the update feature exists.

1. Introduce a new storage path for ordinary file transfers: `client/storage/sent-files/`.
2. Keep the `incoming/` / `staging/` mechanics (checksum verification, chunk reassembly, zip-slip validated extraction) as shared transport-layer logic, but make the **destination** configurable per operation type rather than hardcoded to `updates/`.
3. Update the `SEND_FILE` action path so a plain file/zip send now lands in `sent-files/` instead of `storage/updates/current/`.
4. Verify: send a file/zip from server to one client using the existing `SEND_FILE` action, confirm it lands in `sent-files/`, and confirm nothing under `updates/` is touched.
5. Regression check: confirm Phase 1's original flow (arbitrary package send + extraction) still works end-to-end with the new path.

---

## Milestone C — Introduce Client Versioning (no update logic yet)

**Goal:** Make the server aware of what version every client is running, before any update mechanism exists.

1. Add a `version.json` (or equivalent) to the client application, containing at minimum a `version` field. Add a separate `updater_version` field once Milestone E's updater exists — for now, `client_version` is enough.
2. Extend the client registration message to include `client_version` (and `platform` if not already present).
3. Extend the periodic heartbeat/telemetry message to also include `client_version`, so the server has a live picture even between registrations.
4. On the server, store and surface this per-client (a simple column/field is enough — a "PC / Installed Version" table).
5. Verify: restart a client, confirm the server-side view shows the correct version from both registration and heartbeat.

---

## Milestone D — New Client Folder Structure

**Goal:** Refactor the client's on-disk layout to cleanly separate application code, machine config, updater, and storage — without breaking the currently deployed clients.

1. Target structure:
   ```
   client/
   ├── app/            # the actual monitored application, e.g. client.py, requirements.txt
   ├── config/          # .env and any machine-specific config — never touched by updates
   ├── updater/         # updater.py and its own dependencies — a stable component, not replaced by app updates
   ├── storage/
   │   ├── sent-files/
   │   └── updates/
   │       ├── incoming/
   │       ├── staging/
   │       └── history/
   ├── logs/
   └── venv/            # kept outside app/, so app updates never destroy the environment
   ```
2. Move existing files into this structure. Update all internal path references (imports, config loading, logging paths, startup agent's entry point).
3. Update the installation guide to reflect the new structure.
4. Verify on a single test PC: perform a full manual reinstall following the updated guide, confirm the client starts, connects, registers correctly, and Milestone B/C functionality still works.
5. Do **not** yet build the updater in this milestone — this is a structural refactor only.

---

## Milestone E — Build the Updater

**Goal:** Build the component that safely replaces the running application, with backup and rollback.

1. Define the package format:
   ```
   client-update-<version>.zip
   ├── manifest.json      # version, package type, minimum_updater_version, file hashes
   └── app/                # desired state of the app/ directory
   ```
2. Implement `updater/updater.py` as a standalone process (it must be able to run after `client.py` has exited, since a running process can't safely replace its own files):
   - Receive/locate the staged, already-verified package (reuse Milestone A/B's checksum + zip-slip-safe extraction).
   - Parse and validate `manifest.json` against the current updater's capabilities (e.g. `minimum_updater_version` check).
   - Stop the running client/agent.
   - **Back up** the current `app/` directory (e.g. to `storage/updates/history/<old_version>/`).
   - Replace `app/` with the new package's contents, treating the package as the **desired state** — meaning files present in the old version but absent from the new one must be deleted, not just overwritten. Do not touch `config/`.
   - Diff `requirements.txt` against the current venv and install only what's missing/changed, rather than reinstalling everything.
   - Attempt to start the new client and validate it starts successfully (e.g. connects to the server within a timeout).
   - **On success:** restart the agent normally, report the new version.
   - **On failure at any step:** restore the backed-up `app/` directory, restart the previous version, and report `UPDATE_FAILED` with a specific reason (`TRANSFER_FAILED`, `INVALID_PACKAGE`, `VERSION_INVALID`, `DEPENDENCY_INSTALL_FAILED`, `APPLICATION_START_FAILED`, `ROLLBACK`).
3. Define the `UPDATE_CLIENT` action's state machine in the existing action framework:
   `PENDING → TRANSFERRING → VERIFYING → STAGED → UPDATING → DEPENDENCIES → VALIDATING → RESTARTING → COMPLETED`, with `UPDATE_FAILED` (+ reason) as the failure branch.
4. Verify with deliberately broken test packages: a package with a bad checksum, a package with a zip-slip path, a package with a broken `requirements.txt`, and a package whose `client.py` fails to start. Confirm each triggers the correct failure reason and a clean rollback, and the client is left running its previous, working version in every case.

---

## Milestone F — Single-Client Update (proof of concept)

**Goal:** Wire the `UPDATE_CLIENT` action into the server UI/API for a single target client, using everything built in Milestones A–E.

1. Add a server-side action to select one client and trigger `UPDATE_CLIENT` with a chosen package.
2. Run a full real update against one physical/test client PC: old version → new version, confirming the version shown on the server updates correctly after success.
3. Run a full real failure case (e.g. inject a bad requirements file) against one test client PC, confirming rollback works outside of the earlier automated/local tests — i.e. on an actual machine going through the real network transport, not just a local test harness.
4. This milestone is the checkpoint: don't proceed to bulk updates until single-client update is reliable across at least one success and one forced-failure run on real hardware.

---

## Milestone G — Bulk Update

**Goal:** Extend single-client update to a selectable group of clients, with per-client visibility.

1. Add a multi-select UI (or API parameter) for choosing target clients (individual selection, group, or "all").
2. On trigger, create **one independent `UPDATE_CLIENT` action per selected client** (not one shared action) — this is what gives per-client success/failure visibility rather than an opaque all-or-nothing bulk operation.
3. Surface aggregate + per-client status on the server, e.g.:
   ```
   UPDATE_CLIENT batch (v1.8.0)
   ├── PC-01 → SUCCESS
   ├── PC-02 → SUCCESS
   ├── PC-03 → FAILED (DEPENDENCY_INSTALL_FAILED)
   └── PC-04 → SUCCESS
   18/20 updated, 2 failed
   ```
4. Verify against a small group of test clients (3–5 machines is enough), including at least one deliberately-failing target, to confirm failures don't block or affect the other clients in the batch and each reports its own status independently.

---

## Naming note for the IDE AI

Keep `SEND_FILE` and `UPDATE_CLIENT` as clearly distinct actions sharing only the transport layer (chunked transfer + checksum + zip-slip-safe extraction), not the storage or execution logic. If a future need arises to push a workshop-built application to all PCs in a center, model it as a third action (e.g. `DEPLOY_APPLICATION`) reusing the same transport, rather than overloading `UPDATE_CLIENT`.