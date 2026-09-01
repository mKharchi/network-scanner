# Milestone F: Scenario 2 Rollback Test — Client Process Killing Fix

## Problem Identified

The updater subprocess was failing to stop the client process before attempting to replace app/ files. The `_stop_client()` function was trying to kill a non-existent executable:

```powershell
taskkill /F /IM NetworkScannerClient.exe  # ← This executable doesn't exist
```

The actual client process is a **Python process running `client.py`**, not a compiled executable.

## Solution Applied

Updated `client/updater/updater.py` lines 248–257:

**Before:**
```python
def _stop_client():
    """Stop the running client (platform-specific)."""
    import platform
    if platform.system() == "Windows":
        os.system("taskkill /F /IM NetworkScannerClient.exe")
    else:
        os.system("pkill -f 'python.*client.py'")
```

**After:**
```python
def _stop_client():
    """Stop the running client (platform-specific)."""
    import platform
    if platform.system() == "Windows":
        # Kill the Python process running client.py (not a compiled executable)
        os.system("taskkill /F /IM python.exe /FI \"COMMANDLINE eq *client.py*\"")
    else:
        os.system("pkill -f 'python.*client.py'")
    # Allow time for process to fully release file locks
    time.sleep(1.0)
```

## What This Fixes

1. **Correct Process Targeting**: Uses `taskkill /IM python.exe /FI "COMMANDLINE eq *client.py*"` to find and kill the Python process running client.py
2. **File Lock Release**: Adds a 1-second delay after killing the process to ensure Windows fully releases file locks on the app/ directory
3. **Cross-Platform Consistency**: Linux already had the correct logic; Windows now matches

## Expected Behavior in Scenario 2

When the updater runs with the broken v2.0.1 package:
1. **Stop Phase**: Client process is correctly terminated and file locks released ✅
2. **Extract Phase**: Broken package (with invalid requirements.txt) is extracted to staging ✅
3. **Validation Phase**: Hash check passes, but dependency installation fails (invalid requirements.txt) ✅
4. **Rollback Phase**: Backup of v2.0.0 is restored to app/ ✅
5. **Version**: Client version reverts to 2.0.0 ✅

This time, the rollback is triggered by **intentional package failure** (broken requirements.txt), not by file-locking exception.

## Test Execution

Run Scenario 2 via Postman:
- Create UPDATE_CLIENT action targeting `client-e4fd45ba8b96`
- Use package_id: `pkg-broken` (v2.0.1 with broken requirements.txt)
- Monitor action state: PENDING → RUNNING → FAILED
- Check updater.log for rollback result
- Verify client version returns to 2.0.0
