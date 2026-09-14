# Plan 2 — Device Activity Classification

## Objective

Train a model that estimates what a device is doing from wireless traffic behavior without requiring payload inspection.

The model should produce probabilistic activity estimates over time.

It should answer:

> What activity best explains this device's observed traffic during this window?

It should not claim exact application identity unless the available evidence supports it.

---

## Dependency

Plan 0 must be complete.

Plan 1 is useful but is not a hard dependency for the classifier itself.

---

## Initial activity taxonomy

Start small:

```text
idle
browsing
streaming
file_transfer
other
```

Then expand if the dataset supports it:

```text
chat
voip
p2p
```

Mining should be handled as a separate suspicious-activity detector rather than forced into the normal activity taxonomy.

---

## Input

Use windowed traffic features.

Initial window:

```text
30 seconds
```

Evaluate alternatives later:

```text
15s
30s
60s
```

---

## Features

### Volume

```text
packet_count
byte_count
packet_rate
byte_rate
```

### Packet size

```text
mean
median
std
min
max
percentiles
```

### Timing

```text
mean inter-arrival
median inter-arrival
std inter-arrival
percentiles
```

### Direction

```text
uplink packets
downlink packets
uplink bytes
downlink bytes
uplink/downlink ratios
```

### Bursts

```text
burst_count
burst_rate
burst_duration
burst_size
```

### Radio context

Use only where useful:

```text
signal mean
signal variance
channel/frequency
```

Avoid letting environmental radio conditions dominate the activity prediction.

---

## Dataset strategy

Use public traffic-classification datasets to validate feature choices and establish baselines.

Then collect local labeled traffic.

Controlled scenarios should deliberately generate:

```text
idle
web browsing
streaming
large download
large upload
file sharing
chat
video call
```

Capture the same device and network environment repeatedly.

Label at the window level.

---

## Important dataset rule

Do not randomly split adjacent windows from one continuous session.

Otherwise:

```text
09:00:00 window -> train
09:00:30 window -> test
09:01:00 window -> train
```

can produce unrealistically high scores.

Prefer splitting by:

- capture session
- device
- day
- experiment

depending on the evaluation objective.

---

## Model

Start with a tabular model:

- Random Forest
- Gradient boosting
- LightGBM/XGBoost if available

Compare against a simple baseline.

Do not start with LSTM/CNN unless temporal baseline models fail to provide acceptable results.

---

## Temporal smoothing

Individual windows can be noisy.

Use a short temporal aggregation layer:

```text
window 1
window 2
window 3
window 4
    |
    v
smoothed activity
```

For example, retain the latest N predictions and calculate a stable rolling estimate.

The smoothing layer must remain separate from the model so it can be tuned independently.

---

## Output

Example:

```text
device_id: DEV-017

window:
  14:30:00 - 14:30:30

activity:
  streaming

confidence:
  0.87

probabilities:
  streaming: 0.87
  browsing: 0.08
  file_transfer: 0.03
  other: 0.02

model_version:
  activity-v1
```

Store predictions as derived metadata, not raw traffic.

---

## Dashboard behavior

Show:

```text
Current activity: Streaming
Confidence: 87%

Recent activity:
Browsing -> Streaming -> Streaming -> Streaming
```

Do not show an activity label when confidence is below the configured minimum.

Prefer:

```text
Unknown / mixed
```

over an unjustified classification.

---

## Evaluation

Measure:

- accuracy
- macro F1
- per-class precision/recall
- confusion matrix
- confidence calibration
- performance across devices
- performance across sessions

Pay particular attention to:

```text
streaming vs browsing
file transfer vs streaming
idle vs low-volume activity
```

---

## Deployment

Initially run in shadow mode.

Do not trigger security actions from ordinary activity classification.

Activity predictions should normally be informational.

Only dedicated threat detectors should create security alerts.

---

## Definition of done

Plan 2 is complete when:

- local labeled traffic exists
- public data has been used for feature/baseline validation where appropriate
- feature extraction is stable
- leakage-safe evaluation is implemented
- baseline and ML models are compared
- temporal smoothing is implemented separately
- probabilities/confidence are exposed
- model is versioned
- predictions are stored with provenance
- dashboard can display rolling activity
- low-confidence windows are represented as unknown/mixed
