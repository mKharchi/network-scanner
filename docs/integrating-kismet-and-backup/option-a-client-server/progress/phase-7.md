# Phase 7 — Server Kismet Retention and Cleanup

**Status:** PENDING

## Objective

Implement a dedicated server-side retention lifecycle for verified Kismet output.

## Requirements

- use measured target-server growth, configured retention, free-space reserve, dry-run, audit logs, and explicit cleanup ownership;
- exclude active capture files, active journals/WAL, files under investigation hold, and failed/unknown state;
- do not reuse the client telemetry retention manager without a source-specific safety review;
- test low-space warning, dry-run, eligible closed-file cleanup, permissions failure, and recovery.

## Exit criterion

Storage cannot grow indefinitely and cleanup cannot delete active/unsafe Kismet evidence.
