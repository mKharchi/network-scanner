# Phase 8 — Server Kismet Health and Recovery

**Status:** IN PROGRESS — health endpoint and source-freshness checks implemented; supervisor/recovery verification remains.

## Objective

Expose operational health for the externally supervised server sensor.

## Current implementation evidence

- `GET /api/v1/sensors/wifi/health` exposes process, interface, source-readability, capture-freshness, storage, and latest-capture fields.
- The UI health banner displays sensor state, interface, packet count, last observation time, and low-storage warnings.
- Focused service and REST tests pass; the real-capture runner reports health as `DEGRADED` when Kismet is stopped even though historical files remain.

## Remaining work

- Verify health against the approved service supervisor, adapter disappearance, storage outage, restart, and reboot scenarios.
- Move interface/process assumptions to deployment configuration and document health thresholds.

## Requirements

- report Kismet process/service, capture-source, source-read, storage-free-space, and last-capture health independently;
- define behavior for Kismet stop/restart, adapter disappearance, mount/storage outage, and server reboot;
- keep Kismet management/API local/private and authenticated when enabled;
- do not let a healthy application process imply a healthy capture source.

## Exit criterion

Operations can distinguish unavailable sensor/storage/query failure from a legitimate empty investigation result.
