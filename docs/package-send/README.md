# Sending Files and Updating Clients

This is the operational guide for sending files to network-scanner clients and updating the client application.

The two workflows share the chunked, SHA-256-verified transport, but they have different destinations and behavior:

| Workflow | Action | Client destination | Restarts client | Rollback |
|---|---|---|---|---|
| Send a file | `SEND_FILE` | `client/storage/sent-files/` | No | No |
| Update one client | `UPDATE_CLIENT` | Staged, then replaces `client/app/` | Yes | Yes |
| Update multiple clients | Bulk update | Same as `UPDATE_CLIENT`, independently per client | Yes | Yes |

## Prerequisites

- The server is running and reachable at `http://SERVER_IP:8080`.
- The target client is connected and registered.
- `curl` is available. `jq` is useful when reading JSON responses.
- Update packages are `.zip` files containing `manifest.json` and `app/`.
- Do not put `config/.env` or other machine-specific configuration in an update package. The updater never replaces `client/config/`.

Set these variables in a shell before running the examples:

```bash
SERVER="http://SERVER_IP:8080"
CLIENT_ID="PC-TestUnit-001"
```

## 1. Confirm the server and target client

```bash
curl "$SERVER/health"
curl "$SERVER/api/v1/clients" | jq
curl "$SERVER/api/v1/clients/$CLIENT_ID" | jq
```

Use the client ID reported by the server. The client should be online before starting a transfer.

For update troubleshooting, confirm that the action is registered:

```bash
curl "$SERVER/api/v1/actions?types=1" | jq '.data.supported_actions'
```

The response should include `UPDATE_CLIENT` and `SEND_FILE`.

## 2. Upload a package to the server

The upload API stores the package in the server package store and returns a `package_id`. Keep that ID for the action request.

```bash
PACKAGE_FILE="./some-file-or-package.zip"

curl -X POST "$SERVER/api/v1/packages" \
  -H "Content-Type: application/zip" \
  -H "X-Package-Filename: $(basename "$PACKAGE_FILE")" \
  -H "X-Package-Id: my-package-001" \
  --data-binary "@$PACKAGE_FILE" | jq
```

`/api/packages` is also accepted. If `X-Package-Id` is omitted, the server generates an ID.

Save the returned value:

```bash
PACKAGE_ID="<package_id returned by the upload>"
```

You can verify that the server knows the package with:

```bash
curl "$SERVER/api/v1/packages/$PACKAGE_ID" | jq
```

## 3. Send a file to a client

Use `SEND_FILE` for an ordinary file transfer. The file can be a zip archive, but it is treated as a file and is not installed as application code.

```bash
ACTION_ID="send-$(date +%s)"

curl -X POST "$SERVER/api/actions" \
  -H "Content-Type: application/json" \
  -H "X-Operator-Id: network-operator" \
  -d "{
    \"action_id\": \"$ACTION_ID\",
    \"action_type\": \"SEND_FILE\",
    \"targets\": [\"$CLIENT_ID\"],
    \"parameters\": {
      \"package_id\": \"$PACKAGE_ID\",
      \"filename\": \"$(basename "$PACKAGE_FILE")\"
    }
  }" | jq
```

### What happens

1. The server resolves the uploaded package and calculates its SHA-256 and chunk count.
2. The server sends `DEPLOY_PACKAGE_INIT`, followed by `PACKAGE_CHUNK` messages.
3. The client writes chunks to `client/storage/updates/incoming/` while receiving them.
4. The client verifies the complete SHA-256 hash and moves the file to `client/storage/sent-files/`.
5. The client reports a successful `PACKAGE_RESULT`.
6. The file remains in `sent-files/`; the client application is not stopped or replaced.

Monitor the action:

```bash
curl "$SERVER/api/actions/$ACTION_ID" | jq
```

The final action status should be `SUCCESS`. A failed transfer should be investigated in the server and client logs before retrying.

## 4. Build a client update package

The repository includes a helper that copies `client/app/`, writes a new version, creates a manifest with SHA-256 hashes, and creates the zip file.

From the repository root:

```bash
python scripts/build_test_update_package.py \
  --version 2.0.0 \
  --output-dir ./test_packages
```

The output is `test_packages/client-update-2.0.0.zip`.

To exercise rollback in a test environment, build an intentionally broken package. Do not use this for a real deployment:

```bash
python scripts/build_test_update_package.py \
  --version 2.0.1 \
  --broken \
  --output-dir ./test_packages
```

An update package must have this layout:

```text
client-update-<version>.zip
├── manifest.json
└── app/
    ├── version.json
    ├── requirements.txt
    └── ...application files...
```

The manifest includes `version`, `package_type: "client-update"`, `minimum_updater_version`, and `file_hashes`. The updater rejects missing or invalid manifests, unsafe archive paths, and hash mismatches.

## 5. Update one client

Upload the update package first:

```bash
PACKAGE_FILE="./test_packages/client-update-2.0.0.zip"

UPLOAD=$(curl -s -X POST "$SERVER/api/v1/packages" \
  -H "Content-Type: application/zip" \
  -H "X-Package-Filename: $(basename "$PACKAGE_FILE")" \
  --data-binary "@$PACKAGE_FILE")

echo "$UPLOAD" | jq
PACKAGE_ID=$(echo "$UPLOAD" | jq -r '.data.package_id')
```

Create one `UPDATE_CLIENT` action:

```bash
ACTION=$(curl -s -X POST "$SERVER/api/actions" \
  -H "Content-Type: application/json" \
  -H "X-Operator-Id: network-operator" \
  -d "{
    \"action_type\": \"UPDATE_CLIENT\",
    \"targets\": [\"$CLIENT_ID\"],
    \"parameters\": {\"package_id\": \"$PACKAGE_ID\"}
  }")

echo "$ACTION" | jq
ACTION_ID=$(echo "$ACTION" | jq -r '.data.action_id')
```

Poll until the action reaches a terminal status:

```bash
while true; do
  RESULT=$(curl -s "$SERVER/api/actions/$ACTION_ID")
  echo "$RESULT" | jq '.data // .'
  STATUS=$(echo "$RESULT" | jq -r '.data.status // .data.state // .status // .state')
  case "$STATUS" in
    SUCCESS|FAILED|PARTIAL_SUCCESS|CANCELLED|EXPIRED) break ;;
  esac
  sleep 5
done
```

### Update lifecycle on the client

1. The server streams the package in chunks.
2. The client writes and hashes the incoming package.
3. After the final chunk, the client reports `STAGED` and starts the detached updater process.
4. The updater safely extracts and validates the package.
5. The updater stops the running client and backs up `client/app/` under `client/storage/updates/history/`.
6. The updater replaces `app/` with the package's desired state, including removing old files absent from the new package.
7. Changed or missing dependencies from `requirements.txt` are installed in the existing virtual environment.
8. The new client is started and checked.
9. On success, the client reports completion and re-registers with the new version.

Verify the version after the client has had time to restart and send a heartbeat:

```bash
curl "$SERVER/api/v1/clients/$CLIENT_ID" | jq
```

The client registry should show the new version. The local version is stored in `client/app/version.json`.

## 6. Update multiple clients

Bulk updates create one independent `UPDATE_CLIENT` action per target. One failed client does not stop the others.

First upload the package as in the previous section, then submit:

```bash
BULK_ID="bulk-update-$(date +%s)"

curl -X POST "$SERVER/api/v1/bulk-updates" \
  -H "Content-Type: application/json" \
  -H "X-Operator-Id: network-operator" \
  -d "{
    \"package_id\": \"$PACKAGE_ID\",
    \"bulk_update_id\": \"$BULK_ID\",
    \"target_selection\": {
      \"strategy\": \"individual\",
      \"client_ids\": [\"PC-001\", \"PC-002\", \"PC-003\"]
    }
  }" | jq
```

To target all eligible clients, use:

```json
{"package_id":"PACKAGE_ID","target_selection":{"strategy":"all"}}
```

Monitor aggregate and per-client status:

```bash
curl "$SERVER/api/v1/bulk-updates/$BULK_ID" | jq
```

The response includes aggregate counts and each client's action status and result. A bulk update is complete when `completed + failed` equals `total`.

## 7. Failure and rollback

If an update fails after the backup is created, the updater restores the previous `app/` directory and starts the previous client again. The result includes `status: UPDATE_FAILED`, a reason, and `rolled_back: true` when restoration succeeds.

Common failure reasons are:

| Reason | Meaning |
|---|---|
| `INVALID_PACKAGE` | Invalid zip, missing `manifest.json` or `app/`, or unsafe archive contents |
| `VERSION_INVALID` | Invalid version or incompatible updater version |
| `DEPENDENCY_INSTALL_FAILED` | Required dependency installation failed |
| `APPLICATION_START_FAILED` | The new client did not start successfully |
| `ROLLBACK` | The update failed and the backup could not be restored |

After a failed update, check the action result, confirm the old version is still reported, and verify that the client is running before retrying with a corrected package.

## 8. Logs and useful checks

On the client, inspect:

```text
client/logs/
client/logs/updater.log
client/storage/updates/history/
client/storage/updates/results/
```

On the server, inspect the running server output and the server log directory. Useful checks include:

```bash
curl "$SERVER/health"
curl "$SERVER/api/v1/actions?types=1" | jq
curl "$SERVER/api/v1/packages" | jq
```

Do not expose server ports `5000` or `8080` directly to the public internet. Keep package storage writable and ensure the client can reconnect to the server after an update.