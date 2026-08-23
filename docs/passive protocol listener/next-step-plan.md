# Unified Passive Network Discovery Scanner — Implementation Plan & Guidelines

> **Architectural Objective:** Transform the scanner from a collection of isolated packet listeners into a **unified device-enrichment engine**. Treat DHCP, mDNS, SSDP, LLMNR, NBNS, and ARP not as independent tools, but as concurrent evidence sources that progressively enrich a single device record.

---

# Phase 0 — Inspect the Existing Implementation

Before modifying anything, inspect the entire existing scanner implementation.

Identify:

1. Current passive scanner entry point.
2. Existing protocol listeners.
3. DHCP scanner implementation.
4. ARP scanner implementation.
5. Vendor/OUI lookup implementation.
6. Hostname resolution implementation.
7. Existing device data model.
8. Existing server/API payload format.
9. Existing deduplication logic, if any.
10. Existing timestamps.
11. Existing background/thread/async architecture.
12. How the scanner is started and stopped.
13. How the scanner interacts with the Windows client agent/service.
14. Any existing logging/error-handling mechanism.

Do not immediately rewrite everything. First understand the existing architecture and identify which components can be reused. Produce a short internal architecture summary before making changes.

---

# Phase 1 — Define the Unified Observation Model

Create a normalized internal observation/device model. The scanner should distinguish between:

### Device Identity

* MAC address
* IPv4 addresses
* IPv6 addresses
* Hostname
* Vendor
* Device type
* Model
* Operating system hint
* Software/product hint

### Network Information

* Protocol
* Source IP
* Destination IP
* Source port
* Destination port
* Service type
* Service name
* Protocol-specific fields

### Temporal Information

* `first_seen`
* `last_seen`
* `seen_count`
* `observation_count`
* `last_protocol`
* `protocols_seen`

### Evidence Tracking

Every piece of enrichment should indicate where it came from.

```json
{
    "mac_address": "AA:BB:CC:DD:EE:FF",
    "hostname": "DESKTOP-ABC123",
    "vendor": "Intel Corporate",
    "os_hint": "Windows",
    "model_hint": null,

    "first_seen": "2026-08-22T10:00:00Z",
    "last_seen": "2026-08-22T10:12:32Z",
    "seen_count": 17,

    "evidence": {
        "hostname": ["dhcp", "llmnr", "nbns"],
        "vendor": ["oui"],
        "os_hint": ["dhcp_option_55", "mdns", "ssdp"],
        "model_hint": ["mdns"]
    },

    "protocols_seen": [
        "dhcp",
        "mdns",
        "llmnr"
    ]
}

```

Do not blindly overwrite existing information. If one protocol provides better evidence than another, preserve both.

---

# Phase 2 — Integrate DHCP Into the Passive Scanner

Move the existing DHCP functionality into the unified passive scanner architecture. The DHCP listener should run concurrently with:

* mDNS
* SSDP
* LLMNR
* NBNS
* Existing passive listeners

Do not create a second independent scanner process.

```text
                Unified Passive Scanner
                         |
        +----------------+----------------+
        |                |                |
       DHCP             mDNS             SSDP
        |                |                |
      LLMNR             NBNS        Other protocols
        |                |                |
        +----------------+----------------+
                         |
                 Observation Engine
                         |
                  Device Correlator
                         |
                 Deduplication Layer
                         |
                  Enriched Device
                         |
                  Server/API Output

```

---

# Phase 3 — DHCP Information Extraction

Extract as much useful information as safely and reliably available from DHCP packets.

### DHCP Identity

* Client MAC / `chaddr`
* Transaction ID
* DHCP message type
* Client identifier
* Hostname / Option 12
* Vendor class identifier / Option 60
* Parameter request list / Option 55

### Network Information

* Requested IP
* Assigned IP
* Server identifier
* Subnet mask
* Router/gateway
* DNS servers
* Lease duration
* Renewal/rebinding information when available

### Additional Options

Parse DHCP options generically instead of hardcoding only a few options. Store unknown options rather than discarding them.

```json
{
    "protocol": "dhcp",
    "mac_address": "AA:BB:CC:DD:EE:FF",
    "ip_address": "172.16.2.50",

    "raw_fields": {
        "hostname": "DESKTOP-ABC",
        "vendor_class": "MSFT 5.0",
        "parameter_request_list": [
            1, 3, 6, 15, 31, 33, 43, 44, 46, 47
        ]
    }
}

```

---

# Phase 4 — DHCP Fingerprinting

Use DHCP information as **evidence**, not absolute truth. Implement OS/device hints based on combinations of:

* Vendor Class Identifier
* Parameter Request List
* Hostname patterns
* Client Identifier
* DHCP behavior

```text
MSFT 5.0 + Windows-style hostname + Windows-like Option 55 = strong Windows evidence

```

Do NOT assign 100% confidence simply because a single DHCP field contains a recognizable value. Create confidence levels (`low`, `medium`, `high`) or numeric metrics (`0.0 - 1.0`).

```json
{
    "os_hint": "Windows",
    "confidence": 0.95,
    "evidence": [
        "dhcp.vendor_class",
        "dhcp.parameter_request_list",
        "llmnr"
    ]
}

```

---

# Phase 5 — Integrate DHCP With Existing Device Correlation

DHCP observations must be merged with observations from mDNS, SSDP, LLMNR, NBNS, ARP, and OUI/vendor lookups.

The primary correlation key should normally be **MAC address**. When MAC is unavailable, use a weaker combination such as **IP + Hostname**, marking correlation confidence explicitly.

```text
DHCP:   AA:BB:CC:DD:EE:FF -> 172.16.2.20 -> DESKTOP-ABC
mDNS:   AA:BB:CC:DD:EE:FF -> DESKTOP-ABC.local
LLMNR:  AA:BB:CC:DD:EE:FF -> DESKTOP-ABC
SSDP:   172.16.2.20       -> Windows/10.0.x

Result -> Merged into one single device record.

```

---

# Phase 6 — Implement First Seen / Last Seen

Every device should maintain `first_seen`, `last_seen`, and `seen_count`.

* **`first_seen`:** Set only when the device is observed for the first time. Never update it afterward.
* **`last_seen`:** Update whenever a valid observation is received from that device.

```json
{
    "first_seen": "11:00:01",
    "last_seen": "11:07:52",
    "seen_count": 4
}

```

---

# Phase 7 — Define What "Seen" Means

Do not update `last_seen` merely because an identical packet is repeatedly received if duplicate suppression is active.

Distinguish between:

* **Observation received:** Packet/event captured.
* **Device activity:** Meaningful event received.
* **Duplicate packet:** Same protocol + same source + same payload within a short window.

Update `last_seen` when appropriate, but avoid sending every repeated packet over the network to the server.

---

# Phase 8 — Implement Local Deduplication

Maintain an in-memory observation cache:

```python
devices = {
    mac_address: DeviceObservation(...)
}

```

For every observation:

1. Identify the device.
2. Check whether the device already exists.
3. Create it if it does not.
4. Update `last_seen`.
5. Increment `seen_count`.
6. Merge new information.
7. Preserve existing information.
8. Record the protocol that produced the evidence.
9. Suppress redundant network transmissions (5-minute initial default window).

---

# Phase 9 — Merge Enrichment Intelligently

Never overwrite hostnames or attributes blindly. Implement a structured priority and aggregation strategy.

```text
DHCP hostname -> mDNS hostname -> LLMNR hostname -> NBNS hostname -> Merge -> Best Hostname

```

If conflicting information appears (e.g., DHCP says `DESKTOP-123`, mDNS says `MacBook-Pro.local`), store both under `hostname_sources` and allow the classification layer to evaluate the evidence.

---

# Phase 10 — Expand mDNS Enrichment

Parse standard records (`A`, `AAAA`, `PTR`, `SRV`, `TXT`) and extract key-value pairs from `TXT` fields.

Store both standard and vendor-specific fields (e.g., `model`, `osxvers`, `deviceid`, `features`).

```json
{
    "service_type": "_device-info._tcp.local",
    "raw_fields": {
        "model": "MacBookPro16,2",
        "osxvers": "25",
        "ecolor": "157,157,160"
    }
}

```

---

# Phase 11 — Preserve Software / Service Indicators

Record local discovery service types (e.g., `_spotify-connect._tcp.local`, `_airplay._tcp.local`, `_adb._tcp.local`, `_dosvc._tcp.local`).

> **Note:** Treat these as service/application indicators, **not** as web browsing activity or proof of active user consumption.

---

# Phase 12 — SSDP Enrichment

Extract `SERVER`, `LOCATION`, `USN`, `NT`, `NTS`, `ST`, `CACHE-CONTROL`, `HOST`, device/service types, and UUIDs. Use `SERVER` strings (e.g., `"Windows/10.0 UPnP/1.1 uTorrent"`) strictly as OS/software evidence.

---

# Phase 13 — LLMNR/NBNS Enrichment

Extract queried hostnames, source/destination IPs, query types, NetBIOS names, and domain/workgroup information to enrich Windows detection and local network identity.

---

# Phase 14 — ARP Integration

Integrate ARP information to strengthen `IPv4 <-> MAC` correlation.

```json
{
    "mac_address": "AA:BB:CC:DD:EE:FF",
    "ipv4_addresses": ["172.16.2.20"],
    "sources": {
        "172.16.2.20": ["dhcp", "arp", "mdns"]
    }
}

```

Do not create duplicate device entries when an IP address changes for a known MAC address.

---

# Phase 15 — Vendor Enrichment

Normalize MAC addresses before running OUI lookups (`22:57:79:E7:02:A1` vs `225779E702A1`).

> **Note:** OUI identifies the hardware vendor prefix, not necessarily the specific device model.

---

# Phase 16 — Device Classification Engine

Decouple parsing from classification:

* **Parser:** Answers *"What did we observe?"*
* **Classifier:** Answers *"What does this probably mean?"*

Combine indicators across layers (e.g., DHCP `MSFT 5.0` + LLMNR + NBNS + `_dosvc` mDNS = Windows Workstation with high confidence).

---

# Phase 17 — Confidence-Based Enrichment

Assign explicit structure to inferred attributes:

```json
{
    "device_type": {
        "value": "Windows workstation",
        "confidence": 0.97,
        "evidence": [
            "dhcp.vendor_class",
            "llmnr",
            "nbns",
            "mdns.dosvc",
            "ssdp.server"
        ]
    }
}

```

---

# Phase 18 — Temporal Activity Tracking

Track `first_seen`, `last_seen`, `seen_count`, `observation_frequency`, and `protocols_seen`.

`last_seen` indicates when passive network activity was last observed. Silence does not guarantee a device is disconnected or offline.

---

# Phase 19 — Presence State

Define derived presence states:

* `PASSIVELY_ACTIVE`: Observed within 15 minutes.
* `PASSIVELY_IDLE`: 15–60 minutes.
* `PASSIVELY_STALE`: 1–24 hours.
* `NOT_RECENTLY_OBSERVED`: >24 hours.

If active ARP checks exist, complement this with an `ARP_REACHABLE` flag.

---

# Phase 20 — Unified JSON Payload

Format the complete device update into a normalized payload:

```json
{
    "client_id": "client-e4fd45ba8b96",
    "reporter_mac": "E4:FD:45:BA:8B:96",
    "observed_at": "2026-08-22T12:50:46.255103Z",
    "observations": [
        {
            "mac_address": "22:57:79:E7:02:A1",
            "ip_addresses": ["172.16.2.126"],
            "ipv6_addresses": ["fe80::1c75:504b:bd57:d408"],
            "hostname": "MacBook-Pro-de-Hazar.local",
            "vendor": "Apple, Inc.",
            "device_type": "MacBook",
            "os_hint": "macOS",
            "model_hint": "MacBookPro16,2",
            "protocols_seen": ["mdns"],
            "services": [
                "_device-info._tcp.local",
                "_airplay._tcp.local"
            ],
            "first_seen": "2026-08-22T11:48:46Z",
            "last_seen": "2026-08-22T11:50:21Z",
            "seen_count": 3,
            "evidence": {
                "model": ["mdns"],
                "os_hint": ["mdns"],
                "hostname": ["mdns"]
            },
            "raw_fields": {
                "model": "MacBookPro16,2",
                "osxvers": "25",
                "ecolor": "157,157,160"
            }
        }
    ]
}

```

---

# Phase 21 — Server API Compatibility

Inspect backend requirements before changing schemas. Extend existing schemas cleanly to maintain backward compatibility for existing client agents.

---

# Phase 22 — Concurrency

Run discovery protocols concurrently (using `asyncio`, threads, or background workers) without blocking the primary agent.

---

# Phase 23 — Graceful Shutdown

Ensure clean teardown on service termination:

1. Stop listeners.
2. Leave multicast groups cleanly.
3. Close all open sockets.
4. Terminate background workers.
5. Flush pending deduplicated observations.

---

# Phase 24 — Logging

Implement structured logs for startup, listener initialization, observation ingestion, correlation, deduplication events, and shutdown. Use `DEBUG` for raw packet payloads.

---

# Phase 25 — Testing

Build targeted unit tests covering packet parsing (DHCP, mDNS, SSDP), correlation merging (verifying multi-protocol aggregation onto single MAC keys), deduplication, and timestamp maintenance (`first_seen` immutability).

---

# Phase 26 — Integration Testing

Validate end-to-end traffic ingestion across real hardware (Windows PCs, mobile devices, smart TVs, printers) to verify zero data loss from raw packet capture down to server persistence.

---

# Phase 27 — Compare Against Existing DHCP Scanner

Run both scanners side-by-side on test networks. Verify identical or superior DHCP field extraction in the unified engine before deprecating the old scanner codebase.

---

# Phase 28 — Performance Testing

Profile CPU, memory, socket overhead, and payload sizes under standard workload scaling (10, 25, 50, and 100 concurrent network devices).

---

# Phase 29 — Final Architecture

```text
                         Windows Client Agent
                                |
                                v
                  +---------------------------+
                  | Unified Passive Scanner   |
                  +---------------------------+
                     |       |       |       |
                     v       v       v       v
                   DHCP    mDNS    SSDP   LLMNR/NBNS
                     |       |       |       |
                     +-------+-------+-------+
                             |
                             v
                  +---------------------------+
                  | Observation Normalizer    |
                  +---------------------------+
                             |
                             v
                  +---------------------------+
                  | Device Correlation Engine |
                  +---------------------------+
                             |
                             v
                  +---------------------------+
                  | Local Deduplication       |
                  | first_seen                |
                  | last_seen                 |
                  | seen_count                |
                  +---------------------------+
                             |
                             v
                  +---------------------------+
                  | Classification Engine     |
                  | OS                        |
                  | Device Type               |
                  | Model                     |
                  | Vendor                    |
                  | Services                  |
                  +---------------------------+
                             |
                             v
                  +---------------------------+
                  | Normalized JSON           |
                  +---------------------------+
                             |
                             v
                  +---------------------------+
                  | Central Server            |
                  +---------------------------+

```

---

# Core Architectural Rules

1. **Passive Means Passive:** Never trigger active port scans, HTTP requests, or connection attempts unless explicitly configured as a separate opt-in active discovery module.
2. **Service Discovery $\neq$ Browsing:** Protocol strings like `_spotify-connect._tcp.local` or `uTorrent` signify network service announcements, not web browsing or visited URLs.
3. **Silence $\neq$ Offline:** Lack of recent traffic indicates an absence of observable passive activity, not definitive network disconnection.
4. **Preserve Evidence:** Retain `protocol`, `field`, `value`, `timestamp`, and `confidence` metadata alongside raw records for downstream engine updates.

---

# Core Target State Summary

When processing sequential packet captures:

```text
DHCP Observation:
MAC: 192.168.1.20 | Hostname: DESKTOP-X | Vendor Class: MSFT 5.0

mDNS Observation (subsequent):
MAC: 192.168.1.20 | Hostname: DESKTOP-X.local | Service: _dosvc._tcp.local

```

The output must result in **one progressively enriched device record**:

```text
Device Record
├── first_seen: 10:02:00
├── last_seen: 14:37:00
├── seen_count: 184
├── protocols_seen: [DHCP, mDNS, LLMNR, NBNS]
├── IP Addresses: [192.168.1.20]
├── MAC: AA:BB:CC:DD:EE:FF
├── Hostname: DESKTOP-X
├── Vendor: Microsoft Corporation
├── OS Hint: Windows
├── Model: Workstation
└── Services: [_dosvc._tcp.local]

```