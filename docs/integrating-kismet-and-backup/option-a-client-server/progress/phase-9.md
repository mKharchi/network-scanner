# Phase 9 — End-to-End and Regression Testing

**Status:** PENDING

## Objective

Validate real runtime, storage/query, application path, retention, health, and non-Kismet client behavior together.

## Exit criteria

- real Linux capture produces historical data and queryable known-device observations;
- synthetic unit tests cover deterministic parsing and errors;
- API/UI integration preserves exact range behavior and never uses client TCP for Kismet;
- rotated storage, unavailable storage, stopped Kismet, and invalid requests are distinct failure cases;
- client passive discovery, telemetry, flow aggregation, storage retention, and startup work after client Kismet code is removed;
- regression/build failures are recorded separately from this feature.
