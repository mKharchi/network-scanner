# Network Scanner Project Documentation

This directory is the current, operator-facing documentation set for the
Network Scanner and Management System. It explains the architecture that is
implemented in the repository today, how each major capability works, how to
install and operate the system, and where future work belongs.

The code is the final authority. When this documentation conflicts with the
code, tests, or deployed configuration, update this directory after resolving
the discrepancy. The older phase plans under `docs/` remain useful historical
records and are linked from the relevant pages, but they may describe an
earlier design or an intermediate implementation state.

## Documentation map

```text
docs/project/
├── README.md                         # This index and documentation rules
├── ARCHITECTURE.md                   # Components, processes, boundaries, and data flow
├── API.md                            # REST/SSE route groups and API usage model
├── CONFIGURATION.md                  # Server, client, GUI, Kismet, and storage settings
├── TESTING.md                        # Test suites, build checks, and verification workflow
├── functionalities/
│   ├── README.md                     # Capability index and implementation map
│   ├── server-runtime.md             # TCP server, registry, API, and SSE
│   ├── client-agent.md               # Client lifecycle, roles, listeners, and local state
│   ├── discovery-and-observations.md # Neighbour, DHCP, passive protocol, and packet flows
│   ├── telemetry-and-activity.md     # Health, telemetry, flows, activity, and screenshots
│   ├── security-and-isolation.md     # Policies, alerts, classification, and quarantine
│   ├── remote-actions.md             # Commands, action state machine, and execution
│   ├── packages-and-updates.md       # Package storage, deployment, updater, and rollback
│   ├── spatial-localization.md       # Locations, assignment, floors, and digital twin
│   ├── kismet-investigation.md       # Server-owned wireless capture and investigation
│   ├── gui.md                        # React/Tauri console pages and live data behavior
│   └── storage-and-data-model.md     # MySQL tables and filesystem artifacts
├── operations/
│   ├── server-installation.md        # Linux server installation and startup
│   ├── client-installation.md        # Fresh current client installation
│   ├── legacy-client-migration.md    # PCs that cannot receive server-managed updates
│   ├── client-updates.md             # Build and deploy managed client updates
│   ├── backup-and-recovery.md         # What is backed up, rollback, and recovery boundaries
│   └── operations-and-troubleshooting.md
└── planning/
    └── ROADMAP.md                    # New feature planning and decision template
```

## Read in this order

1. [Architecture](ARCHITECTURE.md)
2. [Functionality index](functionalities/README.md)
3. [Configuration](CONFIGURATION.md)
4. [Server installation](operations/server-installation.md)
5. [Client installation](operations/client-installation.md)
6. [Client updates](operations/client-updates.md)
7. [Testing](TESTING.md)
8. [Future planning](planning/ROADMAP.md)

## Current deployment summary

The supported production shape is a Linux server with MySQL, the Python TCP
and REST services, the React/Tauri operator console, and optional server-owned
Kismet wireless capture. Managed endpoint PCs run the client agent and make an
outbound TCP connection to the server on port `5000`. The REST API and SSE
stream use port `8080`; the current approved host profile binds them to
`127.0.0.1`. Kismet's local HTTP service uses `127.0.0.1:2501`.

The Kismet workload is server-owned. Windows clients do not install Kismet,
read Kismet databases, or run a Kismet protocol listener.

## Source-of-truth links

- Root orientation: [`../../README.md`](../../README.md)
- REST implementation: [`../../server/api_server.py`](../../server/api_server.py)
- REST contract: [`../../server/docs/API_CONTRACT.md`](../../server/docs/API_CONTRACT.md)
- TCP server: [`../../server/server.py`](../../server/server.py)
- Client entrypoint: [`../../client/app/client.py`](../../client/app/client.py)
- Database schema: [`../../server/scripts.sql`](../../server/scripts.sql)
- GUI routes: [`../../server/gui/src/App.tsx`](../../server/gui/src/App.tsx)
- Kismet deployment history: [`../integrating-kismet-and-backup/option-a-client-server/progress/phase-10.md`](../integrating-kismet-and-backup/option-a-client-server/progress/phase-10.md)
