# TCP Protocol Proposal

## Naming

Use the existing `COMMAND`/`RESPONSE` envelope and the repository's command naming style. Proposed command: `GET_KISMET_OBSERVATIONS`. This is a command, not a new top-level message type. The response remains `type: RESPONSE` so `receive_client_messages()` and the existing queue continue to work.

## Request

```json
{
  "type": "COMMAND",
  "command": "GET_KISMET_OBSERVATIONS",
  "args": {
    "request_id": "kismet-<unique-id>",
    "client_id": "client-aabbccddee01",
    "device_mac": "AA:BB:CC:DD:EE:01",
    "start_time": "2026-09-06T11:50:00+00:00",
    "end_time": "2026-09-06T12:00:00+00:00",
    "limit": 500,
    "include_noise": false
  }
}
```

The server creates `request_id`; it must be cryptographically or practically unique for concurrent requests. `client_id` is an assertion for validation/logging, not an authority. The server must not put a user-supplied arbitrary client ID into the selected socket without resolving that ID first.

## Success response

```json
{
  "type": "RESPONSE",
  "command": "GET_KISMET_OBSERVATIONS",
  "data": {
    "status": "ok",
    "request_id": "kismet-<unique-id>",
    "client_id": "client-aabbccddee01",
    "query_window": {
      "start": "2026-09-06T11:50:00+00:00",
      "end": "2026-09-06T12:00:00+00:00",
      "start_inclusive": true,
      "end_inclusive": true,
      "timezone": "UTC"
    },
    "observations": [],
    "summary": {
      "observation_count": 0,
      "total_matched_packets": 0,
      "avg_signal_dbm": null,
      "min_signal_dbm": null,
      "max_signal_dbm": null,
      "channels": [],
      "frame_types": {},
      "noise_filtered": true
    },
    "truncated": false,
    "next_cursor": null
  }
}
```

An observation should preserve the existing UI shape: `timestamp`, `epoch_sec`, `epoch_usec`, `role`, source/destination/transmitter MACs, frame type/subtype, signal, frequency, channel, packet length, sensor, capture file, and packet hash.

## Error response

```json
{
  "type": "RESPONSE",
  "command": "GET_KISMET_OBSERVATIONS",
  "data": {
    "status": "error",
    "request_id": "kismet-<unique-id>",
    "client_id": "client-aabbccddee01",
    "error_code": "KISMET_UNAVAILABLE",
    "message": "No local Kismet database is available.",
    "retryable": true
  }
}
```

Use stable error codes, not exception text as the contract. At minimum: `INVALID_REQUEST`, `INVALID_TIME_RANGE`, `KISMET_UNAVAILABLE`, `KISMET_QUERY_FAILED`, `RESULT_TOO_LARGE`, `IDENTITY_MISMATCH`, and `INTERNAL_ERROR`.

## Correlation and validation

The server accepts a response only when all are true:

- response type is `RESPONSE`;
- command is exact;
- `data.request_id` equals the outstanding request ID;
- `data.client_id` equals the registered client ID for the selected socket;
- `query_window` equals the normalized request window;
- observations are a list and each record validates;
- `status` is `ok` or `error`.

A mismatch is an error and must not be returned as an empty result. Log the selected client, socket-associated ID, request ID, and mismatch reason without logging sensitive raw packet data.

## Size strategy

Start with the existing limit and a strict maximum response size. The current UI asks for 500 and the server service caps at 2,000. Return at most the requested limit, set `truncated: true` when more records exist, and expose `next_cursor` only if an implementation proves pagination necessary. Do not add chunking or compression before measuring actual payloads. If one-frame responses exceed the established socket payload budget, implement the smallest existing package/chunk pattern rather than inventing a stream.
