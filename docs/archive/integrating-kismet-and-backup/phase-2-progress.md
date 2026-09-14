# Phase 2 Progress — Single-Sensor Kismet Pilot

## Phase Objective
Prove that a standalone Kismet sensor can continuously capture useful wireless traffic without interfering with required network connectivity on the pilot host.

---

## Status
- **Status:** COMPLETED
- **Date:** 2026-09-05
- **Deliverable:** [`KISMET_SENSOR_PILOT.md`](file:///home/adonis/network-scanner/docs/integrating-kismet-and-backup/KISMET_SENSOR_PILOT.md)

---

## Summary of Accomplishments

1. **Hardware & Monitor Mode Verification:**
   - Dedicated monitor interface `wlp0s20f3mon` operating on Intel Wi-Fi 6 AX201 (`iwlwifi` driver).
   - Dual-band 2.4 GHz & 5.0 GHz capture with hopping across channels 1–165.
   - Normal network connectivity on `wlp0s20f3` (`172.16.1.238`) remained active with zero downtime.

2. **Continuous Capture Executed:**
   - Evaluated active capture sessions in `/home/adonis/kismet/` (`Kismet-20260905-12-14-56-1.kismet`).
   - Capture duration: 41.23 minutes, 81,969 802.11 frames, 104 distinct wireless devices, 0 error packets.

3. **802.11 Frame Analysis:**
   - Verified reception of Beacon, Probe Request/Response, QoS Data, Data, QoS Null, Block Ack, RTS, CTS, and ACK frames via Radiotap/Dot11 disassembler.

4. **Storage & Retention Benchmarked:**
   - Full `.kismet` DB growth: ~125 MB/hour (~3 GB/day).
   - Filtered observation records: ~5.7 MB/hour (~135 MB/day).
   - Recommended retention policy: 48h for raw captures, 7d for structured observation cache.

---

## Next Steps
Proceed to **Phase 3 — MAC Correlation With the Existing Device Base** to cross-correlate Kismet-observed MAC addresses with the 314 known devices in the network scanner inventory.
