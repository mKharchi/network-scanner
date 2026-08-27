# Phase 2 — Assignment Model

> Plan reference: [auto-manual-client-localization.md](plans/auto-manual-client-localization.md) §29, Phase 2  
> Prior: [phase1-inspection-report.md](phase1-inspection-report.md)

---

## ✅ Task checklist

| # | Task | Status |
|---|------|--------|
| 1 | Add assignment method | ✅ Done |
| 2 | Add assignment status | ✅ Done |
| 3 | Add confidence | ✅ Done |
| 4 | Add verification state | ✅ Done |
| 5 | Add assignment timestamp | ✅ Done |
| 6 | Add assigning administrator | ✅ Done |
| 7 | Preserve localization evidence where available | ✅ Done |

---

## Design choice

Extended the existing **`clients.location_id` FK** and **`client_location_history`** audit table rather than introducing a separate `ClientLocationAssignment` table.

- Current assignment state lives on `clients` (one active location per client).
- Historical assignments (with method/confidence/evidence) live on `client_location_history`.
- Matches Phase 1 guidance: extend the audit trail, do not replace it.

---

## Schema changes

### `clients` (current state)

| Column | Type | Notes |
|--------|------|-------|
| `location_assignment_method` | `VARCHAR(16)` | `AUTO` \| `MANUAL` |
| `location_assignment_status` | `VARCHAR(16)` | `PENDING` \| `ASSIGNED` \| `CONFIRMED` |
| `location_confidence` | `DOUBLE` | Auto-localization confidence |
| `location_verified` | `BOOLEAN` | Default `FALSE`; manual assigns set `TRUE` |
| `location_assigned_at` | `DATETIME` | When the current assignment was made |
| `location_assigned_by` | `VARCHAR(255)` | Operator id or localization actor |
| `location_last_calculated_at` | `DATETIME` | Last auto calculation time |
| `location_source` | `VARCHAR(64)` | `localization_engine` \| `administrator` |
| `location_evidence` | `TEXT` | JSON blob of localization evidence |

### `client_location_history` (audit)

| Column | Type |
|--------|------|
| `assignment_method` | `VARCHAR(16)` |
| `assignment_status` | `VARCHAR(16)` |
| `confidence` | `DOUBLE` |
| `verified` | `BOOLEAN` |
| `source` | `VARCHAR(64)` |
| `evidence` | `TEXT` |

Applied in:

- [`server/scripts.sql`](../server/scripts.sql) — canonical schema for new installs
- [`server/database.py`](../server/database.py) — `_ensure_client_location_assignment_columns` + `_ensure_client_location_history_assignment_columns` for existing DBs

---

## Service layer

New module: [`server/server_components/location_assignment.py`](../server/server_components/location_assignment.py)

- Constants for method / status / source
- Normalization helpers
- Evidence JSON serialize/parse
- `assignment_payload()` for API responses

[`assign_client_location()`](../server/server_components/api_service.py) now accepts:

```text
method, status, confidence, verified, source, evidence, last_calculated_at
```

Defaults preserve existing operator behavior:

```text
method=MANUAL, status=ASSIGNED, verified=True, source=administrator
```

Auto callers (Phase 3) will pass `method=AUTO`, confidence, evidence, and `verified=False`.

### API response shape

Assignment metadata is exposed as:

- `location.assignment` on layout seats / assigned locations
- `location_assignment` on client list/detail summaries
- `assignment` on history entries

Example:

```json
{
  "method": "MANUAL",
  "status": "ASSIGNED",
  "confidence": null,
  "verified": true,
  "assigned_at": "2026-08-27T10:00:00+00:00",
  "assigned_by": "local-network-operator",
  "last_calculated_at": null,
  "source": "administrator",
  "evidence": null
}
```

---

## Frontend types

[`server/gui/src/api/client.ts`](../server/gui/src/api/client.ts) adds `LocationAssignment` and wires it into:

- `ClientLocation.assignment`
- `ManagedClientSummary.location_assignment`
- `ClientLocationHistoryEntry.assignment`
- `ClientLocalizationDebug.location_assignment`

No UI changes in this phase (visualization is Phase 5).

---

## Tests

```text
python3 -m unittest tests.test_location_assignment tests.test_location_assignment_model -v
→ 18 OK
```

Covers manual defaults, auto confidence/evidence storage, and history metadata.

---

## Gaps remaining for later phases

| Gap | Phase |
|-----|-------|
| Automatic localization wrapper + confidence threshold | Phase 3 |
| Unassigned queue + layout Assign flow | Phase 4 |
| AUTO vs MANUAL visual distinction | Phase 5 |
| Confirm / move actions | Phase 6 |
| Real-time `client.location.updated` events | Phase 7 |

---

## Next

**Phase 3 — Automatic Assignment**: wrap existing `triangulate_position` / `find_closest_location` for managed clients on connect, apply a configurable confidence threshold, auto-assign when sufficient, otherwise leave unassigned with a failure reason for the manual queue.
