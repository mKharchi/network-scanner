# Operations Documentation Index

This directory contains runbooks, installation procedures, update strategies, and recovery guides for operators and system administrators managing the Network Scanner and Monitoring system.

---

## 📖 Recommended Reading Order

Follow this sequence to set up, operate, and maintain the deployment:

1. **[Server Installation](server-installation.md)**
   - Initial deployment of Linux backend, MySQL database, supervisor unit, and optional server-owned Kismet sensor.
2. **[Client Installation](client-installation.md)**
   - Step-by-step deployment guide for managed Windows and Linux endpoint agents.
3. **[Client Updates](client-updates.md)**
   - Building semantic update packages, staged deployment, hash verification, and fleet-wide bulk updates.
4. **[Legacy Client Migration](legacy-client-migration.md)**
   - Transitioning unmanaged or legacy flat-layout clients that lack the modern atomic updater.
5. **[Operations & Troubleshooting](operations-and-troubleshooting.md)**
   - Day-to-day operations, log inspection, health check verification, and triage playbooks.
6. **[Backup and Recovery Boundaries](backup-and-recovery.md)**
   - State boundaries, automated rollback mechanics, disaster recovery procedures, and backup guidelines.

---

## 📋 Directory Contents

| Document | Scope | Target Audience |
| :--- | :--- | :--- |
| [`server-installation.md`](server-installation.md) | Linux server, MySQL schema, systemd services, Kismet setup | Server Administrators |
| [`client-installation.md`](client-installation.md) | Endpoint installation, environment config, startup tasks | Desktop / Field Engineers |
| [`client-updates.md`](client-updates.md) | Package creation, REST upload, target action execution, rollback | Operators / DevOps |
| [`legacy-client-migration.md`](legacy-client-migration.md) | Manual migration procedures for older endpoint versions | Field Engineers |
| [`operations-and-troubleshooting.md`](operations-and-troubleshooting.md) | Health verification, fault diagnosis, common error resolutions | Operators / Support |
| [`backup-and-recovery.md`](backup-and-recovery.md) | Data classes, backup requirements, rollback guarantees | System Administrators |
