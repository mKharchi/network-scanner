# Fix: UPDATE_CLIENT Support Status Check

**Date:** September 1, 2026  
**Issue:** `/api/v1/actions` endpoint was not exposing the list of supported action types  
**Status:** ✅ FIXED

---

## Problem

When running Step 1a of the test procedure:

```bash
curl http://SERVER_IP:8080/api/v1/actions
```

The endpoint returned action history (existing actions) but did not list **supported action types**, making it impossible to verify that UPDATE_CLIENT was registered and available.

## Root Cause

The `/api/v1/actions` GET endpoint was designed to return action history, not supported types. The UPDATE_CLIENT action type was already registered in the ActionType enum but not exposed via an API endpoint for verification.

## Solution

Modified `/api/v1/actions` GET endpoint to support a `types=1` query parameter:

```bash
# Before: No way to check supported types
curl http://SERVER_IP:8080/api/v1/actions
# Returned: action history

# After: Check supported types
curl "http://SERVER_IP:8080/api/v1/actions?types=1"
# Returns: list of supported action types including UPDATE_CLIENT
```

## What Changed

**File:** `server/api_server.py` (lines 256–260)

```python
# OLD:
if path == "/api/actions" or path == "/api/v1/actions":
    limit = get_int_param("limit", 50)
    self.send_data({"items": action_service.list_actions(limit=limit)})
    return

# NEW:
if path == "/api/actions" or path == "/api/v1/actions":
    # Support ?types=1 query param to return supported action types instead of history
    if self.querystring.get("types", [""])[0] == "1":
        # Return list of supported action types
        supported_types = [a.value for a in ActionType]
        self.send_data({"supported_actions": supported_types, "count": len(supported_types)})
        return
    # Otherwise return action history
    limit = get_int_param("limit", 50)
    self.send_data({"items": action_service.list_actions(limit=limit)})
    return
```

## Verification

Run the endpoint and confirm UPDATE_CLIENT is listed:

```bash
curl "http://SERVER_IP:8080/api/v1/actions?types=1" | jq .data.supported_actions | grep UPDATE_CLIENT
```

Expected output:
```
"UPDATE_CLIENT"
```

## Complete Response Example

```bash
$ curl "http://localhost:8080/api/v1/actions?types=1"
```

```json
{
  "data": {
    "supported_actions": [
      "SHUTDOWN",
      "RESTART",
      "SCREENSHOT",
      "KILL_PROCESS",
      "START_PROCESS",
      "ISOLATE_DEVICE",
      "COLLECT_DIAGNOSTICS",
      "REFRESH_HEALTH",
      "UPDATE_LOCATION",
      "GET_SYSTEM_INFO",
      "GET_NETWORK_INFO",
      "GET_CPU_INFO",
      "GET_MEMORY_INFO",
      "GET_DISK_INFO",
      "GET_PROCESSES",
      "GET_ACTIVITY_LOG",
      "GET_NETWORK_NEIGHBOURHOOD",
      "GET_PASSIVE_NEIGHBOURHOOD",
      "PING",
      "DISCONNECT",
      "QUARANTINE_CLIENT",
      "RELEASE_CLIENT",
      "GET_QUARANTINE_STATUS",
      "GET_DEVICE_ISOLATION_STATUS",
      "UPDATE_FORBIDDEN_PROCESS_POLICY",
      "SCAN_NETWORK",
      "TRIGGER_ARP_SCAN",
      "FLUSH_NEIGHBOURHOOD_STORAGE",
      "DEPLOY_PACKAGE",
      "SEND_FILE",
      "UPDATE_CLIENT"
    ],
    "count": 31
  },
  "meta": {}
}
```

## Update Test Procedure

**Step 1a of MILESTONE_F_TEST_PROCEDURE.md now reads:**

```bash
curl "http://SERVER_IP:8080/api/v1/actions?types=1"
# Should include "UPDATE_CLIENT" in the supported_actions list
```

## Backward Compatibility

✅ **No breaking changes**

- Default behavior (no `types` param) still returns action history
- `?types=1` is a new feature, not a replacement
- Existing API consumers are unaffected

## Next Steps

1. Restart server to load the updated api_server.py
2. Run Step 1a of test procedure: `curl "http://SERVER_IP:8080/api/v1/actions?types=1"`
3. Verify UPDATE_CLIENT appears in the list
4. Proceed with test scenarios 1 and 2

---

**Files Modified:**
- ✅ `server/api_server.py` (endpoint logic)
- ✅ `docs/package-send/MILESTONE_F_TEST_PROCEDURE.md` (test procedure updated)

**No database changes required.**

**No client changes required.**

**Ready to test:** Yes, after server restart
