# Phase 1 — Wi-Fi Capture Source Validation

**Status:** PENDING

## Entry criteria

Phase 0 target-server runtime evidence must identify the Linux server, Kismet installation/startup owner, management path, capture adapter/interface, and persistent storage mount.

## Objective

Prove that the server-attached Wi-Fi adapter and Kismet datasource observe real 802.11 traffic, not merely that a Kismet process starts.

## Required evidence

- monitor-mode capability, driver/chipset, interface/source configuration, and permissions;
- controlled 30–60 minute capture with known active devices;
- packet/device counters increasing;
- representative MAC, timestamp, RSSI, frequency/channel, and frame data;
- Kismet logs/source health; capture errors; normal network-connectivity impact;
- evidence that the server is the only Kismet sensor in this initial architecture.

## Exit criterion

The capture source remains active and creates data suitable for historical server-side queries.
