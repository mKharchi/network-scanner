# General System Documentation

Welcome to the general architectural and operational documentation for the Network Monitoring & Centralized Endpoint Management System.

This directory establishes how the entire platform operates, its system boundaries, communication protocols, configuration parameters, testing frameworks, and day-to-day operations.

---

## 📖 Recommended Reading Order

For engineers, operators, and developers onboarding onto the project, follow this curated reading sequence:

1. **[System Architecture](ARCHITECTURE.md)**
   - Complete technical overview of endpoint clients, Linux server backend, database persistence, operator console, and optional wireless capture subsystems.
2. **[Configuration Reference](CONFIGURATION.md)**
   - Reference guide for server `.env`, client `config/.env`, port bindings, timeouts, and environmental tuning.
3. **[REST & SSE API Specification](API.md)**
   - Catalog of all REST endpoints (`/api/v1/*`), real-time SSE streams (`/api/v1/events`), and payload envelopes.
4. **[Testing & Verification](TESTING.md)**
   - Test execution guidelines for server unittests, client test suites, frontend bundling, and host verification.
5. **[Application Capabilities Inventory](app-capabilities-and-progress.md)**
   - Executive audit report on feature maturity, capabilities, and system components.
6. **[Operations Runbooks](operations/README.md)**
   - Deep-dive into server installation, client deployment, updating endpoints, and disaster recovery.

---

## 📋 Directory Contents & Structure

```text
docs/general/
├── README.md                            # This document (General index & reading guide)
├── ARCHITECTURE.md                      # System topology, trust boundaries & runtime processes
├── API.md                               # REST & SSE API route groups and interface standards
├── CONFIGURATION.md                     # Server, client, Kismet, and storage configurations
├── TESTING.md                           # Python unittest, frontend, and verification workflows
├── app-capabilities-and-progress.md     # Codebase feature inventory & maturity report
├── codebase-audit-report.md             # Detailed codebase health & dependency audit
└── operations/                          # Installation, deployment, and maintenance runbooks
    ├── README.md                        # Operations reading order & index
    ├── server-installation.md           # Linux server, MySQL, systemd, and sensor setup
    ├── client-installation.md           # Windows/Linux endpoint agent installation
    ├── client-updates.md                # Building, uploading, and executing client updates
    ├── legacy-client-migration.md       # Upgrading older unmanaged or flat-layout clients
    ├── backup-and-recovery.md           # Implemented recovery vs external backup boundaries
    └── operations-and-troubleshooting.md# Triage playbooks, port checks, and log inspection
```

---

## 🔗 Related Documentation
- **[Completed Functionalities](../functionalities/completed/README.md)**: Deep-dive documentation for all fully implemented and verified features.
- **[Uncompleted Functionalities & Roadmap](../functionalities/uncompleted/README.md)**: Research, specifications, and execution plans for upcoming features.
- **[Historical Archive](../archive/README.md)**: Preserved historical sprint logs and research records.
