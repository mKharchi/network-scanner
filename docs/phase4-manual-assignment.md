# Phase 4 — Manual Assignment

> Plan reference: [auto-manual-client-localization.md](plans/auto-manual-client-localization.md) §29, Phase 4  
> Prior: [phase3-automatic-assignment.md](phase3-automatic-assignment.md)

---

## ✅ Task checklist

| # | Task | Status |
|---|------|--------|
| 1 | Create unassigned-client queue | ✅ Done |
| 2 | Add Assign button | ✅ Done |
| 3 | Open center layout | ✅ Done |
| 4 | Select location | ✅ Done |
| 5 | Confirm assignment | ✅ Done |
| 6 | Record administrator and timestamp | ✅ Done (Phase 2 PATCH path) |

---

## Backend

```text
GET /api/clients/unassigned
GET /api/v1/clients/unassigned
```

[`list_unassigned_clients()`](../server/server_components/api_service.py) returns clients with `location_id IS NULL`, plus:

- `unassigned_reason` — from `location_failure_reason` (or `"unassigned"`)
- `localization_confidence` — last auto confidence when present

Manual assignment continues to use:

```text
PATCH /api/clients/{id}/location  { "location_id": N }
```

which writes `MANUAL` / `ASSIGNED` / `verified=true` / administrator via Phase 2 metadata.

---

## Frontend

### Center layout ([`Locations.tsx`](../server/gui/src/pages/Locations.tsx))

- **Assignment queue** panel lists unassigned clients with reason + Assign
- Assign enters mode via `?assign=<client_id>`
- Selecting an empty seat prompts confirm and assigns
- Side panel also offers **Assign … here** for the selected empty seat
- Cancel clears assign mode

### Clients list ([`Clients.tsx`](../server/gui/src/pages/Clients.tsx))

- Unassigned rows show an **Assign** button → `/locations?assign=…`

### Dashboard

- Unassigned count links to `/locations` (queue) instead of only the clients filter

---

## Tests

```text
python3 -m unittest tests.test_location_assignment \
  tests.test_client_localization tests.test_client_registration -v
→ OK (includes test_list_unassigned_clients_adds_reason)
```

---

## Next

**Phase 5 — Center Visualization**: show AUTO vs MANUAL markers, confidence, and assignment method on layout seats.
