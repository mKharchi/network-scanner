# Phase 1 — Wi-Fi Capture Source Validation

**Status:** ✅ DONE — 2026-09-07

## Entry criteria

Phase 0 target-server runtime evidence must identify the Linux server, Kismet installation/startup owner, management path, capture adapter/interface, and persistent storage mount.

## Objective

Prove that the server-attached Wi-Fi adapter and Kismet datasource observe real 802.11 traffic, not merely that a Kismet process starts.

## Required evidence

- monitor-mode capability, driver/chipset, interface/source configuration, and permissions; ✅
- controlled 30–60 minute capture with known active devices; ✅
- packet/device counters increasing; ✅
- representative MAC, timestamp, RSSI, frequency/channel, and frame data; ✅
- Kismet logs/source health; capture errors; normal network-connectivity impact; ✅
- evidence that the server is the only Kismet sensor in this initial architecture. ✅

## Exit criterion

The capture source remains active and creates data suitable for historical server-side queries. ✅

## Completed capture evidence (2026-09-07)

| Field | Value |
|---|---|
| Capture file | `Kismet-20260907-10-38-22-1.kismet` |
| Start (UTC) | 2026-09-07 10:38:23 UTC |
| End (UTC) | 2026-09-07 11:11:52 UTC |
| Duration | **33.5 minutes** |
| Total packets | **264,459** |
| File size | **369.5 MB** |
| Monitor interface | `wlp0s20f3mon` (VIF on `wlp0s20f3`) |
| Management interface | `wlp0s20f3` — stayed connected to SKILLS-CENTER throughout |
| Launch script | `scripts/start_kismet_sensor.sh` |
| Teardown script | `scripts/stop_kismet_sensor.sh` |

Sample source MACs observed: `B0:3C:DC:95:39:36`, `AC:71:2E:FA:88:3F`, `C8:78:7D:C2:CD:00`, `4C:BB:58:F3:4B:97`

Normal network connectivity was unaffected throughout the capture.
