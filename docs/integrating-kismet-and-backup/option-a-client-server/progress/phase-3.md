# Phase 3 — Server-Side Data Access Contract

**Status:** PENDING

## Objective

Define and test the source adapter used by the server application to read the verified local Kismet history source.

## Requirements

- source access remains server-local and read-only;
- canonical MAC, UTC inclusive range, ordering, limit, truncation, and error contracts are fixed;
- source/destination/transmitter role matching and random-MAC handling are documented;
- synthetic fixtures represent the verified target schema/API rather than the former client listener assumptions;
- no client connection, client path, or TCP command is involved.

## Exit criterion

A testable server data-access boundary is ready for `KismetInvestigationService` refactoring.
