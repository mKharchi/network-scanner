# Time-Range Query Contract

## Normalization path

The existing UI sends either a preset (`15m`, `30m`, `1h`, `4h`, `24h`, `all`) or custom `start`/`end`. The API currently forwards those values to `KismetInvestigationService`. Option A should add a single normalization step in the server service before dispatch:

```text
preset/custom API values
  -> parse existing ISO/epoch conventions
  -> UTC-aware start/end
  -> validate and clamp limit
  -> send exact start/end to client
```

Use the existing `parse_lookback_to_minutes()` and `parse_iso_or_epoch()` conventions where they remain appropriate. Do not have the client interpret browser-local time or calculate `now` independently.

## Timestamp rules

- Canonical transport representation: UTC ISO-8601 with an explicit offset, preferably the existing `+00:00` output; accept existing `Z` input.
- Kismet source columns remain integer Unix seconds plus integer microseconds.
- Preserve `epoch_usec` in normalized observations for the UI and order ties by `(ts_sec, ts_usec)`.
- Convert all naive input to UTC only under the repository's existing convention; document that custom UI fields are UTC.
- Use inclusive bounds: `start <= ts <= end`. The SQLite predicate is `ts_sec >= start_epoch AND ts_sec <= end_epoch`; microseconds must be considered when precision is available so a record at the exact end second remains in the requested window.
- Return `query_window.start` and `.end` as the normalized values actually used.

## Presets

For a finite preset, compute `end = now(UTC)` at request handling time and `start = end - duration`. `all` must not silently become an unbounded remote query. Either retain the existing service maximum historical window or reject it for remote clients with `INVALID_TIME_RANGE`; the implementation plan recommends a configured maximum rather than unlimited reads.

For custom ranges, require both values, require `start < end`, and reject malformed, timezone-ambiguous, future/overly old, or over-maximum windows according to configured policy. Preserve the existing alert behavior of using `[detected_at - lookback, detected_at]` for alert investigations.

## Limits and pagination

- Minimum limit: 1.
- Default: existing API default 500.
- Maximum: existing service cap 2,000 unless a shared configuration says otherwise.
- The client applies the limit after deterministic ordering and reports `truncated` if another matching row exists.
- Do not fetch all rows and slice after transport.
- Add cursor pagination only if the UI or observed captures make the bounded response insufficient; a cursor must encode the last `(ts_sec, ts_usec, packet_hash)` and the same query identity.

## Security check

The server must validate the target device MAC and select the client owner before sending. The client must validate the requested MAC, time range, and limit again. A client must not query arbitrary files outside its configured Kismet directory.

## Required tests

- `15m`, `1h`, and `24h` calculate exact UTC bounds.
- Custom ISO and epoch inputs normalize identically.
- Start and end inclusivity work at second and microsecond boundaries.
- Records immediately outside either boundary are excluded.
- Empty range returns successful zero observations.
- Invalid and over-maximum ranges fail before network dispatch.
- A returned record is never outside the echoed query window.
