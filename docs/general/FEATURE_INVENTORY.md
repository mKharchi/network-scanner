# Currently Implemented Features Inventory

This document provides a comprehensive breakdown of all features currently implemented in this **Network Monitoring & Client Management System**. Use this inventory as a reference baseline for comparative analysis against existing network scanning, monitoring, and Remote Monitoring & Management (RMM) software solutions.

---

## 1. Architecture & Core Capabilities

- **Decoupled Architecture**: 
  - Centralized **Server** managing state, database persistence, and orchestration.
  - Multi-platform **Client Agent** (Windows, Linux, macOS) responsible for local metrics collection, active/passive discovery, and executing server commands.
- **Persistence & Storage**:
  - **MySQL Database**: Stores clients, connection history, spatial locations, location history, physical topology, action execution status/targets, alerts, forbidden processes, working hours, and network device observations.
  - **Filesystem Storage**: Timestamped JSON scans, raw client activity logs, and captured screenshot images.
- **API & Interface Layer**:
  - **REST API (`/api/v1/*`)**: HTTP REST endpoints exposing dashboard metrics, client lists/details, network devices, actions, alerts, physical layouts, and screenshots.
  - **Server-Sent Events (SSE)**: Real-time event streaming (`/api/v1/events`) for live alerts, health changes, and execution updates.
  - **Interactive Server CLI**: Terminal-based console for triggering commands, viewing connected clients, scanning networks, and inspecting system state.
  - **Operator GUI Shell**: React/Tauri desktop frontend communicating with the REST API.

---

## 2. Client Management & System Monitoring

- **System & Hardware Telemetry**:
  - Collects Hostname, MAC address, IP address, OS specifications (System, Version, Release, Architecture), CPU details (core counts, usage percentage), Memory metrics (total, available, used, percentage), Disk usage metrics, and System Uptime.
- **Client Health & Connectivity Tracking**:
  - Real-time periodic health heartbeats.
  - Heartbeat status monitoring (`ONLINE`, `DEGRADED`, `OFFLINE`).
  - Active reachability checks via 2-packet ping fallback with custom grace periods (`DISCONNECT_PING_DELAY_SECONDS`, `DISCONNECT_PING_TIMEOUT_SECONDS`).
  - Connection lifecycle auditing (records connect and disconnect events in `connections` table).
- **Process Management & Inspection**:
  - Full running process list enumeration (PID, process name, executable path, command line, status, memory usage, CPU usage, start time, user context).
  - Process termination (`KILL_PROCESS` action by PID or name).
  - Dynamic forbidden process enforcement (automatically checks running processes against forbidden list).
- **User Session & Screen Capture**:
  - Session-aware Windows agent (`user_agent.py` running in user session via scheduled logon task).
  - On-demand screenshot capture (`TAKE_SCREENSHOT`) with configurable display target, resolution scaling, quality compression, and immediate upload to server.
- **Remote Host Controls**:
  - Lock user workstation (`LOCK_WORKSTATION`).
  - System shutdown (`SHUTDOWN_HOST`).
  - System restart (`RESTART_HOST`).

---

## 3. Network Discovery & Device Inventory

- **Passive & Local Network Discovery**:
  - **Client-Side Discovery**: Each client reads local ARP/neighbour tables and resolves hostnames via local DNS/mDNS without server-generated probe traffic.
  - **DHCP Traffic Interception**: Passive DHCP request/offer packet sniffing (`dhcp_listener.py` using Scapy/Npcap) capturing IP allocations, hostnames, and MAC addresses.
  - **OUI Vendor Lookup**: Automatic MAC address vendor classification using built-in IEEE OUI databases (`mas.csv`, `mam.csv`, `mal.csv`).
- **Network Device Classification & Aggregation**:
  - Server aggregates discovery reports into timestamped daily scan snapshots (`network_scan_YYYY-MM-DD.json`).
  - Categorizes network devices into:
    - `MANAGED`: Monitored devices running the client agent.
    - `UNMANAGED`: Discovered active devices lacking the client agent.
    - `UNKNOWN`: Unidentified or unreachable network entities.
- **Passive Traffic & Protocol Fingerprinting**:
  - Protocol sniffing for NetBIOS (NBNS), LLMNR, mDNS, SSDP, and ARP.
  - OS and device fingerprinting based on passive broadcast/multicast traffic.
  - Open port scanning and HTTP service discovery (`passive_protocol_listener.py`).

---

## 4. Security, Compliance & Quarantine Management

- **Forbidden Process Enforcement**:
  - Database-driven forbidden process registry with severity levels (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`).
  - Real-time alert generation upon detecting forbidden processes (e.g., unauthorized messaging apps, browsers, tools).
- **Working Hours & Usage Compliance**:
  - Schedule-based activity compliance tracking per day of the week (`working_hours` table).
  - Flags client activity occurring outside permitted working hours.
- **Network Quarantine & Access Control**:
  - **Platform-Specific Host Quarantine**:
    - **Windows**: Manipulates Windows Firewall rules and routing tables.
    - **Linux**: Applies `iptables` / `nftables` isolation rules.
    - **macOS**: Configures Packet Filter (`pfctl`) rules.
  - Restricts unauthorized network traffic while retaining client-to-server monitoring connectivity.

---

## 5. Physical Location & Network Topology Mapping

- **Physical Location & Center Layout**:
  - Spatial mapping of devices across floors, zones, aisles, tables, rows, and specific seat positions.
  - Assigns physical location tags (`pc_position`, `switch_position`, `ap_position`, `server_position`).
  - Tracks client physical location movement history (`client_location_history`).
- **Physical Neighborhood & Topology Analysis**:
  - Identifies direct network neighbors by inspecting switch ports, ARP adjacency, and TTL metrics.
  - Computes topology depth, gateway proximity, and switch port mappings (`physical_neighbors.py`).

---

## 6. Action Execution Framework

- **Asynchronous Task Engine**:
  - Supports non-blocking long-running execution of tasks across target clients (`action_framework.py`).
  - States: `PENDING`, `IN_PROGRESS`, `SUCCESS`, `FAILED`, `CANCELLED`, `EXPIRED`, `PARTIAL_SUCCESS`.
- **Targeting & Bulk Operations**:
  - Target clients by `client_id`, `mac`, `ip`, or bulk selection (`ALL`, `FILTER`).
- **Supported Remote Actions**:
  - `PING`: Connectivity check.
  - `GET_INFO`: Detailed hardware/software telemetry fetch.
  - `GET_PROCESSES`: Process table snapshot.
  - `KILL_PROCESS`: Process termination.
  - `TAKE_SCREENSHOT`: Real-time desktop screen capture.
  - `GET_ACTIVITY_LOG`: Fetch detailed user activity logs.
  - `ISOLATE_HOST` / `UNISOLATE_HOST`: Network quarantine controls.
  - `LOCK_WORKSTATION`: Lock user desktop.
  - `SHUTDOWN_HOST` / `RESTART_HOST`: Power management operations.
