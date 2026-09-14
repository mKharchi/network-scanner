# Client Updates

## Before updating

- Confirm the client is online and its current version is known.
- Build and test the package against a fixture/canary client.
- Keep `config/.env`, logs, and storage outside the package's `app/` tree.
- Confirm the server package store has enough space and the client has enough
  space for incoming, staging, and backup copies.

## Build a package

From the repository root, the package builder copies `client/app/`, writes the
requested semantic version, hashes every file, and writes a manifest:

```bash
python scripts/build_test_update_package.py \
  --version 2.4.0 \
  --output-dir ./test_packages
```

The server-side API can also build a package through
`POST /api/v1/packages/build-client-update`. The resulting archive contains
`manifest.json` and `app/`; it must not contain machine-specific configuration.

## Upload and update one client

```bash
SERVER=http://127.0.0.1:8080
PACKAGE=./test_packages/client-update-2.4.0.zip
CLIENT_ID=PC-TestUnit-001

curl -X POST "$SERVER/api/v1/packages" \
  -H 'Content-Type: application/zip' \
  -H "X-Package-Filename: $(basename "$PACKAGE")" \
  --data-binary "@$PACKAGE"
```

Use the returned `package_id` to create an `UPDATE_CLIENT` action through the
GUI or API. The action is asynchronous; poll `/api/actions/{action_id}` until
it reaches a terminal state and then confirm the client re-registers with the
new version.

## Bulk updates

Use the GUI bulk update panel or `POST /api/v1/bulk-updates` with a package ID
and explicit client selection. The server creates independent per-client
actions and throttles concurrent deployment. Review every target result;
`PARTIAL_SUCCESS` requires follow-up rather than an automatic retry of the
whole fleet.

## What the updater does

The client updater validates the archive, manifest, semantic version, minimum
updater version, safe paths, and file hashes. It stops the client, backs up
`app/`, replaces it atomically through staging, installs changed dependencies,
starts the new client, and verifies `version.json`. On failure it restores the
backup when possible and writes a result under
`storage/updates/results/`.

## Rollback and troubleshooting

Inspect the action result, client `logs/updater.log`, update state files, and
`storage/updates/history/`. Common statuses include invalid package, invalid
version, dependency failure, application start failure, and rollback failure.
Do not retry repeatedly until the original failure and available disk space
have been checked.

