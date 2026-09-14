# Network Scanner & Endpoint Management Platform Documentation

Welcome to the central documentation library for the Network Monitoring, Device Discovery, and Centralized Endpoint Management system.

This documentation is organized into three primary sections: **General System Information**, **Completed Functionalities**, and **Uncompleted Functionalities & Roadmap**.

---

## 🧭 Master Documentation Layout

```text
docs/
├── README.md                                    # Master Documentation Index (this file)
│
├── general/                                     # Architecture, operations, configuration, and testing
│   ├── README.md                                # General index and recommended reading order
│   ├── ARCHITECTURE.md                          # System topology, boundaries, process lifecycles & data flows
│   ├── API.md                                   # REST API routes (/api/v1/*) & SSE event stream (/api/v1/events)
│   ├── CONFIGURATION.md                         # Environment variables, ports, timeouts, and flags reference
│   ├── TESTING.md                               # Unit testing, frontend build checks, and verification workflows
│   ├── app-capabilities-and-progress.md         # System capabilities inventory & maturity assessment
│   └── operations/                              # Installation, deployment, updating, and runbooks
│       ├── README.md                            # Operations reading order
│       ├── server-installation.md               # Linux server, MySQL database, supervisor unit & Kismet setup
│       ├── client-installation.md               # Windows & Linux client agent deployment guide
│       ├── client-updates.md                    # Building packages, staged deployment, hash checks & updates
│       ├── legacy-client-migration.md           # Upgrading older unmanaged or flat-layout endpoints
│       ├── backup-and-recovery.md               # Implemented rollback boundaries vs disaster recovery
│       └── operations-and-troubleshooting.md    # Production diagnostics, port checks & troubleshooting playbooks
│
├── functionalities/                             # Application features and capabilities
│   ├── README.md                                # Functionalities master index
│   ├── completed/                               # Fully implemented and verified capabilities
│   │   ├── README.md                            # Completed features reading order & capabilities matrix
│   │   ├── server-runtime.md                    # Server TCP registry, client message queues, REST/SSE
│   │   ├── client-agent.md                      # Client daemon, local workers, watchdog, and reconnection loop
│   │   ├── storage-and-data-model.md            # Database schema (MySQL scripts.sql) & filesystem state
│   │   ├── discovery-and-observations.md        # Passive discovery (DHCP, mDNS, SSDP, LLMNR, NBNS) & ARP merge
│   │   ├── telemetry-and-activity.md            # Hardware metrics, flow tracking, active window & screenshots
│   │   ├── security-and-isolation.md            # Forbidden processes, kill loop, network quarantine / isolation
│   │   ├── remote-actions.md                    # Command dispatching framework, state machine & REST control
│   │   ├── packages-and-updates.md              # Staged client updates, SHA-256 chunking, rollback mechanics
│   │   ├── spatial-localization.md              # Physical coordinates, floor geometry, 3D digital twin
│   │   ├── kismet-investigation.md              # Server-side wireless capture, SQLite queries & retention
│   │   └── gui.md                               # React/Tauri console, live SSE stream, component design system
│   │
│   └── uncompleted/                             # In-progress and future planned capabilities
│       ├── README.md                            # Uncompleted features reading order & dependency map
│       ├── ROADMAP.md                           # Master roadmap (P0/P1/P2) & new feature proposal template
│       ├── 01-ml-intelligence/                  # Wireless ML probe fingerprinting, activity & anomaly models
│       ├── 02-3d-and-ar-visualization/          # True 3D topology graphs & mobile AR overlay plans
│       ├── 03-autonomous-edge-agent/            # Disconnected edge inference & autonomous self-healing agent
│       ├── 04-spatial-triangulation/            # Multi-vantage rogue device RSSI trilateration
│       ├── 05-kismet-sensor-mesh/               # Distributed multi-node wireless capture mesh
│       └── 06-managed-client-orchestration/     # Large-fleet scan orchestration & rate limiting
│
└── archive/                                     # Historical sprint notes, phase logs & raw research
    └── README.md                                # Archive index and mapping to canonical documents
```

---

## 📖 Recommended Master Reading Order

If you are new to the repository or setting up the platform, follow this reading sequence:

1. **Understand the System Architecture**: Start with [General System Architecture](general/ARCHITECTURE.md) to understand process boundaries, transports (TCP port `5000`, REST/SSE port `8080`), and components.
2. **Review Configuration Parameters**: Read [Configuration Reference](general/CONFIGURATION.md) to understand server `.env` and client `config/.env` settings.
3. **Explore Completed Functionalities**: Dive into [Completed Functionalities Index](functionalities/completed/README.md) to understand how each specific subsystem works (discovery, telemetry, actions, security, spatial localization, etc.).
4. **Deploy Server & Endpoints**: Follow the operations runbooks starting with [Server Installation](general/operations/server-installation.md) and [Client Installation](general/operations/client-installation.md).
5. **Explore the Future Roadmap**: Review [Feature Roadmap](functionalities/uncompleted/ROADMAP.md) and [Uncompleted Functionalities](functionalities/uncompleted/README.md) for planned machine learning, 3D visualization, and distributed sensor mesh features.

---

## 🔍 Codebase Accuracy & Source of Truth

All documentation in `general/` and `functionalities/completed/` has been verified against the live codebase:
- **Server Entrypoint**: [`server/server.py`](../server/server.py)
- **REST & SSE Server**: [`server/api_server.py`](../server/api_server.py)
- **Client Agent Entrypoint**: [`client/app/client.py`](../client/app/client.py)
- **Database Schema**: [`server/scripts.sql`](../server/scripts.sql)
- **Desktop GUI Console**: [`server/gui/src/App.tsx`](../server/gui/src/App.tsx)
