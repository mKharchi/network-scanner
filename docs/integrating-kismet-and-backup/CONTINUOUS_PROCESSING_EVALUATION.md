# Evaluation: On-Demand Querying vs. Continuous Stream Processing & ML

## 1. Context & Evaluation Objective

During Track 2 of the Kismet integration, we evaluated two architectural paradigms for wireless RF observation data:

1. **On-Demand Targeted Querying (Current Architecture — Phases 4–6)**:
   - Raw packet and device captures reside inside rolling Kismet SQLite files (`.kismet`) managed by bounded retention policies.
   - When an analyst investigates a device or inspects an alert, the backend executes a time-windowed query against the raw captures, decoding 802.11 frame control headers, applying noise filtering, and presenting chronological evidence timelines.

2. **Continuous Stream ETL & Continuous Database Ingestion (Phase 8 Evaluation)**:
   - A real-time daemon tails Kismet FIFO pipes or WebSocket streams, decoding every 802.11 frame, computing aggregate statistical features, and continuously writing packet/observation records to MySQL.
   - Continuous ML anomaly detectors run over sliding temporal windows.

---

## 2. Comparative Analysis

| Evaluation Dimension | On-Demand Querying (Phases 4–6) | Continuous ETL & MySQL Sink |
| :--- | :--- | :--- |
| **Storage Overhead** | **Low & Bounded** (PCAP/Kismet DB rotated on disk; 0 bytes MySQL packet bloat) | **High / Critical Risk** (Millions of daily rows; high write IOPS and disk exhaustion) |
| **CPU / Memory Usage** | **Idle when not querying**; fast indexed SQLite queries on demand | **Continuous high CPU load** decoding every broadcast/beacon frame 24/7 |
| **Analyst Latency** | Sub-second (< 200ms) for 15m–24h investigation lookbacks | Instant for pre-aggregated stats, but identical for deep packet evidence |
| **Forensic Fidelity** | **100% Raw Evidence Preserved** (frame bytes, Radiotap headers, RSSI, offsets) | Potential data loss if stream parser drops unmodeled frame types |
| **Maintenance Burden** | Minimal; standalone decoupled services with clean REST endpoints | High; requires buffer queues, database pruning jobs, and schema migrations |
| **Failure Blast Radius** | Isolated to query failure; zero impact on core network discovery | Pipeline failure could block backend database or queue consumers |

---

## 3. Decision & Recommendation

### Recommendation: MAINTAIN ON-DEMAND ARCHITECTURE (DEFER CONTINUOUS MYSQL SINK)

The on-demand architecture fully satisfies the core operational requirements:
1. **Analyst Workflow Alignment**: Operational investigations are event-driven (`Alert Trigger` $\rightarrow$ `Suspect Device MAC` $\rightarrow$ `15-minute Kismet Window` $\rightarrow$ `Analyst Review`). Continuous ingestion provides zero additional benefit for this workflow while introducing massive database bloat.
2. **Storage Sustainability**: Keeping bulk raw data in Kismet's optimized native storage prevents database degradation and preserves the stability of the central scanner.

---

## 4. Criteria & Roadmap for Future ML Integration

Continuous processing and ML should be adopted **only** if one or more of the following operational triggers are met:

1. **Automated RF Anomaly Detection Requirements**:
   - Need for automated detection of Evil Twin APs (BSSID/ESSID spoofing with unexpected RSSI or MAC vendor discrepancies).
   - Automated detection of 802.11 Deauthentication / Disassociation flood attacks without waiting for client-reported disconnections.
2. **Unsupervised Behavioral Baselines**:
   - Profiling wireless IoT duty cycles (e.g., smart meters transmitting every 300s $\pm 5$s) to flag anomalous data bursts.
3. **Continuous RF Localization / Tracking**:
   - Real-time multi-sensor RSSI triangulation for mobile assets moving across physical floor zones.

### Recommended Lightweight ML Architecture (When Triggered):
```text
Kismet Live WebSocket Stream
           │
           ▼
Lightweight Redis In-Memory Ring Buffer (Last 1 Hour)
           │
           ▼
Vectorized Feature Extractor (Windowed Packet Rates, RSSI Delta, Frame Entropy)
           │
           ▼
Isolation Forest / Lightweight Anomaly Detector
           │
     (Only on Anomaly)
           ▼
Generate Standard Security Alert (Alerts Table) ──► Deep Link to On-Demand Kismet Investigation
```
