# Phase 4 — Server Kismet Investigation Service

**Status:** IN PROGRESS — server-local query hardening implemented; final source-error policy remains.

## Objective

Refactor `KismetInvestigationService` to query only the configured server-owned source and return normalized `KISMET_SERVER` observations.

## Current implementation evidence

- Capture discovery now honors an explicit `capture_dirs` value, `KISMET_CAPTURE_DIRS`, or the configured `KISMET_CAPTURE_ROOT`; it no longer scans client/repository fallback directories by default.
- Queries merge all configured capture files, apply microsecond-exact inclusive bounds, preserve timestamp microseconds, sort globally newest-first, and enforce the result limit after rotation merging.
- Invalid timestamps and limits are rejected before SQLite access.
- Health metadata now reports source readability and capture freshness separately from process, interface, and storage state.
- Focused service and contract coverage is passing locally.

## Requirements

- remove hard-coded server/developer capture discovery paths;
- preserve useful device resolution, MAC normalization, frame parsing, filtering, and summary logic where compatible with verified source;
- enforce bounded UTC time ranges and source-level result limits;
- distinguish empty success from Kismet/source/storage/query errors;
- do not add client Kismet transport, storage, or fallback behavior.

## Remaining work

- Finalize distinct unavailable-storage/query-failure mapping without weakening the frozen empty-result contract.
- Complete API error mapping and source-rotation failure tests.

## Exit criterion

Service unit tests cover MAC roles, exact boundaries, limits, no data, malformed source, unavailable source, rotation, and provenance.
