# REST and SSE API

The canonical detailed contract is [`server/docs/API_CONTRACT.md`](../../server/docs/API_CONTRACT.md).
This page groups the implemented routes by capability so operators can find
the correct area quickly.

## Connection and envelopes

- Base URL: `http://127.0.0.1:8080` on the approved local host profile.
- JSON routes use a `data` envelope for successful responses and an `error`
  envelope containing a stable `code` and message for failures.
- The server also accepts several legacy `/api/...` aliases maintained by
  `api_server.py`.
- `GET /api/v1/events` is an SSE stream used for live UI invalidation.

## Route groups

| Group | Representative routes | Purpose |
| --- | --- | --- |
| Health/dashboard | `/health`, `/api/v1/dashboard` | Service and overview state |
| Clients | `/api/v1/clients`, `/api/v1/clients/{id}` | Fleet inventory, status, connections, health |
| Client commands | `/api/v1/clients/{id}/commands` | Supported commands and synchronous dispatch |
| Actions | `/api/actions`, `/api/actions/{id}`, `/api/actions/{id}/targets` | Asynchronous action lifecycle |
| Network scans | `/api/v1/network/scans`, `/latest`, `/history` aliases | Discovery snapshots and collection jobs |
| Devices | `/api/v1/network/devices`, `/{mac}` | Device inventory, observations, classification |
| DHCP/neighbourhood | `/api/v1/network/dhcp`, neighbourhood collection routes | Passive network audit data |
| Wireless | `/api/v1/sensors/wifi`, `/api/v1/sensors/wifi/health`, device wireless observations | Kismet-backed investigation |
| Alerts | `/api/v1/alerts`, `/api/v1/alerts/{id}` | Triage, acknowledgement, resolution |
| Policies | `/api/v1/settings/working-hours`, `forbidden-processes`, `resource-protection` | Enforcement configuration |
| Locations/spatial | `/api/locations`, `/api/v1/spatial/*` | Assignment, floor maps, topology, replay |
| Screenshots/activity | `/api/v1/screenshots`, `/api/v1/activity-logs` | Evidence and client activity records |
| Packages | `/api/v1/packages`, `/build-client-update` | Upload, list, build, and delete packages |
| Bulk updates | `/api/v1/bulk-updates` | Fan-out update orchestration |

## Operational examples

```bash
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8080/api/v1/clients
curl http://127.0.0.1:8080/api/v1/sensors/wifi/health
curl http://127.0.0.1:8080/api/v1/events
```

For mutating routes, send JSON with `Content-Type: application/json` and use
the operator/action identifiers expected by the contract. Package uploads use
the package headers documented in
[Client updates](operations/client-updates.md).

