# Phase 2 — Kismet Persistence and Storage Configuration

**Status:** PENDING

## Objective

Freeze the target server’s actual Kismet persistence contract and configure output on its verified high-capacity Linux mount.

## Required evidence

- output path/mount, capacity, owner/group/ACL, configuration setting, and free-space reserve;
- actual file/database/API format, schema/version, relevant timestamp/MAC/RSSI/frame fields;
- active-file read behavior, WAL/journal sidecars, rotation, restart continuity, and retention behavior;
- measured hourly growth and capacity projections from target-server capture;
- explicit retention duration, cleanup ownership, dry-run, and active-file safety rules.

## Exit criterion

A bounded historical query source and safe storage lifecycle are documented without assuming the pilot schema or a `D:` path.
