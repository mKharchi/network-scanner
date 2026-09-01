# Phase 2 Milestone E — Standalone Updater Core

Date: 2026-09-01

## Changed

- Added `client/updater/updater.py` as a standalone process/library boundary.
- Defined and validated the `client-update` package manifest fields: `version`, `package_type`, `minimum_updater_version`, and `file_hashes`.
- Reused checksum and zip-slip-safe extraction principles for staged update packages.
- Added desired-state replacement of `app/`, so files absent from the new package are removed.
- Added backup history under `storage/updates/history/<old_version>/` and restoration on failure.
- Kept `config/` outside the replacement tree.
- Added dependency installation through the existing `venv` only when the staged app has `requirements.txt`; the updater invokes pip against that environment.
- Added startup validation hooks and explicit failure reasons: `INVALID_PACKAGE`, `VERSION_INVALID`, `DEPENDENCY_INSTALL_FAILED`, `APPLICATION_START_FAILED`, and `ROLLBACK`.
- Added `UPDATE_CLIENT` to the action vocabularies and long-running action catalog as the next wire-level integration point.
- Added focused updater tests for successful desired-state replacement, zip-slip rejection, dependency rollback, and application-start rollback.

## Tested

- `client/updater/test_updater.py`: **4 tests passed**.
- Full source compilation and server regression suites passed before this milestone.

## Remaining checkpoint

The updater core is not yet wired to a real `UPDATE_CLIENT` server action and has not been exercised against a physical client. Milestone F must add that single-client network action and verify one real success plus one real rollback before bulk update work begins.
