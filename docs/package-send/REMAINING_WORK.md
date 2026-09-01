# Phase 2 Remaining Work Summary

## Current Status

**Milestone F:** Core implementation complete; awaiting real hardware end-to-end test  
**Milestone G:** Design complete; ready for implementation

---

## Milestone F: Completion Checklist

### What's Already Done

✓ Server-side wiring (action_service.py):
  - UPDATE_CLIENT in concurrent fan-out (line 455)
  - Parameter sanitization strips payloads (line 60)
  - deploy_package_to_client() routes to updates/incoming with operation param

✓ Client-side wiring (client_lib.py):
  - _spawn_updater_subprocess() spawns detached subprocess (lines 1441–1489)
  - process_package_chunk() detects UPDATE_CLIENT + final chunk, returns STAGED (lines 1348–1368)
  - UPDATE_CLIENT action registered with _handle_deploy_package_init

✓ Updater subprocess (updater.py):
  - CLI entry point accepts staged path + client_root (lines 208–263)
  - apply_update() handles stop, backup, replace, install, restart with rollback

✓ Unit/integration tests (test_update_client.py):
  - 6 test classes covering action creation, routing, staging, CLI
  - All syntax errors resolved

### What's Still Needed for Milestone F Sign-Off

**Real Hardware Test** (per phase2.md lines 2115–2119):

1. **Success scenario:**
   - Build test package v2.0.0 with bumped version string
   - Upload to server
   - Create UPDATE_CLIENT action via `/api/actions` targeting test PC
   - Monitor: package transfer → staging → updater spawn → version update
   - Verify: server's client registry shows new version within 60 seconds
   - Expected outcome: `action_status=COMPLETED`, client version=2.0.0, server reflects 2.0.0

2. **Failure + rollback scenario:**
   - Build test package v2.0.1 with broken requirements.txt
   - Upload to server
   - Create UPDATE_CLIENT action targeting same test PC
   - Monitor: package transfer → staging → updater spawn → dependency install fails → rollback triggered
   - Verify: server shows old version (2.0.0), client still running, action_status=FAILED with reason
   - Expected outcome: rollback completes, client unaffected, version unchanged

**How to Run:**
1. Follow `docs/package-send/MILESTONE_F_TEST_PROCEDURE.md` steps 1–9
2. Document results in a test report: dates, times, version changes, logs
3. Confirm both success and failure scenarios work end-to-end on physical hardware

**Acceptance Criteria Met When:**
- [ ] Successful update verified on real hardware
- [ ] Server's client version field updates after successful update
- [ ] Failure + rollback verified on real hardware
- [ ] Client continues running after rollback
- [ ] All test results documented

---

## Milestone G: Implementation Tasks

### Overview

Create one independent UPDATE_CLIENT action **per client** in a bulk operation, with aggregate + per-client status tracking.

### Implementation Order

#### Phase 1: Database Schema (30 min)

**File:** Create migration script or add to database initialization

```sql
CREATE TABLE bulk_updates (
  id INT AUTO_INCREMENT PRIMARY KEY,
  bulk_update_id VARCHAR(255) UNIQUE NOT NULL,
  package_id VARCHAR(255) NOT NULL,
  target_selection_strategy VARCHAR(50),
  target_count INT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  created_by VARCHAR(255),
  INDEX (bulk_update_id),
  INDEX (package_id),
  INDEX (created_at)
);

CREATE TABLE bulk_update_actions (
  id INT AUTO_INCREMENT PRIMARY KEY,
  bulk_update_id VARCHAR(255) NOT NULL,
  action_id VARCHAR(255) NOT NULL,
  client_id VARCHAR(255) NOT NULL,
  status VARCHAR(50),
  result JSON,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (bulk_update_id) REFERENCES bulk_updates(bulk_update_id),
  UNIQUE KEY (bulk_update_id, action_id),
  INDEX (bulk_update_id),
  INDEX (client_id),
  INDEX (action_id)
);
```

#### Phase 2: Core API Functions (2–3 hours)

**Files to modify:**
- `server/server_components/api_service.py`: Add 3 new functions
- `server/api_server.py`: Add 2 new routes

**Functions needed:**

1. `create_bulk_update(package_id, target_selection, requested_by, bulk_update_id)` → bulk_update dict with action IDs
   - Validate package exists
   - Determine targets by strategy ("individual" or "all")
   - Create one UPDATE_CLIENT action per client
   - Store bulk_update + bulk_update_actions records
   - Spawn all actions in parallel threads

2. `get_bulk_update_status(bulk_update_id)` → bulk_update_id, package_id, created_at, aggregate_status, per_client_status
   - Query bulk_updates record
   - Join with actions to get current status
   - Calculate counts (total, pending, running, completed, failed)
   - Include per-client hostname + status + result

3. `list_bulk_updates(limit=50)` → list of bulk update summaries
   - Recent bulk updates with basic counts

**Routes to add:**

- `POST /api/v1/bulk-updates/` → create_bulk_update()
- `GET /api/v1/bulk-updates/<bulk_update_id>` → get_bulk_update_status()
- `GET /api/v1/bulk-updates/` → list_bulk_updates()

**Reference:** Full function signatures in `MILESTONE_G_DESIGN.md`

#### Phase 3: Result Tracking Integration (1 hour)

**File:** `server/server_components/action_service.py`

**Change:** When an action completes, update its entry in bulk_update_actions table:

```python
# In execute_action(), after all targets finish:
cursor.execute(
    """UPDATE bulk_update_actions
       SET status = %s, result = %s
       WHERE action_id = %s""",
    (action_status, json.dumps(action_result), action_id)
)
```

Ensure this happens for any action that might be part of a bulk update (check foreign key constraint, ignore if not found).

#### Phase 4: Unit Tests (1–2 hours)

**File:** `server/tests/test_bulk_update.py` (new)

**Test classes needed:**

1. `TestBulkUpdateCreation`
   - test_create_bulk_update_individual_strategy
   - test_create_bulk_update_all_strategy
   - test_create_with_nonexistent_package_fails
   - test_create_with_no_clients_fails

2. `TestBulkUpdateStatus`
   - test_aggregate_status_calculation
   - test_per_client_status_includes_hostname
   - test_status_updates_as_actions_progress
   - test_get_nonexistent_bulk_update_raises

3. `TestBulkUpdateIndependence`
   - test_failure_in_one_action_doesnt_block_others
   - test_each_action_tracks_own_result

**Reference:** Test structure in `MILESTONE_G_DESIGN.md` (Task 4)

#### Phase 5: Real Hardware Integration Test (2–4 hours, plus waiting time)

**Setup:** 3–5 test PCs, at least 1 with intentionally broken package

**Procedure:**

```bash
# Create bulk update targeting all test PCs (e.g., 5 total, 1 will fail)
curl -X POST http://SERVER:8080/api/v1/bulk-updates/ \
  -H "Content-Type: application/json" \
  -d '{
    "package_id": "app-v2.1.0",
    "target_selection": {"strategy": "all"},
    "bulk_update_id": "bulk-real-test-001"
  }'

# Poll aggregate status until complete (5–30 min depending on size)
curl http://SERVER:8080/api/v1/bulk-updates/bulk-real-test-001 | jq '.data.aggregate_status'

# Verify results:
# - 4 clients show COMPLETED with version 2.1.0
# - 1 client shows FAILED (deliberate breakage) with old version
# - All clients remain connected and responsive
```

**Acceptance Criteria:**
- [ ] All 4 successful clients updated to v2.1.0
- [ ] Failed client shows correct failure reason in status API
- [ ] Failed client rolled back to previous version
- [ ] Server's client registry reflects all changes
- [ ] No clients became unresponsive

### Implementation Effort Summary

| Phase | Task | Estimated Time |
|-------|------|-----------------|
| 1 | Database schema | 30 min |
| 2 | API functions + routes | 2–3 hours |
| 3 | Result tracking integration | 1 hour |
| 4 | Unit tests | 1–2 hours |
| 5 | Real hardware integration test | 2–4 hours (+ waiting) |
| **Total** | **All of Milestone G** | **~7–11 hours** |

---

## Remaining Phase 2 Tasks Summary

### Before Proceeding Beyond Milestone F

- [ ] Complete Milestone F real hardware test (success + failure scenarios)
- [ ] Document test results
- [ ] Verify no regressions in existing DEPLOY_PACKAGE, SEND_FILE, or action framework

### Milestone G Implementation

- [ ] Add bulk_updates + bulk_update_actions tables
- [ ] Implement create_bulk_update()
- [ ] Implement get_bulk_update_status()
- [ ] Implement list_bulk_updates()
- [ ] Add API routes (POST, GET)
- [ ] Integrate result tracking into action_service.py
- [ ] Write unit tests (3 test classes, 10+ test cases)
- [ ] Run real hardware integration test (3–5 clients, ≥1 failing)
- [ ] Document final status

### Phase 2 Sign-Off Criteria

✓ Milestone A–E complete and verified  
⏳ Milestone F: real hardware test + pass  
⏳ Milestone G: implementation + real hardware test + pass  

---

## Testing Regression Checklist

Before closing Phase 2, verify all prior functionality still works:

- [ ] DEPLOY_PACKAGE: single client update (old flow) still works
- [ ] SEND_FILE: single client file transfer still works
- [ ] Client registration includes version field
- [ ] Client heartbeat includes version field
- [ ] Server displays client versions correctly
- [ ] Folder structure refactor (app/, config/, updater/, storage/) is stable
- [ ] No database migration issues
- [ ] No API endpoint regressions

---

## Next Phase (Phase 3 concept)

After Phase 2 closes with Milestone G working:

1. **GUI Integration:** Display bulk update status in Tauri/React UI
2. **Advanced Selection:** Group/location-based client selection
3. **Scheduled Updates:** Queue updates for off-peak windows
4. **Delta/Streaming:** Optimize large package transfers
5. **Audit/History:** Full audit log of all updates per client

---

## Documentation Artifacts

**Completed:**
- `docs/package-send/IMPLEMENTATION_STATUS.md` — Milestones A–F current state
- `docs/package-send/MILESTONE_F_TEST_PROCEDURE.md` — Step-by-step real hardware test guide
- `docs/package-send/MILESTONE_G_DESIGN.md` — Full design + function signatures + test structure

**To Complete:**
- Real hardware test report (after Milestone F testing)
- Milestone G implementation PR with test coverage
- Final Phase 2 closeout summary

---

## Questions & Unknowns

1. **Physical test hardware:** Is a dedicated test machine available now, or should we schedule that?
2. **Server environment:** Is the server currently deployed and reachable from test PCs?
3. **Database:** Is the schema migration tooling in place, or should we manually apply SQL?
4. **Timeline:** What's the target completion date for Phase 2?

**Recommendation:** Start with Milestone F real hardware test immediately (can be done in parallel with Milestone G design review). Once F passes, implement G tasks in order (database first, then API, then tests, then real hardware validation).
