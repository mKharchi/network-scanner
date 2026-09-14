# Historical Documentation Archive

This directory contains historical sprint plans, initial feature design notes, research logs, and raw progress tracking reports created during earlier phases of application development.

---

## ⚠️ Notice on Documentation Authority

> [!WARNING]
> The documents inside this `archive/` folder are preserved **strictly for historical context, design evolution records, and past implementation evidence**.
> 
> - **They may describe earlier prototypes, discarded architectures, or intermediate implementation states** (such as legacy client-side Kismet research or early command schemas).
> - **The live codebase and the canonical documentation in [`docs/general/`](../general/README.md) and [`docs/functionalities/completed/`](../functionalities/completed/README.md) are the true sources of authority.**
> - Whenever an archived document conflicts with the current codebase, prefer the canonical documentation.

---

## 📋 Archived Folders Index

| Legacy Directory | Original Subject Area | Current Canonical Location |
| :--- | :--- | :--- |
| `2d-visualization/`, `3d-visualization/` | 2D/3D floor visualization plans & reports | [`docs/functionalities/completed/spatial-localization.md`](../functionalities/completed/spatial-localization.md), [`docs/functionalities/uncompleted/02-3d-and-ar-visualization/`](../functionalities/uncompleted/02-3d-and-ar-visualization/README.md) |
| `alerts/` | Alert models & notification rules | [`docs/functionalities/completed/security-and-isolation.md`](../functionalities/completed/security-and-isolation.md) |
| `api/` | Early API specs & plans | [`docs/general/API.md`](../general/API.md) |
| `client_monitoring/`, `cpu_usage/` | Client metrics & hardware telemetry | [`docs/functionalities/completed/telemetry-and-activity.md`](../functionalities/completed/telemetry-and-activity.md) |
| `endppoint_management/`, `package-send/` | Early package deployment & command plans | [`docs/functionalities/completed/packages-and-updates.md`](../functionalities/completed/packages-and-updates.md), [`docs/functionalities/completed/remote-actions.md`](../functionalities/completed/remote-actions.md) |
| `event-bus/` | Event broadcasting prototypes | [`docs/functionalities/completed/server-runtime.md`](../functionalities/completed/server-runtime.md) |
| `feature-verrification/` | Feature verification audit records | [`docs/general/app-capabilities-and-progress.md`](../general/app-capabilities-and-progress.md) |
| `fix_alert_on_update/`, `fix_kismet/` | Bugfix sprint plans | Implemented into core modules |
| `forbidden processes/`, `quarentine.../` | Forbidden process & network quarantine plans | [`docs/functionalities/completed/security-and-isolation.md`](../functionalities/completed/security-and-isolation.md) |
| `gui/`, `ui-ux/` | Design system, token specs, and UI wireframes | [`docs/functionalities/completed/gui.md`](../functionalities/completed/gui.md) |
| `integrating-kismet-and-backup/` | Phase-by-phase Kismet migration & testing logs | [`docs/functionalities/completed/kismet-investigation.md`](../functionalities/completed/kismet-investigation.md) |
| `kismet_optimization/` | Kismet query and retention optimizations | [`docs/functionalities/completed/kismet-investigation.md`](../functionalities/completed/kismet-investigation.md) |
| `managed_clients/`, `neighborhood.../` | Neighborhood scan orchestration proposals | [`docs/functionalities/uncompleted/06-managed-client-orchestration/`](../functionalities/uncompleted/06-managed-client-orchestration/README.md) |
| `ml/` | Early machine learning prototypes | [`docs/functionalities/uncompleted/01-ml-intelligence/`](../functionalities/uncompleted/01-ml-intelligence/README.md) |
| `network-discovery/`, `network_observation/`, `passive protocol listener/` | Multi-protocol passive discovery development logs | [`docs/functionalities/completed/discovery-and-observations.md`](../functionalities/completed/discovery-and-observations.md) |
| `plans/` | Initial high-level concept proposals | [`docs/functionalities/uncompleted/`](../functionalities/uncompleted/README.md) |
| `project/` | Intermediate documentation draft | Refactored into [`docs/general/`](../general/README.md) and [`docs/functionalities/`](../functionalities/README.md) |
