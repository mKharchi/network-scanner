# Documentation Restructuring & Codebase Accuracy Verification Plan

## Goal Description

The `docs/` directory currently contains 26+ folders created across various development phases, mixing completed architecture, historical sprint notes, intermediate research, and planned capabilities.

The goal is to restructure the entire documentation tree into a clean, modern, verified system:

1. **`docs/general/`**: System architecture, API contracts, configuration, testing, and operation runbooks.
2. **`docs/functionalities/completed/`**: A dedicated markdown file for every fully working capability, specifying:
   - What it does & high-level architecture
   - Associated code components & entrypoints
   - API endpoints, SSE streams, & TCP message types
   - Step-by-step execution flow
   - Data model & persistence
3. **`docs/functionalities/uncompleted/`**: Detailed, structured documentation for capabilities that are partially built, in-progress, or proposed for future iterations.
4. **Dedicated `README.md` for every created folder** with a description of contents and an explicit **reading order**.
5. **No Blind Copying — Codebase Accuracy & Deprecation Verification**:
   - Every file created or moved will be audited against the live codebase (`server/`, `client/app/`, `server/api_server.py`, `scripts.sql`, etc.) to verify its accuracy.
   - Deprecated concepts (e.g., outdated client-side Kismet assumptions, obsolete command names, dead endpoints) will be updated or archived rather than carried forward as current facts.
   - Historical sprint notes and research logs will be preserved in `docs/archive/`.

---

## User Review Required

> [!IMPORTANT]
> **Codebase Accuracy Verification Strategy**
> Before any documentation file is finalized in `docs/general/` or `docs/functionalities/completed/`, it will undergo cross-validation against the running codebase:
>
> 1. **Endpoint & Contract Verification**: Check `server/api_server.py`, `server_components/api_service.py`, and `server/docs/API_CONTRACT.md`. Ensure every documented route and payload reflects the actual routes in code.
> 2. **TCP Message & Protocol Verification**: Check `client/app/client.py` and `server/server_components/server_lib.py` message handling to guarantee frame formats (e.g. `REGISTER`, `HEARTBEAT`, `NEIGHBOURS`, `DHCP_DISCOVER`, `TELEMETRY`, `FLOWS`, `SCREENSHOT`, `ACTION_RESULT`) match reality.
> 3. **Component Architecture Verification**: Validate that class names, file paths, and background thread loops documented in each functionality file actually exist in `client/app/` and `server/server_components/`.
> 4. **Deprecated vs. Implemented Split**:
>    - Example: Any older plan claiming Windows clients run Kismet or capture wireless directly is deprecated. The current reality is: _Kismet is strictly server-owned on Linux_ (`server/kismet_interval_processor.py`, `server/server_components/kismet_service.py`).
>    - Example: Active & passive discovery engines use `unified_passive_discovery` and `network_neighbour_collector.py`. Any obsolete phase notes will be clearly distinguished from current implementations.

---

## Proposed Target Directory Layout

```text
docs/
├── README.md                                    # Root index and reading guide
├── general/                                     # System architecture, operations & configs
│   ├── README.md                                # General index & recommended reading order
│   ├── ARCHITECTURE.md                          # Current system architecture, boundaries & data flows
│   ├── API.md                                   # REST/SSE endpoints summary (verified against code)
│   ├── CONFIGURATION.md                         # Environment variables, ports & configs
│   ├── TESTING.md                               # Test suites & verification guidelines
│   ├── app-capabilities-and-progress.md         # Current capability inventory
│   └── operations/                              # Installation, updates & operational runbooks
│       ├── README.md                            # Operations reading order
│       ├── server-installation.md               # Linux server, MySQL, systemd
│       ├── client-installation.md               # Windows/Linux client deployment
│       ├── client-updates.md                    # Package deployment, updater & rollback
│       ├── legacy-client-migration.md           # Migration procedures for older clients
│       ├── backup-and-recovery.md               # Backup procedures & recovery boundaries
│       └── operations-and-troubleshooting.md    # Production troubleshooting runbook
├── functionalities/                             # Application capabilities
│   ├── README.md                                # Functionality catalog & reading guide
│   ├── completed/                               # Verified, fully implemented capabilities
│   │   ├── README.md                            # Reading order for completed features
│   │   ├── server-runtime.md                    # Server TCP registry, worker queues, REST/SSE
│   │   ├── client-agent.md                      # Client agent daemon, threads, and tasks
│   │   ├── discovery-and-observations.md        # Active ARP/neighbour, DHCP, & passive discovery
│   │   ├── telemetry-and-activity.md            # Hardware metrics, flow tracking, active window & screenshots
│   │   ├── security-and-isolation.md            # Forbidden processes, kill loop, network isolation / quarantine
│   │   ├── remote-actions.md                    # Command framework, state machine, REST dispatch
│   │   ├── packages-and-updates.md              # Package staging, verification, updater execution
│   │   ├── spatial-localization.md              # Coordinates, floor map assignment, digital twin
│   │   ├── kismet-investigation.md              # Server-side wireless capture, SQLite parsing, retention
│   │   ├── gui-console.md                       # React/Tauri frontend, real-time telemetry UI
│   │   └── storage-and-data-model.md            # Database schema (MySQL) & filesystem state
│   └── uncompleted/                             # In-progress and future planned capabilities
│       ├── README.md                            # Reading order, dependency map & priorities
│       ├── ROADMAP.md                           # Master roadmap and feature proposal template
│       ├── 01-ml-intelligence/                  # ML device fingerprinting, activity & threat models
│       │   └── README.md
│       ├── 02-3d-and-ar-visualization/          # 3D topology & AR-enhanced localization
│       │   └── README.md
│       ├── 03-autonomous-edge-agent/            # Edge AI self-healing agent
│       ├── 04-spatial-triangulation/            # Spatio-temporal rogue device triangulation
│       ├── 05-kismet-sensor-mesh/               # Distributed multi-sensor Kismet capture
│       └── 06-managed-client-orchestration/     # Global neighborhood collection orchestration
└── archive/                                     # Historical sprint notes & raw progress logs
    ├── README.md                                # Archive index & explanation of past development phases
    └── [archived phase logs & research]         # Retained for design history without cluttering docs
```

---

## Detailed Accuracy Verification Checklist

Before and during documentation authoring, the following verifications will be performed:

| Target Document                           | Live Code Verification Targets                                                               | Accuracy Checks                                                                                     |
| :---------------------------------------- | :------------------------------------------------------------------------------------------- | :-------------------------------------------------------------------------------------------------- |
| `general/ARCHITECTURE.md`                 | `server/server.py`, `client/app/client.py`                                                   | Verify process boundaries, ports (5000 TCP, 8080 REST), data flow directions.                       |
| `general/API.md`                          | `server/api_server.py`, `server/docs/API_CONTRACT.md`                                        | Verify exact HTTP paths (`/api/v1/...`), methods, and request/response envelopes.                   |
| `general/CONFIGURATION.md`                | `server/.env`, `client/app/client_lib.py`                                                    | Verify all environment variables, default values, and config file locations.                        |
| `completed/server-runtime.md`             | `server/server.py`, `server_components/server_lib.py`                                        | Verify client registration lifecycle, response queues, and worker threads.                          |
| `completed/client-agent.md`               | `client/app/client.py`, `client/app/client_lib.py`                                           | Verify actual collector loops, intervals, and TCP retry logic.                                      |
| `completed/discovery-and-observations.md` | `passive_protocol_listener.py`, `dhcp_listener.py`, `network_neighbour_collector.py`         | Verify protocols supported (mDNS, SSDP, LLMNR, NBNS, DHCP), schema fields, and deduplication logic. |
| `completed/telemetry-and-activity.md`     | `client/app/activity_window_aggregator.py`, `flow_aggregator.py`, `screenshot_manager.py`    | Verify metrics captured, window titling rules, flow hashing, and screenshot encoding.               |
| `completed/security-and-isolation.md`     | `client/app/process_monitor.py`, `quarantine_manager.py`, `server_components/api_service.py` | Verify process kill routines, isolation adapter states, and threat alert creation.                  |
| `completed/remote-actions.md`             | `client/app/action_framework.py`, `server_components/action_service.py`                      | Verify action states (`PENDING`, `DISPATCHED`, `COMPLETED`, `FAILED`), timeout handling.            |
| `completed/packages-and-updates.md`       | `server_components/package_service.py`, `client/updater/`                                    | Verify package packaging, SHA-256 validation, execution, and rollback script.                       |
| `completed/spatial-localization.md`       | `server_components/spatial_engine.py`, `location_repository.py`                              | Verify coordinates model, floor plans, assignment algorithms, and database tables.                  |
| `completed/kismet-investigation.md`       | `server/kismet_interval_processor.py`, `kismet_service.py`, `kismet_rotator.py`              | Verify server-side execution only, SQLite journal handling, retention rules.                        |
| `completed/gui-console.md`                | `server/gui/src/App.tsx`, `server/gui/src/api/client.ts`                                     | Verify UI routes, SSE listeners, state stores, and action triggers.                                 |
| `completed/storage-and-data-model.md`     | `server/scripts.sql`, `server/database.py`                                                   | Verify MySQL table names, foreign keys, indices, and JSON file storage locations.                   |

---

## Execution Phases

### Phase 1: Codebase Audit & Accuracy Pass

- Run targeted checks on `server/api_server.py`, `server/server.py`, `client/app/client.py`, and `server/scripts.sql`.
- Identify any discrepancies between current docs (`docs/project/`, `docs/general/`, `docs/gui/`) and the real code.

### Phase 2: Build `docs/general/`

- Populate `docs/general/` with verified system-wide guides (`ARCHITECTURE.md`, `API.md`, `CONFIGURATION.md`, `TESTING.md`).
- Organize `docs/general/operations/` with verified runbooks for server/client setup, update deployment, and recovery.
- Create `docs/general/README.md` and `docs/general/operations/README.md` with explicit, numbered reading orders.

### Phase 3: Build `docs/functionalities/completed/`

- Author comprehensive, verified markdown documentation for all 11 core capabilities.
- Each document will include:
  1. Purpose & Outcome
  2. Code Implementation Map (verified paths)
  3. API / Protocol Contracts (endpoints, parameters, responses)
  4. End-to-End Workflow / Step-by-Step Flow
  5. Data Storage & Schema
  6. Operational Constraints & Failure Modes
- Create `docs/functionalities/completed/README.md` with a recommended reading order.

### Phase 4: Organize `docs/functionalities/uncompleted/`

- Consolidate ongoing and planned feature research into clearly prioritized modules (ML intelligence, 3D/AR visualization, autonomous agent, spatial triangulation, multi-sensor mesh, managed client orchestration).
- Include `ROADMAP.md` with the feature proposal template.
- Create `docs/functionalities/uncompleted/README.md` outlining the status, reading order, and prerequisites for each uncompleted feature.

### Phase 5: Archive Legacy Notes & Update Root README

- Move historical phase logs and raw research into `docs/archive/`.
- Create `docs/archive/README.md` summarizing what is archived and why.
- Update `docs/README.md` to serve as the unified table of contents and reading roadmap for the entire system.

---

## Verification Plan

### Automated Verification

- Verify link integrity: check that all relative links between markdown documents and references to code files are valid.
- Verify git status: ensure no project code in `server/`, `client/`, or `gui/` has been unintentionally changed.

### Manual Verification

- Review directory structure with `tree docs/ -L 3`.
- Verify every folder contains a `README.md` with description and reading order.
- Verify every completed functionality document accurately reflects current code implementations.
- Verify uncompleted features are cleanly separated from completed features.
