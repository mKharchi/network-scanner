# Milestone F Test Execution Guide

**Purpose:** Execute real hardware end-to-end tests for Milestone F (single-client UPDATE_CLIENT) to validate the complete flow: package upload → staging → updater spawning → version update, and rollback verification.

**Status:** Milestone F core code is complete and unit-tested. This guide provides step-by-step instructions to complete real hardware validation.

---

## Quick Start

### Prerequisites Checklist
- [ ] One dedicated test PC with current client installed (v1.x running)
- [ ] Test PC on same network as server or routing configured
- [ ] Server running on Windows with updated code (api_server.py with UPDATE_CLIENT endpoint fix)
- [ ] Server storage directory exists: `server/storage/packages/` (packages uploaded here)
- [ ] Python 3.8+ on build machine for package creation script
- [ ] Administrator access on test PC (to stop/start services, access app folder)

### Three Simple Steps

**Step 1: Build test packages** (5 min)
```bash
cd network-scanner
python scripts/build_test_update_package.py --version 2.0.0
python scripts/build_test_update_package.py --version 2.0.1 --broken
```

**Step 2: Run success scenario** (15 min)
- Upload v2.0.0 package to server
- Create UPDATE_CLIENT action on test PC
- Monitor and verify version updates to 2.0.0

**Step 3: Run failure scenario** (15 min)
- Upload v2.0.1 broken package to server
- Create UPDATE_CLIENT action on test PC
- Verify rollback to v2.0.0, client continues running

---

## Detailed Walkthrough

### Scenario 1: Successful Update (v1.x → v2.0.0)

#### 1a. Build v2.0.0 Package

On your build machine:

```bash
cd network-scanner
python scripts/build_test_update_package.py --version 2.0.0 --output-dir ./test_packages
```

Output:
```
============================================================
Building test update package v2.0.0
Broken: False
Output dir: C:\Users\...\test_packages
============================================================

  Copying app from C:\Users\...\client\app...
  Creating version.json: 2.0.0
  Created marker file: DEPLOYED_2_0_0
  Calculating file hashes...
  Created manifest.json
  Creating zip archive: client-update-2.0.0.zip
  ✓ Package created: C:\Users\...\test_packages\client-update-2.0.0.zip (3.45 MB)

✓ SUCCESS: Package ready at:
  C:\Users\...\test_packages\client-update-2.0.0.zip
```

#### 1b. Upload Package to Server

Using curl (or Postman):

```bash
SERVER_IP="192.168.1.100"  # Replace with your server IP
PACKAGE_FILE="./test_packages/client-update-2.0.0.zip"

curl -X POST "http://${SERVER_IP}:8080/api/v1/packages/upload" \
  -H "X-Package-Filename: client-update-2.0.0.zip" \
  -H "X-Operator-Id: test-milestone-f" \
  --data-binary "@${PACKAGE_FILE}" \
  -v
```

Expected response:
```json
{
  "data": {
    "package_id": "pkg-20260901-001-abc123",
    "filename": "client-update-2.0.0.zip",
    "size_bytes": 3619328,
    "uploaded_at": "2026-09-01T10:30:45Z",
    "uploaded_by": "test-milestone-f"
  },
  "meta": {}
}
```

**Save the `package_id` for the next step.**

#### 1c. Check Test Client's Current Version

On the test PC, verify current version:

```bash
# Windows (PowerShell)
Get-Content "C:\path\to\client\app\version.json" | ConvertFrom-Json

# Linux/Mac
cat ~/client/app/version.json
```

Expected output:
```json
{
    "version": "1.0.0",
    "release_date": "2026-08-01T00:00:00",
    "updater_version": "1.0.0"
}
```

**Note this timestamp for comparison after update.**

#### 1d. Create UPDATE_CLIENT Action

On server (or via API):

```bash
SERVER_IP="192.168.1.100"
TEST_CLIENT_ID="PC-TestUnit-001"  # Replace with actual client ID from server
PACKAGE_ID="pkg-20260901-001-abc123"  # From step 1b

curl -X POST "http://${SERVER_IP}:8080/api/actions" \
  -H "Content-Type: application/json" \
  -H "X-Operator-Id: test-milestone-f" \
  -d "{
    \"action_type\": \"UPDATE_CLIENT\",
    \"targets\": [\"${TEST_CLIENT_ID}\"],
    \"parameters\": {
      \"package_id\": \"${PACKAGE_ID}\"
    }
  }" \
  -v
```

Expected response:
```json
{
  "data": {
    "action_id": "action-20260901-update-pc001",
    "action_type": "UPDATE_CLIENT",
    "state": "PENDING",
    "targets": [
      {
        "target_id": "PC-TestUnit-001",
        "status": "PENDING"
      }
    ],
    "created_at": "2026-09-01T10:35:00Z"
  }
}
```

**Save the `action_id` for monitoring.**

#### 1e. Monitor Progress

Watch the action progress on server:

```bash
ACTION_ID="action-20260901-update-pc001"

# Check action status (repeat every 5-10 seconds)
curl "http://${SERVER_IP}:8080/api/actions/${ACTION_ID}"
```

Expected progression:
- T=0s: `"state": "PENDING"`, target status `PENDING`
- T=5-10s: `"state": "RUNNING"`, target status `RUNNING` (package transfer in progress)
- T=15-20s: `"state": "RUNNING"`, target status `RUNNING` (updater spawned, installing)
- T=30s: `"state": "COMPLETED"`, target status `COMPLETED`, result shows exit code 0

Full successful response:
```json
{
  "data": {
    "action_id": "action-20260901-update-pc001",
    "action_type": "UPDATE_CLIENT",
    "state": "COMPLETED",
    "created_at": "2026-09-01T10:35:00Z",
    "updated_at": "2026-09-01T10:35:45Z",
    "targets": [
      {
        "target_id": "PC-TestUnit-001",
        "status": "COMPLETED",
        "result": {
          "exit_code": 0,
          "message": "Update successful"
        }
      }
    ]
  }
}
```

#### 1f. Verify Client Version Updated

Wait 30–60 seconds for client to re-register with new version, then check server's client registry:

```bash
curl "http://${SERVER_IP}:8080/api/v1/clients/${TEST_CLIENT_ID}"
```

Expected response includes:
```json
{
  "data": {
    "client_id": "PC-TestUnit-001",
    "version": "2.0.0",
    "last_seen": "2026-09-01T10:36:15Z",
    ...
  }
}
```

**✓ SUCCESS SCENARIO COMPLETE** if:
- Action state is `COMPLETED`
- Target status is `COMPLETED` with exit code 0
- Server's client registry shows version `2.0.0`
- No errors in server/client logs

---

### Scenario 2: Failure + Rollback (Intentionally Broken Package)

#### 2a. Build v2.0.1 Broken Package

```bash
python scripts/build_test_update_package.py --version 2.0.1 --broken --output-dir ./test_packages
```

This package has invalid syntax in requirements.txt to force pip install to fail.

#### 2b. Upload Broken Package

```bash
PACKAGE_FILE="./test_packages/client-update-2.0.1.zip"

curl -X POST "http://${SERVER_IP}:8080/api/v1/packages/upload" \
  -H "X-Package-Filename: client-update-2.0.1.zip" \
  -H "X-Operator-Id: test-milestone-f-broken" \
  --data-binary "@${PACKAGE_FILE}" \
  -v
```

Save the returned `package_id`.

#### 2c. Verify Current Version Still 2.0.0

On test PC:
```bash
cat ~/client/app/version.json
# Should show version: 2.0.0
```

#### 2d. Create UPDATE_CLIENT Action for Broken Package

```bash
PACKAGE_ID="pkg-20260901-broken-def456"  # From upload response

curl -X POST "http://${SERVER_IP}:8080/api/actions" \
  -H "Content-Type: application/json" \
  -H "X-Operator-Id: test-milestone-f-broken" \
  -d "{
    \"action_type\": \"UPDATE_CLIENT\",
    \"targets\": [\"${TEST_CLIENT_ID}\"],
    \"parameters\": {
      \"package_id\": \"${PACKAGE_ID}\"
    }
  }" \
  -v
```

Save the `action_id`.

#### 2e. Monitor Progress

```bash
# Expected: PENDING → RUNNING → FAILED (when pip install fails)
curl "http://${SERVER_IP}:8080/api/actions/${ACTION_ID_BROKEN}"
```

Expected final response (failure):
```json
{
  "data": {
    "action_id": "action-20260901-broken-pc001",
    "state": "FAILED",
    "targets": [
      {
        "target_id": "PC-TestUnit-001",
        "status": "FAILED",
        "result": {
          "exit_code": 1,
          "message": "Dependency installation failed: ERROR: Invalid requirement: '...'",
          "rollback_status": "success"
        }
      }
    ]
  }
}
```

#### 2f. Verify Rollback Restored Old Version

On test PC, verify:

```bash
cat ~/client/app/version.json
# Should show version: 2.0.0 (rolled back from 2.0.1 attempt)
```

Check that client service is still running:
```bash
# Windows
Get-Process | Select-String "client"

# Linux
ps aux | grep client
```

Check server's client registry:
```bash
curl "http://${SERVER_IP}:8080/api/v1/clients/${TEST_CLIENT_ID}"
# version should still be 2.0.0
```

**✓ ROLLBACK SCENARIO COMPLETE** if:
- Action state is `FAILED`
- Target status is `FAILED` with exit code 1
- `rollback_status` field shows `success`
- Client version reverted to `2.0.0` on server
- Client service still running and responsive

---

## Troubleshooting

### Package Upload Fails

**Error:** `413 Payload Too Large`
- **Cause:** Package exceeds size limit (default 500 MB)
- **Fix:** Reduce package size or increase limit in package_service.py

**Error:** `403 Forbidden`
- **Cause:** Server storage directory not writable
- **Fix:** Check server permissions on `server/storage/packages/` directory
- **Note (Windows):** Ensure `server/storage/packages/` exists and is readable/writable by the Python process running the server

### Action Stays in RUNNING for Too Long

**Symptom:** Action stuck at `RUNNING` for >2 minutes
- **Check 1:** Is test PC on network? Ping server from test PC
- **Check 2:** Are client logs showing errors? Check `client/logs/`
- **Check 3:** Is network path writable? Test PC should write to updates/incoming/

### Update Completes but Version Not Updated on Server

**Cause:** Client hasn't sent heartbeat yet
- **Fix:** Wait 60 seconds or manually restart client to force registration
- **Check:** Server logs should show heartbeat with new version

### Rollback Didn't Occur (Old Version Lost)

**Cause:** Backup wasn't created or was deleted
- **Check:** `client/storage/updates/history/` should contain backup of 2.0.0
- **Fix:** Manually restore from backup if available, or reinstall original version

---

## Logging and Diagnostics

### Server-Side Logs

```bash
# Monitor action_service.py logs (should show UPDATE_CLIENT dispatch)
tail -f server/logs/action_service.log

# Monitor package transfer logs
tail -f server/logs/package_service.log
```

Expected log entries:
```
[action_service] UPDATE_CLIENT action-20260901-update-pc001 dispatched
[action_service] Deploying package pkg-20260901-001-abc123 to PC-TestUnit-001
[package_service] Streaming package to client: 3619328 bytes
[action_service] Client PC-TestUnit-001 reported COMPLETED status
```

### Client-Side Logs

On test PC:
```bash
# Windows: Check client logs
type "C:\path\to\client\logs\client.log"

# Linux: Check syslog or client logs
tail -f ~/client/logs/client.log
```

Expected log entries:
```
[client] Received UPDATE_CLIENT action action-20260901-update-pc001
[client] Receiving package chunk 1/50 (81920 bytes)
[client] Received final chunk, checksum validated, staging updater
[client] Spawning updater subprocess: python updater.py ...
[client] Action status updated to STAGED
[client] Client version updated from 1.0.0 to 2.0.0
```

### Updater Logs

```bash
# Updater runs as subprocess, logs to:
cat ~/client/logs/updater_<timestamp>.log
```

Expected entries (success):
```
[updater] Starting update process
[updater] Validating manifest.json
[updater] Backing up app/ to history/2.0.0/
[updater] Replacing app/ with staged package
[updater] Installing dependencies: pip install -r requirements.txt
[updater] Verifying client startup
[updater] Update successful, exiting with code 0
```

Expected entries (failure + rollback):
```
[updater] Starting update process
[updater] Validating manifest.json
[updater] Backing up app/ to history/2.0.0/
[updater] Replacing app/ with staged package
[updater] Installing dependencies: pip install -r requirements.txt
[updater] ERROR: Invalid requirement: '...'
[updater] Installation failed, rolling back
[updater] Restoring app/ from history/2.0.0/
[updater] Rollback successful, exiting with code 1
```

---

## Test Results Documentation

After completing both scenarios, document your results:

```markdown
# Milestone F Test Results
**Test Date:** 2026-09-01  
**Tester:** [Your Name]  
**Test PC:** PC-TestUnit-001  
**Server IP:** 192.168.1.100

## Scenario 1: Successful Update (v1.0.0 → v2.0.0)
- [ ] Package v2.0.0 created successfully
- [ ] Package uploaded to server (ID: ...)
- [ ] UPDATE_CLIENT action created (ID: ...)
- [ ] Action progressed: PENDING → RUNNING → COMPLETED
- [ ] Duration: ___ seconds
- [ ] Server shows version 2.0.0 after update
- [ ] Client log shows no errors
- [ ] Server log shows successful dispatch and completion

**Result:** PASS / FAIL  
**Notes:**

## Scenario 2: Failure + Rollback (v2.0.1 broken)
- [ ] Package v2.0.1 created with broken requirements.txt
- [ ] Package uploaded to server (ID: ...)
- [ ] UPDATE_CLIENT action created (ID: ...)
- [ ] Action progressed: PENDING → RUNNING → FAILED
- [ ] Duration: ___ seconds
- [ ] Rollback completed: server shows rollback_status=success
- [ ] Client version reverted to 2.0.0
- [ ] Client service still running and responsive
- [ ] Client logs show rollback details

**Result:** PASS / FAIL  
**Notes:**

## Overall Result
- [ ] Both scenarios passed on real hardware
- [ ] No service disruption during updates
- [ ] Logs show clean state machine transitions
- [ ] Ready to proceed to Milestone G

**Approved:** ___________  Date: __________
```

---

## What Happens Next

Once both scenarios pass:
1. Document results in test report (template above)
2. Archive test packages and action IDs in test results
3. Mark Milestone F as COMPLETE
4. Proceed to **Milestone G: Bulk Update Implementation**
   - Database schema setup
   - API function implementation
   - Multi-client coordination
   - Real hardware bulk test

---

## Reference

- **IMPLEMENTATION_STATUS.md** — Milestone F completion details
- **MILESTONE_F_TEST_PROCEDURE.md** — Detailed technical steps (alternative format)
- **MILESTONE_G_DESIGN.md** — Next milestone design (when F completes)
- **phase2.md** — Original requirements (lines 2115–2119)
