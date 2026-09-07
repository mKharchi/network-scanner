# Phase 3 — Server-Side Data Access Contract

**Status:** ✅ DONE — 2026-09-07

## Objective

Define and test the source adapter used by the server application to read the verified local Kismet history source.

## Requirements

- source access remains server-local and read-only; ✅ (mode=ro URI, S1)
- canonical MAC, UTC inclusive range, ordering, limit, truncation, and error contracts are fixed; ✅
- source/destination/transmitter role matching and random-MAC handling are documented; ✅
- synthetic fixtures represent the verified target schema/API rather than the former client listener assumptions; ✅
- no client connection, client path, or TCP command is involved. ✅

## Implementation

### Contract Document
`docs/integrating-kismet-and-backup/option-a-client-server/phase-3-contract.md`

Frozen invariants covering 9 sections:
- **S** Source Access (read-only, multi-file, fault-tolerant)
- **M** MAC normalization (uppercase colon, COLLATE NOCASE, LAA not excluded)
- **T** Time window (µs-exact boundaries, reversed range error, `all`/`none`/`unlimited` unbounded, 30m default)
- **R** Ordering and limit (newest-first, clamped to 2000, observation_count == len)
- **F** Frame role priority (SOURCE > TRANSMITTER > DESTINATION > OBSERVED)
- **N** Noise filtering (ACK/CTS/RTS/Block Ack dropped by default, noise_filtered flag)
- **E** Response envelope shape (status, source, device, query_window, summary, observations, capture_files_scanned)

### Contract Test Suite
`server/tests/test_kismet_service_contract.py`

**27 contract tests** across 7 classes (S, M, T, R, F, N, E).
All 27 pass. Combined with existing unit tests = **51 tests total, all green**.

## Exit criterion

A testable server data-access boundary is ready for `KismetInvestigationService` refactoring. ✅
Contract is frozen and enforced by the dedicated test suite.
