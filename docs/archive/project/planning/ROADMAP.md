# Feature Planning and Roadmap

This is the planning entry point for new work. Existing feature plans remain
under `docs/` as design history; new work should add a short proposal here
before implementation and then link the detailed plan.

## Planning rules

Every new feature should define:

1. operator/user outcome;
2. ownership boundary: client, server, GUI, sensor, or deployment;
3. data model and retention impact;
4. API and GUI contract;
5. failure, rollback, and privacy behavior;
6. migration impact for existing clients;
7. tests and operational acceptance evidence;
8. documentation updates required at release.

Do not describe a planned feature as available in the current functionality
guides. Mark it `PLANNED`, `IN PROGRESS`, `VERIFIED`, or `DEFERRED`.

## Current priorities

### P0 — Keep the verified deployment safe

- Move future Linux sensors from the root filesystem to an approved persistent
  mount without changing capture ownership or retention guarantees.
- Add an authenticated identity-aware access boundary if the API ever needs to
  leave localhost.
- Automate backup/restore verification for MySQL, server JSON, screenshots,
  packages, and Kismet captures as separate data classes.
- Keep update canary, rollback, and client legacy-migration procedures tested.

### P1 — Operational hardening

- Add structured deployment records for service versions, interface names,
  mount identity, retention approval, and privacy authorization.
- Add a supported Linux client-service profile if Linux endpoint agents become
  a first-class deployment target.
- Improve package signing/authenticity beyond transport hash verification.
- Add a scheduled, audited retention executor after deletion approval; keep
  dry-run as the default for new hosts.

### P2 — Product capabilities

- Improve spatial calibration and confidence visualization.
- Expand wireless investigation across multiple approved sensors.
- Add richer device classification review/training workflows.
- Improve GUI filtering, saved views, and operator audit exports.

## Existing design directions to reconcile before implementation

These historical plans are useful inputs, not automatic commitments:

- [3D visualization plans](../../3d-visualization/new-plan.md)
- [Client monitoring plan](../../client_monitoring/plan.md)
- [ML plan](../../ml/plan.md)
- [Passive protocol plan](../../passive protocol listener/plan.md)
- [Neighbourhood orchestration plan](../../neighborhood collect orchestration/collection-orchestration-plan.md)
- [Managed client plan](../../managed_clients/plan.md)
- [AR-enhanced topology plan](../../plans/02-ar-enhanced-3d-topology-visualization.md)
- [Autonomous edge-agent plan](../../plans/03-autonomous-edge-ai-self-healing-agent.md)

Before selecting one, compare it against the current architecture and resolve
whether it belongs on the client, server, GUI, or a separate sensor.

## Feature proposal template

```markdown
# Feature: <name>

Status: PLANNED
Owner boundary: client | server | GUI | sensor | deployment

## Outcome

## Current behavior and gap

## Design

## API/data/storage changes

## Client compatibility and migration

## Failure, rollback, and privacy behavior

## Tests and operational acceptance

## Documentation updates
```

## Release gate

A feature is ready only when code, tests, API/UI contracts, migration steps,
rollback behavior, and the relevant documentation agree. Operational features
that touch networking, storage, capture, process control, or privacy require a
host-level verification record in addition to unit tests.

