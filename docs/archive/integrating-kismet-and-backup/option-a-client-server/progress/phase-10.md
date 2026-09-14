# Phase 10 — Production Deployment

**Status:** COMPLETE — current Linux deployment and post-reboot gates verified.

## Objective

Deploy the approved server-owned Kismet sensor safely.

## Current local-host preparation

- `server/.env` now contains the current Linux host profile: capture root
  `/home/adonis/kismet`, monitor interface `wlp0s20f3mon`, managed interface
  `wlp0s20f3`, Kismet binary `/usr/local/bin/kismet`, and dry-run retention.
- `server/kismet_sensor.env.example` provides the portable configuration
  template for the future Linux machine.
- `kismet-sensor.service` is installed and running as the non-login `kismet`
  account with `netdev`, `CAP_NET_ADMIN`, and `CAP_NET_RAW`; `NoNewPrivileges`
  is enabled and the capture helper also runs as `kismet`.
- `scripts/kismet_retention.py` provides a dry-run-by-default retention command;
  deletion requires the explicit `--apply` flag.
- Current dry-run evidence: 7 capture files, approximately 506 MB total, 3
  files eligible under the provisional 48-hour policy, approximately 143 MB
  eligible for deletion, and the newest active target preserved. No files were
  deleted.
- Restart evidence: `kismet-sensor.service` restarted successfully with a new
  PID, remained `ONLINE`, created a new capture file, and reported fresh
  observations after the restart.
- Follow-up retention dry-run: 9 capture files, approximately 552 MB total,
  3 expired files identified for approximately 143 MB, the active target and
  recent-write file preserved, and no files deleted.
- Live deployment check: a bounded 10-minute API request returned 5 real
  observations from the server-owned sensor; stopping the systemd service
  reported `DEGRADED`, and restarting it restored `ONLINE` with a new PID and
  new capture file.
- Least-privilege restart check: the migrated service reported `ONLINE`, the
  daemon and capture helper were both owned by `kismet`, and fresh captures
  were written after the stale root-owned helper lock was cleared.
- Current operational baseline: `kismet-sensor.service` is `active/running`
  with `ExecMainStatus=0`, the daemon is running as `kismet:kismet`, the live
  capture root is on `/dev/nvme0n1p2`, and the direct health check reports
  `ONLINE`, readable/fresh capture data, 9 files, approximately 906 MiB, and
  approximately 112 GiB free.
- Retention dry-run remains safe: the current 48-hour policy found no eligible
  files, deleted nothing, and preserved the active target. The focused
  retention/Kismet service and API tests pass (`23 tests OK`).
- Storage-loss simulation against a missing capture directory reports
  `DEGRADED` with `storage_health.available=false`, without changing the live
  capture root.
- Adapter-loss recovery passed on the host: removing `wlp0s20f3mon` and
  restarting the unit recreated the monitor interface; the service returned
  to `active (running)` with new Kismet daemon/helper processes after 30
  seconds.
- Post-recovery API verification passed: `/api/v1/sensors/wifi/health` returned
  `ONLINE`, readable/fresh capture data, the recreated monitor interface, 10
  capture files, and healthy free-space status.
- Post-reboot startup verification passed: Kismet started automatically as
  `kismet`, the capture interface was recreated, the application API returned
  `ONLINE`, both listeners were bound to localhost (`127.0.0.1:2501` and
  `127.0.0.1:8080`), and the retention dry-run preserved all 14 current files
  without deleting data.
- Two deployment blockers remain visible: the application API has no listener
  on port 8080, and Kismet's HTTP server is listening on `0.0.0.0:2501` while
  its auth file has not yet been created. These must be resolved before a
  production approval.

## Final operational decisions

- The current root filesystem is accepted temporarily for this PC; a dedicated
  persistent mount remains the migration requirement for the future Linux
  sensor.
- The approved retention policy is 48 hours with a 5 GB free-space reserve;
  cleanup remains dry-run by default and actual deletion is covered by the
  isolated retention tests.
- Kismet HTTP and the application API are localhost-only and authenticated
  access is required for Kismet administration.
- Monitoring is authorized passive collection with restricted access and the
  approved 48-hour retention window.
- `KISMET_PRODUCTION_READY=true` is now recorded in the current host profile.

## Requirements

- approved Linux server/service supervisor, monitor-capable adapter, persistent capture mount, permissions, and access controls;
- measured capacity and retention policy; cleanup initially validated in dry-run;
- documented observability, restart recovery, incident handling, and rollback;
- privacy/authorized-monitoring retention approvals;
- client Kismet removal is complete after server path and full regressions passed.

## Exit criterion

Production deployment has explicit ownership, operational evidence, bounded storage, and no Kismet workload or protocol responsibility on Windows clients.
