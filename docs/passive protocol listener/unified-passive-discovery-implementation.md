# Unified Passive Network Discovery Scanner — Implementation Report

> **Architectural Objective:** Transform the passive scanner from a collection of isolated packet listeners into a **unified device-enrichment engine**. Treat DHCP, mDNS, SSDP, LLMNR, NBNS, and ARP not as independent tools, but as concurrent evidence sources that progressively enrich a single device record.

---

## Executive Summary

The network scanner client has been upgraded from independent, disconnected listeners into a **unified discovery and device correlation engine**. 

Previously, DHCP listening was isolated from multicast/broadcast discovery protocols (mDNS, SSDP, LLMNR, NBNS), and observations were either stored in isolated daily files or buffered as disconnected raw packets.

With the completion of this implementation:
1. **Single-Process Capture Pipeline:** A unified capture worker sniffs UDP ports `67`, `68`, `137`, `1900`, `5353`, and `5355` concurrently.
2. **Unified Observation Model:** A rich `DeviceRecord` structure aggregates identity, network addresses, services, raw attributes, evidence sources, and temporal presence.
3. **Multi-Protocol Correlation Engine:** The `DeviceCorrelator` maps multi-protocol events to single device records using MAC address as the primary key and IPv4/IPv6 address as the fallback key.
4. **Intelligent Device Fingerprinting & Synergy:** A dedicated fingerprinting engine evaluates DHCP Option 55 (Parameter Request List) & Option 60 (Vendor Class), mDNS TXT records & service announcements, SSDP `SERVER` headers, and hostname heuristics, scoring confidence and combining cross-protocol indicators.
5. **Presence Tracking:** Derives real-time presence states (`PASSIVELY_ACTIVE`, `PASSIVELY_IDLE`, `PASSIVELY_STALE`, `NOT_RECENTLY_OBSERVED`) and tracks immutable `first_seen` timestamps alongside updated `last_seen` and `seen_count` metrics.
6. **Full Test Suite & Backward Compatibility:** 100% test pass rate across both client and server test suites (145 total unit tests).

---

## Architecture Diagram

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
                      | first_seen (immutable)   |
                      | last_seen (monotonic)     |
                      | seen_count                |
                      +---------------------------+
                                 |
                                 v
                      +---------------------------+
                      | Classification Engine     |
                      | OS & Confidence Rating    |
                      | Device Type & Model       |
                      | Vendor & Service History  |
                      +---------------------------+
                                 |
                                 v
                      +---------------------------+
                      | Unified JSON / REST API   |
                      +---------------------------+
                                 |
                                 v
                      +---------------------------+
                      | Central Server Storage    |
                      +---------------------------+
```

---

## Detailed Implementation Breakdown

### 1. Phase 0 — Existing Implementation Inspection
Inspected all existing scanner components across client and server:
* Entry points: `PassiveProtocolListener` in `client/passive_protocol_listener.py`, `DHCPListener` in `client/dhcp_listener.py`, and `NetworkNeighbourCollector` in `client/network_neighbour_collector.py`.
* Database tables: `network_devices`, `network_device_observations`, `daily_network_scan_files`.
* Server API endpoints: `POST /api/v1/clients/{client_id}/passive-neighbourhood` and `POST /api/v1/clients/{client_id}/network-neighbourhood`.
* Identified reuse opportunities and designed backwards-compatible integration paths.

### 2. Phase 1 — Unified Observation & Device Model
Created `client/device_model.py`:
* **`DeviceRecord`:** Encapsulates complete device state:
  * **Identity:** `mac_address`, `ip_addresses` (IPv4 list), `ipv6_addresses` (IPv6 list), `hostname`, `vendor`, `device_type`, `model_hint`, `os_hint`, `software_hint`.
  * **Classifications with Confidence:** `os_classification`, `device_type_classification`, `model_classification` (each tracking `value`, `confidence: 0.0 - 1.0`, and `evidence: list[str]`).
  * **Evidence Tracking:** Explicit mapping of which protocols provided which fields (`hostname`, `vendor`, `os_hint`, `model_hint`, `device_type`).
  * **Temporal Metrics:** `first_seen` (strictly immutable once set), `last_seen` (updated on valid observation), `seen_count` (incremented monotonically), `observation_count`.
  * **Services & Raw Fields:** Retains announced mDNS service types (e.g. `_airplay._tcp.local`, `_dosvc._tcp.local`) and parsed raw fields (`dhcp` options, `mdns_txt` records).
* **`DeviceCorrelator`:** In-memory, thread-safe cache indexing devices by normalized MAC address and secondary IP index with LRU-style bounded eviction (default 1024 devices).

### 3. Phase 2 — Concurrent Passive Scanner Integration
Updated `client/passive_protocol_listener.py`:
* Replaced isolated capture loops with a single concurrent BPF filter:
  ```text
  udp and (port 67 or port 68 or port 137 or port 1900 or port 5353 or port 5355)
  ```
* Supports all 5 protocols: `dhcp`, `mdns`, `llmnr`, `nbns`, `ssdp`.
* `process_packet` dispatches directly to protocol parsers, updating the raw observation buffer and feeding the `DeviceCorrelator`.

### 4. Phase 3 & 4 — DHCP Extraction & Fingerprinting Engine
Enhanced `client/dhcp_listener.py` and built `client/fingerprinting.py`:
* **Generic Option Parser:** Parses Option 53 (Message Type), Option 50 (Requested IP), Option 12 (Hostname), Option 60 (Vendor Class Identifier), Option 55 (Parameter Request List), Option 61 (Client ID), Subnet Mask (1), Routers (3), DNS Servers (6), Domain Name (15), Broadcast (28), Lease Time (51), and Server ID (54).
* **Fingerprint Signatures:**
  * **Windows Workstations:** Option 60 starting with `MSFT 5.0` + Windows Option 55 PRL `{1, 3, 6, 15, 31, 43}` $\to$ Windows Workstation ($\ge 0.95$ confidence).
  * **Android Devices:** `android-dhcp-*` + Android Option 55 PRL `{1, 3, 6, 15, 26, 28, 51, 58, 59, 43}` $\to$ Android Mobile Device ($\ge 0.95$ confidence).
  * **Apple Devices:** Option 55 PRL `{1, 3, 6, 15, 119, 252}` $\to$ Apple Device ($\ge 0.85$ confidence).
  * **Printers & Network Gear:** `hp-jetdirect`, `cisco`, `printer` detection.

### 5. Phase 5, 8, 9 — Device Correlation & Intelligent Merging
* **MAC Address Primary Key:** Multiple observations with the same MAC address merge into one progressively enriched device.
* **Secondary IP Fallback:** If an observation lacks a MAC (e.g. SSDP query), it correlates by IP and updates the MAC once DHCP or ARP reports it.
* **Priority Hostname Hierarchy:**
  ```text
  DHCP Hostname (Priority 40) > mDNS Hostname (Priority 30) > LLMNR (Priority 20) > NBNS (Priority 10) > Reverse DNS (Priority 5)
  ```
* Cleaner, higher-priority hostnames are retained without losing evidence tags from lower-priority protocols.

### 6. Phase 10 to 13 — Protocol Enrichment Expansions
* **mDNS (`5353`):** Parses PTR, SRV, TXT, A, AAAA. Extracts Apple `model` (e.g. `MacBookPro16,2` $\to$ MacBook, macOS), `osxvers`, and service indicators.
* **SSDP (`1900`):** Parses `SERVER` strings (e.g. `Windows/10.0 UPnP/1.1`, `Linux/4.x`, `Roku`, `Sonos`) and URNs without active HTTP fetches.
* **LLMNR (`5355`) & NBNS (`137`):** Extracts query and response hostnames, NetBIOS name suffixes, and flags.

### 7. Phase 14 & 15 — ARP & Vendor (OUI) Lookups
* Normalized MAC addresses match against IEEE database (`client/oui.py`) prioritizing specific prefixes: MA-S (36-bit) $\to$ MA-M (28-bit) $\to$ MA-L (24-bit OUI).
* Multicast/broadcast MAC addresses are strictly rejected (`FF:FF:FF:FF:FF:FF` or odd first octet).

### 8. Phase 16 & 17 — Classification & Cross-Protocol Synergy
`fingerprinting.py:apply_classification_to_device` evaluates combined evidence:
* If DHCP reports Windows `MSFT 5.0` AND mDNS reports `_dosvc._tcp.local` AND LLMNR is observed $\to$ Confidence boosts to `0.98`.
* If OUI reports Apple, Inc. AND mDNS reports `_airplay._tcp.local` $\to$ Apple Device hint with high confidence.

### 9. Phase 18 & 19 — Temporal Metrics & Presence States
`calculate_presence_state(last_seen)` calculates:
* `PASSIVELY_ACTIVE`: Observed within last 15 minutes.
* `PASSIVELY_IDLE`: 15 to 60 minutes since last observation.
* `PASSIVELY_STALE`: 1 to 24 hours since last observation.
* `NOT_RECENTLY_OBSERVED`: > 24 hours since last observation.

### 10. Phase 20 & 21 — Server API & Central Payload Compatibility
* `server/server_components/server_lib.py` updated to accept `"dhcp"` in addition to `"mdns"`, `"llmnr"`, `"nbns"`, and `"ssdp"`.
* Responses format into backward-compatible snapshots and rich device payloads.

---

## File Modifications & Additions

| File | Status | Description |
|---|---|---|
| [`client/device_model.py`](file:///home/adonis/network-scanner/client/device_model.py) | **Created** | Unified `DeviceRecord`, `DeviceCorrelator`, `EnrichedAttribute`, and presence state calculator. |
| [`client/fingerprinting.py`](file:///home/adonis/network-scanner/client/fingerprinting.py) | **Created** | Multi-protocol classification engine (DHCP PRL/Option 60, mDNS TXT, SSDP Server, Hostname heuristics). |
| [`client/dhcp_listener.py`](file:///home/adonis/network-scanner/client/dhcp_listener.py) | **Enhanced** | Generic DHCP options parsing (options 53, 50, 12, 60, 55, 61, 1, 3, 6, 15, 28, 51). |
| [`client/passive_protocol_listener.py`](file:///home/adonis/network-scanner/client/passive_protocol_listener.py) | **Enhanced** | Single unified capture worker for UDP 67, 68, 137, 1900, 5353, 5355 with integrated correlation engine. |
| [`client/client.py`](file:///home/adonis/network-scanner/client/client.py) | **Updated** | Wired unified discovery listener and callbacks into agent lifecycle. |
| [`server/server_components/server_lib.py`](file:///home/adonis/network-scanner/server/server_components/server_lib.py) | **Updated** | Added `dhcp` to accepted protocol validation set. |
| [`client/tests/test_device_model.py`](file:///home/adonis/network-scanner/client/tests/test_device_model.py) | **Created** | Comprehensive unit tests for device correlation, presence states, and temporal tracking. |
| [`client/tests/test_fingerprinting.py`](file:///home/adonis/network-scanner/client/tests/test_fingerprinting.py) | **Created** | Unit tests for DHCP, mDNS, SSDP, and synergy classification rules. |
| [`client/tests/test_passive_protocol_listener.py`](file:///home/adonis/network-scanner/client/tests/test_passive_protocol_listener.py) | **Updated** | Added multi-protocol capture and unified device correlation test cases. |
| [`server/tests/test_passive_protocol_requests.py`](file:///home/adonis/network-scanner/server/tests/test_passive_protocol_requests.py) | **Updated** | Ensured hermetic test execution with mocked storage snapshots. |

---

## Validation & Test Suite Results

All unit tests across the entire repository were executed and passed cleanly:

```text
======================================================================
Client Test Suite:
Ran 65 tests in 0.156s
OK (65/65 tests passed)

Covering:
- test_device_model.py
- test_fingerprinting.py
- test_passive_protocol_listener.py
- test_dhcp_parser.py
- test_neighbourhood.py
- test_network_neighbour_collector.py
- test_client_background_scan.py
- test_client_identity.py
======================================================================
Server Test Suite:
Ran 80 tests in 0.790s
OK (80/80 tests passed)

Covering:
- test_passive_protocol_requests.py
- test_api_endpoints.py
- test_client_registration.py
- test_connection_alerts.py
- test_disconnect_alerts.py
- test_network_device_storage.py
- test_network_discovery.py
======================================================================
Total: 145/145 Tests Passed (100% Success)
```

---

## Example Correlated Device Output

When the scanner observes sequential DHCP and mDNS traffic:

```json
{
  "mac_address": "E4:FD:45:BA:8B:96",
  "ip_addresses": ["172.16.2.50"],
  "ipv6_addresses": [],
  "hostname": "DESKTOP-DJP05CM",
  "vendor": "Intel Corporate",
  "device_type": "Windows Workstation",
  "model_hint": null,
  "os_hint": "Windows",
  "software_hint": null,
  "protocols_seen": ["dhcp", "mdns", "llmnr"],
  "services": ["_dosvc._tcp.local"],
  "first_seen": "2026-08-22T10:00:00+00:00",
  "last_seen": "2026-08-22T10:14:32+00:00",
  "seen_count": 14,
  "observation_count": 14,
  "presence_state": "PASSIVELY_ACTIVE",
  "os_classification": {
    "value": "Windows",
    "confidence": 0.98,
    "evidence": [
      "dhcp.vendor_class:MSFT 5.0",
      "dhcp.vendor_class.microsoft",
      "dhcp.prl.windows",
      "mdns.service.dosvc",
      "synergy.windows_multi_protocol"
    ]
  },
  "device_type_classification": {
    "value": "Windows Workstation",
    "confidence": 0.98,
    "evidence": [
      "dhcp.vendor_class.microsoft",
      "synergy.windows_workstation"
    ]
  },
  "evidence": {
    "hostname": ["dhcp", "mdns"],
    "vendor": ["oui"],
    "os_hint": [
      "dhcp.vendor_class",
      "dhcp.parameter_request_list",
      "dhcp.vendor_class:MSFT 5.0",
      "dhcp.vendor_class.microsoft",
      "dhcp.prl.windows",
      "mdns.service.dosvc",
      "synergy.windows_multi_protocol"
    ],
    "device_type": [
      "dhcp.vendor_class.microsoft",
      "synergy.windows_workstation"
    ]
  },
  "raw_fields": {
    "dhcp": {
      "transaction_id": "0x3904a3b2",
      "vendor_class": "MSFT 5.0",
      "parameter_request_list": [1, 3, 6, 15, 31, 33, 43, 44, 46, 47]
    }
  }
}
```
