# Milestone F Real Hardware Test Procedure

## Overview

This document provides step-by-step instructions to verify Milestone F's acceptance criteria:
1. Create and run a successful UPDATE_CLIENT on one physical test client (old version → new version)
2. Verify server shows updated version after success
3. Create and run a forced-failure case (bad requirements.txt)
4. Verify rollback restores old version and client continues running

## Prerequisites

- **Test Hardware:** One dedicated test PC running the current client (v1.x)
- **Server:** Network-accessible server running updated action_service.py with UPDATE_CLIENT support
- **Build Environment:** Python 3.8+ with zipfile, json, and pathlib available
- **Network:** Test PC and server must be on same network or have routing configured

## Step 1: Prepare Test Environment

### 1a. On Server: Check Supported Actions

```bash
curl http://SERVER_IP:8080/api/v1/actions
# Should include "UPDATE_CLIENT" in the list
```

### 1b. On Server: Verify Package Directory

```bash
# Server package store should exist and be writable
ls -la server/packages/
```

### 1c. On Test PC: Note Current Version

```bash
# Check installed client version
cat client/app/version.json
# Should show current version, e.g., "1.0.0"
```

## Step 2: Build Test Update Package (v2.0.0)

### 2a. Create Staging Directory

```bash
mkdir -p /tmp/test-update-v2.0.0/app
cd /tmp/test-update-v2.0.0
```

### 2b. Copy Current App and Bump Version

```bash
cp -r client/app/* /tmp/test-update-v2.0.0/app/

# Update version.json
cat > /tmp/test-update-v2.0.0/app/version.json << 'EOF'
{
    "version": "2.0.0",
    "release_date": "2026-09-01",
    "updater_version": "1.0.0"
}
EOF

# Optional: Add a marker file to confirm new version was deployed
cat > /tmp/test-update-v2.0.0/app/DEPLOYED_VERSION << 'EOF'
This file indicates successful deployment of v2.0.0
EOF
```

### 2c. Create Manifest

```bash
cat > /tmp/test-update-v2.0.0/manifest.json << 'EOF'
{
    "version": "2.0.0",
    "package_type": "client-update",
    "minimum_updater_version": "1.0.0",
    "file_hashes": {
        "version.json": "PLACEHOLDER_HASH_1",
        "client.py": "PLACEHOLDER_HASH_2",
        "requirements.txt": "PLACEHOLDER_HASH_3"
    },
    "release_notes": "Test update for Milestone F verification"
}
EOF
```

### 2d. Calculate Real File Hashes

Run this Python script to calculate actual SHA256 hashes:

```python
import hashlib
import json
from pathlib import Path

app_dir = Path("/tmp/test-update-v2.0.0/app")
hashes = {}

for fpath in app_dir.rglob("*"):
    if fpath.is_file():
        rel = fpath.relative_to(app_dir)
        with open(fpath, "rb") as f:
            hashes[str(rel).replace("\\", "/")] = hashlib.sha256(f.read()).hexdigest()

manifest = json.loads(Path("/tmp/test-update-v2.0.0/manifest.json").read_text())
manifest["file_hashes"] = hashes
Path("/tmp/test-update-v2.0.0/manifest.json").write_text(json.dumps(manifest, indent=2))
print("Manifest updated with real file hashes")
```

### 2e. Create Update Package ZIP

```bash
cd /tmp/test-update-v2.0.0
zip -r ../app-v2.0.0.zip manifest.json app/
ls -lh ../app-v2.0.0.zip
# Should be same size as current app (small difference for DEPLOYED_VERSION file)
```

## Step 3: Upload Package to Server

### 3a. Upload via Server API

```bash
PACKAGE_FILE="/tmp/app-v2.0.0.zip"
SERVER_IP="192.168.X.X"  # Change to your server IP

curl -X POST http://${SERVER_IP}:8080/api/v1/packages/upload \
  -F "file=@${PACKAGE_FILE}" \
  -F "package_id=app-v2.0.0" \
  -H "X-Package-Filename=app-v2.0.0.zip"
```

Or if no upload endpoint, copy directly to server's package directory:

```bash
cp /tmp/app-v2.0.0.zip server/packages/
```

### 3b. Verify Package on Server

```bash
# Server-side check
ls -la server/packages/app-v2.0.0*
# Should show the package file
```

## Step 4: Get Test Client ID

### 4a. On Server: List Connected Clients

```bash
curl http://SERVER_IP:8080/api/v1/clients | jq '.data[] | {client_id, hostname, version}'
# Note the client_id of the test PC you'll update
```

Example output:
```json
{
  "client_id": "PC-001-ABC123",
  "hostname": "testpc-001",
  "client_version": "1.0.0"
}
```

## Step 5: Create UPDATE_CLIENT Action

### 5a. POST Action to Server

```bash
CLIENT_ID="PC-001-ABC123"  # Use the ID from Step 4
PACKAGE_ID="app-v2.0.0"
SERVER_IP="192.168.X.X"

curl -X POST http://${SERVER_IP}:8080/api/actions \
  -H "Content-Type: application/json" \
  -H "X-Operator-Id: test-engineer" \
  -d '{
    "action_type": "UPDATE_CLIENT",
    "targets": ["'"${CLIENT_ID}"'"],
    "parameters": {
      "package_id": "'"${PACKAGE_ID}"'",
      "chunk_size": 131072
    }
  }'
```

### 5b. Capture Action ID from Response

```json
{
  "action_id": "action-abc123def456",
  "action_type": "UPDATE_CLIENT",
  "status": "PENDING",
  "targets": ["PC-001-ABC123"],
  "parameters": { ... }
}
```

Save the `action_id` for status tracking.

## Step 6: Monitor Update Progress

### 6a. Check Action Status on Server

```bash
ACTION_ID="action-abc123def456"

# Poll every 5 seconds
while true; do
  curl http://SERVER_IP:8080/api/actions/${ACTION_ID} | jq '.data | {status, action_type, targets}'
  sleep 5
done
```

Expected status progression:
1. `PENDING` → (action dispatched)
2. `RUNNING` → (package transfer in progress)
3. `COMPLETED` → (updater finished successfully)

### 6b. On Test Client: Monitor Client Logs

```bash
# In another terminal on test PC
tail -f client/logs/*.log
# Watch for:
# - PACKAGE_CHUNK frames received
# - PACKAGE_RESULT status=STAGED returned
# - Updater process spawned
# - Version update completed
```

### 6c. On Test Client: Monitor Process List

```bash
# Check if updater subprocess is running
# Windows: tasklist | findstr python
# Linux: ps aux | grep updater.py
```

## Step 7: Verify Successful Update

### 7a. Check Client Version Locally

```bash
# On test PC
cat client/app/version.json
# Should show "2.0.0"

# Check for marker file
ls -la client/app/DEPLOYED_VERSION
# Should exist
```

### 7b. Check Server's View of Client Version

```bash
# Query server API
curl http://SERVER_IP:8080/api/v1/clients/${CLIENT_ID} | jq '.data.client_version'
# Should show "2.0.0" (after client sends next heartbeat, typically ~10 seconds)

# May need to wait for client to send heartbeat
# Expected: within 30 seconds of successful update
```

### 7c. Verify Action Shows COMPLETED Status

```bash
curl http://SERVER_IP:8080/api/actions/${ACTION_ID} | jq '.data | {status, started_at, completed_at}'
# Should show status=COMPLETED
```

## Step 8: Test Failure Case (Bad Requirements)

### 8a. Create Broken Update Package (v2.0.1)

```bash
mkdir -p /tmp/test-update-v2.0.1/app
cp -r client/app/* /tmp/test-update-v2.0.1/app/

# Update version
cat > /tmp/test-update-v2.0.1/app/version.json << 'EOF'
{
    "version": "2.0.1",
    "release_date": "2026-09-01"
}
EOF

# Inject bad requirements that will fail pip install
cat > /tmp/test-update-v2.0.1/app/requirements.txt << 'EOF'
# Valid requirements
requests==2.28.0
cryptography==3.4.8

# Invalid requirement to trigger failure
nonexistent-package-xyz-9999==9999.0.0
EOF

# Calculate hashes and create manifest (as in Step 2d-c)
# Then create ZIP
cd /tmp/test-update-v2.0.1
zip -r ../app-v2.0.1-broken.zip manifest.json app/
```

### 8b. Upload Broken Package

```bash
cp /tmp/app-v2.0.1-broken.zip server/packages/
```

### 8c. Create UPDATE_CLIENT Action with Broken Package

```bash
curl -X POST http://${SERVER_IP}:8080/api/actions \
  -H "Content-Type: application/json" \
  -H "X-Operator-Id: test-engineer" \
  -d '{
    "action_type": "UPDATE_CLIENT",
    "targets": ["'"${CLIENT_ID}"'"],
    "parameters": {
      "package_id": "app-v2.0.1-broken",
      "chunk_size": 131072
    }
  }'
```

### 8d. Monitor Update Failure

```bash
# On test PC, watch logs
tail -f client/logs/*.log
# Expected to see:
# - PACKAGE_CHUNK frames received
# - PACKAGE_RESULT status=STAGED returned
# - Updater process starts
# - Updater process fails during dependency install
# - Rollback triggered
```

### 8e. Verify Rollback

```bash
# Check version on test PC (should still be 2.0.0)
cat client/app/version.json
# Should show "2.0.0", NOT "2.0.1"

# Check client is still running
# Windows: tasklist | findstr client.py
# Linux: ps aux | grep client.py

# Verify server shows version is still 2.0.0
curl http://SERVER_IP:8080/api/v1/clients/${CLIENT_ID} | jq '.data.client_version'
# Should show "2.0.0" (rolled back)

# Check action status shows failure
curl http://SERVER_IP:8080/api/actions/${ACTION_ID_BROKEN} | jq '.data.result'
# Should show status=FAILED, reason=DEPENDENCY_INSTALL_FAILED or similar
```

## Step 9: Acceptance Criteria Checklist

- [ ] **Successful update:** Old version (1.0.0) → new version (2.0.0) completed end-to-end
- [ ] **Server reflects update:** Server's client list shows version 2.0.0 after successful update
- [ ] **Failure case:** Broken package (bad requirements) triggers update failure
- [ ] **Rollback verified:** After failure, client continues running old version (2.0.0)
- [ ] **Rollback visible on server:** Server shows version is still 2.0.0 after failed update attempt
- [ ] **No service disruption:** Client remains connected and responsive throughout tests

## Troubleshooting

### Client Never Receives Package Chunks

**Symptom:** Action stays in RUNNING state for >5 minutes

**Solution:**
1. Check server logs for connection errors
2. Verify test PC can reach server (ping, nc)
3. Check firewall rules on both sides
4. Restart client and try again

### Updater Doesn't Spawn

**Symptom:** PACKAGE_RESULT returns status=STAGED, but client logs don't show updater process starting

**Solution:**
1. Check client has `updater/updater.py` file present
2. Verify Python executable is in PATH on test PC
3. Check client logs for `_spawn_updater_subprocess` error messages
4. Manually test updater: `python client/updater/updater.py <staged_zip_path> <client_root>`

### Version Doesn't Update on Server

**Symptom:** Update completes, but server still shows old version

**Solution:**
1. Wait 30–60 seconds for client to send next heartbeat
2. Manually force heartbeat by restarting client
3. Check client/app/version.json is actually updated
4. Verify server's heartbeat handler correctly reads `client_version` field

### Rollback Doesn't Work

**Symptom:** Client version changes to broken version despite dependency install failure

**Solution:**
1. Check that `storage/updates/history/` directory exists and has backup
2. Verify old app backup was created before replacement
3. Check updater logs for rollback error messages
4. Manually restore from backup: `cp -r storage/updates/history/2.0.0/* app/`

## Success Indicators

✓ **Successful update test:**
- Action status: COMPLETED
- Client version: 2.0.0
- Server version view: 2.0.0
- Client running: Yes
- Server logs: "Package deployed and verified successfully"

✓ **Failure + rollback test:**
- Action status: FAILED (reason: DEPENDENCY_INSTALL_FAILED)
- Client version: 2.0.0 (unchanged from before failed attempt)
- Server version view: 2.0.0
- Client running: Yes (continuous)
- Client logs: "Rollback triggered"

## Next Steps After Milestone F Sign-Off

Once both success and failure scenarios pass on real hardware:
1. Archive these test packages and procedure results
2. Proceed to Milestone G (bulk update with multi-select)
3. Use same test procedure for 3–5 test clients with mixed success/failure
