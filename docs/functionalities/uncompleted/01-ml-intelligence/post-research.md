# Phase 0 ML Foundation — Research-Driven Updates

A new dataset/feature research phase has been completed.

This research changes and refines the Phase 0 implementation requirements. Treat the following as the current authoritative implementation guidance for Phase 0.

## Overall architecture

The system remains:

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

Kismet remains the sole wireless capture system.

Do NOT replace the existing Kismet capture architecture.

Do NOT duplicate raw packet payloads.

Do NOT introduce a separate capture service.

ML training remains offline. Production inference must run on the existing Linux host using CPU resources without interfering with Kismet capture.

---

# 1. Major Phase 0 change: dual-path extraction

The existing observation path filters control-frame noise. That behavior is still useful for the normal observation API, but it is insufficient for ML threat detection.

Phase 0 must therefore add a dual-path architecture.

## Path A — Structured Observation Engine

Used for:

- fingerprinting
- activity classification
- general threat features

It must preserve/extract:

- timestamp
- source MAC
- destination MAC
- BSSID
- frame type/subtype
- frame length
- RSSI/signal
- frequency/channel
- sequence number
- Frame Control flags
- To-DS
- From-DS
- Retry
- Power Management
- management-frame Information Elements
- vendor-specific IE data

For fingerprinting specifically, preserve:

- ordered IE tag sequence
- vendor-specific IE OUIs
- HT capabilities
- VHT capabilities
- HE capabilities
- WMM presence
- sequence number
- randomized-MAC indication

The research indicates these fields are required because MAC-only or OUI-only information cannot support persistent physical-device identity linking across MAC randomization.

## Path B — Control/Threat Rate Engine

Do NOT restore full raw storage of every control frame.

Instead, create high-frequency counters for threat-relevant control frames.

Use 1-second aggregation ticks.

At minimum track:

- RTS count
- CTS count
- deauthentication count
- disassociation count
- authentication request count
- association request count
- null-data count
- retry-related indicators where available
- sequence-gap indicators
- RSSI statistics

This allows threat detection without reintroducing unnecessary storage overhead.

---

# 2. New fingerprint observation schema

Create a stable internal schema approximately equivalent to:

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

Capture fingerprint observations for:

- Probe Request
- Probe Response
- Association Request
- Reassociation Request
- Association Response where useful

The exact underlying Kismet fields must be verified against the installed `.kismet` schema.

Do not assume JSON paths or column names without checking the actual local Kismet database.

The research indicates that IE data may be partially available through Kismet device JSON and must be explicitly parsed/extracted rather than relying solely on the current normalized observation layer.

---

# 3. Randomized MAC detection

Add:

```text
is_randomized_mac
```

This should be derived from the locally administered-address bit:

```text
MAC first_octet & 0x02
```

This is metadata for the fingerprinting pipeline.

Do NOT use the MAC address itself as a model feature for identity matching.

---

# 4. Frame Control extraction

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

Direction must be derived from To-DS / From-DS when the infrastructure-mode interpretation is valid.

Do not infer direction from assumptions outside the captured frame metadata.

---

# 5. Activity representation is now explicitly sliding-window based

The research recommends:

```text
window length = 30 seconds
hop = 5 seconds
```

This is the initial Phase 0 standard.

Do NOT implement only isolated non-overlapping windows.

The reason is that overlapping windows reduce state-transition boundary problems and provide better temporal continuity.

The window abstraction should remain configurable so 15s/30s/60s can be evaluated later.

---

# 6. Traffic Window schema

Create:

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

The derived JSON/object must contain versioned feature names and values.

Do not make downstream models depend directly on arbitrary Kismet database columns.

---

# 7. Required derived activity features

At minimum implement:

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

Definitions must be deterministic and versioned.

The research specifies:

### Packet rate

```text
N / window_duration
```

### Byte rate

```text
sum(frame_length) / window_duration
```

### Mean packet size

```text
mean(frame_length)
```

### Median packet size

```text
median(frame_length)
```

### Packet-size standard deviation

Standard deviation of frame lengths.

### Mean IAT

Mean timestamp delta between consecutive frames for the client.

### Median IAT

Median consecutive-frame timestamp delta.

### IAT standard deviation

Standard deviation of consecutive-frame timestamp deltas.

### Uplink ratio

```text
uplink_bytes / total_bytes
```

### Downlink ratio

```text
downlink_bytes / total_bytes
```

### Burst rate

Initial research definition:

A burst begins when instantaneous IAT is <= 2 ms for more than 3 consecutive frames.

Keep this threshold configurable rather than hardcoded permanently.

### Burst duration

Average duration of detected bursts.

### Periodicity score

Use normalized autocorrelation of a time-binned frame-count series.

The implementation must define:

- bin size
- lag range
- normalization
- minimum sample count
- missing-data behavior

and version the transformation.

---

# 8. New threat tick schema

Create a dedicated 1-second rolling threat observation:

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

This is intentionally different from the 30-second traffic window.

Reason:

- threat events such as floods require fast detection
- activity classification requires broader statistical context

Do not force both problems into one window representation.

---

# 9. Control-frame handling

The old normal observation path may continue suppressing control-frame details.

However, Phase 0 must now have a threat-specific counter path for:

- RTS
- CTS
- other threat-relevant control activity that can be safely aggregated

Store counters, not unnecessary raw payload duplicates.

This is important for identifying high-volume denial/jamming behavior.

---

# 10. Dataset labeling support

Phase 0 must support versioned labeling metadata.

### Fingerprint

Primary:

```text
physical_device_guid
```

Optional auxiliary:

```text
vendor
OS family
```

### Activity

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

### Threat

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

### Mining

Separate binary label:

```text
mining
non_mining
```

Do not force mining into the normal activity classifier.

---

# 11. Important: support multi-label activity probabilities

Although initial activity classification may use a dominant activity label, real devices can perform multiple activities simultaneously.

Phase 0 must therefore permit models to emit probability vectors rather than assuming a single hard class.

Example:

```text
streaming: 0.72
browsing: 0.18
file_transfer: 0.08
other: 0.02
```

Do not design the storage model around a single mandatory argmax label.

---

# 12. Dataset splitting / leakage prevention

This is now a formal Phase 0 requirement.

Never randomly split overlapping sliding windows.

Overlapping windows can leak essentially the same traffic into both training and test.

Phase 0 dataset tooling must support group-aware splits.

Fingerprinting:

```text
group by physical device + capture session
```

Activity/mining:

```text
group by client/session/day
```

Threat:

```text
time-block split by capture day/session
```

The split metadata must be stored with the dataset version.

---

# 13. Required dataset provenance

Every generated ML dataset must record:

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

Track label provenance as:

- ground truth
- weak label
- derived label
- manually reviewed

Do not silently mix them.

---

# 14. Keep public datasets separate from local production data

Research conclusions:

### Fingerprinting

Primary benchmark sources:

- Mendeley labelled probe-request dataset
- UJI Probes / UJI Probes Revisited

### Activity

Primary benchmark:

- ISCXVPN2016

### Mining

Primary dedicated dataset:

- CNT21

### Threat

Primary wireless intrusion benchmark:

- AWID/AWID2/AWID3

Use public datasets for:

- feature validation
- baseline models
- initial experimentation
- benchmark comparison

Do NOT assume benchmark accuracy transfers directly to our Kismet environment.

The final production models should be validated/fine-tuned using locally captured data.

---

# 15. Explicitly ignore unavailable/incompatible features

Do NOT design Phase 0 around:

```text
application_payload
```

or Layer-3/Layer-4 features that are unavailable in encrypted Kismet frame metadata.

The activity architecture must remain viable when WPA2/WPA3 payloads are hidden.

Similarly, do not assume a 5-tuple flow exists in the current Kismet-only architecture.

Use layer-2 timing/size/direction metadata as the primary activity representation.

---

# 16. Production model assumptions

Phase 0 should be model-agnostic, but the current research direction is:

### Identity

```text
IE feature vector
        ↓
pairwise similarity model
        ↓
identity clustering
```

Initial candidate:

```text
LightGBM + clustering
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

Separate:

```text
30/60s behavioral features
        ↓
XGBoost binary classifier
```

Do not hard-code these model types into Phase 0.

Phase 0 must provide clean, versioned feature contracts that allow the models to change later.

---

# 17. Storage guidance

Prefer storing derived ML observations/features rather than raw packet duplication.

Possible internal tables/files:

```text
fingerprint_observations
traffic_windows
threat_ticks
ml_labels
ml_processing_state
```

Every derived object should retain provenance:

```text
sensor_id
capture_file
timestamp/window
source device/MAC
feature_schema_version
```

The raw Kismet database remains the source of truth.

---

# 18. Files/modules to update

Adapt the existing implementation plan to likely require:

```text
server_components/kismet_service.py
```

for richer extraction where appropriate.

Add dedicated modules rather than putting every feature into `kismet_service.py`, for example:

```text
server_components/ml/
    schemas/
    extraction/
    features/
    datasets/
    inference/
```

Likely conceptual modules:

```text
fingerprint.py
activity.py
threat.py
windows.py
labels.py
splits.py
registry.py
```

Exact filenames may follow the existing repository conventions.

---

# 19. Important implementation rule

Before writing extraction code, inspect the actual local `.kismet` schema and verify:

- packets table columns
- packet payload representation
- `dot11` JSON/device structures
- availability of probe-request IE data
- exact timestamp representation
- sequence-number availability
- Frame Control representation
- signal/frequency fields

Do not implement against assumptions from the research report.

The research tells us WHAT we need.

The local Kismet schema determines HOW it must be extracted.

---

# 20. Phase 0 completion criteria

Phase 0 is now complete only when all of the following are true:

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

### ML interface

- all feature schemas are consumable by offline training
- production inference can consume the same feature contract
- model/version metadata can be recorded

### Safety

- Kismet capture behavior remains stable
- raw payload duplication is avoided
- current Kismet API behavior is preserved
- ML processing does not run expensive work inside HTTP handlers
- processing can resume safely after restart

---

## Final directive

Do NOT start implementing the three ML models yet.

First update and implement **Phase 0 — ML Data Foundation** according to the requirements above.

The goal of this phase is to make the following future training workflows possible without changing the Kismet ingestion architecture again:

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

Treat this document as a research-driven revision of the original Phase 0 plan.
