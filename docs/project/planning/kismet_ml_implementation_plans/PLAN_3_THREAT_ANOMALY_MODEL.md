# Plan 3 — Threat and Anomaly Detection Model

## Objective

Train and deploy a model that identifies wireless traffic behaving like known attacks or suspicious activity.

The model should complement deterministic security rules rather than replace them.

Initial goal:

> Detect suspicious wireless behavior with a measurable confidence score and feed confirmed/high-confidence results into the existing alert path.

---

## Dependency

Plan 0 must be complete.

Plans 1 and 2 are useful context but are not required for the first threat model.

---

## Model scope

Separate two concepts:

### Known attack classification

Examples:

```text
normal
deauthentication
disassociation
scanning
flooding
other_attack
```

### Behavioral anomaly detection

Identify traffic that differs substantially from learned normal behavior.

Do not assume that every anomaly is malicious.

The production result should distinguish:

```text
known attack
suspicious/anomalous
normal
```

---

## Input features

Combine appropriate wireless and traffic features.

### 802.11 features

Where available:

```text
frame_type
frame_subtype
management_frame_rate
control_frame_rate
deauthentication_count
disassociation_count
authentication_failure_count
association_failure_count
retry behavior
channel behavior
```

### Traffic behavior

Reuse the activity window infrastructure:

```text
packet_count
byte_count
packet size statistics
inter-arrival statistics
uplink/downlink ratios
burst statistics
duration
```

### Temporal behavior

Add:

```text
rate change
rolling packet rate
rolling byte rate
persistent behavior
burst periodicity
```

Do not include identifiers such as MAC address as direct predictors of maliciousness.

---

## Dataset strategy

Use labeled wireless intrusion datasets such as AWID3 for initial model development and benchmarking.

Treat public-dataset performance as a baseline, not proof of production accuracy.

The local environment must eventually provide validation data because attack tooling, APs, adapters, radio conditions, and normal traffic distributions differ.

---

## Local validation dataset

Create controlled experiments for supported attack classes where legally and operationally appropriate.

Also collect representative normal traffic:

```text
idle
browsing
streaming
file transfer
normal management traffic
normal roaming/reassociation
```

The model must learn that unusual-looking but legitimate wireless behavior is not automatically malicious.

---

## Mining detection

Mining should be treated as a dedicated suspicious-activity detector.

Candidate signals:

```text
persistent low-bandwidth traffic
regular packet timing
long-lived connections
repeated small packets
stable periodicity
```

Train/evaluate mining detection separately when an appropriate labeled dataset is available.

Do not force mining into the same class taxonomy as deauthentication/scanning attacks.

---

## Model

Start with a tree-based classifier.

Candidate implementations:

- Random Forest
- LightGBM
- XGBoost

Build a simple rules-based baseline as well.

The final system may combine:

```text
deterministic rule
       +
ML probability
       +
temporal confirmation
```

---

## Temporal confirmation

Do not generate a high-severity alert from one uncertain window.

Example:

```text
window 1 -> 0.91
window 2 -> 0.94
window 3 -> 0.96
```

can become:

```text
confirmed suspicious behavior
```

while:

```text
window 1 -> 0.91
window 2 -> 0.31
window 3 -> 0.22
```

should not.

Make confirmation thresholds configurable.

---

## Output

Example:

```text
device_id: DEV-031

classification:
  suspected_mining

confidence:
  0.94

evidence_window:
  14:30:00 - 14:32:00

model:
  threat-v1

status:
  suspicious
```

For known attacks:

```text
classification:
  deauthentication_attack

confidence:
  0.97
```

---

## Alert integration

Reuse the existing alert path.

Do not create a separate ML notification system.

Flow:

```text
Threat model
    |
    v
prediction
    |
    v
temporal confirmation
    |
    v
alert policy
    |
    v
existing alerts table
    |
    v
existing SSE/dashboard path
```

The ML system should provide evidence/provenance:

```text
model version
feature/window reference
confidence
classification
timestamp
sensor
device
```

---

## Auto-response policy

Initial deployment:

```text
ML detection
    |
    v
shadow/log only
```

Then:

```text
high-confidence + repeated
    |
    v
alert
```

Only after validation should any ML result be allowed to influence automated quarantine or remote actions.

This is particularly important because external datasets have a domain-gap risk.

---

## Evaluation

Measure:

- precision
- recall
- F1
- ROC-AUC where appropriate
- PR-AUC for rare attacks
- false-positive rate
- false-negative rate
- detection latency
- performance per attack class
- performance on local traffic

For security operation, false-positive behavior is as important as headline accuracy.

---

## Model drift

Monitor:

```text
prediction distribution
confidence distribution
false-positive reports
new traffic patterns
new device types
```

A model trained on a controlled dataset should not be assumed permanently valid.

Store enough metadata to retrain and compare versions.

---

## Testing

Test:

1. Normal wireless traffic.
2. Known attack captures.
3. Mixed normal/attack traffic.
4. Bursty legitimate traffic.
5. Roaming/reassociation.
6. Multiple devices simultaneously.
7. Missing fields.
8. Kismet database rotation.
9. Worker restart.
10. Model-version changes.
11. Repeated attack windows.
12. Mining-like periodic traffic.
13. Non-mining periodic traffic.

---

## Definition of done

Plan 3 is complete when:

- a public-data baseline has been evaluated
- local validation data exists
- normal traffic is represented
- known attacks have measurable performance
- mining is independently evaluated where supported
- temporal confirmation is implemented
- predictions are versioned and stored
- alerts reuse the existing alert infrastructure
- shadow-mode performance has been reviewed
- false-positive behavior is acceptable
- automated response remains disabled until explicitly approved
