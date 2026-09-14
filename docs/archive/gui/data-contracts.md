# Network Monitoring GUI — Data Contracts

## Status and boundary

This is the Milestone 3 contract for the planned graphical interface. It
describes the **read-only operator API that must be added** before a browser
GUI is connected. It is not implemented by the current server.

The existing TCP socket protocol is exclusively for monitoring clients. A
browser must not connect to it: it has no operator authentication, no browser
origin protection, and its `COMMAND` messages can perform client actions.
The GUI should instead use a local server-side HTTP API under `/api/v1`.

All JSON responses use this envelope:

```json
{
  "data": {},
  "meta": {}
}
```

Errors use this envelope:

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "The requested resource does not exist."
  }
}
```

Dates and times are ISO-8601 strings with a UTC offset. A missing value is
`null`, not a made-up string such as `"Unknown"`. MAC addresses are canonical
uppercase, colon-separated strings. Device identity is the MAC address, never
the IP address.

## Existing sources that the adapter may read

| UI concern | Existing source | Notes |
| --- | --- | --- |
| Managed client identity/history | `clients`, `connections` | Connection history is persistent. Current online state is only the in-memory `server_lib.clients` registry. |
| Alerts | `alerts` joined to `clients` | Alert status exists but no status-update handler exists. |
| Activity-log list | `activity_logs` joined to `clients` | Full content is stored in each row's `file_path`. |
| Activity-log content | JSON under `server/storage/logs/client-<db id>/` | The adapter must validate that the requested file belongs to the requested log record. |
| Latest/historical discovery | timestamped JSON files in `server/storage/network_scans/` | Each file has `completed_at`, `network`, `devices_found`, and `devices`. |
| Daily ARP snapshots and DHCP timeline | `network_scan_YYYY-MM-DD.json`, optionally referenced by `daily_network_scan_files` | Daily file has `date`, `neighbour_snapshots`, and `dhcp_observations`. DHCP is file-only, not a device DB observation. |
| Current-ish client observations | `network_devices`, `network_device_observations` | Existing manual aggregation currently filters `CLIENT_ARP` observations by `NETWORK_CLIENT_OBSERVATION_MAX_AGE_SECONDS` (default 3600); daily snapshots therefore become stale after one hour unless that policy changes. |
| Working-hours rules | `working_hours` | Existing server computes a current working-hours result, but it has no read endpoint. |
| Forbidden-process rules | `forbidden_processes` | Existing function supplies these only to a registering client. |

## Shared view models

### Managed client summary

```json
{
  "id": "client-e4fd45ba8b96",
  "database_id": 1,
  "hostname": "DESKTOP-DJP05CM",
  "ip_address": "172.16.0.102",
  "mac_address": "E4:FD:45:BA:8B:96",
  "os": {
    "system": "Windows",
    "release": "11",
    "version": "...",
    "machine": "AMD64"
  },
  "connection": {
    "state": "ONLINE",
    "last_connected_at": "2026-08-17T14:00:00+00:00",
    "last_disconnected_at": null
  },
  "created_at": "2026-08-15T09:00:00+00:00",
  "updated_at": "2026-08-17T14:00:00+00:00"
}
```

`connection.state` is `ONLINE` only when the client is in the live server
registry; otherwise it is `OFFLINE`. `last_connected_at` and
`last_disconnected_at` come from `connections`, not from a guessed heartbeat.

### Network device

```json
{
  "mac_address": "E4:FD:45:BB:18:3B",
  "ip_address": "172.16.0.17",
  "hostname": null,
  "vendor": "Intel Corporate",
  "os": {
    "name": null,
    "family": null,
    "confidence": null
  },
  "classification": "UNMANAGED",
  "is_managed": false,
  "managed_client_id": null,
  "last_observed_at": "2026-08-17T14:32:56+00:00",
  "sources": []
}
```

`classification`, `is_managed`, `managed_client_id`, and `sources` are
available in timestamped scan JSON. The adapter must derive or omit them only
where their source does not provide them; it must not label a daily DHCP event
as a current device presence.

### Alert

```json
{
  "id": 42,
  "client": {"id": "client-e4fd45ba8b96", "hostname": "DESKTOP-DJP05CM"},
  "type": "FORBIDDEN_PROCESS",
  "severity": "HIGH",
  "status": "NEW",
  "detected_at": "2026-08-17T16:23:28+00:00",
  "activity_time": "2026-08-17T16:21:00+00:00",
  "title": "Forbidden process detected",
  "description": "...",
  "activity_log_id": 5
}
```

### Activity-log record

```json
{
  "id": 5,
  "client": {"id": "client-e4fd45ba8b96", "hostname": "DESKTOP-DJP05CM"},
  "period": "1d",
  "generated_at": "2026-08-17T16:23:28+00:00",
  "received_at": "2026-08-17T16:23:30+00:00"
}
```

The detail form adds `since` and `activity`, where each activity item is the
stored `{ "time", "type", "detail" }` structure.

## Page contracts

### Dashboard

**Required request:** `GET /api/v1/dashboard`

**Parameters:** none.

**Response:**

```json
{
  "data": {
    "generated_at": "2026-08-17T16:30:00+00:00",
    "clients": {"online": 2, "offline": 3, "total": 5},
    "alerts": {"new": 4, "critical": 1},
    "latest_scan": {
      "completed_at": "2026-08-17T14:49:41+00:00",
      "devices_found": 12,
      "scan_id": "2026-08-17_14-49-41_384722"
    },
    "dhcp_today": {"date": "2026-08-17", "observations": 8},
    "recent_alerts": [],
    "online_clients": []
  },
  "meta": {}
}
```

**Loading:** show summary-card and table skeletons. **Empty:** zero counts and
an explicit “No completed network scan yet” card. **Error:** retain any last
successful response, mark it stale, and offer retry.

### Clients list and client detail

**Required requests:**

* `GET /api/v1/clients?state=ONLINE|OFFLINE&search=&limit=50&cursor=`
* `GET /api/v1/clients/{client_id}`

**List response:** `{ "data": { "items": [Managed client summary], "next_cursor": null }, "meta": {} }`.

**Detail response:** `{ "data": { "client": Managed client summary, "recent_connections": [], "alert_counts": {"new": 0, "total": 0}, "latest_activity_log": Activity-log record | null }, "meta": {} }`.

**Loading:** table rows or a detail header skeleton. **Empty:** “No managed
clients registered.” **Not found:** `404 NOT_FOUND`. **Error:** a retryable
page-level error. Connection status must never be inferred from an old DB row.

### Network — latest scan

**Required request:** `GET /api/v1/network/scans/latest`

**Parameters:** none initially. Later filtering can be client-side or add
`classification=MANAGED|UNMANAGED` and `search=`.

**Response:**

```json
{
  "data": {
    "scan": {
      "id": "2026-08-17_14-49-41_384722",
      "completed_at": "2026-08-17T14:49:41.384722+00:00",
      "network": {"interface": "client-reported", "local_ip": null, "network": "client-reported", "gateway": null},
      "devices_found": 12,
      "devices": ["Network device"]
    }
  },
  "meta": {}
}
```

**Loading:** table skeleton. **Empty:** “No completed scan is available.”
**Error:** explain that scan data could not be read; do not render a partial or
invalid JSON file.

### Network — scan history

**Required requests:**

* `GET /api/v1/network/scans?from=YYYY-MM-DD&to=YYYY-MM-DD&limit=50&cursor=`
* `GET /api/v1/network/scans/{scan_id}`

The list returns `{items: [{id, completed_at, devices_found, network}],
next_cursor}`. The detail returns the same `scan` model as latest scan. The
adapter derives `scan_id` from a validated timestamped filename and never
accepts a filesystem path from the browser.

**Loading:** list/table skeleton. **Empty:** no scans in selected range.
**Error:** invalid query → `400 INVALID_QUERY`; unreadable individual file →
`500 SCAN_DATA_UNAVAILABLE` without leaking its absolute path.

### Network device detail

**Required request:** `GET /api/v1/network/devices/{mac_address}`

**Parameters:** canonical MAC address in the URL. The adapter may accept
lowercase/hyphen input and normalize it before lookup.

**Response:**

```json
{
  "data": {
    "device": "Network device",
    "observations": [
      {
        "source_type": "CLIENT_ARP",
        "source_client_id": "client-e4fd45ba8b96",
        "ip_address": "172.16.0.17",
        "interface": null,
        "entry_type": "dynamic",
        "observed_at": "2026-08-17T14:32:56+00:00"
      }
    ],
    "dhcp_observations": []
  },
  "meta": {}
}
```

`dhcp_observations` is a historical audit lookup from daily files, matched by
the DHCP neighbour MAC. It must not overwrite the device's ARP observation
history or imply that the IP is permanent.

**Loading:** header and timeline skeleton. **Empty:** a device can have no
DHCP records; show this as a normal empty secondary section. **Not found:**
`404 NOT_FOUND`. **Error:** surface source-specific errors without discarding
the device identity already loaded.

### DHCP activity

**Required request:** `GET /api/v1/network/dhcp?date=YYYY-MM-DD&reporter_mac=&limit=100&cursor=`

`date` defaults to the server's current local date. The response is a
paginated view of the selected daily audit file:

```json
{
  "data": {
    "date": "2026-08-17",
    "items": [
      {
        "received_at": "2026-08-17T16:00:00+00:00",
        "reporting_client_mac": "E4:FD:45:BA:8B:96",
        "neighbours": [],
        "dhcp": {"message_type": 3, "vendor_class": "...", "client_id": "..."}
      }
    ],
    "next_cursor": null
  },
  "meta": {}
}
```

**Loading:** chronological-row skeleton. **Empty:** “No DHCP observations for
this date.” This is normal. **Error:** a missing daily file is an empty result,
while malformed/unreadable JSON is `500 DHCP_AUDIT_UNAVAILABLE`.

### Alerts

**Required requests:**

* `GET /api/v1/alerts?status=NEW&severity=HIGH&client_id=&from=&to=&limit=50&cursor=`
* `GET /api/v1/alerts/{alert_id}`

The list returns paginated `Alert` items. Detail returns one `Alert`, the
managed client summary subset, and its related activity-log metadata when
`activity_log_id` is present.

**Loading:** list/detail skeleton. **Empty:** “No alerts match these filters.”
**Not found:** `404 NOT_FOUND`. **Error:** retryable error with filters kept.

Alert acknowledgement/resolution is intentionally outside this read-only
milestone. It requires a later authenticated `PATCH /api/v1/alerts/{id}`
contract and audit policy.

### Activity logs

**Required requests:**

* `GET /api/v1/activity-logs?client_id=&period=&from=&to=&limit=50&cursor=`
* `GET /api/v1/activity-logs/{log_id}`

The first response is paginated `Activity-log record` metadata. The second
returns `{ log: Activity-log record, since, activity }` from the associated
stored JSON only.

**Loading:** table skeleton and detail timeline skeleton. **Empty:** “No
stored activity logs match these filters.” **Not found:** `404 NOT_FOUND`.
**Error:** missing/corrupt log JSON → `410 LOG_CONTENT_UNAVAILABLE`; keep the
metadata row visible if it was already loaded.

### Settings (read-only first)

**Required requests:**

* `GET /api/v1/settings/working-hours`
* `GET /api/v1/settings/forbidden-processes`

Working-hours response: `{ "data": { "rules": [{"day_of_week": 0,
"start_time": "09:30:00", "end_time": "18:00:00", "enabled": true}],
"current_status": {"within_working_hours": true, "checked_at": "..."} },
"meta": {} }`.

Forbidden-processes response: `{ "data": { "items": [{"process_name":
"discord", "severity": "HIGH", "enabled": true, "description": "..."}] },
"meta": {} }`.

**Loading:** form-row skeleton. **Empty:** no enabled rules / no process rules.
**Error:** settings unavailable, with retry. Editing is deferred until access
control and mutation validation exist.

## Implementation decisions required before the GUI milestone

1. Add an HTTP server or web framework inside the existing Python server
   process (or a tightly coupled local service) and implement these read-only
   routes. Reuse the existing MySQL/database and storage modules; do not make
   the browser read server files directly.
2. Define operator authentication and authorization before serving the GUI on
   any network interface. The project currently has neither authentication nor
   TLS.
3. Decide the network freshness policy. With one ARP snapshot per client per
   day, the existing 3600-second aggregate filter conflicts with a “latest
   scan” view after the first hour.
4. Add explicit query functions for the existing database records. The current
   server exposes them only through terminal menus and internal functions.
5. Keep command execution (`PING`, process operations, disconnect) out of the
   first UI release. Those need separate command, timeout, authorization, and
   audit contracts.
