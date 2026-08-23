# Network Device Discovery & Unmanaged Device Monitoring

## Objective

Monitor devices connected to the center's network, including devices
without our client installed.

The system will eventually track:

-   IP address
-   MAC address
-   hostname, when available
-   vendor, when available
-   OS, when detectable
-   first seen / last seen
-   online presence
-   observation frequency
-   unmanaged-device alerts

Discovery and enrichment are best-effort.

------------------------------------------------------------------------

# Phase 1 --- Understand the Existing Architecture

Inspect the existing:

-   server entry point
-   database
-   models
-   API structure
-   background/task system
-   alert system
-   client/device models
-   authentication
-   client-server communication
-   existing scanner
-   existing logging

Do not create duplicate mechanisms.

------------------------------------------------------------------------

# Phase 2 --- Network Discovery

The system will eventually have two main discovery sources:

``` text
Server-side network scan
          +
Client ARP/neighbour tables
          |
          v
   Server aggregation
          |
          v
     NetworkDevice
          |
          v
     Observations
```

## Sub-step 1 --- Collect ARP/Neighbour Tables From Clients

This is the **first implementation task**.

A managed client should inspect its local ARP/neighbour table and report
the useful entries to the server.

Important limitation:

> An ARP table is not a complete list of every device connected to the
> network. It is a cache of neighbours known by that particular machine.

Therefore client ARP collection is an additional observation source, not
a replacement for server-side scanning.

### Sub-step 1.1 --- Determine the Client Platform

Determine the supported client OS/platform and how its ARP/neighbour
table can be read.

Normalize the result into a platform-independent structure:

``` python
{
    "ip_address": "...",
    "mac_address": "...",
    "entry_type": "dynamic"
}
```

### Sub-step 1.2 --- Implement the Collector

Create a client-side component responsible only for collecting the local
neighbour table.

Conceptual interface:

``` python
class NetworkNeighbourCollector:

    def collect(self) -> list[NetworkNeighbour]:
        ...
```

Do not mix ARP parsing, HTTP/network communication, database operations,
or alerts into this component.

### Sub-step 1.3 --- Parse the Table

Handle:

-   valid entries
-   empty tables
-   malformed entries
-   incomplete entries
-   dynamic entries
-   static entries
-   multicast/broadcast entries

Ignore entries that do not represent useful network devices.

One malformed entry must not crash the collector.

### Sub-step 1.4 --- Send Observations to the Server

Use the project's existing client-server communication mechanism.

Conceptual payload:

``` json
{
  "client_id": "...",
  "observed_at": "...",
  "interface": "...",
  "neighbours": [
    {
      "ip_address": "172.16.0.102",
      "mac_address": "AA:BB:CC:DD:EE:FF",
      "entry_type": "dynamic"
    }
  ]
}
```

Use the existing client authentication.

Do not create an unauthenticated endpoint for arbitrary submissions.

### Sub-step 1.5 --- Preserve the Observation Source

The server must know where an observation came from.

Example:

``` text
Device X
  - observed by Client A
  - observed by Client B
  - observed by Server scan
```

Use source types such as:

``` text
SERVER_SCAN
CLIENT_ARP
```

For client observations, store the reporting client.

### Sub-step 1.6 --- First Client Milestone

Do not implement OS detection, Nmap, scheduling, alerts, or dashboard
work yet.

First make this pipeline work:

``` text
Client
  |
  v
Read local ARP/neighbour table
  |
  v
Normalize
  |
  v
Send to server
  |
  v
Authenticate
  |
  v
Store observation
  |
  v
Verify with a real client
```

Test with at least two clients.

Example result:

``` text
Client A observed:
    172.16.0.102 -> AA:BB:CC:DD:EE:FF
    172.16.1.153 -> BB:CC:DD:EE:FF:AA

Client B observed:
    172.16.0.102 -> AA:BB:CC:DD:EE:FF
```

The server must understand that the same MAC represents one device with
multiple observations.

**Stop and review after this milestone.**

------------------------------------------------------------------------

# Phase 3 --- Server-Side LAN Discovery

Determine dynamically:

-   network interface
-   local IP
-   subnet
-   gateway

Do not hard-code the subnet.

Use the existing ARP-based scanner where possible.

Normalize server discoveries into the same internal representation.

------------------------------------------------------------------------

# Phase 4 --- Combine Discovery Sources

Merge observations from:

-   server ARP scan
-   client ARP tables

Use MAC as the preferred local identity.

Example:

``` text
Server:
    MAC A -> IP 1

Client A:
    MAC A -> IP 1

Client B:
    MAC A -> IP 2
```

These are observations of one device, not three devices.

An IP change must not automatically create a new device.

------------------------------------------------------------------------

# Phase 5 --- Device Enrichment

Only after basic discovery works.

## Hostname

Try, where appropriate:

-   reverse DNS
-   mDNS/Avahi
-   other safe local mechanisms

If unavailable:

``` json
"hostname": null
```

## Vendor

Use MAC/OUI information when available.

If unavailable:

``` json
"vendor": null
```

Do not infer extra information from vendor alone.

## OS

OS detection is best-effort.

Potentially use network fingerprinting/Nmap later.

Support:

``` text
os_name
os_family
os_confidence
```

If detection fails, keep the values null.

Never infer an OS solely from MAC vendor, hostname, or IP.

------------------------------------------------------------------------

# Phase 6 --- Database

Use the existing server database.

**Do not create a separate SQLite database for every device.**

Create/reuse:

``` text
NetworkDevice
```

Possible fields:

``` text
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

MAC should normally be the preferred identity.

IP is not a permanent identity because DHCP can change it.

------------------------------------------------------------------------

# Phase 7 --- Observation History

Create/reuse:

``` text
NetworkDeviceObservation
```

Possible fields:

``` text
id
device_id
source_type
source_client_id
scan_id
ip_address
hostname
vendor
os_name
observed_at
```

The observation source must remain available.

This lets the system answer:

-   Which client saw this device?
-   Did the server see it?
-   How many times was it observed?
-   When was it observed?
-   Which IPs did it use?

------------------------------------------------------------------------

# Phase 8 --- Server Scan History

Create/reuse:

``` text
NetworkScan
```

Possible fields:

``` text
id
started_at
completed_at
network
interface
status
devices_found
error
```

Do not only update `last_seen`; preserve historical observations.

------------------------------------------------------------------------

# Phase 9 --- Managed vs Unmanaged

After discovery:

``` text
Observation
    |
    v
Identify device
    |
    +----------------+
    |                |
    v                v
 Managed          Unmanaged
```

An unmanaged device is **not automatically malicious**.

It only means the device does not correspond to a registered/known
client.

------------------------------------------------------------------------

# Phase 10 --- Scheduling

Once manual discovery works:

-   implement a daily server scan
-   implement periodic client ARP collection
-   use the existing scheduling system if available
-   make intervals configurable
-   handle failures gracefully

Do not introduce a new task framework unnecessarily.

------------------------------------------------------------------------

# Phase 11 --- APIs

Implement APIs only after the underlying discovery pipeline works.

Potential endpoints:

``` text
POST /api/network/scans
GET  /api/network/scans
GET  /api/network/scans/{id}

GET  /api/network/devices
GET  /api/network/devices/{id}
```

Support useful filtering such as:

``` text
managed
unmanaged
online
offline
```

Protect all endpoints with the existing authentication/authorization
system.

Do not expose arbitrary command execution through the API.

------------------------------------------------------------------------

# Phase 12 --- Suspicious-Time Detection

Once presence history is reliable, add rules such as:

``` text
Working hours:
08:00 -> 18:00
```

Example:

``` text
Unmanaged device:
AA:BB:CC:DD:EE:FF

Detected:
02:17

Result:
Unmanaged device detected outside normal hours.
```

Working hours should eventually be configurable.

------------------------------------------------------------------------

# Phase 13 --- Alert Integration

Reuse the existing alert system.

Potential alert types:

``` text
UNMANAGED_DEVICE_DETECTED
UNMANAGED_DEVICE_OUTSIDE_HOURS
```

Do not create an alert for every scan of the same device.

Implement deduplication/cooldown.

------------------------------------------------------------------------

# Phase 14 --- False-Positive Handling

## DHCP

``` text
09:00 -> MAC A -> 192.168.1.20
15:00 -> MAC A -> 192.168.1.42
```

Same device.

## Temporary disconnect

``` text
09:00 -> detected
10:00 -> not detected
11:00 -> detected
```

Do not create a new device.

## MAC randomization

Modern devices may use randomized MAC addresses.

Therefore:

> MAC is the best available local identity, but it is not necessarily a
> permanent physical-device identity.

Do not claim two different MACs are definitely two different physical
devices.

------------------------------------------------------------------------

# Phase 15 --- Error Handling

Gracefully handle:

-   scanner unavailable
-   insufficient permissions
-   network interface unavailable
-   network disconnected
-   invalid subnet
-   timeout
-   hostname resolution failure
-   vendor lookup failure
-   OS detection failure
-   malformed ARP table
-   empty ARP table
-   client unable to report
-   server unavailable

Failure to identify one device must not fail the whole scan.

Example:

``` text
ARP discovery        ✓
Vendor lookup        ✓
Hostname resolution ✗
OS detection         ✗
Client observations  ✓

Overall:
SUCCESS
```

------------------------------------------------------------------------

# Phase 16 --- Logging

Use structured logs for the discovery system.

Example:

``` text
[INFO] Network scan started
[INFO] Interface: wlan0
[INFO] Network: 192.168.1.0/24
[INFO] 14 devices discovered
[INFO] 9 managed devices
[INFO] 5 unmanaged devices
[INFO] Client A reported 7 neighbour entries
[INFO] Client B reported 9 neighbour entries
[WARNING] 1 unmanaged device detected outside working hours
[INFO] Network scan completed
```

Avoid unnecessary sensitive information.

------------------------------------------------------------------------

# Phase 17 --- Testing

## Client ARP Collector

-   [ ] valid ARP/neighbour output
-   [ ] empty table
-   [ ] malformed entry
-   [ ] multicast/broadcast entries
-   [ ] dynamic entry
-   [ ] static entry
-   [ ] parser failure

## Client -\> Server

-   [ ] valid payload
-   [ ] authentication
-   [ ] malformed payload
-   [ ] server unavailable
-   [ ] duplicate observation
-   [ ] multiple clients reporting the same device

## Device Matching

-   [ ] same MAC -\> same device
-   [ ] different MAC -\> different device
-   [ ] same MAC + changed IP -\> same device
-   [ ] multiple clients observing same MAC -\> one device

## Observation Sources

-   [ ] server scan observation
-   [ ] client ARP observation
-   [ ] same device observed by multiple clients
-   [ ] source client correctly recorded

## History

-   [ ] first observation
-   [ ] subsequent observation
-   [ ] last_seen update
-   [ ] multiple scans
-   [ ] IP change
-   [ ] device disappearing

## Managed Detection

-   [ ] known client -\> managed
-   [ ] unknown device -\> unmanaged

## Alerts

-   [ ] unmanaged + normal hours -\> no alert
-   [ ] unmanaged + outside hours -\> alert
-   [ ] duplicate detection -\> no alert spam

------------------------------------------------------------------------

# Implementation Milestones

Implement **one milestone at a time**.

## Milestone 1 --- Client ARP Collection

-   [ ] Inspect existing client architecture
-   [ ] Identify supported client platforms
-   [ ] Implement platform-specific neighbour-table collection
-   [ ] Normalize the result
-   [ ] Ignore irrelevant entries
-   [ ] Add client-side tests
-   [ ] Send normalized observations to server
-   [ ] Authenticate the request
-   [ ] Add server endpoint
-   [ ] Store received observations
-   [ ] Test with a real client
-   [ ] Test with multiple clients

### Success condition

The server receives ARP/neighbour observations from a real client and
can associate each observation with its reporting client.

**Do not continue to Milestone 2 until this works.**

## Milestone 2 --- Server ARP Discovery

-   [ ] Detect server interface/subnet
-   [ ] Run existing ARP discovery
-   [ ] Normalize results
-   [ ] Manual server scan
-   [ ] Test on real network

## Milestone 3 --- Aggregate Discovery Sources

-   [ ] NetworkDevice
-   [ ] NetworkDeviceObservation
-   [ ] source type
-   [ ] source client
-   [ ] MAC-based correlation
-   [ ] IP changes
-   [ ] multiple-client observations

## Milestone 4 --- Device Identification

-   [ ] MAC
-   [ ] IP
-   [ ] vendor
-   [ ] hostname
-   [ ] optional OS detection

## Milestone 5 --- Database & History

-   [ ] NetworkDevice
-   [ ] NetworkScan
-   [ ] NetworkDeviceObservation
-   [ ] migrations
-   [ ] upsert logic
-   [ ] observations
-   [ ] historical IP tracking
-   [ ] first/last seen

## Milestone 6 --- API

-   [ ] Start scan
-   [ ] List scans
-   [ ] Scan details
-   [ ] List devices
-   [ ] Device details
-   [ ] Filtering
-   [ ] Observation history

## Milestone 7 --- Scheduling

-   [ ] Daily server scan
-   [ ] Periodic client ARP collection
-   [ ] Configurable schedule
-   [ ] Scan status
-   [ ] Failure handling

## Milestone 8 --- Managed/Unmanaged

-   [ ] Match discovered devices to clients
-   [ ] Mark unmanaged devices
-   [ ] Dashboard-ready data

## Milestone 9 --- Alerts

-   [ ] Unmanaged device detection
-   [ ] Outside-hours detection
-   [ ] Alert deduplication
-   [ ] Existing alert integration

## Milestone 10 --- Testing & Hardening

-   [ ] Unit tests
-   [ ] Integration tests
-   [ ] Real-network tests
-   [ ] Multiple-client tests
-   [ ] Permissions
-   [ ] Error handling
-   [ ] Documentation

------------------------------------------------------------------------

# Important Design Rules

1.  **Start with client ARP collection.**
2.  Client ARP is an observation source, not a complete network scan.
3.  Keep discovery separate from enrichment.
4.  Preserve the source of every observation.
5.  Prefer MAC for local identity; do not use IP as the unique identity.
6.  Do not treat unmanaged devices as automatically malicious.
7.  Do not implement OS detection or alerts before basic discovery and
    observation storage work.
8.  Do not create a separate database for every client/device.
9.  Reuse existing communication, authentication, scheduling, logging,
    and alert mechanisms where possible.

------------------------------------------------------------------------

# Final Architecture

``` text
                         CENTER NETWORK
                              |
             +----------------+----------------+
             |                                 |
             v                                 v
      MANAGED CLIENTS                    SERVER
             |                                 |
      ARP/Neighbour                         ARP Scan
        Collection                              |
             |                                 |
             +---------------+-----------------+
                             |
                             v
                    DISCOVERY INGESTION
                             |
                             v
                     DEVICE CORRELATION
                             |
                             v
                      NetworkDevice
                             |
              +--------------+--------------+
              |                             |
              v                             v
       Device Identity              Observation History
              |                             |
       +------+-------+              +------+------+
       |      |       |              |      |      |
      MAC   Host    Vendor         Client Server  Time
              |
              v
         OS Detection
              |
              v
      Managed / Unmanaged
              |
              v
       Suspicious Rules
              |
              v
       Existing Alert System
```

# First Task For The IDE AI

Do **only Milestone 1 --- Client ARP Collection**.

Do not implement:

-   OS detection
-   Nmap integration
-   daily scheduling
-   alerts
-   dashboard
-   advanced enrichment

until this pipeline works:

``` text
Client
  |
  v
Collect local ARP/neighbour table
  |
  v
Normalize entries
  |
  v
Send to existing server API
  |
  v
Server authenticates request
  |
  v
Server stores observation
  |
  v
Verify with a real client
```

Once this works, stop and review the implementation before moving to
Milestone 2.
