# Phase 4 — Server Kismet Investigation Service

**Status:** PENDING

## Objective

Refactor `KismetInvestigationService` to query only the configured server-owned source and return normalized `KISMET_SERVER` observations.

## Requirements

- remove hard-coded server/developer capture discovery paths;
- preserve useful device resolution, MAC normalization, frame parsing, filtering, and summary logic where compatible with verified source;
- enforce bounded UTC time ranges and source-level result limits;
- distinguish empty success from Kismet/source/storage/query errors;
- do not add client Kismet transport, storage, or fallback behavior.

## Exit criterion

Service unit tests cover MAC roles, exact boundaries, limits, no data, malformed source, unavailable source, rotation, and provenance.
