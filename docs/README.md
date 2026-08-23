# Network Scanner Documentation Directory

Welcome to the documentation for the Network Monitoring & Passive Scanner system.

## Directory Structure

```text
docs/
├── README.md                                                  # Documentation Index (this file)
├── alerts/
│   └── implementation-plan.md                                 # Alert system design and event dispatching plan
├── api/
│   └── implementation-plan.md                                 # REST API specification and endpoints plan
├── general/
│   ├── app-capabilities-and-progress.md                       # Overall application capabilities & milestones
│   └── codebase-audit-report.md                               # Architectural audit and codebase health report
├── gui/
│   ├── data-contracts.md                                      # UI data contracts and API types
│   ├── design-system.md                                       # Typography, colors, badges, and component styles
│   └── implementation-plan.md                                 # Web frontend implementation plan
├── neighborhood collect orchestration/
│   ├── collection-orchestration-plan.md                       # Orchestrated global neighbourhood collection plan
│   ├── plan.md                                                # Detailed execution roadmap
│   └── progress.md                                            # Development progress log
├── network discovery and monitoring/
│   ├── device-discovery-plan.md                               # Network device active & passive discovery plan
│   ├── device-monitoring-plan.md                              # Persistent device state tracking & classification
│   └── discovery-verification-plan.md                         # Validation & verification strategy
└── passive protocol listener/
    ├── next-step-plan.md                                      # Multi-phase unified passive discovery engine plan
    ├── observation-contract.md                                # Passive observation schema & deduplication rules
    ├── original-implementation-plan.md                        # Original protocol listener plan
    ├── plan.md                                                # Tactical protocol implementation plan
    ├── progress.md                                            # Progress updates for passive scanner phases
    ├── protocol-support.md                                    # Protocol research (mDNS, SSDP, LLMNR, NBNS, DHCP)
    └── unified-passive-discovery-implementation.md            # Final implementation & correlation engine report
```

---

## Key Modules & Guides

* **[Unified Passive Discovery Scanner](passive%20protocol%20listener/unified-passive-discovery-implementation.md)**: Full architecture and implementation details for multi-protocol passive discovery (DHCP, mDNS, SSDP, LLMNR, NBNS) and unified device correlation.
* **[Passive Observation Contract](passive%20protocol%20listener/observation-contract.md)**: Standard observation schema, priority hierarchies, and bounds.
* **[GUI Design System & Contracts](gui/)**: Specifications for the React/Vite dashboard, components, and real-time SSE stream.
* **[Global Neighbourhood Collection](neighborhood%20collect%20orchestration/)**: Multi-client orchestration, rate limiting, and merge algorithms.
