# Kismet Unicast Filter & Probe Scanner — Implementation Progress

**Branch:** `feature/kismet-unicast-filter-probe-scanner`
**Started:** 2026-09-10
**Plan:** [`plan-kismetUnicastFilterProbeScanner.prompt.md`](../planning/plan-kismetUnicastFilterProbeScanner.prompt.md)

---

## Overview

This feature implements a **standalone capture-filtering path** plus a **latest-probe scanner** for Kismet `.kismet` SQLite captures. It is staged in four phases; each phase must be reviewed before the next is started.

```
Phase 1 – Filter policy + standalone filter interface + tests
Phase 2 – Standalone probe scanner + CLI + tests
Phase 3 – Observation vs. ML-pipeline comparison (manual review gate)
Phase 4 – Controlled integration (only after Phase 3 sign-off)
```

---

## Implementation Log

### 2026-09-10 — Phases 1 & 2 implemented

**Files created:**

| Path | Role |
|---|---|
| `tools/kismet_probe_scanner/__init__.py` | Package marker |
| `tools/kismet_probe_scanner/filter.py` | Phase 1 – Packet filter policy |
| `tools/kismet_probe_scanner/scanner.py` | Phase 2 – Probe scanner (reuses server parsers) |
| `tools/kismet_probe_scanner/capture_source.py` | Phase 2 – Capture file discovery adapter |
| `tools/kismet_probe_scanner/__main__.py` | Phase 2 – CLI entry-point |
| `tools/kismet_probe_scanner/tests/__init__.py` | Test package marker |
| `tools/kismet_probe_scanner/tests/test_filter.py` | Phase 1 unit tests |
| `tools/kismet_probe_scanner/tests/test_scanner.py` | Phase 2 unit tests |
| `tools/kismet_probe_scanner/OUTPUT_SCHEMA.md` | Output JSON schema documentation |
| `docs/project/kismet-unicast-filter-probe-scanner/README.md` | This file |

**Pre-implementation contract recorded (Phase 1 step 1):**

- systemd unit: `kismet-sensor.service` — owns Kismet process + monitor VIF lifecycle.
- Capture storage: SQLite `.kismet` files under `KISMET_CAPTURE_ROOT` (default `/home/adonis/kismet`).
- Server readers open files **read-only** via `file:?mode=ro&nolock=1` or `immutable=1` URI.
- Active captures have a `-journal` sidecar; stale journals are detected by mtime comparison.
- Existing parsers live in `server/server_components/kismet_ml_foundation.py` (`parse_80211_packet`, `is_randomized_mac`) and `server/server_components/kismet_service.py` (`normalize_mac`, `frequency_to_channel`, `_probe_metadata`, `_probe_signature`).
- **No parallel 802.11 parser is introduced** — the standalone tool imports from the existing server modules.

**Filter policy (Phase 1):**

| Frame | Decision | Reason |
|---|---|---|
| Data, unicast destination | `KEEP` | Useful client telemetry |
| Data, broadcast destination | `DROP` | Duplicated client traffic |
| Data, multicast destination | `DROP` | Duplicated client traffic |
| Management: Probe Request (broadcast or directed) | `KEEP` | Required for fingerprinting |
| Management: other (Beacon, Auth, Assoc…) | `DROP` | Not needed by standalone scanner |
| Control: ACK, CTS, RTS, Block Ack | `DROP` | RF noise |
| Malformed / unparseable | `DROP` | Cannot classify |

> NOTE: The "unicast-only" rule applies **only to data frames**.  Probe Requests are commonly
> broadcast-destined and must always be retained regardless of their destination address.

**Scanner output contract (Phase 2):**

- Emits exactly **one** latest-probe JSON record (or a no-result envelope) to stdout.
- Never emits raw packet bytes or plaintext SSIDs.
- Scans files newest-to-oldest using the same bounded-batch strategy as `query_recent_probes`.
- Exit codes: `0` = success (result or no-result both count), `1` = operational error.

---

## Phase 3 Gate (pending)

Before integration, the scanner output must be compared against:
- `query_recent_probes` in `KismetInvestigationService`
- `KismetMLExtractor.fingerprint_observations()`
- `device_fingerprinting` and `fingerprint_dataset` feature vectors

Record which fields map to the first ML model's training dataset and note any gaps.

---

## Phase 4 Gate (pending)

- Determine whether Kismet supports native pre-storage filtering for the policy above.
- If yes: update Kismet configuration and measure `.kismet` growth before/after.
- If no: document the explicit alternative chosen (e.g. filter the derived processing stream).

---

## How to Run Tests

```bash
# From the repository root, with the venv active:
python -m pytest tools/kismet_probe_scanner/tests/ -v

# Run existing server-side tests to confirm nothing regressed:
python -m pytest server/tests/test_kismet_probe_service.py server/tests/test_kismet_ml_foundation.py -v
```

## How to Run the CLI

```bash
# Scan the default KISMET_CAPTURE_ROOT and print the latest probe JSON:
python -m tools.kismet_probe_scanner

# Scan a specific directory:
python -m tools.kismet_probe_scanner --capture-dir /home/adonis/kismet

# Scan a single file:
python -m tools.kismet_probe_scanner --capture-file /home/adonis/kismet/Kismet-2026-09-10.kismet

# Pretty-print output:
python -m tools.kismet_probe_scanner | python -m json.tool
```
