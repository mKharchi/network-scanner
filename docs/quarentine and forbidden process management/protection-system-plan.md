```markdown
# Endpoint Monitoring, Forbidden Process Enforcement & Network Quarantine — Implementation Plan

## System Architecture Overview

This plan defines a three-layer endpoint protection system:
* **Passive Network Discovery:** Continuously enriches device information across local network protocols.
* **Forbidden-Process Monitoring:** Detects and stops prohibited processes, escalating repeated violations.
* **Network Quarantine:** Allows the central server to isolate a dangerous endpoint from the network without shutting down the PC.

---

## 0. Objective

Extend the existing Windows client agent into a unified endpoint monitoring and response agent.

The agent must provide three major capabilities:
1. Passive network discovery and DHCP enrichment.
2. Frequent forbidden-process monitoring and enforcement.
3. Remote network quarantine of a dangerous endpoint.

### System Flow
```text
                    Central Server
                         |
             +-----------+-----------+
             |                       |
       Telemetry API           Command API
             |                       |
             v                       v
      Client Information      Endpoint Commands
             |                       |
             +-----------+-----------+
                         |
                  Windows Agent
                         |
        +----------------+----------------+
        |                |                |
        v                v                v
 Passive Scanner   Process Monitor   Quarantine Manager
        |                |                |
        v                v                v
 mDNS/SSDP/etc.     Detect/Stop       Network Isolation
 DHCP enrichment    forbidden apps    / Recovery

```

*Note: The implementation should reuse the existing client/server architecture as much as possible. Do NOT rewrite working components unnecessarily.*

---

## 1. First: Inspect the Existing Project

Before modifying code, inspect the entire existing client agent.

### Components to Identify

* Client entry point
* Existing DHCP scanner
* Existing passive network scanner
* Process scanner
* Forbidden-process configuration
* Process termination logic
* Server API client
* Client registration mechanism
* Authentication mechanism
* Background execution mechanism
* Windows service implementation
* Current logging system
* Current configuration system
* Current JSON telemetry format
* Current heartbeat mechanism
* Existing server endpoints
* Existing database models

### Runtime Determination

Determine which functionality currently runs as:

* Foreground process
* Background process
* Windows service
* Scheduled task

> **Action Required:** Do not duplicate functionality that already exists. Create a short architecture report before changing the code.

---

## 2. Merge DHCP Into the Passive Discovery Scanner

The existing DHCP scanner should no longer be treated as a completely separate discovery system.

### Subsystem Hierarchy

```text
DiscoveryManager
    |
    +-- PassiveProtocolListener
    |      +-- mDNS
    |      +-- SSDP
    |      +-- LLMNR
    |      +-- NBNS
    |      +-- WS-Discovery
    |
    +-- DHCPListener
    |
    +-- ObservationAggregator
    |
    +-- DeviceEnricher
    |
    +-- TelemetryReporter

```

### Execution Rules

* The DHCP listener should run concurrently with the passive protocol listeners.
* Do not block the passive scanner while DHCP processing is occurring.
* Use asynchronous/background execution where appropriate.

---

## 3. Unified Device Observation Model

Create a normalized internal observation model supporting partial information.

```json
{
  "mac_address": "AA:BB:CC:DD:EE:FF",
  "ipv4_address": "192.168.1.25",
  "ipv6_addresses": [],
  "hostname": "DESKTOP-ABC123",
  "vendor": "Intel Corporate",
  "device_type": "Windows Workstation",
  "os_hint": "Windows 11",
  "model_hint": null,
  "services": [],
  "software_hints": [],
  "protocols_seen": [
    "dhcp",
    "mdns",
    "llmnr"
  ],
  "first_seen": "2026-08-22T11:48:46Z",
  "last_seen": "2026-08-22T11:50:21Z",
  "seen_count": 10,
  "reporter_client_id": "client-uuid-here",
  "observed_at": "2026-08-22T11:50:21Z"
}

```

### Protocol Information Mapping

* **DHCP:** MAC + Hostname + DHCP fingerprint
* **mDNS:** MAC + Hostname + Model + Services
* **SSDP:** IP + Server software + UPnP device type
* **LLMNR/NBNS:** Hostname
* **WS-Discovery:** Printer / Camera / Computer information

All observations must be correlated into a single device record.

---

## 4. DHCP Information Extraction

Extract as much useful information as safely available from DHCP packets.

### Fields to Investigate

* Client MAC & IP
* Hostname (Option 12)
* Vendor Class Identifier (Option 60)
* Parameter Request List (Option 55)
* Client Identifier (Option 61)
* Requested IP & DHCP message type
* Lease-related information & relay information
* Vendor-specific options

### Raw DHCP Fingerprint Store Example

```json
{
  "protocol": "dhcp",
  "hostname": "DESKTOP-ABC",
  "vendor_class": "MSFT 5.0",
  "parameter_request_list": [1, 3, 6, 15, 31, 33, 43, 44, 46, 47],
  "client_identifier": "01aabbccddeeff",
  "message_type": "DHCPREQUEST"
}

```

*Note: Do not assume DHCP fields uniquely identify an OS. Treat them as evidence and combine them with other protocol findings.*

---

## 5. Last-Seen / Presence Tracking

Every observation must update `first_seen`, `last_seen`, and `seen_count`.

```json
{
  "first_seen": "2026-08-22T11:48:46Z",
  "last_seen": "2026-08-22T11:50:21Z",
  "seen_count": 37
}

```

### Presence States

Do **NOT** interpret absence of packets as proof that a device is offline. Use threshold-calculated states:

* `ACTIVE`: Recent observation recorded.
* `IDLE`: No observation for a moderate period.
* `STALE`: Long period without observation.
* `OFFLINE`: Mark only if explicit evidence supports disappearance.
* `UNKNOWN`: Default/uncalculated state.

---

## 6. Local Deduplication

Implement a local observation cache or ring buffer keyed primarily by **MAC address** (using IP, hostname, protocol, and service information as enrichment).

*Example Scenario:*
If a device (`AA:BB:CC:DD:EE:FF`) generates 43 observations within 5 minutes, do not send 43 identical telemetry packets. Periodically transmit an aggregated observation record with `seen_count: 43`.

---

## 7. Passive Software / Service Fingerprinting

Extract software hints from protocol payloads:

* **mDNS:** Service names, TXT records (`_spotify-connect`, `_googlecast`, `_adb`, `_ipp`, `_dosvc`)
* **SSDP:** `SERVER` headers, UPnP device types (`uTorrent`)
* **WS-Discovery:** Types & Scopes
* **DHCP:** Vendor class & Option 55 fingerprints
* **LLMNR/NBNS:** Specific broadcast names

```json
{
  "software_hints": [
    "Spotify Connect",
    "Google Cast",
    "uTorrent"
  ]
}

```

*Note: Service discovery indicates protocol activity, not web browser history.*

---

## 8. Forbidden Process Monitoring

Create a dedicated `ForbiddenProcessMonitor` that periodically inspects running processes.

### Configuration Specification

```yaml
process_monitor:
  enabled: true
  scan_interval_seconds: 10

```

### Monitor Execution Workflow

1. Enumerate running processes.
2. Normalize process names.
3. Compare against forbidden-process rules.
4. Identify violations and record events.
5. Terminate the forbidden process.
6. Report events to the central server.

---

## 9. Forbidden Process Detection

### Policy Configuration Schema

```json
{
  "forbidden_processes": [
    {
      "rule_id": "rule-001",
      "name": "utorrent.exe",
      "enabled": true,
      "severity": "high"
    },
    {
      "rule_id": "rule-002",
      "name": "example.exe",
      "enabled": true,
      "severity": "critical"
    }
  ]
}

```

Support evaluation based on process name, optional executable path, enabled state, severity, and rule ID. Avoid relying exclusively on filenames if stronger identification mechanisms exist.

---

## 10. Forbidden Process Violation Event

When a violation occurs, construct an event record:

```json
{
  "event_type": "FORBIDDEN_PROCESS_DETECTED",
  "client_id": "client-uuid-here",
  "process_name": "utorrent.exe",
  "pid": 1234,
  "severity": "high",
  "detected_at": "2026-08-22T16:00:01Z",
  "action": "TERMINATED"
}

```

---

## 11. Process Termination Workflow

```text
Detect Process
   |
   v
Verify Against Policy
   |
   v
Attempt Graceful Termination
   |
   v
If Still Running -> Force Terminate
   |
   v
Verify Process Stopped
   |
   v
Generate Enforcement Event

```

### Result Tracking

The agent must verify process termination using direct checks and log:

* `termination_requested`
* `termination_succeeded`
* `termination_failed`
* `verification_result`

---

## 12. Repeated Violation Detection

To distinguish between single accidental executions and repeated user/automated launch attempts, maintain a rolling violation history.

### Rolling Escalation Threshold Configuration

```yaml
violation_escalation:
  enabled: true
  threshold: 3
  window_seconds: 120

```

If violations exceed `threshold` within `window_seconds`, elevate response and emit `CRITICAL_FORBIDDEN_PROCESS_REPEATED`.

---

## 13. Critical Alert Schema

```json
{
  "event_type": "CRITICAL_FORBIDDEN_PROCESS_REPEATED",
  "client_id": "client-uuid-here",
  "process_name": "utorrent.exe",
  "violation_count": 4,
  "window_seconds": 120,
  "first_violation": "2026-08-22T16:00:01Z",
  "last_violation": "2026-08-22T16:00:45Z",
  "severity": "critical"
}

```

*Note: Displays distinctively on the server console to signal potential user persistence or automated process activity requiring administrative review.*

---

## 14. Add Process Event History

Maintain a bounded, non-persistent local memory structure for window evaluation:

```text
ProcessViolationHistory
-----------------------
client_id
process_name
timestamp
pid
action
result

```

---

## 15. Network Quarantine Feature

Add a `NetworkQuarantineManager` component to temporarily isolate an endpoint from network communication without shutting down the OS or stopping the monitoring agent.

### Quarantine Architecture

```text
Central Server
      |
      | QUARANTINE_CLIENT
      v
Windows Agent
      |
      v
Quarantine Manager
      |
      v
Windows Network Enforcement

```

---

## 16. Separating Agent Management From Network Traffic

### Isolation Strategies Comparison

| Option | Method | Advantages | Disadvantages | Selection Status |
| --- | --- | --- | --- | --- |
| **Option A** | **Windows Firewall Rules** | Machine stays operational; Management channel can remain open for remote unquarantine | Requires firewall manipulation privileges | **PRIMARY CHOICE** |
| **Option B** | **Disable Network Adapter** | Absolute isolation; Simple command | Agent loses server connectivity; Cannot receive remote unquarantine commands | **NOT RECOMMENDED** |

### Firewall Quarantine Traffic Model

```text
Normal State:
PC <----> Local Network / Internet
 |
 +----> Central Server

Quarantined State:
PC --X--> Local Network / Internet
 |
 +----> Central Server Management Channel (Explicitly Whitelisted Rule)

```

---

## 17. Privileged Execution Model

Modify operations requiring privilege escalation (Firewall configuration, force-killing protected processes) to execute through a dedicated Windows Service using authenticated Local IPC.

```text
User-Level Agent
      |
      | Authenticated Local IPC
      v
Privileged Windows Service
      |
      +---- Process Enforcement
      |
      +---- Firewall / Quarantine Operations

```

---

## 18. Quarantine Command Format

```json
{
  "command": "QUARANTINE_CLIENT",
  "client_id": "client-uuid-here",
  "reason": "Repeated forbidden process violations",
  "issued_at": "2026-08-22T16:03:00Z",
  "expires_at": "2026-08-22T17:03:00Z",
  "command_id": "cmd-88392-xyz"
}

```

*Verification Constraint: Commands must be cryptographically verified or authenticated against the server token before execution.*

---

## 19. Quarantine State Machine

```text
       NORMAL
          |
          | (quarantine command)
          v
  QUARANTINE_PENDING ───(failure)───> QUARANTINE_FAILED
          |
          v
     QUARANTINED
          |
          | (release command)
          v
   RESTORE_PENDING
          |
          v
       NORMAL

```

---

## 20. Quarantine Event Reporting

### Quarantine Activated

```json
{
  "event_type": "CLIENT_QUARANTINED",
  "client_id": "client-uuid-here",
  "reason": "Repeated forbidden process violations",
  "timestamp": "2026-08-22T16:03:12Z",
  "enforcement_method": "WINDOWS_FIREWALL"
}

```

### Quarantine Failed

```json
{
  "event_type": "CLIENT_QUARANTINE_FAILED",
  "client_id": "client-uuid-here",
  "reason": "Access denied while applying firewall rule",
  "timestamp": "2026-08-22T16:03:13Z"
}

```

### Quarantine Released

```json
{
  "event_type": "CLIENT_QUARANTINE_RELEASED",
  "client_id": "client-uuid-here",
  "timestamp": "2026-08-22T16:30:00Z"
}

```

---

## 21. Quarantine Safety Mechanisms

1. **Explicit Admin Confirmation:** UI prompts before sending isolation commands.
2. **Audit Logging:** Server tracks issuer ID, target ID, timestamp, reason, and command result.
3. **Idempotency:** Re-issuing active commands maintains state without creating duplicate firewall rules.
4. **Explicit Release Command:** Standardized `RELEASE_CLIENT` command handler.
5. **Fail-Safe Automatic Expiration:** Configurable timeout to handle accidental lockouts.

```yaml
quarantine:
  max_duration_minutes: 60

```

---

## 22. Firewall Rule Management

Quarantine rules must use strict predictable naming conventions:

* `AgentQuarantine-Inbound`
* `AgentQuarantine-Outbound`

### Rule Lifecycle Steps

1. **Pre-Check:** Check if rules with these exact names already exist.
2. **Apply:** Create or enable specific rules block-listing inbound/outbound traffic except server communication.
3. **Release:** Explicitly remove or disable only `AgentQuarantine-*` rules. Never clear or reset general Windows Firewall policies.

---

## 23. Server-Side Device State Extensions

### Device Schema Fields

```text
Device
------
id
client_id
mac_address
ipv4
ipv6
hostname
vendor
device_type
os
model
first_seen
last_seen
presence_state
quarantine_state      <-- (NOT_QUARANTINED | QUARANTINE_PENDING | QUARANTINED | QUARANTINE_FAILED)
quarantine_reason     <-- Text string
quarantined_at        <-- ISO timestamp

```

---

## 24. Server Command Architecture

Endpoints periodically fetch commands over the existing command channel (e.g., `GET /api/client/commands`):

* `QUARANTINE_CLIENT`
* `RELEASE_CLIENT`
* `UPDATE_FORBIDDEN_PROCESS_POLICY`
* `REQUEST_DISCOVERY_SNAPSHOT`

*Note: Avoid introducing secondary communication protocols if the current heartbeat/polling channel is operational.*

---

## 25. Automatic Quarantine Policy

*Disabled by default during testing.* Progressive response hierarchy:

```text
Violation #1 ──> Terminate process ──> Log event
Violation #2 ──> Terminate process ──> Log warning
Violation #3+ ─> Critical alert   ──> Admin manual review / Manual quarantine

```

### Optional Automatic Rule Schema

```yaml
automatic_quarantine:
  enabled: false
  trigger:
    repeated_forbidden_process:
      threshold: 10
      window_seconds: 300

```

---

## 26. Integration With Passive Discovery

When an endpoint enters network quarantine, retain all historical telemetry:

* MAC, IP, Hostname, Vendor, OS hints, Services
* Timestamp parameters (`first_seen`, `last_seen`)
* Process violation log history

---

## 27. Separation of Subsystem Responsibilities

| Subsystem | Primary Question Addressed | Scope |
| --- | --- | --- |
| **Passive Discovery** | What devices & services exist on the local network segment? | Network-wide passive observation |
| **Process Monitoring** | What software is running on *this* managed endpoint? | Local system inspection |
| **Network Quarantine** | Should *this* managed endpoint be isolated from the network? | Local network enforcement |

---

## 28. Final Agent Architecture

```text
Windows Client Agent
│
├── AgentCoordinator
│
├── Discovery
│   ├── PassiveListener
│   │   ├── mDNS
│   │   ├── SSDP
│   │   ├── LLMNR
│   │   ├── NBNS
│   │   └── WS-Discovery
│   │
│   ├── DHCPListener
│   ├── ObservationAggregator
│   └── DeviceEnricher
│
├── ProcessSecurity
│   ├── ProcessScanner
│   ├── ForbiddenProcessMatcher
│   ├── ProcessTerminator
│   └── ViolationTracker
│
├── Response
│   ├── QuarantineManager
│   ├── QuarantineState
│   └── RecoveryManager
│
├── Telemetry
│   ├── ObservationReporter
│   ├── SecurityEventReporter
│   └── Heartbeat
│
└── Communication
    ├── AuthenticatedServerClient
    └── CommandHandler

--------------------------------------------------

Windows Service (Privileged Execution Layer)
│
├── Privileged Process Enforcement
├── Firewall / Network Quarantine
└── Restricted Local IPC

```

---

## 29. Implementation Order

```text
Phase 1: Refactor Discovery
  └── Merge DHCP into passive listeners; normalize observations; build deduplication & telemetry pipeline.

Phase 2: Device Enrichment
  └── Extract DHCP Options (12, 55, 60), mDNS records, SSDP headers, and software hints.

Phase 3: Forbidden Process Monitoring
  └── Implement ProcessMonitor, termination verification, violation tracker, and escalation alerts.

Phase 4: Privileged Enforcement Service
  └── Implement/refactor Windows Service & secure local IPC interface for privileged execution.

Phase 5: Network Quarantine
  └── Implement Firewall QuarantineManager, server command handlers, state machine, and timeouts.

```

---

## 30. Testing Matrix

### Scenario Coverage Matrix

| Category | Test Case | Target Result |
| --- | --- | --- |
| **Discovery** | Packet Reception (DHCP/mDNS/SSDP/LLMNR/NBNS) | Data correctly extracted and normalized |
|  | IP / MAC changes | Record updated without creating duplicate device entries |
| **Presence** | Inactive endpoint | State transitions cleanly through `ACTIVE` -> `IDLE` -> `STALE` |
| **Process Security** | Forbidden app execution | Process terminated within configured interval |
|  | Process termination failure / refusal | Force-kill triggered, failure reported if un-killable |
|  | Rapid repeated launches | Violation counter increments, emits `CRITICAL` alert |
| **Quarantine** | `QUARANTINE_CLIENT` received | Inbound/Outbound rules created, state becomes `QUARANTINED` |
|  | `RELEASE_CLIENT` received | Agent quarantine rules removed, state returns to `NORMAL` |
|  | Agent/Service reboot while quarantined | Quarantine firewall rules persist correctly across reboots |
|  | Expired quarantine timer | Safe automatic rule rollback occurs |

---

## 31. Security Requirements

* **Authenticated Server Commands:** Server commands must contain verifiable authentication signatures.
* **Replay Protection:** Commands must include unique nonces/IDs and timestamp expiration bounds.
* **Least Privilege:** User agent runs unprivileged; privileged service performs firewall operations via restricted local IPC.
* **No Public Trigger Endpoints:** Endpoints must not expose unauthenticated network control ports.

---

## 32. Server Dashboard Interface Example

```text
DEVICE
────────────────────────────────────────────────────
Hostname:       DESKTOP-ABC123
IP:              192.168.1.25
MAC:             AA:BB:CC:DD:EE:FF
Vendor:          Intel
OS:              Windows 11
Device Type:     Workstation

First Seen:      10:32:15
Last Seen:       16:02:31
Presence:        ACTIVE

Network Services:
  mDNS, SSDP, DHCP, LLMNR

Software Hints:
  Spotify Connect, uTorrent

────────────────────────────────────────────────────
SECURITY

Forbidden Process:
  utorrent.exe

Violations:
  7

Window:
  120 seconds

Severity:
  CRITICAL

────────────────────────────────────────────────────
NETWORK STATUS

Status:
  QUARANTINED

Reason:
  Repeated forbidden process violations

Enforcement:
  Windows Firewall

Quarantined:
  16:03:12

[ RELEASE CLIENT ]

```

---

## 33. Success Criteria

1. **Discovery:** Passive listeners and DHCP run concurrently without blocking; records deduplicated and enriched.
2. **Process Security:** Forbidden processes detected, terminated, verified, and escalated when repeated.
3. **Quarantine:** Remote server can isolate endpoint traffic while keeping the device running and recoverable.
4. **Reliability:** State remains consistent across service restarts, agent updates, and brief network disconnects.

---

## 34. Development Workflow Rules

1. Implement in single phased iterations.
2. Test on a Windows test environment after each phase before advancing.
3. Verify server telemetry and edge-case log outputs.
4. Document all architectural updates, privilege requirements, and rollback procedures prior to code modification.

---

## 35. Architecture Recommendation: Privilege Separation

For the network isolation capability, separate process monitoring privileges from system management operations:

```text
                 Central Server
                       │
             Authenticated Command
                       │
                       ▼
        ┌─────────────────────────────┐
        │      User-level Agent       │
        │                             │
        │  • Passive Discovery        │
        │  • DHCP Listener            │
        │  • Process Monitoring       │
        │  • Telemetry Reporting      │
        └──────────────┬──────────────┘
                       │ Secure Local IPC
                       ▼
        ┌─────────────────────────────┐
        │     Privileged Service      │
        │                             │
        │  • Process Enforcement      │
        │  • Network Quarantine       │
        │  • Firewall Control         │
        └─────────────────────────────┘

```

### Key Takeaways

* **Clear Privilege Boundary:** The user agent observes and reports; the central server decides; the local privileged service enforces.
* **Firewall Control over Adapter Disabling:** Prefer controlled Windows Firewall rules for quarantine. Disabling network adapters destroys the telemetry/command link, preventing remote server-initiated recovery.

```

```