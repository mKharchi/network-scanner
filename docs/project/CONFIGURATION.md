# Configuration Reference

## Server environment

The server loads `server/.env` with `python-dotenv`. Keep secrets in the local
file or a deployment secret store; do not commit them.

| Variable | Current/default role |
| --- | --- |
| `SERVER_HOST` / `SERVER_PORT` | TCP bind, normally server LAN address and `5000` |
| `API_HOST` / `API_PORT` | REST/SSE bind, approved profile `127.0.0.1:8080` |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | MySQL connection |
| `NETWORK_SCAN_INTERFACE`, `NETWORK_SCAN_SUBNET` | Server discovery overrides |
| `NETWORK_SCAN_STORAGE_DIR` | Scan JSON storage path |
| `PACKAGE_STORAGE_DIR` | Uploaded package path |
| `MAX_PACKAGE_SIZE_MB` | Package upload/deployment limit |
| `KISMET_CAPTURE_ROOT` | Server-owned `.kismet` capture directory |
| `KISMET_CAPTURE_INTERFACE` | Monitor-mode interface |
| `KISMET_MAIN_INTERFACE` | Managed Wi-Fi interface used to create the monitor VIF |
| `KISMET_HOMEDIR`, `KISMET_BINARY`, `KISMET_CONF_DIR` | Kismet runtime locations |
| `KISMET_RETENTION_HOURS` | Capture retention window; approved value `48` |
| `KISMET_MIN_FREE_BYTES` | Capture free-space reserve; approved value `5368709120` |
| `KISMET_HEALTH_STALE_SECONDS` | Capture freshness threshold; approved value `300` |
| `KISMET_CLEANUP_DRY_RUN` | Keep cleanup non-destructive; approved `true` |
| `KISMET_PRODUCTION_READY` | Deployment gate; set true only after verification |

Use [`server/kismet_sensor.env.example`](../../server/kismet_sensor.env.example)
as the portable Kismet template for another Linux host.

## Client environment

The current client loads `client/config/.env` first and supports the legacy
`client/.env` location during migration.

Required:

```env
SERVER_IP=192.168.1.10
SERVER_PORT=5000
```

Common optional settings include:

```env
CLIENT_ID=
NETWORK_NEIGHBOUR_HOSTNAME_LOOKUP_LIMIT=64
DHCP_LISTEN_INTERFACE=
NETWORK_SCAN_INTERFACE=
NETWORK_SCAN_SUBNET=
FORBIDDEN_PROCESS_SCAN_INTERVAL_SECONDS=600
PROCESS_SCAN_INTERVAL_SECONDS=10
PROCESS_ESCALATION_THRESHOLD=3
PROCESS_ESCALATION_WINDOW_SECONDS=120
RESOURCE_PROTECTION_SCAN_INTERVAL=5
SCREENSHOT_MAX_RESPONSE_BYTES=8388608
QUARANTINE_MAX_DURATION_MINUTES=60
AUTO_ISOLATE_ON_ESCALATION=0
```

The database variables belong only to the server. Do not copy the server
`.env` to endpoint PCs.

## GUI environment

The GUI uses the API origin configured by its Vite/Tauri build setup. In local
development it normally talks to the API on `127.0.0.1:8080`. If the GUI is
served from another machine, use an approved authenticated private proxy; do
not simply widen the API bind to the public network.

## Kismet configuration

Machine-specific Kismet values belong in the deployed Kismet configuration,
not in client code. The repository provides
[`kismet_site.conf.example`](../../kismet_site.conf.example), which binds the
Kismet HTTP service to `127.0.0.1`. Authentication credentials are kept in
Kismet runtime state and must be created and tested during installation.

## Configuration change procedure

1. Record the reason and target host.
2. Edit the local environment/configuration file.
3. Validate syntax and paths.
4. Restart only the affected service.
5. Check listeners, health endpoints, logs, and a real data path.
6. Record the resulting values in the deployment record.

