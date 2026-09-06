# Phase 6 — UI Compatibility and Source Provenance

**Status:** PENDING

## Objective

Validate that the existing wireless investigation UI remains compatible with the server-owned source and expose only necessary source-status/truncation details.

## Requirements

- preserve current lookback/custom range, noise, limit, rendering, and export behavior unless a verified API contract requires a compatible update;
- make `KISMET_SERVER` provenance/sensor identity visible where useful;
- do not add client Kismet controls, client selection, or client-specific retrieval states;
- replace or bound `All Available Captures` if it conflicts with server query safety;
- run TypeScript/build and response-fixture tests.

## Exit criterion

An analyst can query the server-owned sensor through the existing UI with accurate availability/error messaging.
