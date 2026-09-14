# Uncompleted Functionalities & Roadmap

This directory organizes all planned, in-progress, and research-phase capabilities for the Network Scanner & Endpoint Management platform.

It is structured into distinct functional modules, each containing technical design proposals, mathematical models, API contracts, and implementation roadmaps.

---

## 📖 Recommended Reading Order

Follow this sequence to understand the platform's strategic evolution:

1. **[Feature Planning Roadmap](ROADMAP.md)**
   - Prioritized roadmap (P0/P1/P2), planning rules, and standard feature proposal template.
2. **[01. ML & Threat Intelligence](01-ml-intelligence/README.md)**
   - Device fingerprinting, probe classification, behavioral baselining, and anomaly detection.
3. **[02. 3D & AR Visualization](02-3d-and-ar-visualization/README.md)**
   - Multi-floor 3D spatial digital twin rendering and mobile augmented reality overlays.
4. **[03. Autonomous Edge Agent](03-autonomous-edge-agent/README.md)**
   - Disconnected edge decision engines and autonomous self-healing endpoint agents.
5. **[04. Spatio-Temporal Rogue Triangulation](04-spatial-triangulation/README.md)**
   - Multi-sensor RSSI trilateration, signal path-loss modeling, and moving transmitter tracking.
6. **[05. Distributed Kismet Sensor Mesh](05-kismet-sensor-mesh/README.md)**
   - Expanding server-side wireless capture to a multi-node distributed Linux sensor mesh.
7. **[06. Managed Client Orchestration](06-managed-client-orchestration/README.md)**
   - Large-scale neighborhood collection orchestration and network load distribution.

---

## 📋 Module Inventory & Status

| Module | Purpose | Status | Dependencies |
| :--- | :--- | :--- | :--- |
| [`ROADMAP.md`](ROADMAP.md) | Master development roadmap & proposal template | Active Reference | None |
| [`01-ml-intelligence/`](01-ml-intelligence/README.md) | Wireless ML fingerprinting & anomaly modeling | In Progress / Benchmarked | Kismet captures, MySQL foundation |
| [`02-3d-and-ar-visualization/`](02-3d-and-ar-visualization/README.md) | 3D scene rendering & mobile AR overlays | In Progress | Spatial engine, Three.js frontend |
| [`03-autonomous-edge-agent/`](03-autonomous-edge-agent/README.md) | Offline local inference & remediation | Planned | Client agent, Process monitor |
| [`04-spatial-triangulation/`](04-spatial-triangulation/README.md) | Multi-vantage rogue device positioning | Planned | Sensor mesh, Spatial engine |
| [`05-kismet-sensor-mesh/`](05-kismet-sensor-mesh/README.md) | Coordinated multi-sensor wireless capture | Design Phase | Server Kismet runtime, systemd |
| [`06-managed-client-orchestration/`](06-managed-client-orchestration/README.md) | Staggered large-fleet scan orchestration | In Progress | Action framework, TCP server |
