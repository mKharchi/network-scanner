# Phase 8 — Server Kismet Health and Recovery

**Status:** PENDING

## Objective

Expose operational health for the externally supervised server sensor.

## Requirements

- report Kismet process/service, capture-source, source-read, storage-free-space, and last-capture health independently;
- define behavior for Kismet stop/restart, adapter disappearance, mount/storage outage, and server reboot;
- keep Kismet management/API local/private and authenticated when enabled;
- do not let a healthy application process imply a healthy capture source.

## Exit criterion

Operations can distinguish unavailable sensor/storage/query failure from a legitimate empty investigation result.
