# Phase 3 — KismetInvestigationService Source Adapter Contract

**Status:** FROZEN — 2026-09-07
**Enforced by:** `server/tests/test_kismet_service_contract.py`

---

## 1. Scope

This document defines the **frozen data-access contract** for `KismetInvestigationService`
(implemented in `server/server_components/kismet_service.py`).

The contract covers the boundary between:
- the **source** (read-only `.kismet` SQLite files written by the Kismet daemon on this server), and
- the **consumer** (REST API layer in `api_service.py` -> `api_server.py` -> UI).

Nothing below this boundary involves: any client process, TCP message, `KismetListener`, or
remote Kismet REST API. All access is read-only local file I/O.

---

## 2. Source Access Invariants

| # | Invariant | Rationale |
|---|---|---|
| S1 | `.kismet` files are **never written to** by the service. All connections use `?mode=ro` URI. | Protects active captures from corruption. |
| S2 | Files are discovered by globbing `*.kismet` inside `capture_dirs` (env `KISMET_CAPTURE_DIRS` or defaults). | No hard-coded single path; multiple dirs supported. |
| S3 | The service tolerates individual file failures (logs a WARNING, continues to next file). | A single corrupt DB must not crash the endpoint. |
| S4 | The service reads from **all** matching files for a query (not just the newest). | Historical data spanning multiple capture sessions must be reachable. |

---

## 3. MAC Address Contract

| # | Invariant |
|---|---|
| M1 | Input MAC may be uppercase, lowercase, or mixed; with `:` or `-` separators, or 12-char compact. |
| M2 | `normalize_mac()` always returns **uppercase colon-separated** (`AA:BB:CC:DD:EE:FF`) or `None`. |
| M3 | Kismet stores MACs lowercase. The SQL WHERE clause uses `COLLATE NOCASE` to match both cases. |
| M4 | Locally generated / randomised MACs (bit 1 of first octet set) are **not excluded**. |
| M5 | Invalid MAC input resolves to device not found -> `ValueError`. |

---

## 4. Time Window Contract

| # | Invariant |
|---|---|
| T1 | `start_time < end_time` enforced. Reversed range raises `ValueError("start_time must be earlier than end_time")`. |
| T2 | Boundaries are **microsecond-exact**: `pkt_ts = ts_sec + ts_usec / 1_000_000`. Exactly at boundary = included; 1 us outside = excluded. |
| T3 | SQL pre-filter uses `ts_sec >= start_epoch AND ts_sec <= end_epoch` where `end_epoch = int(end_ts) + 1`. Python loop applies exact float check. |
| T4 | Lookback values `"all"`, `"none"`, `"unlimited"` disable time filtering (`has_time_filter = False`). |
| T5 | Default lookback is **30 minutes** when no time args are supplied. |
| T6 | `end_time` defaults to `datetime.now(UTC)` when not supplied. |
| T7 | `query_window.start` is ISO-8601 or `"unbounded"` when unfiltered. |
| T8 | `query_window.lookback_minutes` is `None` when unbounded. |

---

## 5. Result Ordering and Limit Contract

| # | Invariant |
|---|---|
| R1 | Observations are returned **newest-first** (`ORDER BY ts_sec DESC, ts_usec DESC`). |
| R2 | `limit` is clamped to `[1, 2000]`. |
| R3 | `summary.observation_count` equals `len(observations)`. |
| R4 | `summary.total_matched_packets` may be >= `observation_count` (counts all matches before limit cut). |

---

## 6. Frame Role Assignment Contract

| # | Invariant |
|---|---|
| F1 | Each observation has exactly one `role`: `SOURCE`, `TRANSMITTER`, `DESTINATION`, or `OBSERVED`. |
| F2 | Priority: `SOURCE` > `TRANSMITTER` > `DESTINATION` > `OBSERVED`. |
| F3 | `TRANSMITTER` = transmac matches AND sourcemac does not match target. |
| F4 | `DESTINATION` = destmac matches AND neither sourcemac nor transmac matches target. |

---

## 7. Noise Filtering Contract

| # | Invariant |
|---|---|
| N1 | `include_noise=False` (default) drops packets with `frame_subtype` in `{"ACK","CTS","RTS","Block Ack"}`. |
| N2 | Filtered packets do NOT count toward `total_matched_packets`. |
| N3 | `summary.noise_filtered` is `True` when `include_noise=False`. |

---

## 8. Response Envelope Contract

Success always returns:

    {
      "status": "ok",
      "source": "KISMET_SERVER",
      "device": { "mac": str, ... },
      "query_window": { "start": str, "end": str, "lookback_minutes": float|None },
      "summary": { "observation_count": int, "total_matched_packets": int,
                   "avg_signal_dbm": float|None, "min/max_signal_dbm": int|None,
                   "channels": list[int], "frame_types": dict[str,int], "noise_filtered": bool },
      "observations": [ { ...per packet, newest first... } ],
      "capture_files_scanned": int
    }

Each observation includes: `timestamp`, `epoch_sec`, `epoch_usec`, `role`,
`source_mac`, `destination_mac`, `transmitter_mac`, `frame_type`, `frame_subtype`,
`signal_dbm`, `frequency_khz`, `channel`, `packet_length`, `sensor`,
`source` (always `"KISMET_SERVER"`), `capture_file`, `packet_hash`.

Errors raise `ValueError` (mapped to HTTP 400/404 by caller). No partial-success dict.

---

## 9. What Is Explicitly NOT Part of This Contract

- No TCP messages, no client-side KismetListener, no remote Kismet REST API.
- No writing to MySQL `wireless_observations` table (Option A stores nothing in MySQL).
- No deduplication across overlapping capture files.
