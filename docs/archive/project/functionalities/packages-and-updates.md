# Packages, File Deployment, and Client Updates

## Three deployment operations

| Operation | Destination | Restarts client | Rollback |
| --- | --- | --- | --- |
| `SEND_FILE` | Client `storage/sent-files/` | No | No |
| `DEPLOY_PACKAGE` | Client package/current state | Usually no | Package operation failure is reported |
| `UPDATE_CLIENT` | Client `app/` | Yes | Yes |

## Server package lifecycle

`package_service.py` stores uploads under `server/storage/packages/` and records
metadata in the `packages` table. The server limits package size,
normalizes IDs/filenames, calculates SHA-256, and supports a builder endpoint
that copies `client/app/`, writes `version.json`, generates `manifest.json`,
hashes every application file, and creates a zip package.

An update package contains:

```text
client-update-<version>.zip
├── manifest.json
└── app/
    ├── version.json
    ├── requirements.txt
    └── application files
```

The manifest contains semantic version, package type, minimum updater version,
release notes, build time, and per-file SHA-256 hashes.

## Transfer lifecycle

1. Operator uploads/builds a package and receives a `package_id`.
2. Operator creates an `UPDATE_CLIENT`, `DEPLOY_PACKAGE`, or `SEND_FILE` action.
3. The server sends `DEPLOY_PACKAGE_INIT` and bounded `PACKAGE_CHUNK` frames.
4. The client writes to `storage/updates/incoming/`, tracks bytes/hash, and
   reports failure if the sequence or hash is invalid.
5. An update spawns `client/updater/updater.py` so the main client can stop
   cleanly.

## Update and rollback lifecycle

The updater:

1. Safely extracts the zip and rejects path traversal.
2. Validates `manifest.json`, semantic version, updater compatibility, and all
   file hashes.
3. Stops the current client.
4. Copies the current `app/` to `storage/updates/history/<old-version>/`.
5. Replaces `app/` with the staged app tree, removing stale application files.
6. Installs changed `requirements.txt` dependencies into the existing venv.
7. Starts the new client and verifies `version.json`.
8. Writes update state/results for the server and operator.

Any validation, dependency, or startup failure restores the backup when
possible. Configuration outside `app/` is not replaced.

## Concurrency and limits

The server throttles concurrent package deployments and records each target
independently. The package service enforces the configured maximum package
size. Operators should update a test client first, then a small canary group,
then the remaining fleet.

See [Client updates](../operations/client-updates.md) for commands and
[Legacy client migration](../operations/legacy-client-migration.md) for PCs
that cannot receive this protocol.

