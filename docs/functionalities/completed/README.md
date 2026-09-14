# Completed Functionalities Index

This directory contains comprehensive, verified technical documentation for every completed and operational subsystem in the Network Scanner & Endpoint Management Platform.

Every document in this directory has been cross-referenced against the running server, client agent, database schemas, and REST/SSE API implementations to guarantee complete technical accuracy.

---

## 📖 Recommended Reading Order

To understand how each capability is built, connected, and operated, read the documents in this sequence:

1. **[Server Runtime, TCP Registry, & API](server-runtime.md)**
   - Core server architecture, TCP client listener, thread pools, REST endpoints, and Server-Sent Events (SSE).
2. **[Client Agent Daemon](client-agent.md)**
   - Endpoint client lifecycle, task monitors, local storage caching, heartbeat protocol, and reconnection engine.
3. **[Storage & Data Model](storage-and-data-model.md)**
   - Database schema (MySQL `scripts.sql`), repository methods, file audit formats, and retention rules.
4. **[Network Discovery & Observations](discovery-and-observations.md)**
   - Passive protocol listening (DHCP, mDNS, SSDP, LLMNR, NBNS), OS neighbour table aggregation, and multi-source scan merging.
5. **[Telemetry, Flows, & Activity Tracking](telemetry-and-activity.md)**
   - Hardware metrics (CPU/RAM/Disk), flow aggregations, active window logging, and on-demand desktop screenshots.
6. **[Security, Policy, & Network Isolation](security-and-isolation.md)**
   - Forbidden process monitoring, resource protection thresholds, alert dispatching, and quarantine / isolation controls.
7. **[Remote Actions Framework](remote-actions.md)**
   - Command dispatching state machine, asynchronous target execution, and REST action control.
8. **[Packages & Managed Client Updates](packages-and-updates.md)**
   - Package building, SHA-256 chunked transport, atomic extraction, venv dependency installation, and automated rollback.
9. **[Spatial Localization & Digital Twin](spatial-localization.md)**
   - Physical coordinate engine, floor plan geometry, automatic client placement, and 3D digital twin rendering.
10. **[Kismet Wireless Investigation](kismet-investigation.md)**
    - Server-side wireless sensor management, SQLite capture indexing, investigation queries, and capture retention.
11. **[Operator GUI Console](gui.md)**
    - React/Tauri frontend, real-time SSE stream consumption, component design system, and operational views.

---

## 📋 Capabilities Matrix

| Functionality | Summary | Key Code Components | Primary API Routes |
| :--- | :--- | :--- | :--- |
| [Server Runtime](server-runtime.md) | TCP server, registry, REST & SSE stream | `server.py`, `server_lib.py`, `api_server.py` | `/api/v1/dashboard`, `/api/v1/events` |
| [Client Agent](client-agent.md) | Endpoint agent daemon, collectors, watchdog | `client.py`, `client_lib.py` | Outbound TCP `:5000` |
| [Storage & Data](storage-and-data-model.md) | Database persistence & disk artifacts | `database.py`, `scripts.sql`, repositories | MySQL tables, `server/storage/` |
| [Network Discovery](discovery-and-observations.md) | Passive protocol listener, ARP, DHCP | `network_neighbour_collector.py`, `dhcp_listener.py` | `/api/v1/network/devices`, `/scans` |
| [Telemetry & Activity](telemetry-and-activity.md) | Metrics, flows, window logs, screenshots | `event_monitor.py`, `flow_aggregator.py`, `screenshot_manager.py` | `/api/v1/activity-logs`, `/screenshots` |
| [Security & Policy](security-and-isolation.md) | Policy enforcement, alerts, quarantine | `process_monitor.py`, `quarantine_manager.py` | `/api/v1/alerts`, `/settings/*` |
| [Remote Actions](remote-actions.md) | Action framework, state machine, commands | `action_service.py`, `action_framework.py` | `/api/actions`, `/api/v1/actions` |
| [Packages & Updates](packages-and-updates.md) | Staged client updates, rollback safety | `package_service.py`, `updater/updater.py` | `/api/v1/packages`, `/bulk-updates` |
| [Spatial Localization](spatial-localization.md) | Floor coordinates, digital twin, positioning | `spatial_engine.py`, `location_repository.py` | `/api/locations`, `/api/v1/spatial/*` |
| [Kismet Wireless](kismet-investigation.md) | Server-side capture & targeted investigation | `kismet_service.py`, `kismet_retention.py` | `/api/v1/sensors/wifi/*` |
| [Operator GUI](gui.md) | React/Tauri dashboard with live SSE invalidation | `server/gui/src/`, `api/client.ts` | Complete REST & SSE consumer |
