# Probe API Contract

## Endpoint

`GET /api/v1/wifi/probes`

Optional filters: `lookback`, `start`, `end`, `limit` (1–2000), `subtype` (`request`, `response`, `all`), `randomized`, `channel`, `bssid`, `source_mac`, `capture_file`, and `min_signal`.

Responses include a bounded newest-first `observations` list, `candidate_groups`, RF/count summaries, query window, and scanned capture count.

`rejected_captures` identifies files that could not be read (for example, a
malformed capture). `degraded_captures` identifies a Kismet file with a
rollback journal read through SQLite immutable mode; those observations are
the last committed snapshot and may lag packets still inside Kismet's open
transaction. A stale journal remains a degraded warning and should eventually
be recovered by restarting Kismet.

The probe reader walks rows newest-to-oldest in bounded batches until it reaches
the requested start time (or has already collected enough newest matches for the
requested `limit`). The per-capture row budget is independent of `limit`, so a
small UI page size cannot hide an earlier probe burst behind newer data frames.
`truncated_captures` is returned if the safety cap is reached first, so a partial
result cannot be mistaken for a complete time window.

`GET /api/v1/devices/{device_id}/wireless-observations` uses the same journal
snapshot handling, but matches only the device's registered MAC. It is useful
for known-device traffic history and cannot discover a MAC-randomized Probe
Request by its physical-device identity.

Each observation includes normalized addresses, randomized-MAC state, destination delivery kind, RF values, sequence/retry state, IE tag order, rate pattern, vendor OUIs, capability digests, SSID shape only, sensor, and capture filename.

The response intentionally excludes Kismet `packet` BLOB data, raw information-element content, and plaintext SSIDs.

`GET /api/v1/sensors/wifi/health` additionally includes `management_capture`: a bounded sample count of recent Probe Requests/Responses, latest probe time, randomized-source count, and observed channels.
