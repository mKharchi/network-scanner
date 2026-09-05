# Passive Capture Storage Cleanup & Kismet Integration Plan

## Project Goal

Extend the existing network monitoring platform with passive Wi-Fi observation using Kismet, while first solving the existing client-side packet-storage growth problem.

The final objective is to:

1. Keep the existing device base containing MAC, IP, hostname, vendor, classification, location, and timestamps.
2. Deploy one or more Wi-Fi passive-capture sensors using Kismet.
3. Correlate Kismet-observed wireless MAC addresses with existing devices.
4. Query historical wireless observations for a selected device.
5. Investigate suspicious devices after an alert using a configurable lookback window.
6. Expand coverage across the training center only after the pilot is stable.
7. Defer continuous ML/ETL processing until real usage proves it is needed.

The implementation must be incremental. Do not implement all phases simultaneously.

---

## Target Architecture

```text
                         CENTRAL SERVER
                 +-----------------------------+
                 | Device Database             |
                 | Flow Database               |
                 | Alerts                      |
                 | Investigation API           |
                 | Sensor Management            |
                 +---------------+-------------+
                                 |
                 +---------------+----------------+
                 |                                |
        +--------v---------+             +---------v--------+
        | Client Agent    |             | Wi-Fi Sensor     |
        |                 |             |                  |
        | Device discovery|             | Kismet           |
        | IP/MAC           |             | 802.11 capture   |
        | Hostname         |             | PCAP/Kismet DB   |
        | Flow aggregation |             | Wireless data    |
        +------------------+             +------------------+
                 |                                |
                 +---------------+----------------+
                                 |
                           MAC correlation
                                 |
                                 v
                           Device record
```

### Terminology

- **Client Agent** — existing managed endpoint agent responsible for device discovery, system information, observations, and flow aggregation.
- **Wi-Fi Sensor** — machine/NIC dedicated to passive 802.11 observation using Kismet.
- **Central Server** — existing backend/database plus new investigation and sensor functionality.

Do not initially treat Kismet as another normal client agent. It is an observation source.

---

## Track 1 — Passive-Capture Storage

## Phase 0 — Investigate the Existing Storage Pipeline

### Objective

Determine exactly what happens to the existing raw packet files after they are consumed by the flow-generation pipeline.

**No destructive code changes during this phase.**

### Questions to answer

1. Where are raw packet files created?
2. What process creates them?
3. What directory structure and naming convention do they use?
4. What format do they use?
5. Which process/job reads them?
6. Which scheduled job consumes them?
7. Is the aggregation interval 5, 15, 60 minutes, or something else?
8. Are files read again after successful flow generation?
9. Are raw files used by any forensic/replay feature?
10. Are raw files used by any API or UI feature?
11. Are raw files uploaded to the server?
12. Are flows persisted in MySQL?
13. Does the flow model retain everything required by downstream features?
14. What happens when flow processing fails?
15. Can failed processing be retried safely?
16. What is the current folder size?
17. What is the daily growth rate?

### Code investigation

Trace:

```text
packet capture
      ↓
raw file
      ↓
flow computation
      ↓
flow object
      ↓
MySQL
      ↓
downstream consumers
```

Search for:

- raw packet directory paths
- packet-file creation
- file open/read operations
- packet parsing
- flow aggregation
- flow persistence
- scheduled jobs
- cleanup logic
- file uploads
- forensic/replay functionality

### Required deliverable

Create:

```text
STORAGE_PIPELINE_AUDIT.md
```

Document:

```text
Raw capture location:
Raw file format:
Raw file naming convention:
Writer:
Reader:
Flow computation job:
Flow interval:
Database persistence:
Post-processing readers:
Failure behavior:
Current storage size:
Estimated daily growth:
Can raw files be safely deleted?
```

The conclusion must explicitly state:

```text
SAFE TO DELETE AFTER SUCCESSFUL PROCESSING: YES/NO
```

Do not assume the raw files are disposable. Prove it from the code.

---

## Phase 1 — Implement Bounded Raw-File Retention

Begin only if Phase 0 confirms that raw files are intermediate artifacts.

### Objective

Prevent unbounded storage growth while retaining enough data to recover from processing failures.

Moving the folder from C: to D: is not considered a storage solution by itself.

### Recommended lifecycle

```text
RAW FILE
   ↓
PENDING
   ↓
PROCESSING
   ↓
SUCCESS
   ↓
PROCESSED
   ↓
RETENTION WINDOW
   ↓
DELETE
```

Failure:

```text
PROCESSING
   ↓
FAILED
   ↓
KEEP FILE
   ↓
RETRY
```

### Retention

Start with a configurable value such as:

```text
RAW_CAPTURE_RETENTION_HOURS=48
```

Do not hard-code the value.

### Deletion requirements

A raw file may be deleted only when:

```text
flow processing succeeded
AND
configured retention period elapsed
AND
file is not currently being processed
AND
file is not required by another operation
```

Never delete `FAILED`, `PENDING`, or `PROCESSING` files merely because they are old.

### Safety requirements

The cleanup process must:

- log every deletion
- log why it was deleted
- never delete files currently being written
- never delete files currently being processed
- handle missing files gracefully
- handle permission errors gracefully
- avoid crashing the client
- support dry-run mode
- use the existing configuration conventions

### Validation

1. Generate test packet files.
2. Process them successfully.
3. Verify they become eligible after the retention window.
4. Simulate failed flow computation.
5. Verify the failed file is preserved.
6. Simulate a currently-processing file.
7. Verify it is preserved.
8. Run cleanup in dry-run mode.
9. Verify logs.
10. Enable real cleanup.

### Storage decision

Do not create a MySQL row for every raw packet unless a later demonstrated requirement requires it.

Use:

```text
MySQL → structured device/flow/application data
File/Kismet storage → bulk raw capture artifacts
```

---

## Track 2 — Kismet Rollout

## Phase 2 — Single-Sensor Kismet Pilot

### Objective

Prove that a standalone Kismet sensor can continuously capture useful wireless traffic without interfering with required network connectivity.

Do not integrate Kismet into every client yet.

Start with one pilot machine.

### Step 2.1 — Hardware/NIC decision

Determine whether the pilot has:

- Wi-Fi adapter capable of monitor mode
- stable Linux driver
- adequate reception
- a dedicated interface for passive capture

Preferred architecture:

```text
Dedicated Wi-Fi adapter
        ↓
Monitor mode
        ↓
Kismet
```

If the machine needs Wi-Fi connectivity:

```text
Interface 1 → normal connectivity
Interface 2 → Kismet capture
```

Alternatively use a dedicated sensor machine.

### Step 2.2 — Verify monitor mode

Run:

```bash
iw dev
```

and:

```bash
iw list
```

Document:

```text
Sensor:
Operating system:
Wi-Fi adapter:
Driver:
Interface:
Monitor-mode support:
Supported bands:
Supported channels:
```

### Step 2.3 — Configure Kismet

Configure Kismet to use the capture interface.

Verify:

```text
Wi-Fi interface
      ↓
monitor mode
      ↓
Kismet
      ↓
802.11 frames
```

### Step 2.4 — Controlled capture

Run Kismet for 30–60 minutes.

During the test, keep several known devices connected.

Record their:

```text
MAC
IP
hostname
```

This is the ground-truth dataset.

### Step 2.5 — Verify capture

Confirm that Kismet produces usable PCAP-NG/Kismet database data.

Open it in Wireshark.

Verify actual 802.11 frames such as:

- Beacon
- Probe Request
- Probe Response
- QoS Data
- QoS Null
- ACK
- RTS
- CTS
- Block Ack

Do not assume every frame contains a useful device identity.

### Step 2.6 — Measure storage

Measure:

```text
MB/hour
MB/day
```

Define a Kismet retention policy before broad deployment.

### Deliverable

Create:

```text
KISMET_SENSOR_PILOT.md
```

Include:

```text
Sensor hardware:
NIC:
Driver:
Monitor-mode support:
Bands/channels:
Capture duration:
Packets captured:
Capture size:
Estimated daily storage:
Known devices present:
Observed MACs:
Capture reliability:
Connectivity impact:
```

The pilot succeeds only if:

- Kismet captures continuously.
- The machine remains stable.
- Required connectivity remains available.
- Captures open successfully in Wireshark.
- Storage growth is measured.
- Known devices can be observed.

---

## Phase 3 — MAC Correlation With the Existing Device Base

### Objective

Prove that Kismet can become another observation source for the existing device database.

This is the central proof-of-concept phase.

### Existing device model

The existing application contains information such as:

```text
Device
├── MAC
├── IP
├── hostname
├── vendor
├── classification
├── status
├── first_seen
├── last_seen
└── location
```

Kismet provides observations such as:

```text
Observation
├── MAC/address information
├── timestamp
├── frame type
├── frame subtype
├── packet length
├── RSSI, if available
├── channel/frequency, if available
└── other capture metadata
```

### Primary correlation key

Initially use the MAC address.

```text
Existing Device
       |
       | MAC
       v
Kismet Wireless Observation
```

Do not initially use hostname, vendor, IP, or location as the primary identity key.

### 802.11 address handling

802.11 frames may contain:

- transmitter address
- receiver address
- source address
- destination address
- BSSID

Their meaning depends on frame type and direction.

Do not blindly treat the Wireshark `Source` column as the device MAC for every frame.

Implement/verify correct 802.11 address interpretation.

### Correlation experiment

For each known device:

```text
Known device:
MAC = AA:BB:CC:DD:EE:FF
IP = 172.16.1.37
Hostname = PC-17
```

Search the Kismet capture for the MAC.

Record:

```text
Found:
Observation count:
First observation:
Last observation:
Frame types:
RSSI available:
Channel available:
```

Repeat for multiple known devices.

### Required report

Create:

```text
KISMET_MAC_CORRELATION.md
```

with:

| Device | Known MAC | IP  | Found in Kismet | Observation Count | First Seen | Last Seen |
| ------ | --------- | --- | --------------- | ----------------: | ---------- | --------- |

Also report:

```text
Known devices:
Matched devices:
Unmatched devices:
Unknown Kismet MACs:
Match percentage:
```

### Success criterion

Demonstrate reliably:

```text
Existing Device
      ↓
MAC
      ↓
Kismet observations
```

for multiple real devices.

Do not build a large backend integration until this relationship is verified.

---

## Phase 4 — Build the Kismet Investigation Service

### Objective

Expose Kismet observations through the central application's backend without copying the complete raw capture into MySQL.

The user selects a device, not a manually entered MAC.

### Desired flow

```text
User selects Device
       ↓
Backend retrieves device MAC
       ↓
Determine relevant sensor
       ↓
Determine time window
       ↓
Query Kismet
       ↓
MAC correlation
       ↓
Time filtering
       ↓
Noise filtering
       ↓
Structured response
```

Example conceptual endpoint:

```http
GET /devices/{device_id}/network-observations?lookback=30m
```

or:

```http
GET /devices/{device_id}/network-observations?start=...&end=...
```

### Service responsibilities

The service should:

1. Validate the device.
2. Retrieve its MAC.
3. Determine relevant sensor(s).
4. Determine requested time range.
5. Query Kismet data.
6. Match the device's MAC.
7. Correctly interpret 802.11 address fields.
8. Filter irrelevant control-frame noise where appropriate.
9. Normalize observations.
10. Return timestamps.
11. Return frame sizes.
12. Return available radio metadata.
13. Return sensor information.
14. Provide a capture/reference identifier where useful.
15. Avoid exposing raw payload data by default.

### Raw capture principle

Keep:

```text
Kismet
 └── raw capture
```

as the raw evidence source.

MySQL should contain structured application information and references, not an uncontrolled packet-per-row copy of the capture.

---

## Phase 5 — Add Device Investigation UI

### Objective

Allow an analyst to investigate a device directly from the existing device-detail page.

Example:

```text
DEVICE
────────────────────────────

DESKTOP-DRIJDOL
172.16.0.231
E4:FD:45:BB:18:D6

[ Overview ]
[ Network ]
[ Activity ]
[ Investigation ]
```

Investigation view:

```text
KISMET INVESTIGATION

Time range:
[ Last 15 minutes ▼ ]

[ Search ]

────────────────────────────────────

Time       Frame        Size
14:02:31   QoS Data     1480 B
14:02:32   QoS Data      512 B
14:02:35   QoS Data     1480 B
14:02:41   QoS Null       86 B
14:02:42   Block Ack      70 B
```

### Initial UI

Show:

- selected device
- MAC
- IP
- investigation period
- observation count
- timestamp
- frame type
- frame subtype
- packet length
- RSSI if available
- channel/frequency if available
- sensor

Later versions may add:

- timeline visualization
- traffic-volume graph
- sensor/location information
- filtering
- grouping
- suspicious-event highlighting

Do not build complex visualization before the backend data is validated.

---

## Phase 6 — Connect Kismet Investigation to Alerts

### Objective

Automatically connect a suspicious alert to the relevant Kismet observation window.

Desired flow:

```text
Suspicious Alert
      ↓
Suspect Device
      ↓
Device MAC
      ↓
Kismet Investigation
      ↓
Lookback window
      ↓
Evidence/observations
```

Example:

```text
Alert:
15:32:18

Investigation:
15:17:18 → 15:32:18
```

Make the lookback configurable:

```text
ALERT_KISMET_LOOKBACK_MINUTES=15
```

### Integration requirements

When an alert is generated:

1. Identify the associated device.
2. Resolve its MAC.
3. Determine whether a Kismet sensor covers it.
4. Determine the configured lookback.
5. Query or preserve the relevant investigation reference.
6. Attach the investigation reference to the alert.
7. Allow the analyst to open the investigation from the alert.

Do not copy an entire capture into the alert database.

Store a reference such as:

```text
Alert
├── suspect_device_id
├── event_time
└── investigation_reference
```

---

## Phase 7 — Expand Sensor Coverage

Only begin after Phases 2–6 are stable.

### Objective

Increase physical coverage of the training center.

Coverage depends on:

- physical sensor placement
- Wi-Fi bands
- channels
- APs/BSSIDs
- radio sensitivity
- channel hopping
- number of sensors
- number of radios
- floor/building layout

Do not assume one sensor sees every wireless frame in the building.

### Possible architecture

```text
                    CENTRAL SERVER
                         |
          +--------------+--------------+
          |              |              |
      Sensor A       Sensor B       Sensor C
          |              |              |
       Area A          Area B          Area C
```

Each sensor should report:

```text
sensor_id
hostname
location
interface
status
last_seen
capture state
```

### Coverage validation

For every sensor:

1. Identify visible BSSIDs.
2. Record channels/frequencies.
3. Measure known-device visibility.
4. Compare observations from multiple sensor locations.
5. Identify coverage gaps.
6. Determine whether another sensor or radio is needed.

### Relationship with localization

Later, multiple sensors could provide:

```text
Device
   ↓
Sensor A RSSI
Sensor B RSSI
Sensor C RSSI
   ↓
location estimation
```

Do not implement localization as part of the initial Kismet rollout.

---

## Phase 8 — Revisit Continuous Processing Only If Needed

This phase is deliberately deferred.

Do not build a large continuous ETL pipeline merely because it is technically possible.

First observe real usage.

If analysts mainly do:

```text
Alert
 ↓
Investigate
 ↓
Query Kismet
 ↓
Done
```

keep the system on-demand.

If usage demonstrates a need for:

```text
Kismet
 ↓
continuous parser
 ↓
feature extraction
 ↓
database
 ↓
ML/anomaly detection
```

design that pipeline later.

Potential future features include:

- flow reconstruction
- packet/byte statistics
- temporal behavior features
- activity classification
- behavioral baselines
- anomaly detection
- suspicious communication patterns
- spatial-temporal analysis
- ML-based device/activity profiling

Do not start ML until the underlying observation data has been validated.

---

## Database Strategy

### Existing tables

Continue using the existing models for:

```text
devices
flows
alerts
```

Avoid unnecessary redesign.

### New sensor table

Potential model:

```text
wifi_sensors
────────────────────
id
name
hostname
interface
location
status
last_seen
created_at
updated_at
```

### Structured observation table

Potential model:

```text
wifi_observations
────────────────────────────
id
sensor_id
device_id
mac
timestamp
frame_type
frame_subtype
rssi
channel
frequency
packet_length
capture_reference
created_at
```

Finalize the schema only after examining the actual Kismet output and existing database conventions.

### Raw capture storage

Keep raw captures outside MySQL:

```text
Kismet
 ├── kismetdb
 └── PCAP/PCAPNG
```

MySQL contains structured application data and references.

---

## Storage and Retention

There are two independent retention systems.

### Existing client raw captures

```text
Client Agent
    ↓
Raw files
    ↓
Flow generation
    ↓
Successful processing
    ↓
Safety window
    ↓
Delete
```

The retention period must be configurable.

### Kismet captures

```text
Wi-Fi Sensor
    ↓
Kismet
    ↓
Raw capture
    ↓
Kismet retention policy
    ↓
Rotate/delete
```

Kismet retention must also be configurable.

Neither system should be allowed to grow indefinitely.

---

## Security and Privacy Boundaries

The system is for authorized defensive monitoring of the training-center network.

Focus on:

- passive capture
- device identification
- timestamps
- frame metadata
- packet sizes
- radio metadata
- traffic behavior
- investigation timelines
- anomaly detection

Do not make the initial implementation dependent on:

- credential interception
- payload decryption
- traffic injection
- deauthentication
- packet manipulation
- password cracking
- offensive wireless attacks

Kismet's role is observation and investigation.

Also remember that encrypted Wi-Fi and encrypted application protocols may prevent reconstruction of application-level content. Do not promise that packet capture alone can reveal everything a device did.

---

## Validation Strategy

Every phase must have a concrete validation test.

### Phase 0

```text
Can we prove whether raw files are needed after flow processing?
```

### Phase 1

```text
Can we safely remove processed files without losing functionality?
```

### Phase 2

```text
Can one sensor continuously capture usable 802.11 traffic?
```

### Phase 3

```text
Can Kismet MACs be correlated with existing devices?
```

### Phase 4

```text
Can the backend retrieve observations by device ID and time range?
```

### Phase 5

```text
Can an analyst investigate a device from the UI?
```

### Phase 6

```text
Can an alert automatically expose the relevant investigation?
```

### Phase 7

```text
Can multiple sensors provide sufficient building coverage?
```

### Phase 8

```text
Does actual usage justify continuous processing?
```

---

## Development Rules for the IDE AI

### Rule 1 — Work phase-by-phase

Implement only one phase at a time.

Start with Phase 0, review its findings, then implement Phase 1, and so on.

### Rule 2 — Inspect before modifying

Before changing existing code:

- locate relevant modules
- understand existing architecture
- identify dependencies
- identify current database models
- identify scheduled jobs
- identify configuration conventions

Do not create a parallel mechanism when the existing application already has an appropriate one.

### Rule 3 — Preserve existing behavior

Existing client discovery and flow aggregation must continue working.

Kismet should initially be additive.

### Rule 4 — Prefer configuration

Examples:

```text
RAW_CAPTURE_RETENTION_HOURS
KISMET_RETENTION_HOURS
ALERT_KISMET_LOOKBACK_MINUTES
```

Use the project's existing configuration mechanism.

### Rule 5 — Keep raw and structured data separate

```text
Raw:
PCAP / PCAPNG / Kismet DB

Structured:
MySQL
```

Do not create a giant packet-per-row database unless a demonstrated requirement justifies it.

### Rule 6 — Test with real known devices

Maintain a small ground-truth list:

```text
Device
MAC
IP
Hostname
```

Use it to validate correlation.

### Rule 7 — Log important lifecycle events

At minimum:

- sensor started
- sensor stopped
- capture started
- capture failure
- cleanup started
- cleanup completed
- files deleted
- investigation requested
- investigation failed
- sensor last-seen status

---

## Final Target Workflow

```text
                    DEVICE BASE
                         |
                  Device MAC/IP
                         |
              +----------+----------+
              |                     |
        Client observations     Wi-Fi sensors
              |                     |
        IP/hostname/flows      Kismet observations
              |                     |
              +----------+----------+
                         |
                    Device record
                         |
             +-----------+-----------+
             |                       |
          Normal UI               Alert
                                     |
                                     v
                              Investigation
                                     |
                                     v
                                Device MAC
                                     |
                                     v
                                Kismet data
                                     |
                                     v
                              Time-windowed
                              observations
                                     |
                                     v
                              Analyst timeline
```

The eventual forensic workflow is:

```text
Suspicious event
      ↓
Identify device
      ↓
Resolve MAC
      ↓
Find relevant Kismet sensor
      ↓
Query historical observation window
      ↓
Correlate wireless observations
      ↓
Present timeline
      ↓
Analyze behavior
```

Only after this foundation is reliable should the project move toward automated behavioral analysis or ML.

---

## Recommended Implementation Order

```text
M0  Storage Pipeline Audit
 ↓
M1  Safe Raw-File Retention
 ↓
M2  Single Kismet Sensor Pilot
 ↓
M3  MAC Correlation Proof of Concept
 ↓
M4  Investigation Backend/API
 ↓
M5  Device Investigation UI
 ↓
M6  Alert → Investigation Integration
 ↓
M7  Multi-Sensor Coverage
 ↓
M8  Evaluate Continuous Processing / ML
```

### Critical milestones

#### Milestone A

```text
Raw files can be safely pruned after successful flow processing.
```

#### Milestone B

```text
Kismet can continuously capture useful wireless observations without
breaking the sensor machine's required operation.
```

#### Milestone C

```text
Kismet-observed MAC
        ↓
existing Device MAC
        ↓
existing Device record
```

If Milestone C succeeds, the project has established the fundamental bridge between the existing device-management system and passive wireless sensing.

That bridge becomes the foundation for later Kismet investigation, alert integration, localization, and ML features.
