# Network Monitoring — Final Verification & Discovery Cleanup Plan

## Objective

The application is now practically functional. The next step is to verify the existing functionality and clean up/optimize the remaining network-discovery implementation.

Do **not** rewrite working functionality unnecessarily. First inspect the project and trace the existing implementation, then make only the changes required by this plan.

---

# 1. Inspect the Existing Network-Scan Storage

There currently appear to be two different types of files being stored under:

```text
server/storage/network_scans/
```

Example files:

```text
2026-08-19_09-11-31_299482.json
network_scan_2026-08-19.json
```

The first appears to contain the result of an ARP/network scan.

The second contains DHCP-retrieved devices and their hostnames.

## Task

Trace the complete code path responsible for creating both files.

Identify:

- Which function creates the timestamped scan file
- Which function creates the `network_scan_YYYY-MM-DD.json` file
- Which component retrieves DHCP information
- Why DHCP-discovered devices are not appearing in the devices displayed after the network scan
- Whether these are intentionally separate artifacts or should be merged

Do not assume the answer from filenames alone. Inspect the implementation.

---

# 2. Determine the Current Device Discovery Pipeline

Before changing anything, document the actual current flow.

Trace every source that can add a network device.

At minimum investigate:

```text
Server-side ARP scan
        ↓
ARP scan result
        ↓
Device processing/storage
```

and:

```text
Client starts
        ↓
Client reads local ARP/neighbour table
        ↓
Client enriches neighbours
        ↓
Client sends NETWORK_NEIGHBOURS
        ↓
Server processes them
        ↓
Device/observation storage
```

and:

```text
DHCP listener
        ↓
DHCP request detected
        ↓
MAC / requested IP / hostname / vendor class / client ID
        ↓
DHCP storage
```

Determine whether DHCP information currently contributes to the main network-device inventory or is stored independently.

---

# 3. Verify How Devices Appear in the UI

Trace the backend endpoint used by the frontend for:

- Latest network scan
- Network devices
- Device details
- Scan history

Determine exactly where the displayed device list comes from.

Answer these questions from the code:

1. Does the UI display only server-side ARP scan results?
2. Does it also include client-reported neighbour information?
3. Does it include DHCP-discovered devices?
4. Are observations merged from multiple sources?
5. If the same MAC appears through multiple sources, how is it deduplicated?
6. Which source determines the device hostname?
7. Which source determines the vendor?
8. Which source determines the IP?
9. Which source determines whether a device is considered online?

Document the answers before modifying the implementation.

---

# 4. Integrate DHCP Information Where Appropriate

The current situation appears to be:

```text
ARP scan
    ↓
Device displayed in latest scan

DHCP listener
    ↓
network_scan_YYYY-MM-DD.json
    ↓
Hostname available
    ↓
Not reflected in the displayed device
```

Investigate whether DHCP information should enrich the existing `NetworkDevice` record.

If technically appropriate, use DHCP information as another enrichment source.

For example:

```text
ARP
 ├── IP
 └── MAC
       ↓
Network Device
       ↑
DHCP
 ├── Hostname
 ├── Requested IP
 ├── Vendor Class
 └── Client ID
```

Do not create duplicate devices when the MAC address already exists.

If DHCP discovers:

```text
MAC: AA:BB:CC:DD:EE:FF
Hostname: DESKTOP-ABC
IP: 172.16.0.102
```

and ARP already discovered:

```text
MAC: AA:BB:CC:DD:EE:FF
IP: 172.16.0.102
```

these should normally represent the same network device.

Preserve source information if the existing architecture supports it.

---

# 5. Perform ARP Scans From Clients

The current architecture should be reviewed so that clients can perform their own local network discovery.

The client already has functionality for reading its local ARP/neighbour table.

However, reading the existing neighbour table and actively performing an ARP scan are different operations.

Desired concept:

```text
Client
   ↓
Determine local interface/subnet
   ↓
Perform ARP discovery
   ↓
Collect IP + MAC
   ↓
Local enrichment
   ↓
Send results to server
```

## Requirements

Inspect the existing client implementation first.

Determine:

- how the client determines its local subnet
- whether an ARP scanning utility already exists
- whether the client currently only reads the OS neighbour cache
- whether the required permissions are available
- whether the client runs on Linux, Windows, or both

Do not add a dependency blindly.

Prefer existing project mechanisms.

If active ARP scanning is already implemented somewhere in the project, reuse it.

---

# 6. Decide the Role of Server vs Client Scanning

After inspecting the implementation, establish the actual architecture.

The desired architecture should be evaluated as:

```text
                    NETWORK
                       │
          ┌────────────┴────────────┐
          │                         │
     Server ARP scan          Client discovery
          │                         │
          │                  ARP / neighbour table
          │                         │
          └────────────┬────────────┘
                       ↓
                Device processing
                       ↓
                Deduplication
                       ↓
               NetworkDevice
                       ↓
              Observations/history
```

The purpose is not necessarily to eliminate server-side scanning.

Client-side discovery can provide another observation point and potentially discover information visible from that client's network position.

Document:

- why server-side scanning exists
- why client-side scanning exists
- what information each source provides
- how their results are merged

---

# 7. Remove the "Get Network Log" Action

There is currently an action named similar to:

```text
Get Network Log
```

It reportedly returns:

```text
No recent network connection activities
```

This is considered redundant because the existing activity logs already contain browser/network-related activity such as browser history/connections.

## Task

Trace the entire implementation of this action.

Find:

- frontend button/action
- frontend API call
- backend endpoint
- command handler
- service/function
- response model
- tests
- documentation, if any

Then remove the feature cleanly.

Remove:

- frontend UI action
- unused API endpoint
- unused command
- unused backend function
- unused types/models
- unused tests
- dead imports
- obsolete documentation

Only remove it if the investigation confirms that it is genuinely redundant and not used by another feature.

Do not remove the existing browser/activity log functionality.

---

# 8. Verify Network Scan Storage

Inspect the storage implementation for:

```text
server/storage/network_scans/
```

Verify:

- where scan result files are created
- naming conventions
- whether DHCP data is stored separately
- whether scan files are duplicated unnecessarily
- whether old scan artifacts are cleaned up
- whether the API reads from these files or from database records
- whether storage is consistent with `NETWORK_SCAN_STORAGE_DIR`

Do not change the storage architecture unless there is an actual bug.

---

# 9. Verify Scan History Semantics

Determine what one network scan actually means in the current implementation.

A scan should have a clear relationship between:

```text
NetworkScan
    ↓
Devices observed during that scan
```

Verify whether the current implementation stores:

- scan timestamp
- scanner/source
- interface/network
- discovered devices
- DHCP information
- client-reported observations

If multiple sources are represented, identify the source explicitly if the current data model allows it.

---

# 10. Verify Device Deduplication

Devices can now be discovered through:

- server ARP scan
- client neighbour table
- client active ARP scan
- DHCP requests

The same device must not become four separate devices.

Preferred identity:

```text
MAC address
```

with the understanding that MAC randomization can make this imperfect.

Verify the current deduplication logic.

Test scenarios such as:

```text
ARP discovers MAC A
DHCP discovers MAC A
Client discovers MAC A
```

Expected result:

```text
One NetworkDevice
Multiple observations/enrichment sources
```

---

# 11. Verify Hostname Enrichment

Trace the current hostname pipeline.

Potential sources include:

```text
DHCP hostname
      ↓
mDNS
      ↓
Reverse DNS
      ↓
Other local discovery
```

Determine the current priority.

If a reliable DHCP hostname exists, it should not be discarded merely because ARP itself does not provide one.

Do not change the priority without inspecting the current implementation.

---

# 12. Verify the Existing Client Neighbour Feature

Inspect:

```text
NetworkNeighbourCollector
```

and its usage.

Verify:

- Linux support
- Windows support
- macOS support if present
- ARP/neighbour parsing
- OUI enrichment
- hostname enrichment
- DHCP enrichment
- reporting to server
- periodic scan interval
- error handling

Confirm exactly what happens when a client starts.

Expected investigation path:

```text
Client connects
      ↓
Client registers
      ↓
Client receives configuration
      ↓
Initial neighbour collection
      ↓
NETWORK_NEIGHBOURS message
      ↓
Server receives it
      ↓
Server stores/processes it
      ↓
Background neighbour collection
```

Document any deviations.

---

# 13. Add/Update Tests Before Final Cleanup

Add tests for the discovered architecture.

## DHCP + ARP merge

Test:

```text
ARP device + DHCP device with same MAC
```

Expected:

```text
one device
hostname enriched
```

## Client + server discovery merge

Test:

```text
Server ARP → MAC A
Client ARP → MAC A
```

Expected:

```text
one device
multiple observations
```

## Different IP

Test:

```text
MAC A → IP 172.16.0.10
MAC A → IP 172.16.0.25
```

Expected:

```text
same device
IP history/updated IP
```

## DHCP-only discovery

If the architecture supports DHCP-only devices, test:

```text
DHCP → MAC A + hostname
```

and verify whether the device appears in the appropriate device inventory.

---

# 14. Manual Real-Network Verification

After implementation, perform a real test.

Use a known nearby device.

### Test A — Server scan

1. Connect device to Wi-Fi.
2. Run server network scan.
3. Confirm device appears.
4. Record MAC/IP/vendor/hostname.

### Test B — Client discovery

1. Run a client.
2. Ensure client performs its neighbour discovery.
3. Confirm the target device appears in the client report.
4. Confirm the server receives it.

### Test C — DHCP

1. Disconnect target device from Wi-Fi.
2. Reconnect it.
3. Capture its DHCP request.
4. Confirm hostname is detected.
5. Confirm the hostname enriches the corresponding device when appropriate.

### Test D — Deduplication

Confirm that the device is still represented as one logical device despite being discovered by multiple mechanisms.

---

# 15. Final Verification Checklist

- [ ] Network scan storage path is correct
- [ ] Duplicate/parallel scan artifacts are understood
- [ ] DHCP storage is understood
- [ ] DHCP devices are correctly integrated/enriched where appropriate
- [ ] Device discovery sources are documented
- [ ] Server ARP scanning is verified
- [ ] Client neighbour discovery is verified
- [ ] Client active ARP scanning is evaluated/implemented where appropriate
- [ ] Device deduplication works across discovery sources
- [ ] Hostname enrichment works
- [ ] Vendor enrichment works
- [ ] "Get Network Log" is removed if confirmed redundant
- [ ] Dead backend/frontend code is removed
- [ ] Tests pass
- [ ] Frontend build passes
- [ ] Backend tests pass
- [ ] Real-network verification passes

---

# Important Instructions for the IDE AI

1. **Inspect first, modify second.**
2. Do not assume how the architecture works based on filenames.
3. Trace the complete data flow from discovery to storage to API to UI.
4. Reuse existing models/services/functions where possible.
5. Do not create duplicate device records for different discovery sources.
6. Do not remove functionality before verifying that it is unused.
7. Do not rewrite working code unnecessarily.
8. Keep client discovery and server discovery conceptually separate, but merge their observations into the same device model where appropriate.
9. Treat DHCP as an enrichment/discovery source rather than assuming DHCP and ARP represent separate devices.
10. After each significant change, run the relevant tests/build and report the result.

## Final Goal

The resulting architecture should clearly answer:

> **How did we discover this device, what information do we know about it, when did we see it, and where did each piece of information come from?**

The system should support multiple discovery sources while maintaining one coherent network-device inventory.
