# Kismet Wireless Investigation

## Ownership model

Kismet belongs to the Linux server/sensor. The server runs the Kismet daemon
and capture helper, stores `.kismet` SQLite databases locally, and reads them
for targeted historical wireless investigation. Endpoint clients have no
Kismet listener or capture responsibility.

## Runtime

The current host profile is represented in `server/.env` and
`server/kismet_sensor.env.example`:

```text
managed interface:  wlp0s20f3
monitor interface:  wlp0s20f3mon
capture root:       /home/adonis/kismet
runtime state:      /var/lib/kismet
binary:             /usr/local/bin/kismet
Kismet HTTP:        127.0.0.1:2501
```

`kismet-sensor.service` runs as `kismet:kismet`, uses only the network
capabilities needed for capture, recreates the monitor VIF, and restarts on
failure. The `kismet_site.conf` override binds the Kismet HTTP service to
localhost. Authentication is configured in the Kismet runtime state.

## Query path

`server_components/kismet_service.py`:

1. Resolves a target device identifier/MAC.
2. Finds configured `.kismet` files.
3. Opens SQLite databases read-only.
4. Applies exact start/end/lookback and result limits.
5. Normalizes frame type/subtype, MAC roles, signal, frequency/channel,
   packet length, sensor, and capture-file provenance.
6. Filters control-frame noise by default and returns summary statistics.

The API exposes sensor inventory, health, and device wireless observation
routes. Health separates process, interface, source readability/freshness,
storage availability, and free-space reserve.

## Retention

`server_components/kismet_retention.py` and `scripts/kismet_retention.py` use
the approved 48-hour retention window and 5 GB free-space reserve. Safety rules
preserve the active target, recent-write files, SQLite sidecars, and
investigation-hold markers. Dry-run is the default; deletion requires an
explicit apply operation after reviewing the audit output.

## Incident and privacy boundary

Wireless captures may contain sensitive metadata. Access is localhost-only,
retention is bounded, and any investigation hold must be explicit. A future
Linux host needs a persistent mount, calibrated adapter, matching permissions,
authentication, and the same operational recovery tests before migration.

