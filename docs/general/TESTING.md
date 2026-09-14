# Testing and Verification

## Python suites

Client tests:

```bash
PYTHONPATH=client/app client/.venv/bin/python -m unittest discover \
  -s client/tests -p 'test_*.py'
```

Server tests:

```bash
server/.venv/bin/python -m unittest discover \
  -s server/tests -p 'test_*.py'
```

Kismet-focused tests:

```bash
server/.venv/bin/python -m unittest \
  server.tests.test_kismet_retention \
  server.tests.test_kismet_investigation_service
```

Some network/socket tests require normal host permissions; a sandboxed run may
fail before the test code executes. Record whether a failure is a test
assertion or an environment permission failure.

## Frontend checks

```bash
cd server/gui
npm run build
```

The build runs TypeScript validation and Vite production bundling. Warnings
about large chunks should be reviewed but are not automatically failures.

## Operational Kismet verification

The current Linux host uses:

```bash
bash scripts/phase10_post_reboot_check.sh
```

The checker validates the systemd service, monitor interface, localhost
listeners, application sensor health, and retention dry-run. It is read-only.

For a new Linux host also test:

- monitor-interface loss and systemd recreation;
- unavailable capture storage and degraded health;
- stopped Kismet and API health transition;
- reboot/startup order;
- retention dry-run and isolated actual-prune fixtures;
- localhost binding and Kismet authentication.

## Update verification

Before a fleet update, test a package against an isolated client fixture and a
canary endpoint. Confirm:

1. manifest and every file hash validate;
2. the old app backup exists;
3. configuration remains untouched;
4. dependencies install in the existing venv;
5. the new version registers;
6. a deliberately broken package rolls back.

