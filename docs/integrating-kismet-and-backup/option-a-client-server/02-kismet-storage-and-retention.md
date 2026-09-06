# Kismet Server Storage and Retention Design

**Status:** Storage location and format are verification-gated.

## Ownership and placement

Kismet historical data belongs on server-side persistent storage with sufficient capacity. The project refers to a large `D:` drive, but that Windows-style name is not a Linux path. Deployment must first identify the actual mounted filesystem, capacity, filesystem ownership, and stable mount point. Configuration must use that verified Linux path, not a hard-coded `D:/` or an unverified `/storage` path.

```text
Linux filesystem -> verified high-capacity mount -> Kismet output root
                                      -> active capture files
                                      -> retained historical files
                                      -> optional bounded archive
```

The Kismet process writes there; the server application receives read-only access through a dedicated group/ACL or equivalent. Windows clients have no access.

## Data model decision

Do not add a raw-observation MySQL table. Prefer Kismet’s own persistent representation when it supports bounded MAC-and-time queries with the fields required by the investigation UI. Raw capture and structured application data stay separate:

```text
Kismet persistence: packet/device metadata and optional raw evidence
MySQL: device identity, client observations, alerts, location, configuration
```

The pilot indicates a `.kismet` SQLite database and a `packets` table may be available, with timestamp, MAC, signal, frequency, packet length, datasource, DLT, raw packet, and hash fields. The target version must confirm this before it becomes the query contract. If the target uses a different database, files, API history, or only device summaries, adapt the server reader to that verified source instead of emulating an old schema.

## Queryable historical source

Choose exactly one initial historical path after runtime verification:

1. **Local Kismet persistence** — preferred when the server application can safely open the active/rotated database read-only and the required schema is present.
2. **Local authenticated Kismet API** — acceptable only if it provides bounded historical data, required fields, and documented access controls.
3. **Combined** — local API for process/source health; local persistence for historical investigation.

The reader must handle active-file journaling/WAL, rotation, missing/corrupt files, and multiple retained files. It must not scan arbitrary home directories or guess capture paths.

## Retention and cleanup

Capture retention is independent of the existing `client/app/retention_manager.py`. That manager protects client JSON telemetry artifacts after flow processing; it is not a safe Kismet cleanup mechanism and must not be redirected at Kismet files without a dedicated server-side design.

Define configuration after actual growth is measured:

```text
KISMET_CAPTURE_ROOT=<verified Linux path>
KISMET_RETENTION_HOURS=<approved duration>
KISMET_MIN_FREE_BYTES=<safety reserve>
KISMET_CLEANUP_DRY_RUN=<true during rollout>
```

A server-side retention job may remove only an eligible, closed capture after the verified retention period. It must never delete the active write target, a file with active journal/sidecar use, or a file retained for an open investigation policy. It must log candidates, bytes, reasons, errors, and remaining free space. Start in dry-run mode and verify recovery from a failed cleanup.

## Capacity and measurement

The pilot documented about 86 MB for 41.23 minutes and an estimate of roughly 125 MB/hour. These are **pilot-specific** observations, not server sizing commitments. Target-server Phase 2 must measure capture bytes over a representative interval, then calculate daily/weekly/monthly retention needs using that measured rate and the confirmed output types. Include filesystem reserve and rotation overlap in capacity planning.

## Security and privacy

- Bind any Kismet management/API interface to localhost or a private approved address; require authenticated access if enabled.
- Do not expose raw Kismet files through the client TCP protocol or browser.
- Restrict capture-root read access to the Kismet service and server application account/group.
- Return normalized metadata by default, never raw packet payloads.
- Define retention/deletion according to the organization’s authorized-monitoring and privacy requirements.

## Storage acceptance criteria

Before `KismetInvestigationService` is changed, document actual output format, paths, ownership, schema/API capabilities, time precision, MAC fields, read concurrency behavior, file rotation, observed growth, retention target, cleanup mechanism, and restart behavior.
