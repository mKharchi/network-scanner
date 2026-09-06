# Phase 10 — Production Deployment

**Status:** PENDING

## Objective

Deploy the approved server-owned Kismet sensor safely.

## Requirements

- approved Linux server/service supervisor, monitor-capable adapter, persistent capture mount, permissions, and access controls;
- measured capacity and retention policy; cleanup initially validated in dry-run;
- documented observability, restart recovery, incident handling, and rollback;
- privacy/authorized-monitoring retention approvals;
- client Kismet removal only after server path and full regressions pass.

## Exit criterion

Production deployment has explicit ownership, operational evidence, bounded storage, and no Kismet workload or protocol responsibility on Windows clients.
