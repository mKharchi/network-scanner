# Installing a Client on a Legacy PC

Some older installations cannot receive `UPDATE_CLIENT` packages. They may
use the old flat layout, lack `client/app/version.json`, lack
`client/updater/updater.py`, or run a client version whose updater predates the
current manifest/chunk protocol. Do not send a managed update to such a PC and
assume it will self-install.

## 1. Identify the legacy state

On the PC, check for:

```text
client\app\version.json
client\updater\updater.py
client\config\.env
```

Also check the running launcher and scheduled task/service. A flat root
`client.py` alone is not proof that the current updater is available.

## 2. Preserve the old installation

Before migration:

1. Stop the old Windows service or scheduled task.
2. Copy the complete old client directory to a dated backup location.
3. Save the old `SERVER_IP`, `SERVER_PORT`, custom environment values, and
   any local logs needed for troubleshooting.
4. Confirm the old client is no longer connected before installing the new
   one, so two agents do not register as the same endpoint.

## 3. Install the current layout manually

Copy/extract the current client distribution to a new permanent location such
as `C:\NetworkScanner\client`. Do not copy the server directory or database
credentials. Create a fresh virtual environment and install
`app\requirements.txt` as described in
[Fresh Client Installation](client-installation.md).

Create `config\.env` with the endpoint's server address, test a foreground
connection, and then install the user-session task. Preserve the old install
until the new client has registered, reported its version, and passed a basic
command/health test.

## 4. Why manual migration is required

The server-managed update begins only after the client receives
`DEPLOY_PACKAGE_INIT`/`PACKAGE_CHUNK` frames and can launch the updater. A
legacy client cannot reliably receive or apply that lifecycle. Manual
migration installs the updater first; subsequent versions can then use the
normal package/update workflow.

## 5. Rollback

If the new client fails to connect or collect required data:

1. Stop its task/service.
2. Restore the old installation and its saved configuration.
3. Start only the old launcher.
4. Confirm the original client ID is online.
5. Inspect logs before retrying the migration.

Do not delete the old backup until the migration has been accepted by the
operator.

