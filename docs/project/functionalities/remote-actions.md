# Remote Actions and Client Management

## Action model

The server represents remote work as an action with one or more target rows.
The lifecycle is:

```text
PENDING -> RUNNING -> COMPLETED
                    -> FAILED
                    -> TIMED_OUT
                    -> CANCELLED
```

Bulk updates add a parent bulk record and independent per-client actions so a
failure on one endpoint does not automatically stop other targets.

## Implementation path

| Layer | File | Responsibility |
| --- | --- | --- |
| Action names/states | `server_components/action_framework.py` | Enum, aliases, supported command inventory, progress summaries |
| Dispatch and persistence | `server_components/action_service.py` | Create, execute, target fan-out, result/cancel handling |
| Transport | `server_components/server_lib.py` | Framed command delivery and response matching |
| Client execution | `client/app/client_lib.py` and `action_framework.py` | Validate and run supported commands |
| REST | `server/api_server.py` | Action and command endpoints |
| GUI | `ClientDetail.tsx`, `UpdateClientPanel.tsx`, `Locations.tsx` | Operator controls and progress display |

## Supported action families

- Client information: processes, CPU, memory, disk, network, system health,
  activity logs, and ping.
- Control: disconnect, restart, shutdown, kill/start process.
- Collection: network neighbourhood, passive neighbourhood, diagnostics,
  screenshots, telemetry sync.
- Policy: update forbidden processes, resource protection, observation scope.
- Isolation: isolate, release, and inspect device state.
- Deployment: send file, deploy package, update client.
- Spatial: assign, propose, confirm, or update client location.

Every command must be validated on the client before execution. Long-running
actions use server-side timeouts and result records rather than holding an HTTP
request open indefinitely.

## Safety rules

- Require a connected target for commands that need an active socket.
- Show confirmation for destructive actions in the GUI.
- Preserve action ID, operator ID, target, status, and result/error details.
- Use the package workflow for updates; do not overwrite a running client
  manually from the API.

