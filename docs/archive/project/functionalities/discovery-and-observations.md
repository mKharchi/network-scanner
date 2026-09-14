# Network Discovery and Observations

## Overview

Discovery is a passive-first pipeline. Endpoint clients observe their local
network without sending routine probe traffic, and the server merges reports
from multiple clients into device records and scan snapshots.

## Sources

| Source | Collector | Data |
| --- | --- | --- |
| OS neighbour table | `network_neighbour_collector.py` | IP, MAC, state, interface, hostname/vendor enrichment |
| DHCP broadcast | `dhcp_listener.py` | Client MAC, requested IP, hostname, vendor class, client ID, message type |
| mDNS/LLMNR/NetBIOS/SSDP | `passive_protocol_listener.py` | Names, services, protocol observations |
| Packet observer | `packet_observer.py`, `packet_extractor.py` | Normalized protocol/packet telemetry |
| Server merge | `network_discovery.py` | Recent client observations and scan composition |

Client active-ARP helpers remain in the code for compatibility/future use, but
normal current client neighbourhood reporting does not depend on active ARP
probing. Any future active discovery must be separately approved and documented.

## End-to-end flow

1. A client collector reads local neighbour state and normalizes MAC/IP fields.
2. DHCP and passive protocol listeners add observations as they arrive.
3. The client stores a daily neighbourhood snapshot and sends a typed report
   through the TCP connection.
4. `server_lib.handle_network_neighbour_report()` validates and routes the
   report.
5. `network_device_storage.py` upserts device identity and inserts an
   observation with its source provenance (`CLIENT_ARP`, `CLIENT_DHCP`, or
   another source).
6. `network_scan_storage.py` maintains daily JSON audit files for neighbour
   snapshots and DHCP activity.
7. `network_discovery.py` merges recent observations, prior scan data, and any
   approved server-side source into a deduplicated scan.
8. The API and GUI expose latest/history scans, device detail, DHCP activity,
   and reporting-client provenance.

## Data semantics

Devices are deduplicated by normalized MAC address. IP, hostname, vendor,
first/last-seen times, sources, and reporting clients are merged without
discarding useful provenance. DHCP data is both an audit record and a device
enrichment source; it is not isolated from the main device registry.

Two filesystem formats have distinct purposes:

- `server/storage/network_scans/<timestamp>.json`: point-in-time merged scan
  snapshots used by latest/history views.
- `server/storage/network_scans/network_scan_<date>.json`: daily neighbour and
  DHCP audit data.

## Server-side active scan status

The repository still contains active ARP scan and global-scan compatibility
paths. The current product direction is passive collection and controlled
server orchestration; do not describe active scanning as the default behavior
unless the corresponding feature is deliberately re-enabled and tested.

