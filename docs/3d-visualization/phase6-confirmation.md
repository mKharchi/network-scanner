# Phase 6 — Confirmation

> Plan reference: [auto-manual-client-localization.md](plans/auto-manual-client-localization.md) §29, Phase 6
> Prior: [phase5-center-visualization.md](phase5-center-visualization.md)

---

## Status

| Task | Status |
|---|---|
| Confirm automatic assignments | ✅ Done |
| Correct/move automatic assignments | ✅ Done |
| Protect confirmed assignments from silent automatic overwrite | ✅ Done |
| Record changes | ✅ Done |

## Implementation

- `POST /api/clients/{id}/location/confirm` confirms the current assignment.
- Confirmation preserves the `AUTO` or `MANUAL` method while setting status to `CONFIRMED` and `verified = TRUE`.
- The authenticated operator is recorded through `X-Operator-Id` and the existing `client_location_history` audit row.
- The existing PATCH location flow provides the manual Move/Correction path and creates a new history entry when the location changes.
- Automatic recalculation now remains eligible for an unconfirmed `AUTO` assignment, but refuses to overwrite any verified or `CONFIRMED` assignment.
- Manual assignments remain protected by the existing manual-assignment guard.

## Verification

- Backend tests: `27` tests passed.
- Frontend build: TypeScript compilation and Vite build passed.
- Build warning: the installed Node.js version is below the Vite-recommended patch version; the build still completed successfully.
