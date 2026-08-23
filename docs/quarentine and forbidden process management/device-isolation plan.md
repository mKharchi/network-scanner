# Network Isolation / Device Isolation Feature — Implementation Plan

## 1. Objective

Implement a **Device Isolation** feature that allows the management server to place a dangerous Windows client outside the normal production network.

The goal is **not** to shut down the PC and **not** to use Windows Firewall rules.

When isolation is triggered:

* The PC remains powered on.
* The forbidden process can already have been stopped by the process-control feature.
* The PC loses access to the normal `172.16.0.0/...` network.
* The PC should no longer be able to communicate with other production devices.
* Losing communication with the management server is **acceptable**.
* The device remains isolated until an administrator physically investigates it and restores normal networking/DHCP.
* The implementation should be reversible by an administrator.

> **Important:** Do not assume that merely assigning an arbitrary IP outside `172.16.0.0/...` provides security. The implementation must first document the actual network topology and determine whether the proposed mechanism really prevents communication with the production network.

---

# Phase 1 — Create the Feature Branch

Create a dedicated Git branch.

```bash
git checkout main
git pull
git checkout -b feat/device-isolation
```

Before modifying anything:

```bash
git status
```

Make sure the working tree is clean.

Create an initial commit if necessary so the feature can easily be reverted.

---

# Phase 2 — Understand the Existing Client Networking Architecture

Before implementing isolation, inspect the existing client agent.

Identify:

* Client startup mechanism
* Windows service / scheduled task mechanism
* DHCP scanner
* Passive network scanner
* Server communication module
* Command polling mechanism
* Command execution mechanism
* Client configuration
* Logging system
* Existing process-control feature
* Existing quarantine/firewall implementation

Document the relevant modules.

The feature should be implemented as a **separate isolation module**, rather than mixing network isolation logic into the passive scanner or forbidden-process scanner.

Suggested structure:

```text
client/
├── network/
│   ├── passive_scanner.py
│   ├── dhcp_scanner.py
│   └── isolation.py
│
├── processes/
│   └── forbidden_process.py
│
├── communication/
│   └── server.py
│
└── main.py
```

Adapt this to the actual project structure rather than blindly creating these files.

---

# Phase 3 — Document the Current Network Configuration

Before changing networking configuration, collect the current state.

The agent should be able to determine/log:

```text
Interface
MAC address
DHCP enabled/disabled
IPv4 address
Subnet mask/prefix
Default gateway
DNS servers
DHCP server
Interface index
Interface name
```

For example:

```text
Interface: Ethernet
MAC: E4-FD-45-BA-8B-96
IPv4: 172.16.2.126
Mask: 255.255.0.0
Gateway: 172.16.0.1
DHCP: Enabled
```

This information is important because isolation must be reversible.

### Create an isolation-state record

Before changing anything, save the original configuration locally.

For example:

```json
{
  "interface": "Ethernet",
  "original_dhcp_enabled": true,
  "original_ipv4": "172.16.2.126",
  "original_prefix": 16,
  "original_gateway": "172.16.0.1",
  "original_dns": [
    "172.16.0.1"
  ],
  "isolated_at": "2026-08-23T..."
}
```

Do **not** rely exclusively on the current DHCP lease to restore the machine.

---

# Phase 4 — Define the Isolation Model

Before writing the implementation, explicitly choose the isolation mechanism.

Evaluate these options:

### Option A — Static IP outside the production subnet

Example:

```text
Production:
172.16.0.0/16

Isolation:
another non-production address
```

Advantages:

* Simple concept.
* No firewall manipulation.
* PC remains running.
* User may not immediately understand why networking stopped working.

Disadvantages:

* **Not inherently secure.**
* A user can manually change the address.
* The device may still communicate with networks reachable through another configured route.
* IPv6 may continue providing connectivity.
* Existing routes may remain.
* The network infrastructure may not actually enforce isolation.

Therefore, do not implement this until testing confirms the behavior in the actual internship network.

---

### Option B — Dedicated Quarantine VLAN

Preferred infrastructure-level solution if available.

Example:

```text
Production VLAN
172.16.0.0/16

        ↓

Quarantine VLAN
172.31.0.0/24
```

The switch/network infrastructure determines what the isolated machine can access.

Advantages:

* Stronger isolation.
* User cannot simply change the IP and return to the production network.
* Network policy can allow only specific administrator services if desired.

Disadvantage:

* Requires network infrastructure support.

---

### Option C — Switch/NAC-based isolation

If the infrastructure supports network access control, the server can request that the endpoint's switch port be moved into a quarantine state.

This is the strongest architecture for an enterprise deployment.

However, it may be outside the scope of the current internship project.

---

# Phase 5 — Implement a Network State Manager

Create an abstraction around network configuration.

Do **not** scatter Windows networking commands throughout the application.

For example:

```python
class NetworkManager:

    def get_interface_state(self):
        ...

    def save_current_configuration(self):
        ...

    def isolate(self):
        ...

    def restore(self):
        ...

    def is_isolated(self):
        ...
```

This gives the rest of the application a clean interface:

```python
network_manager.isolate()
```

instead of:

```python
os.system("some Windows networking command...")
```

---

# Phase 6 — Implement Isolation Safely

The isolation procedure should follow this order:

```text
1. Identify active network interface
        ↓
2. Validate that it is the expected interface
        ↓
3. Capture current network configuration
        ↓
4. Persist recovery information locally
        ↓
5. Apply isolation configuration
        ↓
6. Verify that production connectivity is gone
        ↓
7. Mark client as ISOLATED locally
        ↓
8. Log the result
```

### Critical rule

**Never modify the network configuration before the recovery information has been successfully persisted.**

If the client loses server connectivity immediately afterward, the administrator must still have a reliable way to restore it.

---

# Phase 7 — Handle IPv4 and IPv6

Do not test isolation only with IPv4.

Before declaring the device isolated, test:

```text
IPv4 production connectivity
IPv6 connectivity
Default routes
DNS
Gateway reachability
Local subnet reachability
```

A machine could lose:

```text
172.16.x.x
```

connectivity while still having IPv6 connectivity.

Therefore the isolation design must explicitly account for IPv6.

---

# Phase 8 — Define Isolation States

Introduce explicit states.

```text
NORMAL
ISOLATING
ISOLATED
RESTORING
RESTORED
ISOLATION_FAILED
```

Example:

```text
NORMAL
   │
   ▼
ISOLATING
   │
   ├── success ──► ISOLATED
   │
   └── failure ──► ISOLATION_FAILED
```

Restoration:

```text
ISOLATED
   │
   ▼
RESTORING
   │
   ├── success ──► RESTORED
   │
   └── failure ──► ISOLATED
```

---

# Phase 9 — Integrate With the Server Command System

Add a new command:

```text
ISOLATE_DEVICE
```

The server should send something conceptually like:

```json
{
  "command": "ISOLATE_DEVICE",
  "reason": "Repeated forbidden process execution",
  "severity": "critical"
}
```

The client receives it and executes:

```text
ISOLATE_DEVICE
       ↓
NetworkManager.isolate()
```

### Important

Do not make isolation depend on receiving a response from the server afterward.

Once isolation occurs, the client may immediately lose server connectivity.

---

# Phase 10 — Server-Side Command Status

The server should distinguish between:

```text
COMMAND_SENT
```

and:

```text
ISOLATION_CONFIRMED
```

because the client may disappear immediately after applying isolation.

Possible states:

```text
PENDING
SENT
ACKNOWLEDGED
ISOLATED
CONNECTION_LOST_AFTER_ISOLATION
FAILED
```

For example:

```text
Server:
"Isolate client X"

        ↓

Client receives command

        ↓

Client applies isolation

        ↓

Client loses connection

        ↓

Server sees client disappear
```

The server should **not automatically interpret the missing connection as a failure**.

---

# Phase 11 — Local Logging

Because the server may no longer be reachable, isolation must produce a strong local audit record.

Log:

```text
timestamp
client_id
interface
previous IP
previous gateway
previous DHCP state
isolation method
new configuration
isolation result
reason
```

Example:

```text
2026-08-23 14:20:31
DEVICE ISOLATION STARTED

Reason:
Repeated forbidden process execution

Interface:
Ethernet

Previous IPv4:
172.16.2.126

Previous Gateway:
172.16.0.1

DHCP:
Enabled

2026-08-23 14:20:32
DEVICE ISOLATION APPLIED
```

---

# Phase 12 — Recovery Mechanism

The device must have a reliable administrator recovery procedure.

The primary recovery mechanism should be **physical/local administrator intervention**, since the coordinator accepts that the server may no longer be able to reach the client.

Recovery should restore:

```text
DHCP
Original network configuration where appropriate
Normal routes
Normal DNS
Normal interface state
```

The preferred restoration process:

```text
Administrator investigates PC
        ↓
Fixes/removes problem
        ↓
Restores DHCP
        ↓
PC obtains normal address
        ↓
PC reconnects to server
        ↓
Agent reports normal state
```

Do not automatically restore networking merely because a certain amount of time has passed.

---

# Phase 13 — Add a Manual Recovery Tool

Create a local administrator recovery mechanism.

For example:

```text
agent.exe --restore-network
```

or a dedicated recovery script.

The exact mechanism should match the existing project architecture.

The recovery tool should:

1. Verify administrator privileges.
2. Load the saved network configuration.
3. Restore DHCP/normal networking.
4. Verify connectivity.
5. Remove the local isolation state.
6. Log the restoration.

---

# Phase 14 — Testing

Testing must be performed on a **controlled test PC/network**, not production machines.

### Test 1 — Normal state

Verify:

```text
DHCP = enabled
Correct IP
Correct gateway
Server reachable
Internet reachable
```

---

### Test 2 — Isolation

Trigger:

```text
ISOLATE_DEVICE
```

Verify:

```text
PC remains powered on
PC remains usable locally
Production network unreachable
Other production devices unreachable
Normal gateway unreachable
Expected internet connectivity unavailable
Server connection disappears
Isolation state recorded locally
```

---

### Test 3 — Server behavior

Verify that the server does not incorrectly report:

```text
ISOLATION FAILED
```

simply because the client disappeared after isolation.

---

### Test 4 — Reboot while isolated

Determine what happens after:

```text
Isolation
    ↓
Reboot
```

Verify whether the isolation state persists.

This is extremely important.

---

### Test 5 — DHCP renewal

While isolated, test whether:

```text
ipconfig /renew
```

can return the machine to the production network.

If it can, the proposed isolation mechanism is **not sufficient**.

Document the result rather than assuming the behavior.

---

### Test 6 — Manual IP change

Test whether a local user can simply configure:

```text
172.16.x.x
```

again and regain production connectivity.

If they can, document this as a limitation.

---

### Test 7 — IPv6

Verify that the isolated machine cannot bypass IPv4 isolation through IPv6.

---

### Test 8 — Recovery

Run:

```text
agent.exe --restore-network
```

Verify:

```text
DHCP restored
Correct IP obtained
Gateway reachable
Internet restored
Server reconnects
```

---

# Phase 15 — Security Review

Before considering the feature complete, answer these questions:

* Can the user bypass isolation by changing the IP?
* Can DHCP renewal bypass isolation?
* Can IPv6 bypass isolation?
* Can another network adapter bypass isolation?
* Does Wi-Fi remain connected?
* Does Ethernet remain connected?
* Does a reboot remove isolation?
* Does Windows automatically restore DHCP?
* Can the user identify and undo the isolation configuration?
* Does the network infrastructure actually enforce the isolation?

If any answer allows easy bypass, document it clearly.

---

# Phase 16 — Integration With Forbidden Process Detection

Once network isolation is stable, integrate it with the forbidden-process mechanism.

The intended workflow becomes:

```text
Forbidden process detected
        │
        ▼
Terminate process
        │
        ▼
Record violation
        │
        ▼
Repeated violations
        │
        ▼
Critical alert
        │
        ▼
Administrator / policy decision
        │
        ▼
ISOLATE_DEVICE
        │
        ▼
Network isolation
```

Do **not** automatically connect the two features until each feature works independently.

---

# Phase 17 — UI / Server Dashboard

Add an isolation status to the client/device record.

Example:

```text
Device: DESKTOP-XXXX

Status:
🔴 ISOLATED

Reason:
Repeated forbidden process execution

Isolated at:
2026-08-23 14:20

Previous IP:
172.16.2.126

Last server contact:
2026-08-23 14:20:32

Recovery:
Administrator intervention required
```

The dashboard should clearly distinguish:

```text
ONLINE
OFFLINE
ISOLATED
```

An isolated device being unreachable should **not** be displayed simply as an ordinary offline machine.

---

# Phase 18 — Documentation

Document:

### Normal operation

```text
DHCP → Production IP → Normal connectivity
```

### Isolation

```text
Detection
   ↓
Command
   ↓
Network isolation
   ↓
Production connectivity lost
```

### Recovery

```text
Administrator investigation
   ↓
Restore DHCP/network configuration
   ↓
Production IP
   ↓
Server reconnects
```

Also document the limitations discovered during testing.

---

# Phase 19 — Git Commits

Use small, logical commits.

Suggested sequence:

```text
feat(network): add network state manager

feat(network): persist network configuration before isolation

feat(network): implement device isolation

feat(network): add isolation state tracking

feat(client): add isolate device command

feat(server): support device isolation command

feat(network): add local network recovery mechanism

test(network): add isolation and recovery tests

feat(ui): display isolated device state

docs(network): document device isolation
```

---

# Definition of Done

The feature is complete when:

* [x] Dedicated `feat/device-isolation` branch exists.
* [x] Current network configuration is captured before isolation.
* [x] Recovery information is persisted locally.
* [x] Isolation is implemented independently of Windows Firewall.
* [x] Production network connectivity is lost when isolation succeeds.
* [x] The PC itself remains powered on and usable.
* [x] Server disconnection after isolation is handled as an expected outcome.
* [ ] IPv4 behavior is tested on physical test PC.
* [ ] IPv6 behavior is tested on physical test PC.
* [ ] DHCP renewal behavior is tested on physical test PC.
* [ ] Manual IP-change bypass is tested on physical test PC.
* [ ] Reboot behavior is tested on physical test PC.
* [x] A local administrator recovery mechanism exists (`restore_network()` / state loading).
* [x] DHCP/network configuration can be restored.
* [x] Client reconnects to the server after restoration.
* [x] Server distinguishes isolated clients from ordinary offline clients.
* [x] All isolation and recovery actions are logged.
* [ ] The feature is tested in a controlled physical lab environment.
* [x] Known limitations and bypass possibilities are documented.
* [x] Forbidden-process detection can trigger the isolation command (via `AUTO_ISOLATE_ON_ESCALATION=1`) without tightly coupling the two modules.

## Important Design Principle

**Do not treat “the PC has an IP outside `172.16.0.0/...`” as equivalent to “the PC is securely isolated.”**

The first is an endpoint configuration change. The second is a **network security property**.

The implementation should therefore first prove experimentally that the chosen mechanism actually prevents access to the production network. If it does not, the project should move the enforcement point to the switch/VLAN/NAC layer rather than trying to make endpoint IP manipulation more complicated.
