# Milestone G: Bulk Update Design & Implementation

## Overview

Milestone G extends Milestone F's single-client UPDATE_CLIENT to a selectable group of clients, with per-client visibility and aggregate status tracking.

**Key Design Decision:** Create **one independent UPDATE_CLIENT action per selected client** (not one shared action with multiple targets). This ensures:
- Per-client success/failure visibility (not opaque all-or-nothing)
- Failure in one client does not block others
- Easy to surface aggregate status (e.g., "18/20 updated, 2 failed")

## Requirements (from phase2.md)

1. Add multi-select UI/API for choosing target clients (individual, group, or "all")
2. On trigger, create **one independent action per selected client**
3. Surface aggregate + per-client status on server
4. Test on 3–5 test machines with ≥1 deliberately failing target
5. Confirm failures don't block other clients

## Architecture

### Client Selection

**Input Methods:**
- API: `POST /api/v1/bulk-updates/` with target selection strategy
- UI: Multi-select list of clients, or radio buttons (individual/all)

**Selection Strategies:**
- `"individual"`: Explicit list of client_ids
- `"all"`: All connected clients
- `"group"`: Clients matching a label/location (future feature)

### Action Creation Flow

**User Input:**
```
POST /api/v1/bulk-updates/
{
  "package_id": "app-v2.0.0",
  "target_selection": {
    "strategy": "individual" | "all",
    "client_ids": ["PC-001", "PC-002", ...]  // required if strategy="individual"
  },
  "bulk_update_id": "bulk-20260901-001"  // optional, for idempotency
}
```

**Server Processing:**
1. Validate package exists
2. Fetch target client list (based on strategy)
3. For each client, create **independent UPDATE_CLIENT action**
4. Return bulk update metadata with per-client action IDs
5. Dispatch all actions in parallel (ThreadPoolExecutor, same as fan-out)

**Response:**
```json
{
  "bulk_update_id": "bulk-20260901-001",
  "package_id": "app-v2.0.0",
  "created_at": "2026-09-01T10:30:00Z",
  "target_count": 5,
  "actions": [
    {
      "action_id": "action-pc001-...",
      "client_id": "PC-001",
      "status": "PENDING"
    },
    ...
  ],
  "aggregate_status": {
    "total": 5,
    "pending": 5,
    "running": 0,
    "completed": 0,
    "failed": 0
  }
}
```

### Monitoring/Status

**Endpoint:** `GET /api/v1/bulk-updates/<bulk_update_id>`

**Response:**
```json
{
  "bulk_update_id": "bulk-20260901-001",
  "package_id": "app-v2.0.0",
  "created_at": "2026-09-01T10:30:00Z",
  "target_count": 5,
  "aggregate_status": {
    "total": 5,
    "pending": 0,
    "running": 1,
    "completed": 3,
    "failed": 1
  },
  "per_client_status": [
    {
      "action_id": "action-pc001-...",
      "client_id": "PC-001",
      "hostname": "pc001.workshop",
      "status": "COMPLETED",
      "result": { "new_version": "2.0.0", "old_version": "1.0.0" }
    },
    {
      "action_id": "action-pc002-...",
      "client_id": "PC-002",
      "hostname": "pc002.workshop",
      "status": "FAILED",
      "result": { "reason": "DEPENDENCY_INSTALL_FAILED", "error": "..." }
    },
    {
      "action_id": "action-pc003-...",
      "client_id": "PC-003",
      "hostname": "pc003.workshop",
      "status": "RUNNING",
      "progress": { "bytes_transferred": 50000000, "total_bytes": 100000000 }
    },
    ...
  ]
}
```

### Storage

**Database Schema Addition:**

```sql
CREATE TABLE bulk_updates (
  id INT AUTO_INCREMENT PRIMARY KEY,
  bulk_update_id VARCHAR(255) UNIQUE NOT NULL,
  package_id VARCHAR(255) NOT NULL,
  target_selection_strategy VARCHAR(50),  -- "individual" | "all" | "group"
  target_count INT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  created_by VARCHAR(255),  -- operator ID
  INDEX (bulk_update_id),
  INDEX (package_id),
  INDEX (created_at)
);

CREATE TABLE bulk_update_actions (
  id INT AUTO_INCREMENT PRIMARY KEY,
  bulk_update_id VARCHAR(255) NOT NULL,
  action_id VARCHAR(255) NOT NULL,
  client_id VARCHAR(255) NOT NULL,
  status VARCHAR(50),  -- mirrors action status
  result JSON,  -- final success/failure result
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (bulk_update_id) REFERENCES bulk_updates(bulk_update_id),
  UNIQUE KEY (bulk_update_id, action_id),
  INDEX (bulk_update_id),
  INDEX (client_id),
  INDEX (action_id)
);
```

## Implementation Tasks

### Task 1: API Endpoint for Bulk Update Initiation

**File:** `server/server_components/api_service.py` (new function) + `server/api_server.py` (new route)

**Function:** `create_bulk_update(package_id, target_selection, requested_by, bulk_update_id)`

```python
def create_bulk_update(
    package_id: str,
    target_selection: Dict[str, Any],
    requested_by: str,
    bulk_update_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a bulk UPDATE_CLIENT operation targeting multiple clients.
    
    Returns one independent UPDATE_CLIENT action per target client.
    """
    bulk_update_id = bulk_update_id or uuid.uuid4().hex
    
    # 1. Validate package exists
    if not package_service.get_package(package_id):
        raise ValueError(f"Package '{package_id}' not found")
    
    # 2. Determine target clients based on strategy
    strategy = target_selection.get("strategy")
    if strategy == "individual":
        client_ids = target_selection.get("client_ids", [])
    elif strategy == "all":
        client_ids = [c["client_id"] for c in api_service.get_clients()]
    else:
        raise ValueError(f"Unknown selection strategy: {strategy}")
    
    if not client_ids:
        raise ValueError("No target clients selected")
    
    # 3. Create one action per client
    actions = []
    for client_id in client_ids:
        action = action_service.create_action(
            ActionType.UPDATE_CLIENT.value,
            [client_id],
            parameters={"package_id": package_id},
            requested_by=requested_by,
        )
        actions.append(action)
    
    # 4. Store bulk update record
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """INSERT INTO bulk_updates
               (bulk_update_id, package_id, target_selection_strategy, target_count, created_by)
               VALUES (%s, %s, %s, %s, %s)""",
            (bulk_update_id, package_id, strategy, len(client_ids), requested_by)
        )
        
        for action in actions:
            cursor.execute(
                """INSERT INTO bulk_update_actions
                   (bulk_update_id, action_id, client_id)
                   VALUES (%s, %s, %s)""",
                (bulk_update_id, action["action_id"], action["targets"][0])
            )
        
        conn.commit()
    finally:
        cursor.close()
        conn.close()
    
    # 5. Dispatch all actions in parallel
    for action in actions:
        threading.Thread(
            target=action_service.execute_action,
            args=(action,),
            daemon=True,
        ).start()
    
    return {
        "bulk_update_id": bulk_update_id,
        "package_id": package_id,
        "target_count": len(client_ids),
        "actions": actions,
        "aggregate_status": {
            "total": len(client_ids),
            "pending": len(client_ids),
            "running": 0,
            "completed": 0,
            "failed": 0,
        }
    }
```

**API Route:** `POST /api/v1/bulk-updates/`

```python
# In api_server.py do_POST handler
if path == "/api/v1/bulk-updates/":
    payload = self._read_json_payload()
    if payload is None:
        self.send_error_response(400, "INVALID_PAYLOAD", "Invalid JSON payload.")
        return
    
    try:
        bulk_result = api_service.create_bulk_update(
            package_id=payload.get("package_id"),
            target_selection=payload.get("target_selection", {}),
            requested_by=self.headers.get("X-Operator-Id") or "local-network-operator",
            bulk_update_id=payload.get("bulk_update_id"),
        )
        self.send_data(bulk_result, status_code=201)
    except ValueError as exc:
        self.send_error_response(400, "INVALID_REQUEST", str(exc))
    return
```

### Task 2: Status Tracking for Bulk Updates

**File:** `server/server_components/api_service.py` (new function)

**Function:** `get_bulk_update_status(bulk_update_id)`

```python
def get_bulk_update_status(bulk_update_id: str) -> Dict[str, Any]:
    """
    Fetch aggregate and per-client status for a bulk update.
    """
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # Get bulk update metadata
        cursor.execute(
            "SELECT * FROM bulk_updates WHERE bulk_update_id = %s",
            (bulk_update_id,)
        )
        bulk_rec = cursor.fetchone()
        if not bulk_rec:
            raise ValueError(f"Bulk update '{bulk_update_id}' not found")
        
        # Get all actions and their current status
        cursor.execute(
            """SELECT ba.action_id, ba.client_id, a.status, a.result
               FROM bulk_update_actions ba
               JOIN actions a ON a.action_id = ba.action_id
               WHERE ba.bulk_update_id = %s
               ORDER BY ba.created_at""",
            (bulk_update_id,)
        )
        action_rows = cursor.fetchall()
        
        # Calculate aggregate status
        status_counts = {"total": len(action_rows), "pending": 0, "running": 0, "completed": 0, "failed": 0}
        per_client = []
        
        for row in action_rows:
            status = row.get("status") or "PENDING"
            if status == ActionState.PENDING.value:
                status_counts["pending"] += 1
            elif status == ActionState.RUNNING.value:
                status_counts["running"] += 1
            elif status == ActionState.COMPLETED.value:
                status_counts["completed"] += 1
            elif status == ActionState.FAILED.value:
                status_counts["failed"] += 1
            
            # Get client details for richer output
            client_rec = server_lib.get_client(row["client_id"])
            client_hostname = client_rec.get("hostname") if client_rec else "unknown"
            
            per_client.append({
                "action_id": row["action_id"],
                "client_id": row["client_id"],
                "hostname": client_hostname,
                "status": status,
                "result": json.loads(row.get("result") or "{}"),
            })
        
        return {
            "bulk_update_id": bulk_update_id,
            "package_id": bulk_rec.get("package_id"),
            "created_at": bulk_rec.get("created_at").isoformat() if bulk_rec.get("created_at") else None,
            "target_count": bulk_rec.get("target_count"),
            "aggregate_status": status_counts,
            "per_client_status": per_client,
        }
    finally:
        cursor.close()
        conn.close()
```

**API Route:** `GET /api/v1/bulk-updates/<bulk_update_id>`

```python
# In api_server.py do_GET handler
m = re.match(r"^/api/v1/bulk-updates/([^/]+)$", path)
if m:
    try:
        bulk_status = api_service.get_bulk_update_status(urllib.parse.unquote(m.group(1)))
        self.send_data(bulk_status)
    except ValueError as exc:
        self.send_error_response(404, "NOT_FOUND", str(exc))
    return
```

### Task 3: List Bulk Updates

**Function:** `list_bulk_updates(limit=50)`

```python
def list_bulk_updates(limit: int = 50) -> List[Dict[str, Any]]:
    """Fetch list of bulk update operations with aggregate status."""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """SELECT bu.*, 
                      COUNT(bua.action_id) as total_actions,
                      SUM(CASE WHEN a.status = %s THEN 1 ELSE 0 END) as completed_count,
                      SUM(CASE WHEN a.status = %s THEN 1 ELSE 0 END) as failed_count
               FROM bulk_updates bu
               LEFT JOIN bulk_update_actions bua ON bu.bulk_update_id = bua.bulk_update_id
               LEFT JOIN actions a ON bua.action_id = a.action_id
               GROUP BY bu.id
               ORDER BY bu.created_at DESC
               LIMIT %s""",
            (ActionState.COMPLETED.value, ActionState.FAILED.value, limit)
        )
        results = cursor.fetchall()
        
        return [
            {
                "bulk_update_id": r["bulk_update_id"],
                "package_id": r["package_id"],
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                "target_count": r["target_count"],
                "completed": r.get("completed_count") or 0,
                "failed": r.get("failed_count") or 0,
                "pending": r["target_count"] - (r.get("completed_count") or 0) - (r.get("failed_count") or 0),
            }
            for r in results
        ]
    finally:
        cursor.close()
        conn.close()
```

**API Route:** `GET /api/v1/bulk-updates/`

### Task 4: Update Action Result Tracking

**Modification:** When an UPDATE_CLIENT action completes, update the `bulk_update_actions` table with the final result.

**File:** `server/server_components/action_service.py`

**Function:** `finalize_action(action_id, status, result)`

Add logic to execute_action (after action completes) to update bulk_update_actions.result:

```python
# In execute_action, after all targets complete:
conn = get_connection()
cursor = conn.cursor()
try:
    # Update bulk_update_actions if this action is part of a bulk update
    cursor.execute(
        """UPDATE bulk_update_actions bua
           SET bua.status = (SELECT status FROM actions WHERE action_id = bua.action_id)
           WHERE bua.action_id = %s""",
        (action_id,)
    )
    conn.commit()
finally:
    cursor.close()
    conn.close()
```

## Testing Strategy

### Unit Tests

**File:** `server/tests/test_bulk_update.py`

```python
class TestBulkUpdateCreation(unittest.TestCase):
    def test_create_bulk_update_individual_strategy(self):
        """Verify bulk update creates one action per selected client."""
        # Setup: mock clients
        # Call: create_bulk_update(package_id, {"strategy": "individual", "client_ids": ["PC-001", "PC-002"]})
        # Expect: 2 independent UPDATE_CLIENT actions created
        
    def test_create_bulk_update_all_strategy(self):
        """Verify bulk update with 'all' selects all connected clients."""
        # Setup: 5 mock connected clients
        # Call: create_bulk_update(package_id, {"strategy": "all"})
        # Expect: 5 independent actions
        
    def test_bulk_update_preserves_independence(self):
        """Verify failure in one action doesn't affect others."""
        # Setup: create 3 actions
        # Simulate: mark action 1 as FAILED
        # Expect: actions 2 and 3 remain independent (can still succeed/fail)

class TestBulkUpdateStatus(unittest.TestCase):
    def test_aggregate_status_calculation(self):
        """Verify aggregate status reflects per-action states correctly."""
        # Setup: 5 actions with mixed statuses (1 pending, 2 running, 1 completed, 1 failed)
        # Call: get_bulk_update_status()
        # Expect: aggregate_status counts are correct
        
    def test_per_client_status_includes_hostname(self):
        """Verify per-client status includes client hostname for UI display."""
        # Setup: action with client_id "PC-001"
        # Call: get_bulk_update_status()
        # Expect: per_client_status[0] includes hostname from client record
```

### Integration Tests (Real Hardware)

**Procedure:** Use 3–5 test clients, deliberately fail 1.

```bash
# Step 1: Create bulk update targeting 5 test PCs
curl -X POST http://SERVER:8080/api/v1/bulk-updates/ \
  -d '{
    "package_id": "app-v2.1.0",
    "target_selection": {"strategy": "all"},
    "bulk_update_id": "bulk-test-001"
  }'

# Step 2: Poll status until complete
while true; do
  curl http://SERVER:8080/api/v1/bulk-updates/bulk-test-001 | jq '.data.aggregate_status'
  sleep 10
done

# Expected final status: 4 completed, 1 failed
# Per-client: PC-001, PC-002, PC-003, PC-004 = SUCCESS; PC-005 = FAILED (injected bad requirements)
# Verify: PC-005 rolled back, still running old version
```

## Implementation Order

1. **Database schema** (`bulk_updates`, `bulk_update_actions` tables)
2. **Core function** `create_bulk_update()` in api_service.py
3. **Core function** `get_bulk_update_status()` in api_service.py
4. **API routes** in api_server.py (POST + GET endpoints)
5. **Result tracking** in action_service.py (finalize logic)
6. **Unit tests** in test_bulk_update.py
7. **Integration tests** on real hardware (3–5 test clients)
8. **UI integration** (optional, for Phase 2 closeout)

## Acceptance Criteria

- [ ] `POST /api/v1/bulk-updates/` creates N independent UPDATE_CLIENT actions for N clients
- [ ] `GET /api/v1/bulk-updates/<id>` returns accurate aggregate + per-client status
- [ ] Real hardware test: 5 clients with 1 deliberately failing; all others succeed independently
- [ ] Failed client shows correct failure reason in status API
- [ ] Successful clients all show new version in their profiles
- [ ] Failed client rolled back and shows old version

## Notes

- **No UI required for Phase 2 sign-off**, but API is stable and ready for GUI integration
- **Bulk update ID is optional** (server generates UUID if not provided) for idempotency
- **Streaming progress is per-action**, not per-bulk-update (client queries individual action_ids for detailed progress)
- **Future enhancement:** Add filtering/grouping by location, label, or OS type via extended selection strategies
