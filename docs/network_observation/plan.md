# Passive Network Packet Observation & Daily Local Storage

## Objective

Implement a new passive network packet observation feature in the existing client application.

The purpose of this feature is **data collection for a future ML team**.

Another team will later use the collected data to train models for things such as:

- network activity classification
- device behavioral profiling
- anomaly detection
- suspicious/threat behavior detection

**This implementation must NOT implement any ML.**

The client only needs to:

1. Observe packets that are actually visible to the client.
2. Extract useful metadata from each observed packet.
3. Normalize the metadata into a consistent structure.
4. Store the observations locally.
5. Organize the stored observations into one JSON file per day.
6. Never send these packet observations to the server in this first version.

The feature will later be deployed to all clients using the existing client-update mechanism.

---

# 1. Important Scope

This is a **V1 data-collection feature**.

Do NOT implement:

- ML models
- model training
- anomaly detection
- threat scoring
- activity classification
- server transmission
- server-side packet storage
- flow aggregation
- dashboards
- API endpoints
- packet payload storage
- automatic threat alerts

The goal is simply:

```text
Network interface
        ↓
Packet observation
        ↓
Metadata extraction
        ↓
Normalized observation
        ↓
Local daily JSON file
```

---

# 2. First Task: Audit the Existing Client

Before writing new code, inspect the existing client implementation carefully.

Identify every mechanism that currently observes, listens for, captures, or gathers network information.

At minimum, investigate:

- DHCP listener
- mDNS listener
- LLMNR listener
- NBNS listener
- SSDP listener
- ARP/neighbour discovery
- DNS resolution
- any Scapy sniffers
- any raw socket listeners
- any packet capture functionality
- any network-interface detection
- any background network collectors

Do not assume that all of these are currently implemented exactly as expected.

Inspect the actual code.

Produce an internal understanding of:

```text
Listener
    ↓
What does it observe?
    ↓
Which interface does it use?
    ↓
How is it started?
    ↓
How is it stopped?
    ↓
What data does it currently extract?
    ↓
Where is that data currently stored?
```

### Important

Do not rewrite existing listeners simply because the new feature overlaps with them.

The existing DHCP/mDNS/LLMNR/NBNS/SSDP functionality must continue working.

The new packet-observation feature should be added with minimal disruption.

---

# 3. Existing Passive Discovery Must Continue Working

The application already has passive network discovery functionality.

Known existing observations include:

- DHCP
- mDNS
- LLMNR
- NBNS
- SSDP

The new packet observer must not break these features.

For example, DHCP currently provides useful information such as:

```text
MAC
DHCP message type
requested IP
hostname
vendor class
client ID
```

That existing functionality should remain intact.

The new packet observation system may observe the same DHCP packet, but it should create its own normalized observation record for local packet telemetry.

---

# 4. New Component: Packet Observer

Create a dedicated component responsible for observing packets.

Use the existing project architecture and naming conventions.

A reasonable structure would be:

```text
client/
    ...
    network/
        packet_observer.py
        ...
    storage/
        passive_packets/
            ...
```

Do not blindly create these exact paths if the existing project has a better structure.

First inspect the repository and integrate with the existing architecture.

The packet observer should have responsibilities similar to:

```python
start()
stop()
capture_packet(packet)
extract_metadata(packet)
```

The exact API is up to the existing project architecture.

---

# 5. Packet Capture

Use the packet-capture mechanism already used by the project where possible.

Scapy is already used by the client for passive network listening, so investigate whether the new observer can use Scapy's capture functionality consistently.

The observer should capture packets that are actually visible to the client.

### VERY IMPORTANT NETWORK LIMITATION

Do not assume that a client can see all traffic on the LAN.

A normal endpoint connected to a switched network generally sees:

- its own traffic
- traffic addressed to it
- broadcast traffic
- multicast traffic
- other traffic that the network interface/OS makes visible

It generally does NOT see arbitrary unicast traffic between other devices on a switched network.

Therefore this feature must be described as:

> locally observable passive traffic

not:

> all network traffic.

Do not attempt to bypass switching behavior, enable promiscuous-mode assumptions without checking the platform, or implement network-wide monitoring.

The first version should simply record whatever packets the client can legitimately observe.

---

# 6. Interface Selection

Reuse the existing network-interface detection logic if one already exists.

Do not hardcode:

```text
eth0
Ethernet
Wi-Fi
```

unless the existing project already does this.

The client must work with the existing network configuration.

If the project already has a function that determines:

- local IP
- interface
- network
- gateway

reuse that functionality where appropriate.

The packet observer should log which interface it is capturing from.

Example:

```text
[PACKET_OBSERVER] Started on interface Ethernet
```

If interface detection fails:

```text
[PACKET_OBSERVER] Unable to determine capture interface
```

and fail gracefully without crashing the client.

---

# 7. Generic Packet Metadata

For every packet that is observed, extract useful metadata.

The first version should collect as much useful metadata as reasonably available without storing the actual packet payload.

A generic record should contain fields similar to:

```json
{
  "timestamp": "2026-09-02T13:42:18.381Z",
  "observer_client_id": "client-17",
  "interface": "Ethernet",

  "src_mac": "AA:BB:CC:DD:EE:FF",
  "dst_mac": "11:22:33:44:55:66",

  "src_ip": "192.168.1.42",
  "dst_ip": "142.250.185.14",

  "protocol": "TCP",

  "src_port": 52341,
  "dst_port": 443,

  "packet_length": 1460,

  "tcp_flags": "PA"
}
```

Only include fields that are actually available for that packet.

For example:

- ARP has no TCP ports.
- ICMP has no TCP ports.
- Ethernet-only packets may not contain IP addresses.
- UDP packets do not have TCP flags.

Do not invent values.

Use `null` or omit the field according to the project's JSON conventions.

---

# 8. Metadata to Consider

The observer should attempt to extract the following where available.

## Timestamp

Record the observation timestamp with sufficient precision.

Example:

```json
"timestamp": "2026-09-02T13:42:18.381Z"
```

Use a consistent timezone strategy throughout the implementation.

Prefer UTC for stored timestamps unless the project already has an established convention.

---

## Observer Client

Record which client observed the packet.

Example:

```json
"observer_client_id": "client-17"
```

Use the existing client ID mechanism.

Do not invent a second client identity system.

---

## Interface

Example:

```json
"interface": "Ethernet"
```

---

## MAC Addresses

Where available:

```json
"src_mac": "AA:BB:CC:DD:EE:FF",
"dst_mac": "11:22:33:44:55:66"
```

Normalize MAC addresses consistently.

Prefer the existing MAC normalization helper if the project already has one.

---

## IP Addresses

Where available:

```json
"src_ip": "192.168.1.42",
"dst_ip": "142.250.185.14"
```

Support IPv4.

If IPv6 is already naturally handled by the packet parser, support it as well.

Do not add unnecessary IPv6 complexity if it destabilizes the existing implementation.

---

## Transport Protocol

Record the observed transport/network protocol.

Examples:

```text
TCP
UDP
ICMP
ARP
IPv6
```

Use a consistent representation.

---

## Ports

For TCP/UDP:

```json
"src_port": 52341,
"dst_port": 443
```

If ports are not applicable:

```json
"src_port": null,
"dst_port": null
```

or follow the project's preferred omission convention.

---

## Packet Length

Record the packet length where available.

Example:

```json
"packet_length": 1460
```

This is important for future behavioral analysis.

---

## TCP Flags

For TCP packets, capture useful TCP flags.

Example:

```json
"tcp_flags": "S"
```

or:

```json
"tcp_flags": "PA"
```

Useful flags include:

```text
SYN
ACK
FIN
RST
PSH
URG
ECE
CWR
```

Use a normalized representation.

---

# 9. Direction

If it is possible to determine reliably whether a packet is:

```text
inbound
outbound
unknown
```

then include:

```json
"direction": "outbound"
```

However, do NOT guess.

Direction should be calculated using the client's known local interface/IP/MAC information.

If direction cannot be reliably determined:

```json
"direction": "unknown"
```

Do not infer direction merely from the port number.

---

# 10. Protocol-Specific Metadata

Generic packet metadata is the baseline.

Where the observer can identify a protocol, it should optionally include protocol-specific metadata.

The existing passive listeners already parse several protocols.

The new system should be designed so that protocol-specific fields can be added without changing the generic packet schema.

For example:

```json
{
  "timestamp": "...",
  "protocol": "DHCP",
  "src_ip": "...",
  "dst_ip": "...",

  "protocol_metadata": {
    "message_type": "REQUEST",
    "requested_ip": "172.16.0.102",
    "hostname": "DESKTOP-DJP05CM",
    "vendor_class": "MSFT 5.0",
    "client_id": "..."
  }
}
```

Do not duplicate every field at the top level if the existing architecture benefits from a `protocol_metadata` object.

---

# 11. DHCP

The existing DHCP listener already observes DHCP requests.

Do not remove or modify its current behavior unless necessary.

The new packet observer should be capable of recording DHCP observations.

Useful metadata includes:

```text
message_type
requested_ip
hostname
vendor_class
client_id
MAC
```

Example:

```json
{
  "protocol": "DHCP",
  "protocol_metadata": {
    "message_type": "REQUEST",
    "requested_ip": "172.16.0.102",
    "hostname": "DESKTOP-DJP05CM",
    "vendor_class": "MSFT 5.0",
    "client_id": "..."
  }
}
```

---

# 12. mDNS

If an observed packet is mDNS, record useful metadata that can be extracted without storing the raw packet.

Potential fields:

```text
query/response
name
record type
service
hostname
address
port
TXT information where already parsed
```

Do not aggressively parse arbitrary payloads.

Only extract structured protocol information that can be safely and reliably parsed.

---

# 13. LLMNR

For LLMNR observations, record useful information such as:

```text
query/response
queried name
record type
source
destination
```

---

# 14. NBNS

For NBNS:

```text
query/response
NetBIOS name
record type
source
destination
```

---

# 15. SSDP

For SSDP, where available, record useful headers/metadata such as:

```text
method
ST
NT
USN
USER-AGENT
SERVER
LOCATION
```

Do not actively request the LOCATION URL.

This feature is passive observation only.

---

# 16. DNS

If DNS packets are visible to the observer, extract useful DNS metadata.

Potentially:

```text
query/response
query name
query type
response type
```

Example:

```json
{
  "protocol": "DNS",
  "protocol_metadata": {
    "message_type": "query",
    "query_name": "example.com",
    "query_type": "A"
  }
}
```

Do not store raw DNS packet payloads.

Do not perform additional DNS queries as part of this feature.

---

# 17. Do Not Store Raw Payloads

This is a strict requirement for V1.

Do NOT store:

- raw Scapy packet objects
- hexadecimal packet dumps
- complete payload bytes
- PCAP files
- arbitrary application data
- credentials
- message bodies
- HTTP bodies
- file contents

The objective is metadata collection.

The stored data should describe the packet rather than reproduce it.

---

# 18. Daily Local Storage

Create a dedicated storage location for passive packet observations.

Preferred conceptual structure:

```text
client/
└── storage/
    └── passive_packets/
        ├── 2026-09-01.json
        ├── 2026-09-02.json
        ├── 2026-09-03.json
        └── ...
```

Do not use a single permanent file.

Every calendar day gets its own JSON file.

---

# 19. Daily File Format

Each file should contain metadata about the observation day and the packet observations.

Example:

```json
{
  "date": "2026-09-02",
  "observer_client_id": "client-17",
  "packets": [
    {
      "timestamp": "2026-09-02T13:42:18.381Z",
      "interface": "Ethernet",
      "src_mac": "AA:BB:CC:DD:EE:FF",
      "dst_mac": "11:22:33:44:55:66",
      "src_ip": "192.168.1.42",
      "dst_ip": "142.250.185.14",
      "protocol": "TCP",
      "src_port": 52341,
      "dst_port": 443,
      "packet_length": 1460,
      "tcp_flags": "PA",
      "direction": "outbound"
    }
  ]
}
```

Use the project's existing JSON conventions if they differ.

---

# 20. Do NOT Rewrite the Entire File for Every Packet

Packet capture can generate a large number of observations.

Do not implement:

```python
load_json()
append_packet()
write_entire_json()
```

for every packet.

That would create unnecessary disk I/O.

Instead use a buffered writer.

Conceptually:

```text
Packet
   ↓
Metadata extraction
   ↓
In-memory buffer
   ↓
Periodic flush
   ↓
Daily JSON file
```

The exact buffer size/flush interval should be chosen based on the existing client architecture.

The first implementation should prioritize correctness over aggressive optimization.

---

# 21. Crash Safety

The storage mechanism should minimize data loss if the client crashes.

At minimum:

- flush observations periodically
- flush remaining observations when the observer stops
- safely create the daily file
- avoid corrupting the JSON file when writing

If the existing project already has an atomic JSON-writing utility, reuse it.

If not, implement safe writes consistent with the existing storage architecture.

---

# 22. Day Rotation

The observer must automatically use the correct daily file.

For example:

```text
Before midnight:

storage/passive_packets/2026-09-02.json

After midnight:

storage/passive_packets/2026-09-03.json
```

Do not require restarting the client at midnight.

When a new observation belongs to a new calendar day:

1. flush the previous day's buffer
2. close/finish the previous day's file
3. initialize the new day's file
4. continue collecting

---

# 23. Storage Volume

Do not prematurely optimize by converting observations into flows.

For V1, the requirement is:

> Store individual packet observations.

We want to inspect the real-world dataset first.

After deployment we will determine:

- packets per minute
- packets per hour
- packets per day
- file sizes
- protocol distribution
- useful fields
- redundant fields
- whether raw packet-level observations are sustainable

Only after observing real data should we decide whether to introduce:

- flow aggregation
- sampling
- time windows
- compression
- retention limits
- feature aggregation

Do not implement these in V1 unless required for basic stability.

---

# 24. Logging

Add concise operational logs.

Examples:

```text
[PACKET_OBSERVER] Starting
[PACKET_OBSERVER] Capture interface: Ethernet
[PACKET_OBSERVER] Started
```

Periodically log aggregate statistics, not individual packets.

For example:

```text
[PACKET_OBSERVER] Observed=12482 Stored=12482 TCP=7120 UDP=4210 DHCP=12 mDNS=84 Other=1056
```

Do not print every packet to the console.

The observer must not flood the client's logs.

When stopping:

```text
[PACKET_OBSERVER] Stopping
[PACKET_OBSERVER] Flushed 183 observations
[PACKET_OBSERVER] Stopped
```

---

# 25. Statistics

Maintain simple runtime counters.

For example:

```text
total_observed
total_stored
tcp_count
udp_count
icmp_count
arp_count
dhcp_count
dns_count
mdns_count
llmnr_count
nbns_count
ssdp_count
other_count
```

These counters are for diagnostics only.

Do not send them to the server in V1.

---

# 26. Error Handling

The packet observer must never crash the client.

Handle gracefully:

- interface unavailable
- permission denied
- Scapy capture errors
- malformed packets
- unsupported packets
- invalid addresses
- JSON storage errors
- disk errors

A malformed packet should be skipped rather than terminating the observer.

Example:

```text
[PACKET_OBSERVER] Failed to parse packet: ...
```

Then continue capturing.

---

# 27. Permissions

Packet capture may require elevated privileges depending on the operating system and capture backend.

Do not silently assume that capture will always work.

If capture permission is unavailable:

```text
[PACKET_OBSERVER] Packet capture unavailable: permission denied
```

The rest of the client must continue operating normally.

The new feature is an additional telemetry capability and must not prevent:

- client registration
- existing passive listeners
- neighborhood collection
- server communication

from functioning.

---

# 28. Existing Client Lifecycle

Integrate the packet observer into the current client lifecycle.

The final conceptual lifecycle should be:

```text
Client starts
     ↓
Existing initialization
     ↓
Network/interface detection
     ↓
Existing listeners start
     ↓
Packet observer starts
     ↓
Normal client operation
     ↓
Packets are observed
     ↓
Metadata is stored locally
```

On shutdown:

```text
Client shutdown
     ↓
Stop packet observer
     ↓
Flush pending observations
     ↓
Close storage
     ↓
Continue normal shutdown
```

Do not tie packet observation to the existing `FORBIDDEN_PROCESSES` message unless inspection of the current architecture shows that this is necessary.

The packet observer should start as part of the client's normal network telemetry lifecycle.

---

# 29. No Server Integration

This requirement is strict for V1.

The packet observations must NOT be:

- sent during client registration
- sent during neighborhood synchronization
- sent in response to `GET_NETWORK_NEIGHBOURHOOD`
- sent in response to `GET_PASSIVE_NEIGHBOURHOOD`
- uploaded automatically
- added to server network-scan storage
- added to passive-neighborhood server storage

The data remains entirely local.

The only purpose of this version is to collect data for later analysis.

---

# 30. Do Not Mix Packet Telemetry With Passive Neighborhood Storage

The project already has a passive-neighborhood storage system.

Do not put the new packet observations into:

```text
passive_neighborhood
```

Those two datasets have different purposes.

### Passive neighborhood

Answers:

> What devices/services have been observed?

### Passive packet telemetry

Answers:

> What network packets were observable from this client?

Keep them separate.

Conceptually:

```text
storage/
├── network_neighbourhood/
├── passive_neighborhood/
└── passive_packets/
```

---

# 31. Relationship With Existing Device Discovery

The packet observations may contain IP/MAC information corresponding to devices already known by the application.

However, V1 should NOT attempt to merge every packet into the device database.

Do not modify the existing device records automatically.

Simply record the observations.

Later, the server/data-processing layer can correlate:

```text
packet.src_mac
packet.src_ip
        ↓
known device
        ↓
device_id
```

That is intentionally outside this implementation.

---

# 32. Future ML Use Case

The collected data is intended to eventually support another team's ML work.

The future architecture may become:

```text
Client
   ↓
Passive packet telemetry
   ↓
Daily dataset
   ↓
Data processing
   ↓
Feature engineering
   ↓
ML training
   ↓
Threat / activity model
```

The model might eventually use features such as:

```text
packet frequency
packet size
protocol distribution
destination diversity
port diversity
connection frequency
connection duration
traffic timing
DNS behavior
TCP behavior
internal vs external communication
normal vs unusual activity patterns
```

But the current implementation must NOT assume a particular model.

The data collection layer should remain model-agnostic.

---

# 33. Important Security/Privacy Principle

The goal is behavioral/network telemetry, not content surveillance.

Therefore:

```text
STORE:
    packet metadata
    protocol metadata
    addresses
    ports
    lengths
    timestamps
    flags
    observable protocol fields

DO NOT STORE:
    packet payloads
    credentials
    message contents
    files
    application bodies
```

This also makes the dataset more appropriate for future ML processing.

---

# 34. Testing Requirements

Before considering the feature complete, test it on a development machine.

### Test 1 — Startup

Confirm:

```text
client starts
packet observer starts
existing client features still work
```

### Test 2 — File creation

Confirm that:

```text
storage/passive_packets/YYYY-MM-DD.json
```

is created.

### Test 3 — Packet observation

Generate ordinary traffic:

- browse a website
- ping another device
- resolve a DNS name
- trigger mDNS activity if available
- trigger DHCP activity if possible

Verify that packet observations appear in the JSON file.

### Test 4 — Protocol parsing

Verify that TCP and UDP observations contain:

```text
src_port
dst_port
```

and TCP observations contain:

```text
tcp_flags
```

Verify that protocols without ports do not contain fabricated port values.

### Test 5 — Existing DHCP

Verify that the existing DHCP listener still works.

### Test 6 — Existing passive discovery

Verify that:

- mDNS
- LLMNR
- NBNS
- SSDP

continue functioning if they are currently implemented.

### Test 7 — Restart

Stop and restart the client.

Verify:

- existing JSON data remains
- new observations are appended
- the file is not corrupted

### Test 8 — Day rotation

Test the storage logic with a simulated date transition if practical.

Verify that a new daily file is created.

### Test 9 — Capture failure

Run without sufficient capture permissions if applicable.

Verify:

```text
packet observer fails gracefully
client continues running
```

### Test 10 — High traffic

Generate a reasonable amount of traffic and verify:

- client remains responsive
- memory does not continuously grow without bound
- buffers flush correctly
- JSON remains valid

---

# 35. Data Validation

After implementation, inspect an actual generated daily file.

We want to answer:

1. What protocols are actually being observed?
2. How many observations are generated?
3. How large is the JSON file?
4. Which fields are populated?
5. Which fields are frequently null?
6. Are source/destination addresses available?
7. Are ports available?
8. Can direction be determined?
9. How much DHCP traffic is visible?
10. How much mDNS/LLMNR/NBNS/SSDP traffic is visible?
11. What percentage is TCP/UDP/ICMP/etc.?
12. Are malformed packets being encountered?

Do not modify the design based on assumptions before seeing real data.

---

# 36. Code Quality Requirements

Follow the existing project conventions.

Do not introduce:

- unnecessary dependencies
- a second packet-capture framework
- duplicate network-interface detection
- duplicate MAC normalization
- duplicate logging infrastructure
- duplicate storage utilities

Reuse existing utilities where appropriate.

Keep responsibilities separated:

```text
Packet capture
      ↓
Packet parsing
      ↓
Normalization
      ↓
Storage
```

Avoid putting everything into one giant class/function.

---

# 37. Suggested Internal Architecture

A clean conceptual design is:

```text
PacketObserver
    │
    ├── capture
    │
    ▼
PacketMetadataExtractor
    │
    ├── generic metadata
    ├── TCP metadata
    ├── UDP metadata
    ├── DHCP metadata
    ├── DNS metadata
    ├── mDNS metadata
    ├── LLMNR metadata
    ├── NBNS metadata
    └── SSDP metadata
    │
    ▼
PacketObservation
    │
    ▼
DailyPacketStorage
    │
    ├── current day
    ├── buffer
    ├── flush
    └── rotation
```

Do not necessarily create exactly these classes if the existing architecture suggests simpler functions/modules.

The separation of responsibilities is what matters.

---

# 38. Example Final Observation

A normal TCP packet might produce:

```json
{
  "timestamp": "2026-09-02T13:42:18.381Z",
  "observer_client_id": "client-17",
  "interface": "Ethernet",
  "src_mac": "AA:BB:CC:DD:EE:FF",
  "dst_mac": "11:22:33:44:55:66",
  "src_ip": "192.168.1.42",
  "dst_ip": "142.250.185.14",
  "protocol": "TCP",
  "src_port": 52341,
  "dst_port": 443,
  "packet_length": 1460,
  "tcp_flags": "PA",
  "direction": "outbound"
}
```

A DHCP request might produce:

```json
{
  "timestamp": "2026-09-02T13:44:01.120Z",
  "observer_client_id": "client-17",
  "interface": "Ethernet",
  "src_mac": "E4:FD:45:BA:8B:96",
  "dst_mac": "FF:FF:FF:FF:FF:FF",
  "src_ip": "0.0.0.0",
  "dst_ip": "255.255.255.255",
  "protocol": "DHCP",
  "src_port": 68,
  "dst_port": 67,
  "packet_length": 342,
  "direction": "outbound",
  "protocol_metadata": {
    "message_type": "REQUEST",
    "requested_ip": "172.16.0.102",
    "hostname": "DESKTOP-DJP05CM",
    "vendor_class": "MSFT 5.0"
  }
}
```

These are examples only. Use the actual values available from the captured packet.

---

# 39. Definition of Done

The feature is complete when:

- [ ] Existing client code has been audited for all current network listeners.
- [ ] Existing DHCP listener continues functioning.
- [ ] Existing mDNS listener continues functioning if present.
- [ ] Existing LLMNR listener continues functioning if present.
- [ ] Existing NBNS listener continues functioning if present.
- [ ] Existing SSDP listener continues functioning if present.
- [ ] A new generic packet observer exists.
- [ ] The observer captures packets visible to the client.
- [ ] Raw packet payloads are NOT stored.
- [ ] Packet metadata is normalized.
- [ ] TCP/UDP ports are captured where available.
- [ ] TCP flags are captured where available.
- [ ] Packet length is captured.
- [ ] Source/destination MAC addresses are captured where available.
- [ ] Source/destination IP addresses are captured where available.
- [ ] Timestamp is recorded.
- [ ] Observer client ID is recorded.
- [ ] Interface is recorded.
- [ ] Direction is recorded only when determinable.
- [ ] Protocol-specific metadata can be recorded.
- [ ] Daily JSON files are created.
- [ ] Observations remain local.
- [ ] Nothing is transmitted to the server.
- [ ] Buffered writes are used.
- [ ] Storage survives client restart.
- [ ] Daily rotation works.
- [ ] Capture failures do not crash the client.
- [ ] Logging is concise and useful.
- [ ] Runtime statistics are available for diagnostics.
- [ ] A real generated daily JSON file has been inspected.

---

# 40. IMPORTANT: Implementation Strategy

Do NOT immediately modify many files.

Follow this sequence:

## Step 1

Inspect the repository and identify:

- client entry point
- existing listeners
- network utilities
- storage utilities
- logging utilities
- client ID mechanism
- interface detection
- shutdown mechanism

## Step 2

Explain briefly which existing components will be reused.

## Step 3

Implement the packet observation/storage modules.

## Step 4

Run unit/local tests for packet parsing and storage.

## Step 5

Integrate the observer into the client lifecycle.

## Step 6

Run the client and generate real network traffic.

## Step 7

Inspect the generated daily JSON.

## Step 8

Fix any issues found.

## Step 9

Run the complete existing client test suite/build.

## Step 10

Report exactly:

```text
Files changed:
...

Files added:
...

Existing functionality verified:
...

Packet protocols observed:
...

Storage location:
...

Example observation:
...

Tests:
...

Known limitations:
...
```

---

# Final Requirement

The most important goal of this feature is:

> **Collect high-quality, structured, locally stored observations of the network traffic that each client can actually see, without sending anything to the server and without storing raw packet payloads.**

Do not implement ML.

Do not implement threat detection.

Do not implement activity classification.

Do not implement server integration.

The resulting daily JSON datasets will later be provided to another team so they can determine how to engineer features and train their models.
