# Phase 2 Milestone B — File Transfer Storage Separation

Date: 2026-09-01

## Changed

- Added `client/storage/sent-files/` as the ordinary file-transfer destination.
- Added `SEND_FILE` to both client and server action vocabularies and the server supported-command catalog.
- Extended the existing chunk/checksum transport initialization with an explicit `operation` and destination filename.
- `DEPLOY_PACKAGE` retains the existing `updates/incoming/`, `updates/staging/`, and `updates/current/` extraction/swap flow.
- `SEND_FILE` writes the verified file to `storage/sent-files/` and does not extract or modify `updates/current/`.
- Destination filenames and package IDs are validated as single relative filenames to prevent traversal.
- `SEND_FILE` uses the existing persistent action API and per-target action state; no parallel state machine was introduced.
- `DEPLOY_PACKAGE` callers retain their previous function signature and behavior.

## Tested

- Existing server package deployment tests and action framework tests: **22 tests passed**.
- Changed Python modules and tests: `py_compile` passed.
- Added client-side regression tests covering:
  - verified plain file delivery into `sent-files/`;
  - no update directory mutation;
  - traversal filename rejection.
- The client test module could not be executed in the managed environment because the runtime does not currently provide the client dependency `psutil`; syntax compilation passed instead.

## Physical/end-to-end limitation

A real server-to-client `SEND_FILE` transfer still requires a connected test client and the project’s runtime dependencies. That hardware/network verification remains outstanding and should be performed before treating Milestone B as production-validated.
