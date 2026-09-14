# Phase 9 — End-to-End and Regression Testing

**Status:** IN PROGRESS — runtime and client/server regressions pass; deployment fault-injection evidence remains.

## Objective

Validate real runtime, storage/query, application path, retention, health, and non-Kismet client behavior together.

## Current verification evidence

- `server/tests/e2e_phase9_real_capture.py`: 38 checks passed against seven local Kismet capture databases, including exact ten-minute bounds, ordering, provenance, limits, noise behavior, and health shape.
- Focused server service, contract, and retention suites: 49 tests passed.
- REST endpoint suite: 6 tests passed when run with local socket access.
- GUI `npm run build`: TypeScript and Vite build completed successfully.
- Live API query: a 10-minute request for `B0:3C:DC:95:39:36` returned 5
  bounded `KISMET_SERVER` observations from the active capture source, with
  microsecond timestamps and the expected summary/provenance fields.
- Recovery test: stopping Kismet produced `DEGRADED` health with the process
  and monitor interface absent; restarting it restored `ONLINE` health with a
  new process and capture file.
- Client baseline before removal: 275 tests passed, 1 skipped.
- Client cleanup: removed the obsolete Kismet listener module, startup/shutdown
  lifecycle wiring, listener tests, and client Kismet event-monitor exclusions.
- Client regression after removal: 266 tests passed, 1 skipped.
- Server regression after the resource-protection and network-test fixes:
  371 tests passed.

## Remaining work

- Verify rotated/active storage, unavailable storage, stopped Kismet, adapter loss, and supervisor recovery on the target Linux deployment.
- Record deployment-specific evidence and separate any pre-existing failures before marking Phase 9 complete.

## Exit criteria

- real Linux capture produces historical data and queryable known-device observations;
- synthetic unit tests cover deterministic parsing and errors;
- API/UI integration preserves exact range behavior and never uses client TCP for Kismet;
- rotated storage, unavailable storage, stopped Kismet, and invalid requests are distinct failure cases;
- client passive discovery, telemetry, flow aggregation, storage retention, and startup work after client Kismet code is removed;
- regression/build failures are recorded separately from this feature.
