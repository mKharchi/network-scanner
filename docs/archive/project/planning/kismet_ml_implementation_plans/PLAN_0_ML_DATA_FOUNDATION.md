# Phase 0 ML Data Foundation

## Status

This document is the authoritative, research-revised Phase 0 implementation plan. It supersedes earlier Phase 0 wording that did not capture the research findings, and it remains aligned with the existing Kismet capture architecture and API.

This plan does not replace Kismet. It does not introduce a separate capture service. It does not change the runtime capture path. It only defines the required ML extraction, feature, dataset, and lifecycle contracts required for downstream fingerprinting, activity, threat, and mining models.

## Dependency relationship

This plan remains the foundation for the subsequent model plans:

1. `PLAN_0_ML_DATA_FOUNDATION.md`
2. `PLAN_1_DEVICE_FINGERPRINTING.md`
3. `PLAN_2_DEVICE_ACTIVITY_MODEL.md`
4. `PLAN_3_THREAT_ANOMALY_MODEL.md`

Plan 0 must complete before Plans 1–3 can be implemented. The downstream model work depends on the feature schemas and dataset contracts defined here.

---

## Summary

Phase 0 extends the current Kismet-to-ML extraction pipeline from a basic normalized observation stream into a dual-path ML foundation. The system will continue to ingest the existing Kismet `.kismet` SQLite captures and decode them via the existing server-side extraction layer, but the ML path must now preserve structured 802.11 metadata that was previously suppressed or discarded.

The component architecture remains:

```text
Kismet
   ↓
.kismet SQLite
   ↓
Phase 0 ML extraction layer
   ├── Structured Observation Engine
   └── Control/Threat Rate Engine
            ↓
      derived feature schemas
            ↓
      offline datasets + online inference
```

Implementation must preserve the existing Kismet capture architecture and the current API behavior. The ML pipeline must read the local capture database in a controlled, read-only way and generate derived observations, windowed activity features, and threat-rate ticks without duplicating raw packet payloads into ML storage.

---

## 1. Required architectural changes

### 1.1 Dual-path extraction

Phase 0 must implement a dual-path extraction design.

#### Path A: Structured Observation Engine

Used for fingerprinting, activity features, and general threat/behavior representation. It must preserve or extract:

- timestamp
- source MAC
- destination MAC
- BSSID
- frame type and subtype
- frame length
- RSSI/signal
- frequency/channel
- sequence number
- Frame Control flags
- To-DS / From-DS
- Retry
- Power Management
- management-frame Information Elements
- vendor-specific IE data

For fingerprinting specifically, it must explicitly preserve:

- ordered IE tag sequence
- vendor-specific IE OUIs
- HT capabilities
- VHT capabilities
- HE capabilities
- WMM presence
- randomized-MAC indication

#### Path B: Control/Threat Rate Engine

This path does not restore full raw storage of every control frame. Instead, it must aggregate high-frequency threat-relevant control-frame counters into one-second rate ticks. At minimum, the system must track:

- RTS count
- CTS count
- deauthentication count
- disassociation count
- authentication request count
- association request count
- null-data count
- retry-related indicators if available
- sequence-gap indicators
- RSSI statistics

This allows threat detection without reintroducing unnecessary storage overhead.

### 1.2 Local schema verification before implementation

The local Kismet schema must be inspected before writing extraction code. This is a hard requirement.

Implementation must verify:

- `packets` table columns
- packet payload representation
- `dot11` JSON/device structures
- availability of probe-request IE data
- exact timestamp representation
- sequence-number availability
- Frame Control representation
- signal/frequency fields
- whether `BSSID` is actually present as a database column
- whether radiotap length must be parsed before 802.11 headers are located
- device JSON decoding requirements for `devices.device` and Kismet JSON structures

The plan explicitly forbids implementation against assumptions from research alone. The local Kismet schema determines the extraction method.

---

## 2. Local schema safeguards

The updated plan explicitly states that:

- the local `packets` table must be inspected before implementation;
- BSSID must not be assumed to be a database column;
- radiotap length must be parsed before locating 802.11 headers;
- sequence and Frame Control offsets must be validated with fixtures;
- `devices.device` and Kismet JSON structures must be decoded and verified;
- raw payloads may be parsed in memory but must not be duplicated into ML storage.

These safeguards are mandatory and are part of the Phase 0 implementation contract.

---

## 3. Fingerprint observation schema

Create a stable internal schema equivalent to:

```text
FingerprintObservation

observation_id
timestamp_epoch_ms
source_mac
is_randomized_mac

frame_subtype
sequence_number

signal_dbm
frequency_mhz

ie_tag_sequence
ie_vendor_ouis

ht_capabilities_hex
vht_capabilities_hex
he_capabilities_hex

wmm_capabilities_present
```

Fingerprint observations must be captured for:

- Probe Request
- Probe Response
- Association Request
- Reassociation Request
- Association Response where useful

The exact fields are subject to local Kismet schema verification, but the plan requires the extraction of the IE sequence, vendor OUIs, capability bitmasks, and sequence numbers for physical-device identity linking.

### 3.1 Randomized MAC detection

Add:

```text
is_randomized_mac
```

This should be derived from the local-administered-address bit:

```text
MAC first_octet & 0x02
```

This is metadata for the fingerprinting pipeline and must not be used as a direct feature for identity matching.

### 3.2 Frame Control extraction

Phase 0 must expose the following header-level signals:

```text
To-DS
From-DS
Retry
Power Management
```

These become foundational features for:

- activity classification
- mining detection
- threat detection

Direction must be derived from To-DS / From-DS only when the infrastructure-mode interpretation is valid.

---

## 4. Traffic window schema and temporal aggregation

The research recommends a sliding window design with:

```text
window length = 30 seconds
hop = 5 seconds
```

The plan requires overlapping windows and a configurable window abstraction so 15s/30s/60s can be evaluated later.

```text
TrafficWindow

window_id
client_mac
window_start_ms
window_end_ms

total_frame_count
total_byte_count

uplink_frame_count
downlink_frame_count

uplink_byte_count
downlink_byte_count

retry_frame_count

data_frame_count
mgmt_frame_count
ctrl_frame_count

derived_features_json
```

The derived JSON or object must contain versioned names and values. Downstream models must not depend directly on raw Kismet database columns.

### 4.1 Required deterministic activity features

At minimum, the implementation must compute the following deterministic, versioned features:

```text
packet_rate
byte_rate

mean_packet_size
median_packet_size
packet_size_std

mean_interarrival
median_interarrival
interarrival_std

uplink_ratio
downlink_ratio

burst_rate
burst_duration

periodicity_score
```

Definitions:

- packet rate = N / window_duration
- byte rate = sum(frame_length) / window_duration
- mean packet size = mean(frame_length)
- median packet size = median(frame_length)
- packet-size standard deviation = frame-length standard deviation
- mean inter-arrival time = mean(delta between consecutive frames)
- median inter-arrival time = median(delta between consecutive frames)
- inter-arrival time standard deviation = standard deviation of consecutive-frame deltas
- uplink ratio = uplink_bytes / total_bytes
- downlink ratio = downlink_bytes / total_bytes
- burst rate = number of detected burst events per window normalized appropriately
- burst duration = average duration of detected bursts
- periodicity score = normalized autocorrelation of a time-binned frame-count series

These features must define:

- bin size
- lag range
- normalization
- minimum sample count
- missing-data behavior

and the transformation must be versioned.

### 4.2 Burst definition

The implementation must keep the burst threshold configurable rather than hardcode it permanently.

Initial research definition:

- a burst begins when instantaneous IAT <= 2 ms for more than 3 consecutive frames

This threshold is a starting point and must remain configurable.

---

## 5. Threat tick schema

Create a dedicated one-second rolling threat observation:

```text
ThreatTick

threat_tick_id
timestamp_sec
channel_frequency
bssid

deauth_frame_count
disassoc_frame_count

assoc_req_count
auth_req_count

null_data_frame_count

sequence_gap_delta_sum

mean_rssi_dbm
rssi_std_dev
```

This is intentionally different from the 30-second traffic window because threat events such as floods are fast-moving and require higher temporal resolution.

### 5.1 Control-frame handling

The old normal observation path may continue suppressing control-frame details, but Phase 0 must now maintain a threat-specific counter path for:

- RTS
- CTS
- other threat-relevant control activity that can be safely aggregated

These counters must be stored as aggregate observations instead of duplicating raw packets.

---

## 6. Labeling model and provenance

Phase 0 must support versioned labeling metadata.

### 6.1 Label categories

#### Fingerprint labels

Primary:

```text
physical_device_guid
```

Optional auxiliary:

```text
vendor
OS family
```

#### Activity labels

Support:

```text
idle
browsing
streaming
file_transfer
chat
voip
p2p
other
```

#### Threat labels

Support:

```text
normal
deauth_flood
disassoc_flood
scanning
rogue_ap
power_save_injection
anomaly
```

#### Mining labels

Separate binary label:

```text
mining
non_mining
```

Mining must not be embedded into the normal activity classifier.

### 6.2 Label provenance

Every label source must be tracked as one of:

- ground truth
- weak label
- derived label
- manually reviewed

The plan forbids silently mixing label types.

### 6.3 Multi-label probability vectors

The schema must support multi-label activity probabilities rather than assuming a single hard class. Example:

```text
streaming: 0.72
browsing: 0.18
file_transfer: 0.08
other: 0.02
```

The storage model must permit vector-valued outputs and must not be restricted to a single mandatory argmax label.

---

## 7. Dataset generation and leakage-safe splitting

Phase 0 must provide formal dataset tooling for offline training and evaluation.

### 7.1 Dataset provenance

Every ML dataset must record:

```text
dataset_version
feature_schema_version
source_dataset
capture period
capture environment
label source/type
split strategy
generation timestamp
```

### 7.2 Group-aware, leakage-safe splits

Phase 0 must support group-aware splitting and must never randomly split overlapping sliding windows.

#### Fingerprinting

Group by:

```text
physical device + capture session
```

#### Activity and mining

Group by:

```text
client/session/day
```

#### Threat

Use time-block split by capture day/session.

The split metadata must be stored with the dataset version.

### 7.3 Required dataset manifests

Each dataset should include:

- source metadata
- capture manifests
- schema version
- label provenance
- split metadata
- generation metadata

The plan requires explicit dataset provenance and source-capture manifests.

---

## 8. Model schema compatibility and registry requirements

The ML registry must enforce schema compatibility checks before accepting a model or model artifact.

Required checks:

- feature column compatibility
- schema-version compatibility
- dataset-version compatibility
- label schema compatibility
- aggregation-window compatibility
- prediction output shape compatibility

The registry must reject incompatible model artifacts and require a clear record of which feature schema version the model was trained against.

---

## 9. Shadow processing, restart resilience, and checkpointing

Phase 0 must include checkpointed shadow processing that survives capture rotation and restart.

This means:

- processing state must be checkpointed
- in-flight windows must survive capture rotation
- processing resumes after restart without duplicating or dropping data
- the ML pipeline can resume safely without corrupting downstream data
- the raw Kismet files remain the source of truth

This requirement applies to intermediate processing state and dataset generation pipelines.

---

## 10. External benchmark data usage

Public datasets must remain separate from local production data.

### Fingerprinting benchmarks

- Mendeley labelled probe-request dataset
- UJI Probes / UJI Probes Revisited

### Activity benchmarks

- ISCXVPN2016

### Mining benchmark

- CNT21

### Threat benchmark

- AWID / AWID2 / AWID3

These sources are used for:

- feature validation
- baseline models
- benchmark comparison
- transfer-learning experiments

They are not a substitute for locally captured production data.

The final production models should be validated and fine-tuned on local Kismet captures.

---

## 11. Explicitly unsupported assumptions

The Phase 0 design must not require or assume:

- application payload access
- Layer-3 / Layer-4 features that are unavailable on encrypted Wi-Fi data
- flow IDs derived from 5-tuples when Kismet only exposes layer-2 metadata
- random splitting of sliding windows
- direct dependence on raw Kismet columns in downstream model schemas
- raw payload duplication into ML storage

Phase 0 must remain viable when WPA2/WPA3 payloads are hidden and when the capture data is a Kismet-only, layer-2 view.

---

## 12. Production model assumptions and interfaces

Phase 0 is model-agnostic, but it must expose clean, versioned interfaces for the downstream model families.

### Identity

```text
IE feature vector
        ↓
pairwise similarity model
        ↓
identity clustering
```

### Activity

```text
30s sliding feature vector
        ↓
LightGBM classifier
```

### Threat

```text
1s rate detection
        +
Isolation Forest
        +
supervised threat classifier
```

### Mining

```text
30/60s behavioral features
        ↓
XGBoost binary classifier
```

None of these model choices are hard-coded into the core Phase 0 contract. The contract must remain flexible enough for future model changes.

---

## 13. Storage guidance

Prefer storing derived ML observations/features rather than raw packet duplication.

Recommended internal objects:

```text
fingerprint_observations
traffic_windows
threat_ticks
ml_labels
ml_processing_state
```

Each derived object must retain provenance:

```text
sensor_id
capture_file
timestamp/window
source device/MAC
feature_schema_version
```

The raw Kismet database remains the source of truth.

---

## 14. Likely implementation modules

The implementation should adapt the existing extraction flow, including

```text
server_components/kismet_service.py
```

and may add dedicated modules such as:

```text
server_components/ml/
    schemas/
    extraction/
    features/
    datasets/
    inference/
```

Likely module names:

```text
fingerprint.py
activity.py
threat.py
windows.py
labels.py
splits.py
registry.py
```

The exact filenames may follow repository conventions, but the responsibilities and schema contracts must match this plan.

---

## 15. Phase 0 completion criteria

Phase 0 is complete only when all of the following are true:

### Extraction

- management-frame IE data can be extracted
- sequence numbers can be extracted
- Frame Control flags can be extracted
- randomized MAC state can be derived
- control-frame threat counters exist
- timestamps and frame lengths are preserved

### Feature engineering

- 30s / 5s-hop sliding windows exist
- traffic statistics are deterministic
- burst metrics exist
- periodicity feature exists
- directional ratios exist
- 1s threat ticks exist

### Data engineering

- schemas are versioned
- labels are supported
- label provenance is tracked
- leakage-safe splits are supported
- dataset provenance is recorded
- source-capture manifests are present
- model/schema compatibility checks are enforced

### ML interface

- all feature schemas are consumable by offline training
- production inference can consume the same feature contract
- model/version metadata can be recorded
- prediction shapes support multi-label activity probabilities

### Safety

- Kismet capture behavior remains stable
- raw payload duplication is avoided
- current Kismet API behavior is preserved
- ML processing does not run expensive work inside HTTP handlers
- processing can resume safely after restart
- checkpointed shadow processing survives rotation/restart

### Tests

The phase must include verification that:

- management IE parsing works against real Kismet fixtures
- sequence numbers and frame-control fields decode correctly
- radiotap and 802.11 header offsets are validated
- `devices.device` and Kismet JSON structures are decoded correctly
- randomized-MAC detection matches expected behavior
- 30s / 5s sliding windows produce deterministic outputs
- 1s threat ticks capture deauth/disassoc/auth/assoc/RTS/CTS/null-data/retry/sequence-gap/RSSI events
- leakage-safe dataset splits prevent overlap across training/evaluation
- dataset provenance and label provenance are recorded in the generated artifacts
- model registry compatibility checks reject mismatched schemas

---

## 16. Contradiction check and authoritative status

This document is intentionally written to supersede older Phase 0 wording and to resolve earlier contradictions.

It explicitly states:

- the Kismet capture architecture and API remain unchanged;
- the ML system remains a derived feature pipeline on top of Kismet capture;
- the older assumption of a single flat observation stream is replaced by dual-path extraction;
- threat detection is not forced into the same window abstraction as activity classification;
- mining is treated as a separate detector under the threat/intelligence layer;
- all label, split, and dataset requirements are explicit and versioned;
- no raw payload duplication is permitted.

This plan contains no contradictory older requirements. It is the authoritative research-revised Phase 0 plan.

---

## 17. Scope boundary

This plan does not implement the downstream ML models themselves. It only establishes the foundation required by the later fingerprinting, activity, threat, and mining model plans.

It does not alter the application runtime configuration or Kismet capture behavior. It is a data-layer and schema definition plan only.

The goal of this phase is to enable future training workflows without revisiting the Kismet ingestion architecture again:

```text
Kismet
  ↓
Phase 0
  ↓
┌──────────────────┬──────────────────┬──────────────────┐
│                  │                  │
Fingerprint       Activity           Threat
features          windows            ticks/features
│                  │                  │
↓                  ↓                  ↓
Model 1           Model 2            Model 3+
```

This plan is therefore the required foundation for the downstream ML roadmap.
