# Phase 5 — REST and Alert Integration

**Status:** PENDING

## Objective

Keep the existing device and alert wireless-investigation routes while mapping stable server-sensor results/errors appropriately.

## Requirements

- API calls the server-local service only;
- preserve compatible device/query-window/summary/observations responses;
- validate lookback/custom-range semantics and bounded `all` policy;
- route alert-derived time windows through the same service;
- map unavailable sensor, unavailable storage, invalid range, and query failure separately;
- assert no client TCP request occurs.

## Exit criterion

Endpoint and alert integration tests pass with server-source fixtures.
