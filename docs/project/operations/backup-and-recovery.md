# Backup and Recovery Boundaries

This page distinguishes implemented rollback behavior from backups that still
need an external operational solution.

## Implemented recovery

### Client update rollback

The client updater copies the current `app/` tree to
`storage/updates/history/<version>/` before replacement. If validation,
dependency installation, or startup fails, it restores that tree and starts
the previous client when possible. Update results and state transitions remain
under `storage/updates/results/` for investigation.

### Network quarantine recovery

The client stores the prior network configuration and firewall/isolation state
before applying quarantine. `NetworkStateManager.restore_network()` uses the
saved state for local or authorized recovery. If the client is isolated from
the server, local administrator access may still be required.

### Kismet cleanup safety

Kismet retention is a cleanup safeguard, not a backup system. The retention
manager protects active targets, recent writes, sidecars, and investigation
holds. A separate copy/backup policy is required when captures must survive
source-disk failure or outlive the retention window.

## Data that needs an external backup policy

An operational backup plan should address each class separately:

- MySQL database: schema, client/device records, actions, alerts, locations,
  and classification state.
- `server/storage/`: activity logs, scan JSON, screenshots, packages, and
  feature-specific artifacts.
- Kismet capture root: `.kismet` files and any approved investigation holds.
- Deployment configuration: redacted environment templates, systemd units,
  Kismet override, interface/mount choices, and operator procedures.
- Endpoint data: only the local state required for migration/recovery; do not
  back up secrets or personal data by default.

## Recovery procedure

1. Identify the failed data class and stop only the affected writer.
2. Preserve logs, timestamps, action IDs, and current service state.
3. Restore into a staging path or database where possible.
4. Verify ownership, permissions, schema, and version compatibility.
5. Restart the affected service and run health/API checks.
6. Confirm a real read/write path before returning to production.
7. Record what was restored and what data was intentionally not recovered.

## Current limitation

The repository does not provide one universal production backup command. Do not
describe files under `backups/` as a complete restore set. Add a concrete,
tested backup implementation to the roadmap before relying on it for disaster
recovery.

