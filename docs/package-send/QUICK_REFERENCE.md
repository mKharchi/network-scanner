# Phase 2 Quick Reference Card

## Current Phase
**Milestone F: Single-Client UPDATE_CLIENT** — Ready for real hardware testing

---

## 3-Step Testing (40 minutes)

### 1. Build Packages (5 min)
```bash
cd network-scanner
python scripts/build_test_update_package.py --version 2.0.0
python scripts/build_test_update_package.py --version 2.0.1 --broken
```

### 2. Test Success Scenario (15 min)
```bash
# Upload v2.0.0 to server
curl -X POST "http://SERVER_IP:8080/api/v1/packages/upload" \
  -H "X-Package-Filename: client-update-2.0.0.zip" \
  --data-binary "@./test_packages/client-update-2.0.0.zip"

# Create UPDATE_CLIENT action with returned package_id
curl -X POST "http://SERVER_IP:8080/api/actions" \
  -H "Content-Type: application/json" \
  -d "{ \"action_type\": \"UPDATE_CLIENT\", \"targets\": [\"PC-ID\"], \"parameters\": { \"package_id\": \"PACKAGE_ID\" } }"

# Monitor action (should go PENDING → RUNNING → COMPLETED)
curl "http://SERVER_IP:8080/api/actions/ACTION_ID"

# Verify client version updated to 2.0.0 on server
curl "http://SERVER_IP:8080/api/v1/clients/PC-ID"
```

**Pass If:** Action shows COMPLETED, exit code 0, server shows version 2.0.0

### 3. Test Failure Scenario (15 min)
Same steps but with v2.0.1 broken package.

**Pass If:** Action shows FAILED, exit code 1, rollback_status=success, server still shows version 2.0.0

---

## Critical Files

| File | Purpose |
|------|---------|
| [TEST_EXECUTION_GUIDE.md](TEST_EXECUTION_GUIDE.md) | **Start here** — full walkthrough with examples |
| [MILESTONE_F_TEST_PROCEDURE.md](MILESTONE_F_TEST_PROCEDURE.md) | Alternative format with detailed steps |
| [build_test_update_package.py](../../scripts/build_test_update_package.py) | Automate package building |
| [PHASE_2_NEXT_STEPS.md](PHASE_2_NEXT_STEPS.md) | Action items and effort estimates |
| [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) | Current state of all milestones |
| [MILESTONE_G_DESIGN.md](MILESTONE_G_DESIGN.md) | Design for next milestone (when F completes) |
| [phase2.md](phase2.md) | Original specification |

---

## Milestones Status

```
✓ A: Audit
✓ B: Storage Separation
✓ C: Versioning
✓ D: Folder Refactor
✓ E: Updater
→ F: Single-Client UPDATE_CLIENT (TESTING NOW)
  G: Bulk Updates (blocked until F passes)
```

---

## Key Contacts / Logs

**Server logs:**
```bash
tail -f server/logs/action_service.log
tail -f server/logs/package_service.log
```

**Client logs:**
```bash
tail -f ~/client/logs/client.log
tail -f ~/client/logs/updater_*.log
```

**Test results template:** See bottom of TEST_EXECUTION_GUIDE.md

---

## Expected Timings

- Package build: 5 min
- Package upload: 30 sec
- Action creation: 10 sec
- Package transfer: 10–20 sec
- Updater execution: 10–30 sec
- Client re-registration: 30–60 sec
- **Total end-to-end: 2–3 minutes**

---

## Troubleshooting Quick Checks

| Issue | Check | Fix |
|-------|-------|-----|
| Package upload fails | Server logs, disk space | Check `server/packages/` permissions |
| Action stuck RUNNING | Network connectivity | Ping test PC from server, check client logs |
| Version not updated on server | Time elapsed | Wait 60 sec or restart client to force registration |
| Rollback didn't work | Check `client/storage/updates/history/` | Verify backup was created before replacement |
| Client offline after update | Check service status | Verify client process still running, check logs |

---

## What Happens After F Passes

1. Document test results (template in TEST_EXECUTION_GUIDE.md)
2. Start Milestone G (see MILESTONE_G_DESIGN.md)
3. Estimate: **7–11 hours** for full Milestone G

---

## Copy-Paste Commands

**Check test client version on server:**
```bash
curl "http://192.168.1.100:8080/api/v1/clients/PC-TestUnit-001" | grep version
```

**Monitor action until complete:**
```bash
while true; do 
  curl -s "http://192.168.1.100:8080/api/actions/ACTION_ID" | grep -o '"state":"[^"]*"'
  sleep 3
done
```

**Generate test package with script:**
```bash
python scripts/build_test_update_package.py --version 2.0.0 --output-dir ./test_packages
```

**Check for network issues (from test PC to server):**
```bash
ping 192.168.1.100
curl http://192.168.1.100:8080/health
```

---

**Created:** September 1, 2026  
**Last Updated:** September 1, 2026  
**Status:** Ready for Milestone F testing
