# Plan 0 — ML Data Foundation

## Objective

Build the shared ML data and inference foundation on top of the existing Kismet integration.

This phase does **not** train production models. It makes Kismet observations reproducible, structured, feature-complete, labelable, and consumable by three future models:

1. Device fingerprinting / identity linking
2. Device activity classification
3. Threat / anomaly classification

The Linux server remains the only Kismet capture owner. ML inference consumes stored Kismet observations and must not interfere with capture.

---

## Existing system assumptions

Kismet runs on the Linux sensor/server and stores `.kismet` SQLite databases locally.

Existing components include:

- `server_components/kismet_service.py`
- `server_components/kismet_retention.py`
- `scripts/kismet_retention.py`
- Kismet HTTP bound to localhost
- 48-hour capture retention
- existing device wireless-observation API
- existing alert path
- existing background producer/consumer patterns

Do not replace the existing Kismet observation path. Add an ML-specific extraction path beside it.

---

## Architecture

```text
Kismet
  |
  v
.kismet SQLite
  |
  +-------------------------+
  |                         |
  v                         v
Existing observation     ML extraction
service                      |
                             +-------------------+
                             |                   |
                             v                   v
                     Management frames     Traffic/security
                             |                   |
                             v                   v
                       Fingerprints       Window/features
                             |                   |
                             +---------+---------+
                                       |
                                       v
                                ML data layer
                                       |
                    +------------------+------------------+
                    |                  |                  |
                    v                  v                  v
               Fingerprint        Activity          Threat model
                  model             model               model
```

---

## Deliverables

### 1. ML module structure

Create a dedicated ML package, for example:

```text
server_components/ml/
    __init__.py
    schemas.py
    extraction/
        __init__.py
        kismet_ml_extractor.py
        management.py
        traffic.py
        security.py
    features/
        __init__.py
        fingerprint.py
        activity.py
        threat.py
        windows.py
    datasets/
        __init__.py
        writer.py
        labels.py
        splits.py
    inference/
        __init__.py
        model_interface.py
        registry.py
```

Keep training code separate from production server code if practical.

---

### 2. Fingerprint observation schema

Create a stable schema for management-frame observations.

Minimum conceptual fields:

```text
sensor_id
capture_file
timestamp
source_mac
destination_mac
frame_type
frame_subtype
channel
frequency
signal

supported_rates
extended_supported_rates
ht_capabilities
vht_capabilities
he_capabilities
rsn_information
wmm_information
vendor_specific_ies
other_information_elements

sequence_number
```

The exact Kismet column mappings must be verified against the installed Kismet database schema before implementation.

Do not invent fields that are not available from the local capture.

---

### 3. Traffic window schema

Create a time-window abstraction independent of Kismet.

Initial window:

- 30 seconds
- configurable later
- sliding-window support should be designed for

Example:

```text
device_key
sensor_id
start_time
end_time

packet_count
byte_count

mean_packet_size
median_packet_size
std_packet_size
min_packet_size
max_packet_size

mean_interarrival
median_interarrival
std_interarrival

uplink_packets
downlink_packets
uplink_bytes
downlink_bytes

burst_count
burst_rate

signal_mean
signal_std
```

Direction must be derived only where the captured 802.11 metadata supports it.

---

### 4. Threat feature schema

Create a separate threat/security feature representation.

Reuse traffic features where appropriate, then add available wireless-security indicators such as:

```text
frame_type
frame_subtype
management_frame_rate
control_frame_rate
retry statistics
deauthentication count
disassociation count
authentication failures
association failures
channel behavior
```

Only include features demonstrably available from the Kismet capture.

---

## Feature extraction rules

### Fingerprinting

Preserve raw/structured Information Elements rather than reducing management frames to only:

- type
- subtype
- signal
- channel
- length

Fingerprinting requires the richer management-frame representation.

### Activity

Aggregate data-frame observations into windows.

Calculate packet, byte, timing, direction, and burst statistics.

### Threat

Build a feature vector capable of representing both traffic behavior and 802.11 attack indicators.

---

## Dataset format

Use a versioned, tabular dataset format for training.

Recommended structure:

```text
datasets/
    fingerprint/
    activity/
    threat/
```

Every generated dataset should record:

```text
dataset_version
feature_schema_version
source
capture_period
label_definition
generation_timestamp
```

Do not mix incompatible feature schemas silently.

---

## Labeling

Build a labeling mechanism that can support:

- external/public datasets
- controlled local experiments
- manually reviewed windows
- future investigation labels

Labels must be explicit.

Example activity labels:

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

Example threat labels:

```text
normal
deauthentication
disassociation
scanning
flooding
other_attack
```

Mining should be represented explicitly if the training dataset supports it.

---

## Training split policy

Never randomly split adjacent windows from the same capture without considering leakage.

Prefer:

```text
training captures/devices
validation captures/devices
test captures/devices
```

For fingerprinting, evaluate on devices/MAC situations not trivially memorized by the model.

For activity and threat models, preserve temporal separation where possible.

---

## Model interface

Define a common production interface.

Conceptually:

```python
predict(features) -> Prediction
```

Prediction should contain:

```text
prediction
confidence
probabilities
model_name
model_version
feature_schema_version
timestamp
```

The server should not care whether the implementation uses Random Forest, LightGBM, XGBoost, or another model.

---

## Model registry

Create a small registry/configuration mechanism:

```text
fingerprint-v1
activity-v1
threat-v1
```

Store:

- model artifact path
- model version
- expected feature schema version
- training dataset version
- enabled/disabled state

Never load an arbitrary model artifact without checking its schema/version.

---

## Background processing

Follow the existing background worker pattern.

Do not run expensive ML extraction directly inside HTTP request handlers.

Suggested flow:

```text
Kismet DB
  |
  v
ML worker
  |
  v
new observations since checkpoint
  |
  v
feature extraction
  |
  v
windows
  |
  v
inference
```

Persist a processing checkpoint so the worker does not repeatedly process the same capture range.

---

## Storage

Store ML predictions separately from raw Kismet packets.

Example conceptual tables:

```text
ml_activity_predictions
ml_threat_predictions
device_fingerprints
ml_processing_state
```

Raw packet data remains governed by the existing Kismet retention policy.

Predictions should contain provenance back to:

- device
- sensor
- capture file
- time window
- model version

---

## Privacy and retention

Do not duplicate raw packet payloads into ML tables.

Store derived features and predictions instead.

The existing 48-hour Kismet retention remains authoritative unless a future explicit investigation-hold policy says otherwise.

---

## Testing

Before moving to model training, prove:

1. Kismet databases can be read safely.
2. New observations can be extracted incrementally.
3. Fingerprint observations contain the required management-frame information.
4. Traffic windows are deterministic.
5. Feature extraction is deterministic.
6. Direction calculations are correct for available frame metadata.
7. Missing fields do not crash extraction.
8. Dataset generation is reproducible.
9. Dataset versions are recorded.
10. Model interface can load a dummy model and return a versioned prediction.
11. Worker restart does not duplicate processing.
12. Existing Kismet API behavior remains unchanged.

---

## Definition of done

Plan 0 is complete when:

- Kismet remains the sole capture source.
- Fingerprint observations can be extracted.
- Activity/threat windows can be generated.
- All three feature schemas are versioned.
- Labeled datasets can be generated.
- Train/validation/test splits can be generated safely.
- Production inference has a common interface.
- Model artifacts can be registered and versioned.
- Background inference can consume new observations.
- Existing Kismet functionality and retention behavior remain intact.

Only after this should model training begin.
