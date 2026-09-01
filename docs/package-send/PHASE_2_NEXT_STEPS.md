# Phase 2: Next Steps (September 1, 2026)

**Current Status:** Milestone F core code is complete and unit-tested. Ready for real hardware testing.

---

## Executive Summary

| Milestone | Status | Blocker | ETA |
|-----------|--------|---------|-----|
| A: Audit | ✓ Complete | — | — |
| B: Storage Separation | ✓ Complete | — | — |
| C: Versioning | ✓ Complete | — | — |
| D: Folder Refactor | ✓ Complete | — | — |
| E: Updater | ✓ Complete | — | — |
| **F: Single-Client UPDATE_CLIENT** | **Ready to Test** | Real hardware test | **This week** |
| **G: Bulk Updates** | Designed, blocked by F | F completion | **Next week** |

---

## Immediate Action Items (Milestone F)

### What to Do Now

1. **Run real hardware tests** using the new TEST_EXECUTION_GUIDE.md
   - Build success package: `python scripts/build_test_update_package.py --version 2.0.0`
   - Build failure package: `python scripts/build_test_update_package.py --version 2.0.1 --broken`
   - Follow Scenario 1 and Scenario 2 in TEST_EXECUTION_GUIDE.md

2. **Verify successful update flow:**
   - Package upload → staging → updater spawn → version update on server ✓
   - Duration should be 20–40 seconds end-to-end

3. **Verify rollback:**
   - Broken package upload → staging → dependency install fails → rollback restores old version ✓
   - Client continues running, action marked FAILED with rollback_status=success

4. **Document results** in test report format included in TEST_EXECUTION_GUIDE.md

### Expected Outcomes

**Success Scenario (Pass Criteria):**
- Action state: `COMPLETED`
- Target status: `COMPLETED` with exit code 0
- Server shows client version: `2.0.0`
- Client service: running and responsive
- Logs: clean state machine transitions

**Failure Scenario (Pass Criteria):**
- Action state: `FAILED`
- Target status: `FAILED` with exit code 1
- `rollback_status`: `success`
- Server shows client version: `2.0.0` (reverted)
- Client service: running and responsive
- Logs: show rollback execution

### Time Estimate
- Build packages: 5 minutes
- Run both scenarios: 30 minutes
- Document results: 5 minutes
- **Total: 40 minutes**

---

## After Milestone F Passes

### Environment Notes

**Server Configuration (Windows):**
- Server package storage: `server/storage/packages/`
- Packages are uploaded and stored in this directory
- Ensure directory exists and has read/write permissions for the server process

### Immediate Tasks (Milestone G)

**Phase 1: Database Schema** (30 min)
- Create `bulk_updates` table (tracking bulk operations)
- Create `bulk_update_actions` table (tracking per-client results)
- Add indexes on `bulk_update_id`, `package_id`, `created_at`

**Phase 2: API Functions** (2–3 hours)
- Implement `create_bulk_update()` in api_service.py
- Implement `get_bulk_update_status()` in api_service.py
- Implement `list_bulk_updates()` in api_service.py

**Phase 3: REST Routes** (1 hour)
- Add POST `/api/v1/bulk-updates/` (create)
- Add GET `/api/v1/bulk-updates/{id}` (status)
- Add GET `/api/v1/bulk-updates/` (list)

**Phase 4: Integration** (1 hour)
- Connect bulk_update creation to action fan-out
- Implement per-client action creation and tracking
- Add aggregate status calculation

**Phase 5: Tests** (1–2 hours)
- Unit tests for bulk_update functions
- Integration tests for action creation flow
- Real hardware test on 3–5 clients

**Total Effort: 7–11 hours**

### Resources for Milestone G

- **MILESTONE_G_DESIGN.md** (528 lines)
  - Complete architecture with API contracts
  - Database schema with field definitions
  - Function signatures and docstrings
  - Test class structure and case list
  - Acceptance criteria checklist

- **REMAINING_WORK.md** (304 lines)
  - Implementation order
  - Code templates and SQL
  - Test structure outline

---

## Testing Verification Checklist

Use this before marking Milestone F complete:

### Server-Side
- [ ] `api_server.py` includes `UPDATE_CLIENT` in LONG_RUNNING_ACTION_TYPES
- [ ] `/api/actions` endpoint accepts action_type=UPDATE_CLIENT
- [ ] `action_service.py` routes UPDATE_CLIENT to concurrent fan-out
- [ ] `deploy_package_to_client()` accepts operation=UPDATE_CLIENT parameter
- [ ] Package stored in `client/storage/updates/incoming/` with correct naming

### Client-Side
- [ ] `client_lib.py` detects UPDATE_CLIENT + final chunk
- [ ] `process_package_chunk()` triggers updater spawn
- [ ] `_spawn_updater_subprocess()` creates detached process
- [ ] Updater receives correct staged_package_path and client_root

### Updater
- [ ] `updater.py` CLI accepts two positional args (staged_path, client_root)
- [ ] `apply_update()` validates manifest, backs up old version, replaces files
- [ ] Dependency install failure triggers rollback
- [ ] Exit code 0 = success, 1 = failure
- [ ] `version.json` updated on success

### Regression
- [ ] Existing DEPLOY_PACKAGE actions still work
- [ ] SEND_FILE still lands in `sent-files/`
- [ ] Client registration/heartbeat unchanged
- [ ] Database migrations applied cleanly

---

## Documentation Files

### Created This Session

1. **TEST_EXECUTION_GUIDE.md** (524 lines)
   - Quick start section (3 steps, 40 min total)
   - Detailed walkthrough for both scenarios
   - Troubleshooting section
   - Logging/diagnostics guide
   - Test results documentation template

2. **build_test_update_package.py** (198 lines)
   - Automates v2.0.0 and v2.0.1 package creation
   - Handles hash calculation, manifest generation, zip creation
   - Broken package variant for rollback testing
   - Usage: `python build_test_update_package.py --version 2.0.0 [--broken]`

3. **PHASE_2_NEXT_STEPS.md** (this document)
   - Executive summary and action items
   - Time estimates and acceptance criteria
   - Verification checklist
   - Reference to all documentation

### Existing Documentation

- **IMPLEMENTATION_STATUS.md** (105 lines)
  - Current state of Milestones A–F
  - Identifies what's done vs. what's missing
  - Known limitations and notes

- **MILESTONE_F_TEST_PROCEDURE.md** (435 lines)
  - Original technical test procedure
  - Step-by-step bash/curl commands
  - Alternative format to TEST_EXECUTION_GUIDE.md

- **MILESTONE_G_DESIGN.md** (528 lines)
  - Complete architecture for bulk updates
  - Database schema and API contracts
  - Function signatures and test structure
  - Ready for implementation when F completes

- **REMAINING_WORK.md** (304 lines)
  - Consolidated task list with effort estimates
  - Implementation order and code templates
  - Regression checklist

- **phase2.md** (143 lines)
  - Original Phase 2 specification
  - Ground rules and milestone definitions
  - Acceptance criteria for each milestone

---

## Key Decisions Documented

1. **One action per client in bulk operations** (not one shared action)
   - Rationale: Per-client visibility, failure isolation, simpler status calculation
   - Implementation: `create_bulk_update()` loops over target clients, calls `create_action()` N times

2. **Updater as detached subprocess** (not in-process)
   - Rationale: Can't replace running app's files from within the app process
   - Implementation: `_spawn_updater_subprocess()` creates subprocess, parent exits cleanly

3. **Version tracking via heartbeat**
   - Rationale: Allows server to observe version changes without polling
   - Limitation: Version updates are eventual consistency, not real-time

4. **Package as desired-state** (files to delete are not present in package)
   - Rationale: Simpler manifest, no deletion list to track
   - Implementation: `apply_update()` diffs old vs. new, deletes files only in old

5. **Backup in `history/` before replacement**
   - Rationale: Allows rollback if new version fails
   - Limitation: Disk space required (consider cleanup policy)

---

## Success Criteria for Phase 2 Completion

### Milestone F
- [ ] Real hardware test: successful update v1.0.0 → v2.0.0 passes
- [ ] Real hardware test: failure + rollback passes
- [ ] Both scenarios documented in test report
- [ ] No regression in existing functionality

### Milestone G
- [ ] Database schema deployed
- [ ] API functions and routes implemented
- [ ] Unit tests passing (3 test classes, 10+ cases)
- [ ] Real hardware integration test on 3–5 clients
- [ ] Aggregate status and per-client tracking working
- [ ] Documentation updated with workflows

### Phase 2 Complete When
- All 7 milestones (A–G) have passing tests
- Real hardware verification done for both single-client (F) and bulk (G)
- No open issues blocking deployment
- Documentation is current and complete
- Code is merged to main branch

---

## How to Use This Document

1. **Start here for context** — Read executive summary and immediate action items
2. **For Milestone F testing** — Follow TEST_EXECUTION_GUIDE.md (or MILESTONE_F_TEST_PROCEDURE.md)
3. **For Milestone G design details** — Read MILESTONE_G_DESIGN.md
4. **For implementation specifics** — Refer to REMAINING_WORK.md code templates
5. **For original requirements** — See phase2.md

---

## Questions or Blockers?

If you encounter issues during testing:

1. **Check logs first** (client, server, updater — see TEST_EXECUTION_GUIDE.md diagnostic section)
2. **Review TROUBLESHOOTING section** in TEST_EXECUTION_GUIDE.md
3. **Verify prerequisites** are met (network, permissions, paths)
4. **Consult IMPLEMENTATION_STATUS.md** for known limitations

---

**Last Updated:** September 1, 2026  
**Next Review:** After Milestone F test completion  
**Owner:** Network Scanner Development Team
