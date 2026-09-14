# Machine Learning & AI Threat Intelligence

This module encompasses the machine learning pipeline, wireless probe fingerprinting, device behavioral baselining, and anomaly detection models built on top of the server's telemetry and Kismet data foundations.

---

## 📖 Recommended Reading Order

Follow this sequence to understand the ML roadmap from data foundations to live inference:

1. **[PLAN 0: ML Data Foundation](PLAN_0_ML_DATA_FOUNDATION.md)**
   - SQLite ETL pipeline, feature extraction from `.kismet` databases, and training dataset curation.
2. **[PLAN 1: Device Fingerprinting](PLAN_1_DEVICE_FINGERPRINTING.md)**
   - Unsupervised clustering and semi-supervised classification of randomized MAC addresses and wireless hardware profiles.
3. **[Server Probe Visualization Plan](plan_1_server_probe_visualization/PLAN.md)**
   - Server-side REST API contracts and UI workflows for visualizing wireless probes and fingerprint clusters.
4. **[PLAN 2: Device Activity Model](PLAN_2_DEVICE_ACTIVITY_MODEL.md)**
   - Behavioral baselining, Markov transition matrices, and normal usage pattern modeling.
5. **[PLAN 3: Threat & Anomaly Model](PLAN_3_THREAT_ANOMALY_MODEL.md)**
   - Isolation Forest and deep autoencoder models for rogue device detection, beacon spoofing, and lateral movement detection.

---

## 📋 Module Contents

| Document / Subfolder | Focus Area | Status |
| :--- | :--- | :--- |
| [`PLAN_0_ML_DATA_FOUNDATION.md`](PLAN_0_ML_DATA_FOUNDATION.md) | Data extraction, SQLite parsers, labeling pipelines | In Progress / Partially Implemented |
| [`PLAN_1_DEVICE_FINGERPRINTING.md`](PLAN_1_DEVICE_FINGERPRINTING.md) | Probe request feature extraction & clustering | In Progress / Benchmarked |
| [`plan_1_server_probe_visualization/`](plan_1_server_probe_visualization/) | REST API contract & UI for probe visualization | In Progress |
| [`PLAN_2_DEVICE_ACTIVITY_MODEL.md`](PLAN_2_DEVICE_ACTIVITY_MODEL.md) | Temporal activity profiling & session labeling | In Progress / Benchmarked |
| [`PLAN_3_THREAT_ANOMALY_MODEL.md`](PLAN_3_THREAT_ANOMALY_MODEL.md) | Anomaly scoring & threat dispatching | Planned |
| [`post-research.md`](post-research.md) | Algorithm benchmarks, model evaluation metrics | Completed Research |
