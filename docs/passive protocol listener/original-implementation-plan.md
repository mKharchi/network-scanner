# Passive Protocol Listener — Implementation Plan

## 1. Objective

Add a new, independent **Passive Protocol Listener** feature to the Windows client.

The purpose of this feature is to passively observe additional network protocols that may reveal useful information about nearby/unmanaged devices.

Initial protocols to investigate and support:

- DHCP / DHCP-related information
- mDNS / DNS-SD
- LLMNR
- NBNS
- SSDP / UPnP
- DHCPv6
- LLDP, if technically available from the client environment
- CDP, only if technically applicable

### Important architectural rule

This feature must be **separate from the existing network-neighbourhood and DHCP functionality**.

Do NOT rewrite or replace:

- the existing ARP/neighbourhood collector
- the existing daily neighbourhood storage
- the existing DHCP listener
- the existing DHCP observation storage
- the existing neighbourhood request/response mechanism

The new listener is an additional source of network intelligence.

---

# Phase 0 — Development Environment / Windows Service Task

Before modifying the client:

1. Inspect how the current Windows client is launched.
2. Confirm that the client is currently configured as a **per-user Windows logon task**.
3. Do not modify the scheduled task implementation yet.

For development, use the following workflow:

```text
Existing logon task
        ↓
Stop / uninstall temporarily
        ↓
Modify client
        ↓
Run client manually from terminal
        ↓
Test new listener
        ↓
Fix problems
        ↓
Validate complete client
        ↓
Reinstall/reconfigure logon task
```

The implementation must NOT depend on the client being launched through the scheduled task.

The client must continue to work when started manually.

### Important

Do not change the startup mechanism as part of this feature.

The startup task will be handled only after the client implementation has been validated.

---

# Phase 1 — Inspect the Existing Architecture

Before changing code, inspect the repository.

Read the existing architecture/audit documentation first, especially:

```text
network-scanner/codebase_audit_report.md
```

Pay particular attention to:

- Network Discovery & Architecture
- discovery sources
- device flow
- architecture diagram
- scan files analysis

Then inspect the actual implementation.

Identify:

### Client

- client entry point
- client command handling
- socket communication
- background thread startup
- existing DHCP listener
- existing ARP/neighbourhood collector
- daily neighbourhood storage
- neighbourhood synchronization
- DHCP observation storage
- logging

### Server

- command dispatch
- client command execution
- neighbourhood endpoints
- existing DHCP/network APIs
- network device models/storage
- global scan implementation

### GUI

- API client
- network/device pages
- existing scan/neighbourhood actions
- button/action patterns
- loading/error/success states

---

# Phase 2 — Define the New Feature Boundary

Create a new conceptual component:

```text
PassiveProtocolListener
```

The architecture should become:

```text
                    CLIENT
                      │
          ┌───────────┴────────────┐
          │                        │
 Existing systems            New listener
          │                        │
   ┌──────┴──────┐          ┌──────┴────────┐
   │             │          │               │
 ARP         DHCP Listener  mDNS          SSDP
   │             │          │               │
   │             │          LLMNR          NBNS
   │             │          │               │
   └──────┬──────┘          └──────┬────────┘
          │                        │
          ▼                        ▼
 Existing neighbourhood       Passive protocol
      system                    observations
```

The two systems may share common utility functions where appropriate, but they must remain logically independent.

---

# Phase 3 — Research and Validate Protocol Support

Before implementing every protocol, determine what is realistically capturable from a Windows client.

For each protocol document:

```text
Protocol
Capture mechanism
Python library/API
Required privileges
Interface requirements
Information obtainable
Expected traffic volume
Potential limitations
```

Investigate at minimum:

### DHCP

Already implemented.

Do not replace the current DHCP listener.

The new listener may reuse compatible parsing/utilities only if this does not alter the existing DHCP implementation.

### mDNS / DNS-SD

Investigate:

- UDP 5353
- multicast traffic
- `.local` names
- service advertisements
- service types
- device names
- TXT records

### LLMNR

Investigate:

- UDP 5355
- hostname queries
- hostname responses
- IPv4/IPv6 information

### NBNS

Investigate:

- UDP 137
- NetBIOS names
- Windows device names
- IP/MAC correlation where available

### SSDP / UPnP

Investigate:

- UDP 1900
- NOTIFY messages
- M-SEARCH responses
- device type
- server information
- `LOCATION`
- manufacturer/model information where exposed

### DHCPv6

Investigate:

- IPv6 DHCP traffic
- client identifiers
- hostname-related options
- vendor information

### LLDP / CDP

Determine whether these can realistically be observed by a normal Windows client on the target network.

Do not implement them merely because they exist.

---

# Phase 4 — Define a Normalized Passive Observation Format

Do not allow each protocol to create its own completely unrelated device structure.

Create a normalized observation format.

Example:

```json
{
    "protocol": "mdns",
    "observed_at": "...",
    "source_client": "...",
    "ip_address": "...",
    "mac_address": "...",
    "hostname": "...",
    "device_name": "...",
    "service_type": "...",
    "vendor": "...",
    "model": "...",
    "raw_fields": {}
}
```

Fields should remain optional.

A DHCP observation may contain:

```text
protocol
mac_address
ip_address
hostname
vendor_class
client_id
```

An SSDP observation may contain:

```text
protocol
ip_address
device_type
server
location
manufacturer
model
```

An mDNS observation may contain:

```text
protocol
hostname
service_type
service_name
ip_address
```

Do not force every protocol to provide every field.

---

# Phase 5 — Implement the Listener as an Independent Component

Create a dedicated module for the new feature.

For example:

```text
passive_protocol_listener.py
```

The listener should expose a small interface similar to:

```text
start()
stop()
```

and internally manage the protocol listeners.

Conceptually:

```text
PassiveProtocolListener
        │
        ├── MDNSListener
        ├── LLMNRListener
        ├── NBNSListener
        └── SSDPListener
```

Do not create one uncontrolled thread per packet or per observation.

Use controlled background workers.

---

# Phase 6 — Listener Lifecycle

The listener should start alongside the existing DHCP listener.

Current lifecycle:

```text
Client connects
       ↓
Registration
       ↓
Receive configuration
       ↓
Start existing background systems
       ↓
Start DHCP listener
```

New lifecycle:

```text
Client connects
       ↓
Registration
       ↓
Receive configuration
       ↓
Start existing background systems
       ↓
Start DHCP listener
       ↓
Start Passive Protocol Listener
```

The new listener must not block:

- socket communication
- command handling
- activity scanning
- neighbourhood collection
- DHCP observation

All passive capture must run asynchronously.

---

# Phase 7 — Startup Logging

Make startup unambiguous.

When the client starts the listener, the logs should clearly show:

```text
[PASSIVE LISTENER] Starting...
[PASSIVE LISTENER] mDNS listener started
[PASSIVE LISTENER] LLMNR listener started
[PASSIVE LISTENER] NBNS listener started
[PASSIVE LISTENER] SSDP listener started
[PASSIVE LISTENER] Listener ready
```

If a protocol cannot be started:

```text
[PASSIVE LISTENER] SSDP unavailable: <reason>
```

This must NOT prevent the other listeners from starting.

Example:

```text
mDNS   ✓
LLMNR  ✓
NBNS   ✓
SSDP   ✗
```

Overall listener state:

```text
PARTIALLY_AVAILABLE
```

rather than completely failed.

---

# Phase 8 — Observation Storage on the Client

The new listener should maintain a bounded in-memory collection of observations.

Do not immediately send every packet to the server.

The purpose of this feature is specifically to avoid creating another continuous network-reporting mechanism.

Group observations by device where possible.

For example:

```text
MAC A
 ├── DHCP observation
 ├── mDNS observation
 ├── SSDP observation

MAC B
 ├── LLMNR observation
 └── NBNS observation
```

Use timestamps so the server can understand when the observation occurred.

Implement sensible deduplication.

For example, receiving the same mDNS announcement repeatedly should not generate hundreds of identical entries.

---

# Phase 9 — Enhanced Neighbourhood Request

Add a NEW client command:

```text
GET_PASSIVE_NEIGHBOURHOOD
```

This must be separate from:

```text
GET_NETWORK_NEIGHBOURHOOD
```

The existing command must continue behaving exactly as before.

### Existing command

```text
GET_NETWORK_NEIGHBOURHOOD
```

returns the existing daily neighbourhood:

```text
ARP/neighbour cache
+
existing DHCP-derived information
```

### New command

```text
GET_PASSIVE_NEIGHBOURHOOD
```

returns observations collected by the new passive listener.

---

# Phase 10 — Passive Neighbourhood Response

The response should contain:

```json
{
    "type": "RESPONSE",
    "command": "GET_PASSIVE_NEIGHBOURHOOD",
    "data": {
        "observed_at": "...",
        "reporter": "...",
        "observations": []
    }
}
```

Each observation should identify its source protocol.

Example:

```json
{
    "protocol": "ssdp",
    "observed_at": "...",
    "ip_address": "172.16.0.102",
    "hostname": "...",
    "device_type": "...",
    "manufacturer": "...",
    "model": "..."
}
```

---

# Phase 11 — Server Command Support

Add server-side support for:

```text
GET_PASSIVE_NEIGHBOURHOOD
```

The server should be able to request passive observations from one specific connected client.

Flow:

```text
GUI
 ↓
Server
 ↓
Client X
 ↓
GET_PASSIVE_NEIGHBOURHOOD
 ↓
Client collects current buffered observations
 ↓
Client response
 ↓
Server receives/stores response
```

Do not modify the existing global network-neighbourhood mechanism yet.

---

# Phase 12 — Server API

Expose a dedicated API endpoint for this feature.

Use the existing API architecture and naming conventions.

Conceptually:

```text
POST /network/clients/{client_id}/passive-neighbourhood
```

or the equivalent endpoint structure already used by the project.

The API should:

1. Validate the client.
2. Ensure the client is connected.
3. Send the command.
4. Wait for the bounded response.
5. Validate the response.
6. Store/return the observations.

Do not expose arbitrary protocol-capture commands.

---

# Phase 13 — GUI Integration

Add a new action to the existing network/device UI.

Example button:

```text
Get Passive Network Information
```

The button should call the new API endpoint.

UI states:

```text
Idle
 ↓
Requesting...
 ↓
Success
```

or:

```text
Idle
 ↓
Requesting...
 ↓
Error
```

Display:

- number of observations
- protocols detected
- devices discovered
- latest observation time

Example:

```text
Passive Network Information

Devices observed: 8
mDNS: 5
SSDP: 2
LLMNR: 3
NBNS: 4

Last observation: 09:42:17
```

---

# Phase 14 — Do Not Mix the Two Neighbourhoods Yet

For the first implementation, keep the data visually and logically separate.

Existing:

```text
Network Neighbourhood
```

New:

```text
Passive Protocol Observations
```

Do not immediately merge them into the existing network device database.

First verify what information each protocol actually produces.

Later we can implement:

```text
ARP
DHCP
mDNS
SSDP
LLMNR
NBNS
       ↓
Device correlation
       ↓
NetworkDevice
```

But that should be a separate future phase.

---

# Phase 15 — Testing

Test each protocol independently.

## mDNS

- [ ] Listener starts
- [ ] mDNS packet detected
- [ ] hostname extracted
- [ ] service extracted
- [ ] duplicate announcements deduplicated

## LLMNR

- [ ] Listener starts
- [ ] query detected
- [ ] response detected
- [ ] hostname extracted

## NBNS

- [ ] Listener starts
- [ ] NetBIOS name detected
- [ ] IP associated correctly

## SSDP

- [ ] Listener starts
- [ ] NOTIFY detected
- [ ] response detected
- [ ] device type extracted
- [ ] location extracted where available

## Listener lifecycle

- [ ] Starts after client initialization
- [ ] Does not block client
- [ ] Survives one protocol failure
- [ ] Stops cleanly
- [ ] Does not create duplicate listeners
- [ ] Does not leak threads

---

# Phase 16 — Real Network Validation

Use several real devices.

At minimum:

```text
Windows PC
Android phone
iPhone
Mac
network printer / smart device if available
```

For each device document:

```text
What we know beforehand
What protocols it generates
What our listener detects
What information we extract
```

Example:

```text
Android phone
    ↓
mDNS ✓
SSDP ✓
DHCP ✓
LLMNR ✗
NBNS ✗
```

This will tell us which protocols are actually useful on the center's network.

---

# Phase 17 — Performance / Resource Validation

Measure:

- CPU usage
- memory usage
- packet rate
- number of observations
- duplicate rate
- listener startup time

The listener must remain lightweight because it will run continuously on approximately 25 Windows client machines.

Do not continuously persist every packet.

Do not send every observation immediately to the server.

Do not perform active scanning as part of this feature.

---

# Phase 18 — Windows Logon Task Reinstallation

Only after the implementation has passed manual testing:

```text
Client manually started
        ↓
Passive listener verified
        ↓
Existing DHCP verified
        ↓
Existing neighbourhood verified
        ↓
Server request verified
        ↓
GUI button verified
        ↓
Resource usage verified
        ↓
Reinstall/reconfigure Windows logon task
```

Do not modify the task itself unless required by the final client entry point.

The installed task should ultimately launch the same client entry point that was tested manually.

---

# Phase 19 — Validation Gates

The IDE AI must NOT implement the entire feature in one pass.

After each phase, STOP and provide a summary.

The summary must contain:

```text
## Completed

- Files inspected
- Files changed
- Functions/classes added
- Existing functionality preserved
- Tests performed
- Test results

## Current Architecture

Explain how the new component currently fits into the client.

## Issues / Limitations

List anything uncertain or unavailable.

## Next Step

Explain exactly what the next phase will implement.
```

Then STOP.

Do not continue until explicitly approved.

---

# Required Implementation Order

The IDE AI must follow this exact sequence:

```text
PHASE 0
Windows task / development setup
        ↓
PHASE 1
Architecture inspection
        ↓
PHASE 2
Feature boundary
        ↓
PHASE 3
Protocol research
        ↓
PHASE 4
Observation contract
        ↓
PHASE 5
Listener implementation
        ↓
PHASE 6
Listener lifecycle
        ↓
PHASE 7
Logging
        ↓
PHASE 8
Client observation buffering
        ↓
PHASE 9
GET_PASSIVE_NEIGHBOURHOOD
        ↓
PHASE 10
Response format
        ↓
PHASE 11
Server command handling
        ↓
PHASE 12
Server API
        ↓
PHASE 13
GUI button
        ↓
PHASE 14
Separation verification
        ↓
PHASE 15
Tests
        ↓
PHASE 16
Real network testing
        ↓
PHASE 17
Resource validation
        ↓
PHASE 18
Windows logon task
```

# Critical Constraints

1. **Do not remove or rewrite the existing DHCP listener.**

2. **Do not remove or rewrite the existing ARP/neighbourhood collector.**

3. **Do not change the existing `GET_NETWORK_NEIGHBOURHOOD` behavior.**

4. **Do not replace the current daily neighbourhood storage.**

5. **Do not introduce active network scanning into the new listener.**

6. **Do not send every captured packet immediately to the server.**

7. **Do not block the client command/socket thread.**

8. **A failure of one protocol must not stop the other listeners.**

9. **Do not modify the Windows logon task until the new client implementation has been manually tested successfully.**

10. **Do not merge passive observations with the existing `NetworkDevice` records yet.**

11. **Do not implement protocols blindly. First determine what is actually available on Windows and on the target network.**

12. **Stop after every phase and wait for explicit approval before continuing.**

# Final Intended Architecture

After this implementation, the client should conceptually look like:

```text
                         CLIENT
                           │
                  ┌────────┴────────┐
                  │                 │
             Existing             New
             Systems             Listener
                  │                 │
       ┌──────────┼─────────┐       │
       │          │         │       │
      ARP       DHCP     Activity   │
       │       Listener     │       │
       │          │         │       │
       └──────────┴─────────┘       │
                  │                 │
          Existing neighbourhood   │
                                   │
                       ┌───────────┼────────────┐
                       │           │            │
                      mDNS       LLMNR        NBNS
                       │           │            │
                      SSDP       DHCPv6        ...
                       └───────────┴────────────┘
                                   │
                       Passive observations
                                   │
                                   ▼
                       GET_PASSIVE_NEIGHBOURHOOD
                                   │
                                   ▼
                                SERVER
                                   │
                                   ▼
                                  GUI
```

The immediate goal is **not** to create a perfect device-identification system.

The immediate goal is to build a reliable, independently testable **passive observation layer** and determine, from the real center network, which protocols actually provide valuable information.