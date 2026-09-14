# Network Device Discovery & Unmanaged Device Monitoring

## 1. Objective

Implement server-side monitoring for devices connected to the center's local network that **do not have our client installed**.

The server should periodically discover devices on the local network and maintain a history of:

- IP address
- MAC address
- hostname, when available
- manufacturer/vendor, when available
- operating system, when detectable
- first seen
- last seen
- whether the device is currently online
- number/frequency of appearances
- suspicious activity based on presence/time rules

The initial objective is **device identification and presence tracking**, not deep inspection of network traffic.

The system must not assume that every device can be identified perfectly. OS and hostname detection are best-effort.

---

# Phase 1 — Understand the Existing Architecture

## Step 1. Inspect the existing server

Identify:

- server entry point
- database configuration
- existing models
- API structure
- background/task system
- existing alert implementation
- existing client/device models
- existing authentication
- logging system

Do not create duplicate models or mechanisms if equivalent functionality already exists.

## Step 2. Inspect the existing scanner

The project already has network-scanning functionality using tools such as:

- `arp-scan`
- `nmap`
- `avahi-resolve-address`

Understand exactly what the existing scanner currently returns.

Create/confirm a normalized internal representation such as:

```python
{
    "ip_address": "...",
    "mac_address": "...",
    "hostname": "...",
    "vendor": "...",
    "os": "...",
}
```

Do not make OS/hostname mandatory.

---

# Phase 2 — Define the Concept of a Network Device

### Managed device

A device that has our client installed and communicates with the server.

### Unmanaged device

A device detected on the network that does not correspond to a registered/known client.

The scanner should discover **all devices**, then the server determines whether each device is managed.

Do NOT make the scanner responsible for deciding this.

---

# Phase 3 — Network Discovery

## Step 1. Determine the local network

For Linux, inspect information equivalent to:

```bash
ip addr
ip route
```

Determine:

- network interface
- local IP
- subnet
- gateway

Example:

```text
Interface: wlan0
Local IP: 192.168.1.20
Network: 192.168.1.0/24
Gateway: 192.168.1.1
```

Do not hard-code `192.168.1.0/24`.

## Step 2. Perform LAN discovery

Use the existing ARP-based scanner where possible.

Primary goal:

> Who is currently connected?

For each discovered device collect:

```text
IP
MAC
Vendor
```

ARP discovery should be considered the primary mechanism for determining presence on a local IPv4 LAN.

---

# Phase 4 — Device Enrichment

After discovering a device, attempt to obtain additional information.

This should be a **separate phase** from discovery.

Do not run expensive OS detection against every device immediately.

## Step 1. Hostname detection

Attempt hostname resolution using available mechanisms:

- reverse DNS
- mDNS / Avahi
- existing hostname information from discovery

If hostname cannot be resolved:

```json
"hostname": null
```

This is normal.

## Step 2. Vendor detection

Use the MAC address/OUI to determine manufacturer.

If vendor cannot be determined:

```json
"vendor": null
```

The scanner must not fail because vendor lookup fails.

## Step 3. OS detection

OS detection should be treated as **best effort**.

Potentially use:

```bash
nmap -O <ip>
```

However:

- OS detection can be slow.
- It may require elevated privileges.
- It can return uncertain results.
- Some devices will return no useful OS information.
- Some devices may produce multiple possible fingerprints.

Support:

```text
os_name
os_family
os_confidence
```

Example:

```json
{
    "os_name": "Android",
    "os_family": "Android",
    "os_confidence": 0.75
}
```

If detection fails:

```json
{
    "os_name": null,
    "os_family": null,
    "os_confidence": null
}
```

Do not infer an OS from the vendor.

---

# Phase 5 — Create the Device Database Model

Do not create a separate SQLite database for every device.

Use the existing server database.

Create a model such as:

```text
NetworkDevice
```

Suggested fields:

```text
id
mac_address
ip_address
hostname
vendor
os_name
os_family
os_confidence

first_seen
last_seen
last_scan_id

is_managed
is_currently_online

created_at
updated_at
```

The MAC address should be the primary identity where possible.

### Important

IP addresses should **not** uniquely identify a device.

A DHCP server can give the same device different IP addresses over time. MAC address is therefore the preferred identity.

---

# Phase 6 — Scan History

Do not only update `last_seen`.

We also need to know **when the device was observed**.

Create a scan/session model:

```text
NetworkScan
```

Suggested fields:

```text
id
started_at
completed_at
network
interface
status
devices_found
error
```

Then create:

```text
NetworkDeviceObservation
```

An observation represents:

> Device X was detected during scan Y.

Suggested fields:

```text
id
scan_id
device_id

ip_address
hostname
vendor
os_name

observed_at
```

This provides historical presence.

---

# Phase 7 — Why Scan History Is Important

Example:

```text
09:00 → device detected
12:00 → device detected
15:00 → device detected
18:00 → device detected
```

This allows the system to answer:

- When was this device seen?
- How many times was it seen?
- Was it present at night?
- Was it present outside normal working hours?
- Was it seen for several consecutive days?

This is more useful than storing only `last_seen`.

---

# Phase 8 — Managed vs Unmanaged Devices

After discovery, compare each discovered device against registered client devices.

Flow:

```text
Scan network
      ↓
Discover devices
      ↓
For each device
      ↓
Find matching MAC/device identity
      ↓
 ┌───────────────┐
 │               │
Managed       Unmanaged
 │               │
Update         Store/update
client         NetworkDevice
status
```

An unmanaged device should **not automatically be considered malicious**.

It simply means:

> The server discovered a device that does not have our client installed.

---

# Phase 9 — Daily Scan Scheduler

Implement a server-side scheduled scan.

Initial requirement:

> Run once per day.

First inspect the existing project and use its existing scheduling mechanism if one exists.

Possible mechanisms:

- cron
- systemd timer
- Celery beat
- APScheduler

Do not introduce a new task framework only for this feature if the project does not otherwise need it.

---

# Phase 10 — Manual Scan API

Before relying on the scheduler, implement a manual scan.

Example:

```http
POST /api/network/scans
```

Return:

```json
{
    "scan_id": 42,
    "status": "started"
}
```

Then provide:

```http
GET /api/network/scans/42
```

This makes development and debugging easier.

---

# Phase 11 — Current Devices Endpoint

Create:

```http
GET /api/network/devices
```

Support filtering:

```text
managed
unmanaged
online
offline
```

Example response:

```json
[
    {
        "id": 12,
        "ip_address": "192.168.1.25",
        "mac_address": "AA:BB:CC:DD:EE:FF",
        "hostname": "Android-4",
        "vendor": "Xiaomi",
        "os": "Android",
        "managed": false,
        "first_seen": "...",
        "last_seen": "...",
        "currently_online": true
    }
]
```

---

# Phase 12 — Device Detail

Create:

```http
GET /api/network/devices/{id}
```

Provide:

### Identity

```text
MAC
IP
Hostname
Vendor
OS
```

### Presence

```text
First seen
Last seen
Currently online
```

### History

```text
Number of observations
Previous IP addresses
Previous hostnames
Dates/times detected
```

---

# Phase 13 — Unmanaged Device Detection

Once basic scanning works, mark devices that don't correspond to an installed client as unmanaged.

Consider an explicit category:

```text
UNKNOWN
MANAGED
UNMANAGED
```

Do not immediately label unknown devices as threats.

---

# Phase 14 — Suspicious-Time Detection

Once presence history works, implement the first security rule.

Example:

```text
Center working hours:
08:00 → 18:00
```

A device detected outside that period can generate an alert.

Example:

```text
Device:
AA:BB:CC:DD:EE:FF

Detected:
02:17

Managed:
No

Alert:
Unmanaged device detected outside normal hours.
```

Working hours should eventually be configurable rather than hard-coded.

---

# Phase 15 — Alert Integration

Reuse the existing alert system.

Do not create a second alert mechanism.

Possible alert types:

```text
UNMANAGED_DEVICE_DETECTED
UNMANAGED_DEVICE_OUTSIDE_HOURS
```

Example:

```json
{
    "type": "UNMANAGED_DEVICE_OUTSIDE_HOURS",
    "severity": "medium",
    "device_id": 42,
    "message": "An unmanaged device was detected at 02:17."
}
```

Avoid creating an alert every time the same device is detected during every scan.

Implement alert deduplication/cooldown.

---

# Phase 16 — Avoid False Positives

## Phone temporarily disconnects

```text
09:00 detected
10:00 not detected
11:00 detected
```

Do not consider this a new device.

## DHCP changes IP

```text
09:00 → MAC A → 192.168.1.20
15:00 → MAC A → 192.168.1.42
```

This is the same device.

## MAC randomization

Modern phones can use randomized MAC addresses.

Therefore:

> MAC address is the best available local identity, but not an absolutely reliable permanent identity.

Do not claim that two different randomized MAC addresses are definitely different physical devices.

---

# Phase 17 — Security and Permissions

Network scanning should only be performed by the authorized server process.

Protect endpoints such as:

```text
POST /network/scans
GET /network/devices
GET /network/scans
```

with the project's existing authentication/authorization system.

Do not expose arbitrary commands such as:

```http
POST /scan
{
    "command": "nmap ..."
}
```

The API should expose predefined scanner operations.

---

# Phase 18 — Error Handling

Gracefully handle:

- `arp-scan` not installed
- `nmap` not installed
- permission denied
- network interface unavailable
- no network connection
- invalid subnet
- timeout
- DNS resolution failure
- OS detection failure

A failure to identify the OS should **not** cause the entire scan to fail.

Example:

```text
ARP scan       ✓
Vendor lookup  ✓
Hostname       ✓
OS detection   ✗
```

Overall scan:

```text
SUCCESS
```

with:

```text
os = unknown
```

---

# Phase 19 — Logging

Add structured logs for the scanner itself.

Example:

```text
[INFO] Network scan started
[INFO] Interface: wlan0
[INFO] Network: 192.168.1.0/24
[INFO] 14 devices discovered
[INFO] 9 managed devices
[INFO] 5 unmanaged devices
[WARNING] 1 unmanaged device detected outside working hours
[INFO] Network scan completed
```

Do not log sensitive information unnecessarily.

---

# Phase 20 — Testing

Implement tests progressively.

## Scanner tests

- [ ] valid ARP output
- [ ] empty ARP output
- [ ] malformed output
- [ ] vendor lookup failure
- [ ] hostname lookup failure
- [ ] Nmap failure

## Device matching

- [ ] same MAC → same device
- [ ] different MAC → different device
- [ ] same MAC + changed IP → same device

## Scan history

- [ ] first observation
- [ ] subsequent observation
- [ ] `last_seen` update
- [ ] multiple scans

## Managed detection

- [ ] known client → managed
- [ ] unknown device → unmanaged

## Alerting

- [ ] unmanaged + normal hours → no alert
- [ ] unmanaged + outside hours → alert
- [ ] duplicate detection → no alert spam

---

# Phase 21 — Implementation Order

The IDE AI should implement **one phase at a time**.

## Milestone 1 — Discovery

- [ ] Inspect existing scanner
- [ ] Detect network interface/subnet
- [ ] Run ARP discovery
- [ ] Normalize scan results
- [ ] Manual scan from server
- [ ] Test with real network

## Milestone 2 — Identification

- [ ] MAC
- [ ] IP
- [ ] vendor
- [ ] hostname
- [ ] optional OS detection
- [ ] normalized device object

## Milestone 3 — Database

- [ ] `NetworkDevice`
- [ ] `NetworkScan`
- [ ] `NetworkDeviceObservation`
- [ ] migrations
- [ ] device upsert logic
- [ ] observation creation

## Milestone 4 — API

- [ ] Start scan
- [ ] List scans
- [ ] Scan details
- [ ] List devices
- [ ] Device details
- [ ] filtering

## Milestone 5 — Scheduling

- [ ] Daily scan
- [ ] configurable schedule
- [ ] scan status
- [ ] failure handling

## Milestone 6 — Managed/Unmanaged

- [ ] Match discovered devices to clients
- [ ] Mark unmanaged devices
- [ ] Prepare dashboard-ready data

## Milestone 7 — Alerts

- [ ] Unmanaged device detection
- [ ] Outside-hours detection
- [ ] Alert deduplication
- [ ] Integrate with existing alert system

## Milestone 8 — Testing & Hardening

- [ ] Unit tests
- [ ] Integration tests
- [ ] Real-network test
- [ ] Permissions
- [ ] Error handling
- [ ] Documentation

---

# Important Design Rule

**Do not start with OS detection or alerts.**

The core pipeline should first work:

```text
NETWORK
   ↓
DISCOVERY
   ↓
DEVICE
   ↓
DATABASE
   ↓
OBSERVATION HISTORY
   ↓
MANAGED / UNMANAGED
   ↓
SCHEDULED SCAN
   ↓
ALERTS
```

If the first four pieces work correctly, everything afterward becomes much easier.

## Separation from Client Activity Logs

This feature is **not** another activity-log system.

The existing client logs answer:

> "What did this managed computer do?"

The network monitoring system answers:

> "Which computers were present on our network, including computers that don't have our client?"

These are two different concepts and should remain separate.
