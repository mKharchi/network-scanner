# Storage and Data Model

## MySQL

`server/scripts.sql` is the canonical schema for new installations. The main
table groups are:

| Group | Tables |
| --- | --- |
| Accounts of observed endpoints | `clients`, `connections`, `network_devices`, `sensors` |
| Device evidence | `network_device_observations`, `telemetry_devices`, `telemetry_activity_windows` |
| Spatial state | `locations`, `client_location_history`, `device_location_estimates`, `device_location_events` |
| Security | `alerts`, `forbidden_processes`, `working_hours`, `resource_protection_settings`, `rogue_device_assessments` |
| Operations | `actions`, `action_targets`, `packages`, `bulk_updates`, `bulk_update_actions` |
| Evidence | `activity_logs`, `screenshots`, `daily_network_scan_files` |
| Classification | `device_classifications`, `device_labels` |

Foreign keys and indexes in `scripts.sql` preserve ownership and make common
client/device/time/status queries bounded.

## Server filesystem

```text
server/storage/
├── activity_logs/       # persisted client activity payloads
├── network_scans/       # daily audit files and point-in-time scan snapshots
├── packages/            # uploaded/build client update packages
└── screenshots/         # validated images grouped by client
```

The server can also retain diagnostic and feature-specific files below
`server/storage/`. Keep these paths writable by the server process and protect
them from direct public web serving.

## Client filesystem

```text
client/
├── app/                 # replaceable application code and version.json
├── config/              # machine-specific .env, not replaced by updates
├── logs/                # startup, service, updater, and component logs
└── storage/
    ├── network_neighbourhood/
    ├── network_telemetry/
    ├── passive_packets/
    ├── updates/{incoming,staging,current,history,results}/
    └── device isolation, policy caches, and activity state
```

## Kismet filesystem

Kismet writes `.kismet` SQLite captures under the configured capture root and
runtime state under `/var/lib/kismet`. The server reads captures read-only for
investigation and retention metadata. Never delete the active target or its
sidecars manually.

## Retention and backups

Storage policies are source-specific. Client local state, server JSON/audit
files, screenshots, packages, MySQL, and Kismet captures must not be treated
as one undifferentiated backup set. The correct backup and deletion owner
should be recorded before adding a new persistent artifact.

