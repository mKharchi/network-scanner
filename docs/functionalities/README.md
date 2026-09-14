# Functionalities Catalog

This directory is the central index of capabilities for the Network Monitoring & Endpoint Management System. It categorizes all system features into **Completed Functionalities** (operational and verified against code) and **Uncompleted Functionalities** (in-progress and future roadmap).

---

## 📖 Directory Structure & Navigation

```text
docs/functionalities/
├── README.md                            # This document (Master capability catalog)
├── completed/                           # Verified, fully implemented capabilities
│   ├── README.md                        # Reading order for completed features
│   ├── server-runtime.md                # Server TCP registry, worker queues, REST/SSE
│   ├── client-agent.md                  # Client agent daemon, background tasks, and state
│   ├── storage-and-data-model.md        # Database schema (MySQL) & filesystem state
│   ├── discovery-and-observations.md    # Active & passive discovery engines & packet flow
│   ├── telemetry-and-activity.md        # Hardware metrics, flow tracking, active window & screenshots
│   ├── security-and-isolation.md        # Forbidden processes, kill loop, network quarantine
│   ├── remote-actions.md                # Command framework, state machine, REST dispatch
│   ├── packages-and-updates.md          # Package staging, verification, updater execution
│   ├── spatial-localization.md          # Coordinates, floor map assignment, digital twin
│   ├── kismet-investigation.md          # Server-side wireless capture, SQLite queries, retention
│   └── gui.md                           # React/Tauri console & real-time telemetry UI
└── uncompleted/                         # In-progress and future planned capabilities
    ├── README.md                        # Reading order, dependency map & priorities
    ├── ROADMAP.md                       # Master roadmap and feature proposal template
    ├── 01-ml-intelligence/              # ML device fingerprinting, activity & threat models
    ├── 02-3d-and-ar-visualization/      # 3D topology & AR-enhanced localization
    ├── 03-autonomous-edge-agent/        # Edge AI self-healing agent
    ├── 04-spatial-triangulation/        # Spatio-temporal rogue device triangulation
    ├── 05-kismet-sensor-mesh/           # Distributed multi-sensor Kismet capture
    └── 06-managed-client-orchestration/ # Global neighborhood collection orchestration
```

---

## 🧭 Which section should you read?

- If you are configuring, troubleshooting, deploying, or verifying the **current running system**, go to:
  👉 **[Completed Functionalities Index](completed/README.md)**
- If you are designing, planning, or implementing **new features, machine learning models, or visualization upgrades**, go to:
  👉 **[Uncompleted Functionalities Index](uncompleted/README.md)**
