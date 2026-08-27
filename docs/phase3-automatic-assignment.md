# Phase 3 — Automatic Assignment

> Plan reference: [auto-manual-client-localization.md](plans/auto-manual-client-localization.md) §29, Phase 3  
> Prior: [phase2-assignment-model.md](phase2-assignment-model.md)

---

## ✅ Task checklist

| # | Task | Status |
|---|------|--------|
| 1 | Run localization when a client becomes eligible | ✅ Done |
| 2 | Apply confidence threshold | ✅ Done |
| 3 | Assign automatically when confidence is sufficient | ✅ Done |
| 4 | Send low-confidence clients to the manual queue | ✅ Done |
| 5 | Store the reason when automatic assignment fails | ✅ Done |

---

## What was built

### Localization wrapper

New module: [`server/server_components/client_localization.py`](../server/server_components/client_localization.py)

| Function | Role |
|----------|------|
| `calculate_client_location(client_id)` | Collect observations → `triangulate_position` → `find_closest_location` (assignable `pc_position` only). Does **not** write. |
| `try_automatic_client_location_assignment(client_id)` | Guard → calculate → threshold → assign or record failure |
| `schedule_automatic_client_location_assignment(client_id)` | Daemon thread; never blocks TCP registration |

Does **not** rewrite `spatial_engine` — it reuses the existing triangulation math.

### Confidence threshold

```text
CLIENT_LOCATION_AUTO_CONFIDENCE_THRESHOLD  (default 0.80)
```

```text
confidence >= threshold  →  AUTO + ASSIGNED (verified=false)
confidence <  threshold  →  PENDING + failure_reason=low_confidence
```

### Failure reasons stored on `clients.location_failure_reason`

| Reason | Meaning |
|--------|---------|
| `insufficient_evidence` | No usable sensor observations |
| `no_location_match` | Triangulation ok but no assignable seat |
| `low_confidence` | Below threshold |
| `location_occupied` | Matched seat already taken |
| `localization_unavailable` | DB unavailable |
| `manual_assignment_protected` | Skip — verified MANUAL location |
| `already_assigned` | Skip — client already has a seat |

Failed attempts set `method=AUTO`, `status=PENDING`, leave `location_id` NULL — these are the Phase 4 unassigned queue candidates.

### Connect hook

[`register_client`](../server/server_components/server_lib.py) schedules auto-assignment after successful new/reconnect registration (service/combined agents). Interactive-only early return is unchanged.

Protected: verified/confirmed **MANUAL** locations are never overwritten.

### API

```text
POST /api/clients/{client_id}/location/auto
```

Returns the structured auto-assignment outcome (assigned or reason + confidence).

Frontend helper: `api.autoAssignClientLocation(clientId)`.

---

## Tests

```text
python3 -m unittest tests.test_location_assignment \
  tests.test_location_assignment_model \
  tests.test_client_localization \
  tests.test_client_registration -v
→ 27 OK
```

---

## Gaps remaining

| Gap | Phase |
|-----|-------|
| Unassigned-client queue UI + Assign from layout | Phase 4 |
| AUTO vs MANUAL visual distinction on layout | Phase 5 |
| Confirm / move actions | Phase 6 |
| Real-time `client.location.updated` events | Phase 7 |

---

## Next

**Phase 4 — Manual Assignment**: `GET /api/clients/unassigned`, Assign button, open center layout, select seat, confirm, record administrator + timestamp (existing PATCH path already writes MANUAL metadata from Phase 2).
