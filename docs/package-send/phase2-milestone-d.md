# Phase 2 Milestone D — New Client Folder Structure

Date: 2026-09-01

## Changed

- Moved replaceable application runtime code and bundled data into `client/app/`.
- Added `client/config/` for machine-specific configuration, `client/updater/` for the stable updater, `client/logs/`, and `client/storage/updates/{incoming,staging,history}/`.
- Added `client/storage/sent-files/` and retained existing durable storage directories.
- Added root compatibility launch/module shims so existing scheduled tasks, service references, test imports, and currently deployed flat-layout clients continue to resolve while migrating.
- Kept the virtual environment outside `app/`; the root `requirements.txt` bridges to `app/requirements.txt`.
- Updated application path constants for config, logs, storage, update staging/current, sent files, neighbourhood data, isolation state, and client location state.
- Updated the installation guide and PyInstaller spec for the new structure.
- No updater replacement behavior was added to the application tree during the structural portion; the updater is a separate stable component.

## Tested

- `python -m compileall -q client server`: passed.
- Server registration/action/package regressions: **26 tests passed**.
- GUI production build: passed.

## Installation limitation

A full manual reinstall and startup against a physical test PC was not possible from this source workspace. The guide, compatibility launchers, and path layout are ready for that checkpoint, but physical registration/connection verification remains required.
