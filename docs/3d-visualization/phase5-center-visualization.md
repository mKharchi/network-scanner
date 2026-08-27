# Phase 5 — Center Visualization

> Plan reference: [auto-manual-client-localization.md](plans/auto-manual-client-localization.md) §29, Phase 5  
> Prior: [phase4-manual-assignment.md](phase4-manual-assignment.md)

---

## ✅ Task checklist

| # | Task | Status |
|---|------|--------|
| 1 | Display assigned clients | ✅ Done (existing) |
| 2 | Display automatically assigned clients differently | ✅ Done |
| 3 | Display manually assigned clients | ✅ Done |
| 4 | Show client identity | ✅ Done |
| 5 | Show confidence | ✅ Done |
| 6 | Show assignment method | ✅ Done |
| 7 | Add client selection | ✅ Done (existing) |
| 8 | Add location inspection | ✅ Done (extended) |

---

## Visual language

Shape markers (not color-only), per plan §11:

| Marker | Meaning |
|--------|---------|
| ● | AUTO |
| ◆ | MANUAL |
| ○ | Empty |

Seat meta shows e.g. `AUTO 91% · Healthy` or `MANUAL · Healthy`.

Helpers: [`server/gui/src/utils/stationAssignment.ts`](../server/gui/src/utils/stationAssignment.ts)

## Side panel

When a seat has a client, inspection shows:

- Assignment method (+ verified / unconfirmed)
- Confidence
- Assigned by / source / assigned at

Uses `location.assignment` from the layout join, falling back to `client.location_assignment`.

## Legend

Second legend row documents AUTO / MANUAL / empty markers alongside health colors.

---

## Next

**Phase 6 — Confirmation**: Confirm / Move actions for automatic assignments; keep manual confirmed seats protected from silent auto overwrite.
