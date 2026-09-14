# Kismet Interval Processing and Activity Summaries

## Summary

Introduce a staged workflow that preserves continuous Kismet capture, classifies completed 30-second activity windows, stores compact derived results, and removes raw capture data only after successful verification.

The first deliverable is analysis only. No deletion or production behavior changes will occur until the inference risk is documented and explicitly approved.

## Phase 1 — Inspect and document the inference risk

Inspect:

- `KismetMLShadowProcessor`, `KismetMLExtractor`, `TrafficWindow`, activity model artifacts, smoothing, and prediction storage.
- Kismet service configuration, SQLite schema, active journals, capture growth, retention behavior, and systemd timers.
- Current per-window inference path and whether it is bounded, idempotent, and safe against disappearing source captures.
- Installed Kismet logging API/version and whether `.kismet` logs can be stopped and reopened without restarting the sensor.

The primary risk to analyze is domain mismatch: the VNAT model was trained on wired traffic, while live Kismet windows contain Wi-Fi management/control/retry/radio features that may be absent or constant in training. This can produce out-of-distribution and overconfident activity predictions.

Write the findings to:

```text
docs/optimizing_kismet/problem.md
```

The document will contain:

- Evidence from the current implementation.
- Training-versus-live feature distribution differences.
- Impact on prediction accuracy and confidence.
- Whether randomized/unmapped MACs affect attribution.
- Capture-rotation feasibility and failure modes.
- Candidate fixes, with a recommended fix.
- Required tests, rollback strategy, and acceptance criteria.

Then stop. No code changes, capture deletion, rotation automation, or service restart will be performed at this checkpoint.

Kismet’s official documentation must be treated as a compatibility constraint: its API supports stopping and starting logs, but notes that some log types such as `kismetdb` may permit only one logging instance. This must be verified against the installed version before relying on log rotation. [Kismet logging API](https://www.kismetwireless.net/docs/api/logging/), [KismetDB logging](https://www.kismetwireless.net/docs/readme/logging/kismetdb/)

## Phase 2 — Apply the approved inference fix

After explicit approval:

- Implement the selected feature/schema fix.
- Validate artifact compatibility and label order.
- Keep low-confidence output as `unknown`.
- Add feature-distribution or domain-shift diagnostics.
- Ensure inference is bounded to completed windows rather than repeatedly loading all historical windows.
- Preserve raw payload exclusion.
- Run unit, integration, and replay tests before enabling deletion.

## Phase 3 — Continuous interval processing

Use UTC wall-clock-aligned 10-minute intervals:

```text
00:00–00:10, 00:10–00:20, ...
```

Each interval contains exactly twenty complete 30-second windows. The scheduler must align to clock boundaries rather than accumulating drift with repeated sleeps.

For each closed interval:

1. Identify the finalized Kismet capture segment(s).
2. Read packets read-only and derive traffic windows.
3. Run activity inference and temporal smoothing.
4. Write per-window predictions to an atomic JSONL file containing:
   - interval bounds
   - window bounds
   - observed MAC/client identity
   - activity and probabilities
   - confidence/status
   - model and feature-schema versions
   - source capture provenance
5. Write a completion manifest only after all windows and predictions are durable.
6. Verify counts, timestamps, model compatibility, and storage writes.
7. Mark the interval safe for raw-capture cleanup.

Unmapped and randomized MACs will be included as observed identities without creating permanent device records.

Manual control will initially be CLI-only:

```text
process one completed interval
finalize a day
retry a failed interval
show interval status
```

## Phase 4 — Daily summaries

At local end-of-day or via the manual CLI:

- Read all verified per-window prediction files for that day.
- Generate summaries in the existing derived SQLite store.
- Retain all observed MAC identities, including randomized/unmapped identities.
- Store per-identity:
  - first/last observation
  - total active duration
  - activity durations and counts
  - confidence statistics
  - unknown/low-confidence duration
  - packet/byte totals where available
  - source interval count and provenance
- Merge consecutive compatible activity windows into daily segments.
- Preserve `unknown` rather than forcing a label.
- Make summary generation idempotent using date plus source-manifest hashes.

After successful summary verification:

- Delete that day’s per-window activity files.
- Retain daily summaries for seven days.
- Delete summaries older than seven days through a dry-run-first retention job.

Raw Kismet files may be deleted only after their interval completion manifests and daily-summary requirements are satisfied. Active files, journaled files, failed intervals, and held investigations must never be removed.

## Tests and acceptance criteria

- Confirm 30-second boundary alignment and no cross-interval windows.
- Confirm repeated interval execution is idempotent.
- Simulate malformed, active-journal, incomplete, and missing captures.
- Verify no raw packet bytes enter prediction files or SQLite summaries.
- Verify capture deletion is blocked until durable processing verification succeeds.
- Verify randomized and unmapped MAC identities are summarized.
- Verify `unknown` is returned below the confidence threshold.
- Verify Kismet logging API behavior on the installed runtime.
- Verify disk usage decreases after safe cleanup.
- Verify daily summaries remain readable after per-window files are removed.
- Verify seven-day summary retention.
- Replay a completed interval and confirm deterministic output.

## Assumptions

- Default interval: 10 minutes.
- Activity windows: 30 seconds, non-overlapping.
- Detailed prediction files: retained until daily finalization, then deleted.
- Daily summaries: retained for seven days.
- Manual operation: CLI-only initially.
- All observed MACs are included, but they do not become permanent inventory devices.
- No additional online dataset is required for this optimization phase.
