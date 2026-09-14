# ML Device Classification — Implementation Plan

## 1. Objective

Introduce an ML-assisted device classification system that automatically determines the broad type of devices discovered by the network clients.

The system should use the passive observations already collected by the platform, including:

* MAC OUI / vendor
* DHCP information
* DHCP option fingerprints
* mDNS observations
* mDNS TXT records
* SSDP observations
* LLMNR observations
* NBNS observations
* Hostname characteristics
* Observed protocol combinations
* Observation frequency
* Other existing device metadata

The first version should classify devices into broad categories and return a confidence score.

Example:

```text
Device:
AA:BB:CC:DD:EE:FF

Classification:
Android Smartphone

Confidence:
94%

Source:
ML

Model:
device-classifier-v1
```

The system must also allow administrators to review and correct classifications so that verified classifications can eventually become training data.

---

# 2. Scope

## Version 1

The first implementation should focus on:

1. Collecting and normalizing device observations.
2. Extracting ML-compatible features.
3. Creating a labeled dataset.
4. Training an initial classification model.
5. Evaluating the model.
6. Integrating the model into the backend.
7. Returning classification + confidence.
8. Displaying the prediction in the UI.
9. Allowing administrators to correct predictions.
10. Storing model predictions and human-confirmed labels.

Do not attempt to build a fully autonomous AI system in this phase.

---

# 3. Initial Classification Categories

Start with broad categories rather than specific device models.

Recommended classes:

```text
WINDOWS_WORKSTATION
APPLE_WORKSTATION
ANDROID_MOBILE
APPLE_MOBILE
SMART_TV_MEDIA
PRINTER
NETWORK_DEVICE
IOT_DEVICE
UNKNOWN
```

The `UNKNOWN` category is important.

The model should be allowed to say:

```text
UNKNOWN
```

instead of being forced to make an unreliable prediction.

Later versions can introduce more granular classifications such as:

```text
ANDROID_MOBILE
    ├── Xiaomi
    ├── Samsung
    ├── Google
    └── Other
```

or:

```text
WINDOWS_WORKSTATION
    ├── Dell
    ├── HP
    ├── Lenovo
    └── Other
```

This should not be part of v1.

---

# 4. High-Level Architecture

The feature should eventually fit into the service architecture being introduced in the platform.

```text
                         NETWORK CLIENT
                                │
                                ▼
                       DEVICE OBSERVATION
                                │
                                ▼
                         DEVICES SERVICE
                                │
                                ▼
                       FEATURE EXTRACTION
                                │
                                ▼
                    DEVICE INTELLIGENCE SERVICE
                                │
                   ┌────────────┴────────────┐
                   ▼                         ▼
             Rule Engine                 ML Model
                   │                         │
                   └────────────┬────────────┘
                                ▼
                       CLASSIFICATION RESULT
                                │
                                ▼
                         STORAGE SERVICE
                                │
                                ▼
                            DATABASE
                                │
                                ▼
                           FRONTEND
```

The ML model should not communicate directly with the database.

The Device Intelligence Service should own the classification logic.

---

# 5. Important Architectural Principle

The ML system must not replace the existing discovery system.

Instead:

```text
Existing Discovery
       +
Existing Heuristics
       +
ML Classification
       ↓
Device Intelligence
```

The current rule-based classification should remain available as a baseline and fallback.

This allows the system to compare:

```text
Rule prediction
ML prediction
Human verification
```

rather than blindly trusting the model.

---

# 6. Phase 1 — Audit Existing Device Data

Before writing ML code, inspect the current data model and discovery pipeline.

Identify:

* [ ] Device model.
* [ ] Device observation model.
* [ ] Client model.
* [ ] Location model.
* [ ] Existing device classification fields.
* [ ] Existing vendor detection.
* [ ] DHCP parser.
* [ ] mDNS parser.
* [ ] SSDP parser.
* [ ] LLMNR parser.
* [ ] NBNS parser.
* [ ] Existing device fingerprinting.
* [ ] Existing rule-based classification.
* [ ] Existing API endpoints.
* [ ] Existing frontend device representation.

Document exactly which fields are currently available.

Do not create duplicate data structures if equivalent structures already exist.

---

# 7. Phase 2 — Define the Device Observation Model

Separate the concept of an observation from the device itself.

A device may be observed many times by many clients.

Conceptually:

```text
Device
    │
    ├── Observation
    ├── Observation
    ├── Observation
    └── Observation
```

An observation could contain:

```text
device_id
client_id
timestamp
protocol
source
raw_data
```

Examples:

```text
Device X
    DHCP observation
    mDNS observation
    SSDP observation
```

This preserves the original evidence.

---

# 8. Phase 3 — Define the Classification Model

Create a separate classification representation.

Suggested fields:

```text
DeviceClassification

id
device_id
predicted_class
confidence
model_version
source
classified_at
features_version
```

Where:

```text
source:
    ML
    RULE
    HUMAN
    HYBRID
```

Example:

```text
device_id:
42

predicted_class:
ANDROID_MOBILE

confidence:
0.94

model_version:
device-classifier-v1

source:
ML
```

Do not overwrite raw device observations.

---

# 9. Phase 4 — Define Human Labels

Create a mechanism for storing verified classifications.

Suggested model:

```text
DeviceLabel

id
device_id
label
source
confirmed_by
created_at
```

Example:

```text
device_id:
42

label:
ANDROID_MOBILE

source:
ADMIN

confirmed_by:
admin_id

created_at:
...
```

This becomes the ground-truth dataset.

---

# 10. Phase 5 — Feature Engineering

Create a dedicated feature extraction pipeline.

Conceptually:

```text
Raw Device Data
       ↓
Feature Extractor
       ↓
Normalized Features
       ↓
ML Model
```

Potential features:

### Vendor

```text
vendor
vendor_family
```

### DHCP

```text
dhcp_present
dhcp_option_12
dhcp_option_55
dhcp_option_60
dhcp_fingerprint
```

### mDNS

```text
mdns_present
mdns_txt_present
mdns_service_types
mdns_characteristics
```

### SSDP

```text
ssdp_present
ssdp_server_header
ssdp_device_type
```

### LLMNR

```text
llmnr_present
```

### NBNS

```text
nbns_present
hostname_characteristics
```

### Behavioral features

```text
number_of_protocols
observation_frequency
number_of_clients_observing
```

Use only features that are actually available and reliable in the existing system.

---

# 11. Avoid Data Leakage

Do not use features that allow the model to memorize individual devices.

Avoid directly training on:

```text
full MAC address
full IP address
unique client ID
unique device ID
```

Instead derive useful information.

For MAC:

```text
MAC
 ↓
OUI
 ↓
Vendor
```

The model should learn device characteristics rather than memorize known devices.

---

# 12. Phase 6 — Build the Initial Dataset

The first dataset should contain:

```text
features → label
```

Example:

```text
Vendor     DHCP    mDNS    SSDP    Hostname    Label

Xiaomi     Yes     Yes     No      Redmi       ANDROID_MOBILE
Dell       Yes     No      No      PC-01       WINDOWS_WORKSTATION
Apple      Yes     Yes     No      iPhone      APPLE_MOBILE
HP         Yes     Yes     Yes     Printer     PRINTER
```

The dataset should contain multiple physical devices from each class.

Do not build the dataset using only a few devices.

---

# 13. Dataset Requirements

Try to collect examples across:

* different manufacturers;
* different device models;
* different operating-system versions;
* different locations;
* different clients observing devices;
* different network conditions.

The objective is:

```text
Known device
        ↓
Model learns characteristics
        ↓
New device
        ↓
Model recognizes characteristics
```

not:

```text
Device X
        ↓
Model memorizes Device X
```

---

# 14. Phase 7 — Label Collection

Initially, labels can come from:

### Existing reliable rules

```text
Rule engine
    ↓
Initial labels
```

but these should not automatically be considered perfect ground truth.

Better sources include:

```text
Known device inventory
Administrator verification
Manual inspection
Existing trusted metadata
```

Create a distinction between:

```text
PROVISIONAL LABEL
```

and:

```text
VERIFIED LABEL
```

Only high-quality labels should be used for the final training dataset.

---

# 15. Phase 8 — Data Cleaning

Before training:

* [ ] Remove duplicate samples.
* [ ] Normalize vendor names.
* [ ] Normalize protocol names.
* [ ] Handle missing values.
* [ ] Normalize DHCP fingerprints.
* [ ] Normalize hostname patterns.
* [ ] Remove irrelevant identifiers.
* [ ] Check class imbalance.
* [ ] Remove corrupted observations.
* [ ] Verify labels.

Example:

```text
"Xiaomi Inc."
"Xiaomi"
"XIAOMI"

        ↓

"Xiaomi"
```

---

# 16. Phase 9 — Dataset Splitting

Do not randomly split individual observations if multiple observations belong to the same device.

Instead split by device.

Example:

```text
Devices
   │
   ├── 70% → Training
   ├── 15% → Validation
   └── 15% → Test
```

This ensures that the model is evaluated on devices it has not seen during training.

---

# 17. Phase 10 — Establish a Rule-Based Baseline

Before ML training, run the existing classification system against the test dataset.

Record:

```text
accuracy
precision
recall
F1-score
confusion matrix
```

Example:

```text
Rule-based classifier:

Accuracy: 82%
```

This becomes the baseline.

The ML system should demonstrate measurable improvement.

---

# 18. Phase 11 — Train the First ML Model

Start with a classical machine-learning model.

Recommended first candidate:

```text
Random Forest
```

Then compare against:

```text
Gradient Boosting
XGBoost / LightGBM
```

if appropriate.

Do not start with deep learning.

The first objective is to establish a reliable baseline, not to maximize model complexity.

---

# 19. Phase 12 — Model Evaluation

Evaluate:

```text
Accuracy
Precision
Recall
F1-score
Confusion Matrix
Per-class performance
```

Example:

```text
Class                  Precision    Recall

Windows Workstation       0.94       0.92
Android Mobile            0.91       0.95
Apple Mobile              0.96       0.93
Printer                   0.89       0.91
Smart TV                  0.84       0.78
IoT                       0.76       0.72
```

Do not rely solely on overall accuracy.

A model can have high overall accuracy while performing badly on a minority class.

---

# 20. Phase 13 — Confidence Handling

The model must return confidence.

Example:

```json
{
    "class": "ANDROID_MOBILE",
    "confidence": 0.94
}
```

Define thresholds.

Example:

```text
>= 0.90
    HIGH CONFIDENCE

0.70 – 0.89
    MEDIUM CONFIDENCE

< 0.70
    LOW CONFIDENCE
```

Low-confidence results should not be treated as authoritative.

---

# 21. Phase 14 — Unknown Device Handling

The system must be able to produce:

```text
UNKNOWN
```

when evidence is insufficient.

Example:

```text
Device:
Unknown Vendor

DHCP:
Incomplete

mDNS:
None

SSDP:
None

Prediction:
UNKNOWN

Confidence:
41%
```

This is preferable to:

```text
Android Smartphone — 51%
```

being presented as a fact.

---

# 22. Phase 15 — Hybrid Decision Engine

Combine:

```text
Rule Engine
+
ML Model
```

Example:

```text
                    Device
                       │
             ┌─────────┴─────────┐
             ▼                   ▼
        Rule Engine          ML Model
             │                   │
        Android               Android
             │                  94%
             └─────────┬─────────┘
                       ▼
                Decision Engine
                       │
                       ▼
              Android Smartphone
                 Confidence 96%
```

If the two systems disagree:

```text
Rule:
PRINTER

ML:
SMART_TV

→ Classification conflict
```

The system can mark the device:

```text
NEEDS_REVIEW
```

rather than silently selecting one.

---

# 23. Phase 16 — Device Intelligence Service

Once the model has been validated, create the service boundary.

Suggested service:

```text
Device Intelligence Service
```

Responsibilities:

```text
feature extraction
rule classification
ML classification
confidence calculation
classification reconciliation
model loading
model version management
```

It should expose an internal API such as:

```text
POST /classify
```

Request:

```json
{
    "device_id": 42
}
```

Response:

```json
{
    "device_id": 42,
    "classification": "ANDROID_MOBILE",
    "confidence": 0.94,
    "source": "ML",
    "model_version": "device-classifier-v1"
}
```

---

# 24. Phase 17 — Storage Integration

The Device Intelligence Service should send the result to the Storage Service.

```text
Devices Service
       ↓
Device Intelligence
       ↓
classification
       ↓
Storage Service
       ↓
Database
```

Example:

```http
POST /device-classifications
```

with:

```json
{
    "device_id": 42,
    "classification": "ANDROID_MOBILE",
    "confidence": 0.94,
    "model_version": "device-classifier-v1"
}
```

The Storage Service remains responsible for persistence.

---

# 25. Phase 18 — Automatic Classification

When a new device is sufficiently observed:

```text
Device discovered
       ↓
Devices Service
       ↓
Device Intelligence
       ↓
Classification
       ↓
Storage
```

Do not necessarily classify a device from its first packet.

Wait until enough useful evidence has been collected.

For example:

```text
Observation 1
    ↓
insufficient evidence

Observation 2
    ↓
insufficient evidence

Observation 3
    ↓
classify
```

The required evidence threshold should be configurable.

---

# 26. Phase 19 — Reclassification

Devices may reveal additional information later.

Therefore classification should be recalculable.

Example:

```text
Initial:

UNKNOWN
Confidence: 42%

        ↓

More observations

        ↓

ANDROID_MOBILE
Confidence: 91%
```

Store the latest result while retaining classification history where useful.

---

# 27. Phase 20 — Model Versioning

Every prediction must record the model version.

Example:

```text
device-classifier-v1
device-classifier-v2
```

This allows the system to answer:

> Which model produced this classification?

It also allows comparisons between models.

Example:

```text
v1 → Android Mobile, 74%
v2 → Android Mobile, 93%
```

---

# 28. Phase 21 — Administrator UI

Add classification information to the device details page.

Example:

```text
DEVICE

PC-TRAINING-07

Classification
────────────────────
Windows Workstation

Confidence
────────────────────
94%

Source
────────────────────
ML

Model
────────────────────
device-classifier-v1

[Correct Classification]
```

---

# 29. Phase 22 — Classification Review Interface

Create a review interface for uncertain devices.

```text
DEVICE CLASSIFICATION REVIEW

┌──────────────────────────────────────────────┐
│ Device: AA:BB:CC:DD:EE:FF                  │
│ Vendor: Unknown                            │
│ Protocols: DHCP / mDNS                      │
│                                             │
│ ML Prediction: IoT Device                  │
│ Confidence: 67%                             │
│                                             │
│ [Windows] [Android] [Apple]                │
│ [Printer] [Smart TV] [IoT] [Unknown]       │
└──────────────────────────────────────────────┘
```

This interface generates verified labels.

---

# 30. Phase 23 — Human Feedback Loop

When an administrator corrects:

```text
ML:
ANDROID_MOBILE

Admin:
SMART_TV
```

store:

```text
Predicted:
ANDROID_MOBILE

Actual:
SMART_TV
```

This information becomes valuable training data.

The workflow becomes:

```text
Discovery
   ↓
ML prediction
   ↓
Human review
   ↓
Verified label
   ↓
Training dataset
   ↓
Model improvement
```

---

# 31. Phase 24 — Model Retraining

Do not automatically retrain the production model after every correction.

Instead:

```text
Verified labels
      ↓
Dataset update
      ↓
Dataset validation
      ↓
Training
      ↓
Evaluation
      ↓
Compare with current model
      ↓
Deploy only if better
```

This prevents bad labels from degrading the model.

---

# 32. Phase 25 — Monitoring

Track classification performance over time.

Metrics should include:

```text
classification count
high-confidence predictions
low-confidence predictions
human corrections
rule/ML disagreements
unknown classifications
classification distribution
```

For example:

```text
Today's classification

Windows       42%
Android       31%
Apple         12%
Printer        7%
IoT            5%
Unknown        3%
```

And:

```text
ML corrections:
7 / 342

Correction rate:
2.0%
```

A rising correction rate may indicate model degradation or new device types.

---

# 33. Phase 26 — Model Drift Detection

Over time, new devices may appear that weren't represented in the training dataset.

Monitor:

```text
Unknown rate
Low-confidence rate
Human correction rate
New vendor frequency
New protocol patterns
```

For example:

```text
v1

Unknown: 3%

Six months later:

Unknown: 18%
```

This may indicate:

```text
new device types
new manufacturers
network changes
model drift
```

This should trigger model review.

---

# 34. Phase 27 — Integration With Location

Once classification is reliable, expose it to the spatial system.

The center layout could show:

```text
Floor 2
────────────────────────

● Windows PC
● Windows PC
● Android Phone
◆ Printer
● Smart TV
```

Selecting a device could show:

```text
Device:
PC-07

Type:
Windows Workstation

Confidence:
96%

Location:
Training Room 2 / Seat 4
```

Classification should complement the location system, not control it.

---

# 35. Phase 28 — Integration With Future Rogue Detection

Device classification should become one feature used by future anomaly/rogue detection.

Example:

```text
Device:

Type:
Android Smartphone

Location:
Training Room 1

Expected devices:
Windows Workstations

Time:
02:15

Classification confidence:
94%

        ↓

Future Rogue Detection

Risk:
HIGH
```

The classification itself should not automatically make the device rogue.

It is simply one signal.

---

# 36. Phase 29 — Integration With Future Spatial-Temporal Analysis

Classification can also become a feature for your future spatial-temporal engine.

Example:

```text
Device type:
Android Smartphone

Normal locations:
Reception
Training Rooms

Observed:
Server Room

Time:
03:12
```

This combination becomes much more meaningful than any individual signal.

---

# 37. Testing Strategy

## Unit Tests

Test:

* [ ] Feature extraction.
* [ ] Missing feature handling.
* [ ] Vendor normalization.
* [ ] DHCP normalization.
* [ ] Protocol encoding.
* [ ] Classification result parsing.
* [ ] Confidence thresholds.
* [ ] Unknown classification.
* [ ] Rule/ML conflict handling.

## Model Tests

Test:

* [ ] Accuracy.
* [ ] Precision.
* [ ] Recall.
* [ ] F1-score.
* [ ] Confusion matrix.
* [ ] Unseen devices.
* [ ] Missing observations.
* [ ] Unknown devices.

## Integration Tests

Test:

```text
Device discovered
    ↓
Devices Service
    ↓
Device Intelligence
    ↓
ML classification
    ↓
Storage Service
    ↓
Database
```

## UI Tests

Test:

* [ ] Classification display.
* [ ] Confidence display.
* [ ] Review workflow.
* [ ] Manual correction.
* [ ] Classification history.

---

# 38. Security

The ML service should not have unrestricted database access.

Recommended:

```text
Device Intelligence
        ↓
Storage API
```

rather than:

```text
Device Intelligence
        ↓
direct database access
```

Only authorized administrators should be able to:

* confirm classifications;
* correct classifications;
* trigger model-related operations.

Clients should never be able to directly modify their classification.

---

# 39. Performance Considerations

Do not run model inference unnecessarily.

Avoid:

```text
Every packet
    ↓
ML model
```

Instead:

```text
New device
    ↓
Collect observations
    ↓
Enough evidence?
    ↓
YES
    ↓
Classification
```

Reclassify when:

* significant new evidence appears;
* classification confidence is low;
* administrator requests recalculation;
* a new model is deployed.

Cache the latest classification.

---

# 40. Recommended Project Structure

A possible structure:

```text
device-intelligence-service/
│
├── app/
│   ├── api/
│   │   └── classification.py
│   │
│   ├── classification/
│   │   ├── rules.py
│   │   ├── model.py
│   │   ├── decision.py
│   │   └── confidence.py
│   │
│   ├── features/
│   │   ├── dhcp.py
│   │   ├── mdns.py
│   │   ├── ssdp.py
│   │   └── hostname.py
│   │
│   ├── models/
│   │   └── device_classifier_v1.pkl
│   │
│   └── main.py
│
├── training/
│   ├── dataset/
│   ├── preprocessing.py
│   ├── train.py
│   ├── evaluate.py
│   └── export_model.py
│
├── tests/
│
├── requirements.txt
└── README.md
```

The exact structure should follow the existing project conventions.

---

# 41. Recommended Implementation Order

Implement in this exact progression:

```text
1. Audit existing device data
        ↓
2. Define observation structure
        ↓
3. Define classification structure
        ↓
4. Define human labels
        ↓
5. Build feature extractor
        ↓
6. Collect/clean dataset
        ↓
7. Establish rule-based baseline
        ↓
8. Train Random Forest
        ↓
9. Evaluate model
        ↓
10. Implement confidence handling
        ↓
11. Implement UNKNOWN handling
        ↓
12. Build Device Intelligence Service
        ↓
13. Integrate Storage Service
        ↓
14. Implement automatic classification
        ↓
15. Add UI classification display
        ↓
16. Add human review
        ↓
17. Collect verified labels
        ↓
18. Implement model versioning
        ↓
19. Implement retraining workflow
        ↓
20. Integrate classification with future
    anomaly/rogue detection
```

---

# 42. Definition of Done — V1

The feature is considered complete when:

* [ ] Newly discovered devices can be classified.
* [ ] Classification uses existing passive discovery information.
* [ ] The system supports the initial device categories.
* [ ] The ML model produces a confidence score.
* [ ] The system can return UNKNOWN.
* [ ] Raw observations remain unchanged.
* [ ] Classification results are stored separately.
* [ ] Model versions are recorded.
* [ ] Existing rule-based classification remains available.
* [ ] Rule/ML disagreements can be identified.
* [ ] Administrators can correct classifications.
* [ ] Human-confirmed classifications are stored as labels.
* [ ] Classification appears in the device UI.
* [ ] The ML service does not directly access the database.
* [ ] Classification can be recalculated.
* [ ] The model is evaluated against previously unseen devices.
* [ ] Performance is measurable against the existing rule-based baseline.

---

# 43. Future Evolution

Once V1 is stable, the system can evolve into:

```text
                 DEVICE INTELLIGENCE
                         │
          ┌──────────────┼───────────────┐
          ▼              ▼               ▼
    Classification   Fingerprinting   Similarity
          │              │               │
          └──────────────┼───────────────┘
                         ▼
                  Anomaly Detection
                         │
                         ▼
                  Rogue Prediction
                         │
                         ▼
                Spatial-Temporal AI
                         │
                         ▼
                 Risk Prediction
                         │
                         ▼
                Autonomous Response
```

The first classifier therefore becomes the foundation for the future AI layer rather than an isolated feature.

---

# 44. Final Architecture

The final V1 flow should be:

```text
                         NETWORK
                            │
                            ▼
                       CLIENT AGENT
                            │
                            ▼
                    DEVICE OBSERVATION
                            │
                            ▼
                     DEVICES SERVICE
                            │
                            ▼
                   DEVICE INTELLIGENCE
                            │
              ┌─────────────┴─────────────┐
              │                           │
              ▼                           ▼
        RULE CLASSIFIER              ML CLASSIFIER
              │                           │
              └─────────────┬─────────────┘
                            ▼
                     DECISION ENGINE
                            │
                            ▼
                 CLASSIFICATION RESULT
                            │
                            ▼
                     STORAGE SERVICE
                            │
                            ▼
                        DATABASE
                            │
              ┌─────────────┴─────────────┐
              ▼                           ▼
         VISUALIZATION              TRAINING DATA
                                          │
                                          ▼
                                    HUMAN LABELS
                                          │
                                          ▼
                                    MODEL TRAINING
                                          │
                                          ▼
                                  NEW MODEL VERSION
```

The central principle is:

> **The ML model should be an intelligence layer on top of your existing discovery system, not a replacement for it.**

This approach lets you deploy a useful classifier early, collect verified labels from real network environments, measure whether ML actually improves your existing heuristics, and progressively turn the collected device history into the foundation for your future anomaly detection, rogue-device prediction, and spatial-temporal intelligence systems.