# Plan 1 — Device Fingerprinting and Identity Linking

## Objective

Train and deploy the first ML model to answer:

> Which observations probably belong to the same physical device?

The model must complement, not replace, existing identifiers such as MAC, OUI, hostname, DNS, or IP.

The primary objective is persistent identity linking, including cases where a device changes/randomizes its MAC address.

---

## Dependency

Plan 0 — ML Data Foundation must be complete.

Required inputs:

- management-frame extraction
- Information Element extraction
- fingerprint feature schema
- labeled fingerprint dataset
- model registry/inference interface

---

## Model boundary

Do not make the first version responsible for perfect commercial device identification such as:

```text
"Samsung Galaxy S25 Ultra"
```

The first target is:

```text
observation A
observation B
      |
      v
same physical device?
```

Device vendor/type classification can be added later.

---

## Input features

Use management-frame and behavioral fingerprint features available from Kismet.

Candidate groups:

### Information Elements

```text
supported rates
extended rates
HT capabilities
VHT capabilities
HE capabilities
RSN information
WMM information
vendor-specific IEs
other stable IE structures
```

### Radio/behavioral features

```text
probe interval
channel behavior
signal statistics
sequence-number behavior
frame subtype distribution
probe timing patterns
```

Do not include raw MAC address as a predictive feature for MAC de-randomization.

Avoid features that simply memorize the training device.

---

## Dataset strategy

Use public labeled probe-request datasets to validate the extraction and feature methodology.

Then create a local labeled dataset using controlled devices.

Local collection should include:

- multiple device models
- repeated observations
- different power/display states where possible
- different locations/radio conditions
- MAC randomization scenarios where available

The dataset should distinguish:

```text
same device / same MAC
same device / changed MAC
different devices
```

---

## Training approaches

Evaluate at least two approaches:

### Baseline

Feature similarity / distance-based matching.

### ML classifier

A tree-based classifier or other suitable tabular model.

The first production model should favor:

- explainability
- low inference cost
- robustness
- easy retraining

Do not introduce deep sequence models unless the baseline fails to meet requirements.

---

## Identity linking

The model should return a similarity/confidence score.

Conceptually:

```text
new fingerprint
      |
      v
candidate device fingerprints
      |
      v
similarity/model score
      |
   +--+----------------+
   |                   |
high confidence     uncertain
   |                   |
link device          new candidate
```

Do not automatically merge identities at low confidence.

---

## Device identity registry

Create a persistent logical device identity:

```text
device_identity_id
first_seen
last_seen
confidence
fingerprint_version
```

Associate observed identifiers:

```text
MAC
IP
hostname
OUI
fingerprint
```

with provenance and confidence.

---

## Evaluation

Measure more than accuracy.

Required metrics:

- precision
- recall
- F1
- false merge rate
- false split rate
- accuracy under MAC randomization

False merges are particularly important because incorrectly combining two physical devices can corrupt all later activity/security analysis.

---

## Operational behavior

Use confidence thresholds:

```text
high confidence
    -> link automatically

medium confidence
    -> retain as candidate

low confidence
    -> do not link
```

Log model version and evidence used for each identity decision.

---

## Testing

Test:

1. Same device repeatedly observed.
2. Same device with MAC randomization.
3. Different devices with similar capabilities.
4. Missing IEs.
5. Partial management frames.
6. Different signal conditions.
7. Multiple sensors if supported.
8. Model-version migration.
9. Identity persistence across Kismet database rotation.

---

## Shadow mode

Initial deployment must be shadow-only.

The model should produce:

```text
candidate identity
confidence
observed MAC
timestamp
```

without changing authoritative device identity automatically.

Review results before enabling automatic linking.

---

## Definition of done

Plan 1 is complete when:

- fingerprint features are extracted reliably
- a labeled dataset exists
- baseline and ML approaches are evaluated
- MAC randomization is explicitly tested
- false merge/split behavior is measured
- model artifact is versioned
- inference integrates with the device identity layer
- low-confidence matches remain non-authoritative
- shadow-mode results are reviewable
