# Phase 7 — Server Kismet Retention and Cleanup

**Status:** IN PROGRESS — retention manager and focused safety tests exist; operational policy is not approved.

## Objective

Implement a dedicated server-side retention lifecycle for verified Kismet output.

## Current implementation evidence

- `server/server_components/kismet_retention.py` provides dry-run cleanup, retention-age and free-space checks, audit details, storage metrics, active-target protection, sidecar protection, and investigation-hold markers.
- Focused retention tests cover empty storage, dry-run behavior, deletion, active-target preservation, SQLite sidecars, and investigation holds.

## Remaining work

- Replace developer-default values with approved target-server configuration.
- Measure target-server growth and agree on retention/free-space values.
- Validate the cleanup job under the real supervisor in dry-run mode before enabling deletion.

## Requirements

- use measured target-server growth, configured retention, free-space reserve, dry-run, audit logs, and explicit cleanup ownership;
- exclude active capture files, active journals/WAL, files under investigation hold, and failed/unknown state;
- do not reuse the client telemetry retention manager without a source-specific safety review;
- test low-space warning, dry-run, eligible closed-file cleanup, permissions failure, and recovery.

## Exit criterion

Storage cannot grow indefinitely and cleanup cannot delete active/unsafe Kismet evidence.
