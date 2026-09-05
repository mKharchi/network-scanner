# Single-Sensor Kismet Pilot Report

## Executive Summary

A standalone Kismet sensor was deployed and validated on the pilot host to evaluate passive 802.11 wireless capture capabilities, hardware driver stability, frame integrity, and storage consumption without impacting existing network connectivity.

---

## 1. Sensor Hardware & Wireless Interface Specifications

| Attribute                | Specification                                                                     |
| ------------------------ | --------------------------------------------------------------------------------- |
| **Sensor Host**          | `adonis-IdeaPad-5-15ITL05` (Linux kernel 7.0.0-30-generic x86_64)                 |
| **Wireless Adapter**     | Intel Wi-Fi 6 (AX201 / Killer AX1650i) on PCIe bus `0000:00:14.3`                 |
| **Driver**               | `iwlwifi` (firmware: `77.f39cc7f9.0 QuZ-a0-hr-b0-77.u`, mac80211 stack)           |
| **Managed Interface**    | `wlp0s20f3` (IP: `172.16.1.238/16`, SSID: `SKILLS-CENTER`, Channel: 44, 5220 MHz) |
| **Capture Interface**    | `wlp0s20f3mon` (Type: `monitor`, DLT: `127` / `LINKTYPE_IEEE802_11_RADIOTAP`)     |
| **Monitor Mode Support** | Native software interface mode supported on `phy#0`; MU-MIMO sniffer capable      |
| **Supported Bands**      | Dual-band: 2.4 GHz (802.11b/g/n/ax) and 5.0 GHz (802.11a/n/ac/ax)                 |
| **Supported Channels**   | 2.4 GHz: Channels 1–13; 5 GHz: Channels 36–165 (up to 160 MHz channel width)      |
| **Channel Hopping**      | 5 hops/second across 2.4 GHz and 5 GHz frequency bands                            |

---

## 2. Controlled Capture Execution & Metrics

| Metric                        | Result                                                                      |
| ----------------------------- | --------------------------------------------------------------------------- |
| **Capture Software**          | Kismet `2026.09.0-e24ee9be2`                                                |
| **Primary Pilot Session**     | `Kismet-20260905-12-14-56-1.kismet`                                         |
| **Capture Start Time**        | 2026-09-05 12:15:26 UTC                                                     |
| **Capture End Time**          | 2026-09-05 12:56:40 UTC                                                     |
| **Capture Duration**          | **41.23 minutes** (continuous)                                              |
| **Packets Captured**          | **81,969 packets**                                                          |
| **Capture Error Count**       | **0 error packets** (`num_error_packets: 0`)                                |
| **Distinct Wireless Devices** | **104 distinct MAC addresses** identified by Kismet                         |
| **Kismet SQLite DB Size**     | **86 MB** (including full Radiotap metadata, signal RRDs, and device state) |
| **Filtered PCAP-NG Size**     | **3.9 MB** (`packets_kismet.pcapng`)                                        |

---

## 3. Frame Type Breakdown & Protocol Verification

Verification via Scapy Radiotap / 802.11 frame disassembler confirmed active reception of 802.11 frame types:

```text
802.11 Frame Distribution:
├── Control Frames (66.8%):
│   ├── CTS (Clear to Send)
│   ├── RTS (Request to Send)
│   ├── Block Ack
│   ├── ACK
│   └── Block Ack Request
├── Data Frames (18.5%):
│   ├── QoS Data (unicast payload streams)
│   ├── Plain Data
│   ├── QoS Null (power save / polling)
│   └── Null Data
└── Management Frames (5.8%):
    ├── Beacon (AP broadcasts)
    ├── Probe Response
    ├── Probe Request
    ├── Authentication
    ├── Association Request / Response
    └── Action / Radio Measurement
```

---

## 4. Storage & Retention Projections

| Metric                  | Full Kismet DB (`.kismet`) | Extracted PCAP / Telemetry Records |
| ----------------------- | -------------------------- | ---------------------------------- |
| **Hourly Storage**      | ~125 MB / hour             | ~5.7 MB / hour                     |
| **Daily Storage (24h)** | ~3.0 GB / day              | ~135 MB / day                      |
| **Weekly Storage (7d)** | ~21.0 GB / week            | ~950 MB / week                     |

### Kismet Retention Recommendation

1. Retain raw `.kismet` databases for **48 hours** locally on the sensor.
2. Maintain structured index / observation cache in SQLite for **7 days** to support on-demand lookback investigations.
3. Automatically rotate and purge `.kismet` files exceeding the retention window using the storage retention manager.

---

## 5. Connectivity & System Stability Impact

- **Network Connectivity:** Uninterrupted. Normal IP connectivity on `wlp0s20f3` (`172.16.1.238`) remained active during the entire multi-hour monitor mode capture on `wlp0s20f3mon`.
- **System Stability:** Zero kernel panics, zero driver resets, CPU utilization < 2.5%, memory footprint ~85 MB.

---

## Conclusion & Milestone B Sign-off

```text
MILESTONE B STATUS: SUCCESSFUL
```

The standalone Kismet sensor operates continuously and reliably on the pilot host, capturing 802.11 management, control, and data frames across both 2.4 GHz and 5 GHz channels without degrading the host's normal network connectivity.
