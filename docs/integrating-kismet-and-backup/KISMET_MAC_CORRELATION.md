# Kismet MAC Correlation Report

## Executive Summary

This report establishes the proof-of-concept for correlating passive 802.11 wireless observations captured by Kismet with the existing network monitoring device inventory.

Using the device MAC address as the primary correlation key, 82 known network devices across the facility were positively matched in Kismet wireless captures with rich RF telemetry (signal strength RSSI, frequency channels, frame types, packet counts, and observation timestamps).

---

## Correlation Summary

| Metric                                                                   | Count / Value |
| ------------------------------------------------------------------------ | ------------- |
| **Known Devices in Database Base**                                       | **314**       |
| **Distinct MAC Addresses in Kismet Captures**                            | **816**       |
| **Positively Matched Known Devices**                                     | **82**        |
| **Unmatched Known Devices (Out of RF range of single sensor)**           | **232**       |
| **Unknown / Transient Kismet MACs (Mobile probes, visitors, AP BSSIDs)** | **734**       |
| **Single-Sensor Match Percentage**                                       | **26.11%**    |

---

## 802.11 Address Interpretation Methodology

802.11 frames use multiple address fields whose semantics vary based on frame type and DS status:

- **Transmitter Address (TA):** Physical source of the RF transmission.
- **Receiver Address (RA):** Target receiver of the RF transmission.
- **Source Address (SA):** Original payload sender (Client MAC on ToDS=1).
- **Destination Address (DA):** Final payload recipient (Client MAC on FromDS=1).
- **BSSID:** Access point identifier.

Correlation parses both directional endpoints:

```text
[Existing Device MAC]  <───►  [Kismet Packet Address (Source / Dest / Transmitter / Device)]
```

---

## Matched Devices Table (Sample of Verified Endpoints)

| Device Hostname         | Known MAC           | IP Address       | Vendor            | Packets Observed |  Avg RSSI | First Seen           | Last Seen            |
| ----------------------- | ------------------- | ---------------- | ----------------- | ---------------: | --------: | -------------------- | -------------------- |
| Gateway / AP            | `AC:71:2E:FA:88:3F` | `172.16.255.254` | Fortinet, Inc.    |          111,458 | -57.0 dBm | 2026-09-05T09:53:53Z | 2026-09-05T12:56:40Z |
| Pilot Host              | `B0:3C:DC:95:39:36` | `172.16.1.238`   | Intel Corporate   |           96,372 | -55.0 dBm | 2026-09-05T10:59:33Z | 2026-09-05T12:56:39Z |
| `DESKTOP-8FHPTNP`       | `E4:FD:45:BA:8A:EC` | `172.16.1.173`   | Intel Corporate   |           47,099 | -71.6 dBm | 2026-09-05T09:56:25Z | 2026-09-05T10:30:26Z |
| Endpoint `172.16.1.175` | `B2:33:38:58:CC:16` | `172.16.1.175`   | Unknown           |           29,542 | -83.6 dBm | 2026-09-05T09:53:59Z | 2026-09-05T11:11:44Z |
| Endpoint `172.16.3.232` | `E4:FD:45:BB:3B:5E` | `172.16.3.232`   | Intel Corporate   |           25,299 | -78.8 dBm | 2026-09-05T09:56:21Z | 2026-09-05T10:30:25Z |
| `DESKTOP-GCO8PU9`       | `E4:FD:45:BB:2E:F7` | `172.16.1.11`    | Intel Corporate   |           21,238 | -77.3 dBm | 2026-09-05T09:53:54Z | 2026-09-05T12:55:22Z |
| `realme-C31`            | `06:9C:34:86:4F:83` | `172.16.2.145`   | Unknown           |           15,165 | -66.6 dBm | 2026-09-05T09:53:53Z | 2026-09-05T12:56:20Z |
| `DESKTOP-30OOMFF`       | `E4:FD:45:BB:18:45` | `172.16.0.36`    | Intel Corporate   |            9,451 | -74.7 dBm | 2026-09-05T09:53:54Z | 2026-09-05T12:56:35Z |
| Endpoint `172.16.3.211` | `B6:30:2E:CC:33:64` | `172.16.3.211`   | Unknown           |            8,611 | -69.5 dBm | 2026-09-05T09:53:54Z | 2026-09-05T12:54:59Z |
| `realme-Note-70`        | `A6:18:1A:02:3B:B1` | `172.16.0.30`    | Unknown           |            7,792 | -68.3 dBm | 2026-09-05T09:53:54Z | 2026-09-05T10:59:29Z |
| `DESKTOP-7BEVSLC`       | `E4:FD:45:BB:F4:09` | `172.16.1.247`   | Intel Corporate   |            6,960 | -61.7 dBm | 2026-09-05T10:23:16Z | 2026-09-05T12:56:27Z |
| `OPPO-A5-Pro`           | `D6:55:3F:7D:30:80` | `172.16.0.183`   | Unknown           |            6,897 | -77.8 dBm | 2026-09-05T09:55:03Z | 2026-09-05T12:46:06Z |
| `DESKTOP-ILGIRV7`       | `C4:75:AB:D2:6A:C2` | `172.16.3.17`    | Intel Corporate   |            6,254 | -82.9 dBm | 2026-09-05T09:55:08Z | 2026-09-05T11:04:09Z |
| `OPPO-F9`               | `A2:02:BE:08:D0:B4` | `172.16.1.60`    | Unknown           |            5,674 | -58.2 dBm | 2026-09-05T10:23:16Z | 2026-09-05T10:30:24Z |
| `DESKTOP-98QGO55`       | `58:A0:23:8C:CA:9E` | `172.16.4.45`    | Intel Corporate   |            5,365 | -76.2 dBm | 2026-09-05T09:54:18Z | 2026-09-05T12:55:27Z |
| `DESKTOP-OVF15IC`       | `E4:FD:45:BA:4D:C5` | `172.16.0.234`   | Intel Corporate   |            5,327 | -71.8 dBm | 2026-09-05T09:54:10Z | 2026-09-05T12:56:38Z |
| `DESKTOP-QVLFRAQ`       | `14:5A:FC:08:C5:EB` | `172.16.2.212`   | Liteon Technology |            5,248 | -58.7 dBm | 2026-09-05T09:53:54Z | 2026-09-05T12:53:24Z |
| `DESKTOP-J0LR2GT`       | `E4:FD:45:BB:38:9D` | `172.16.0.9`     | Intel Corporate   |            5,172 | -62.3 dBm | 2026-09-05T09:53:54Z | 2026-09-05T12:56:03Z |
| `DESKTOP-F0DU7BR`       | `4C:D5:77:C0:A4:0B` | `172.16.3.223`   | Chongqing Fugui   |            4,461 | -76.8 dBm | 2026-09-05T10:23:15Z | 2026-09-05T10:30:25Z |
| `rong-yaoX50`           | `1C:C9:92:7F:21:7F` | `172.16.2.134`   | Honor Device Co.  |            4,304 | -55.9 dBm | 2026-09-05T09:54:24Z | 2026-09-05T12:50:43Z |

---

## Findings & Insights

1. **MAC as Primary Key:**
   - MAC-based correlation successfully connected disparate layers: IP/hostname discovery from ARP/DHCP and physical RF 802.11 signal metrics from Kismet.
2. **RF Signal & Presence Visibility:**
   - The pilot sensor in its current location achieved line-of-sight and near-field observation of 82 devices (26.11% of the building).
   - Signal levels range realistically from `-29 dBm` (adjacent APs) to `-89 dBm` (distant desktop PCs across multiple rooms/walls).
3. **Multi-Source Fusion:**
   - Combining Kismet with network discovery allows an analyst investigating an alert on `DESKTOP-8FHPTNP` (`172.16.1.173`) to immediately inspect 47,099 wireless packets with exact signal strength and frame timestamps.

---

## Conclusion & Milestone C Sign-off

```text
MILESTONE C STATUS: SUCCESSFUL
```

The fundamental bridge between the network-scanner device management database and passive wireless sensing via Kismet is fully demonstrated and verified.
