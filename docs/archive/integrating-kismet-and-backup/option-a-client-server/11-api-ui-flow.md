# API and UI Flow

## Existing contract to preserve

The current route is:

```text
GET /api/v1/devices/{id}/wireless-observations
```

Aliases already exist for network devices and network observations. Query parameters are `lookback`, `start`, `end`, `limit`, and `include_noise`. The response is wrapped by the existing API envelope and contains `device`, `query_window`, `summary`, and `observations`.

The UI's `WirelessInvestigationPanel` already supports presets, custom UTC/ISO inputs, a maximum observation selector, noise filtering, loading/stale-error/error/empty states, table filters, and JSON/CSV export. No UI code or new behavior is required for Option A.

## Request flow

```text
Panel chooses 15m / 1h / 24h / custom
  -> existing API client serializes query parameters
  -> api_server parses them
  -> api_service delegates
  -> KismetInvestigationService resolves target and exact UTC window
  -> selected client command
  -> response normalized to existing API shape
  -> send_data envelope
  -> panel renders existing fields
```

## Response compatibility

The client must return the fields the current server formatter/UI uses, including `epoch_usec`, frame role/type/subtype, channel, sensor, capture file, and packet hash. Do not return only the reduced live-listener payload unless the server enriches it from information that is impossible to obtain remotely; the server cannot recover remote Radiotap bytes or file metadata after the fact.

The existing TypeScript type expects `device.mac_address` while the service result currently uses `device.mac`. This is an existing contract inconsistency. Option A should not broaden scope to a UI rewrite, but the implementation must choose one canonical compatibility mapping and add a regression test so the relay does not amplify the mismatch.

## Error presentation

- Empty successful query: retain the current “No wireless observations in time window” state.
- Offline client/Kismet unavailable/query failure: return an error that the panel renders as a failed refresh, not as “no observations.”
- Invalid time range: return the API's existing client-error style after confirming current conventions; do not turn it into a successful empty response.

## Alert flow

`get_alert_wireless_investigation()` derives the suspect MAC and uses the alert's `[detected_at - lookback, detected_at]` interval. It should call the same remote service path, so alert investigations and the device panel cannot diverge in timestamp filtering or storage source.

## No frontend changes planned

Files to inspect during implementation but not change by default:

- `server/gui/src/components/WirelessInvestigationPanel.tsx`
- `server/gui/src/api/client.ts`
- `server/gui/src/pages/DeviceDetail.tsx`

Only change them if an API contract regression is demonstrated by tests. The requested feature is a backend routing correction, not a new UI feature.
