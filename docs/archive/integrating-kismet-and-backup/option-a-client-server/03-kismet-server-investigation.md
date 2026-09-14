# Server-Side Kismet Investigation Design

## Responsibility

`server/server_components/kismet_service.py` is the correct ownership boundary for historical wireless investigation. It must query only the verified server-local Kismet source; it must never request Kismet data from a client.

```text
UI/API -> KismetInvestigationService -> server Kismet persistence/API -> normalized result
```

## Existing reusable implementation

The current service already provides reusable foundations:

- application MAC normalization;
- device lookup through MySQL, local scan fallback, and direct-MAC use;
- UTC ISO/epoch parsing and range handling;
- SQLite Kismet query shape with source/destination/transmitter MAC matching;
- 802.11/Radiotap frame parsing, role selection, noise filtering, channel mapping, and summary statistics;
- REST/API and UI contracts that already accept time ranges, limits, and noise selection.

It also has deployment assumptions to remove during implementation: hard-coded developer directories, inferred pilot interface/driver defaults, unbounded `all` behavior, and schema assumptions that are not yet verified on the server.

## Query contract

Input:

```text
device identifier or normalized MAC
start UTC / end UTC or recognized bounded lookback
limit
include_noise
```

Processing:

1. Resolve the device using the existing device base and obtain canonical uppercase colon-separated MAC.
2. Normalize the time window once on the server. Bounds are inclusive and every returned observation must satisfy `start <= timestamp <= end`.
3. Reject invalid, reversed, future-only where policy requires, or over-maximum ranges. `all` must be configured as a finite maximum window or rejected; it must not mean unbounded database scanning.
4. Query only configured, verified Kismet repository files/API data for the MAC in source, destination, and transmitter roles.
5. Preserve microsecond ordering when that precision exists; apply deterministic ordering and result limits in the source query where possible.
6. Filter routine control-frame noise only when requested; return empty results as successful `observations: []`.
7. Return distinct `KISMET_UNAVAILABLE`, `KISMET_STORAGE_UNAVAILABLE`, `KISMET_QUERY_FAILED`, and validation failures; never convert them into an empty success.

Output remains compatible with `WirelessInvestigationPanel`:

```text
device
query_window
summary
observations[]
```

Each result must state `observation_source: KISMET_SERVER` and include server-sensor/capture identity where that metadata is available. This distinguishes it from existing client-derived `observation_sources` such as `CLIENT_ARP` and `CLIENT_DHCP`.

## API/UI integration

Keep the existing REST and UI path initially:

```text
GET /api/v1/devices/{id}/wireless-observations
GET /api/v1/alerts/{id}/wireless-investigation
```

`api_service.get_device_wireless_observations()` and alert lookback handling already call the server service directly. Preserve UI time-window controls and normalized display. Update the UI only if the verified query contract requires compatible fields such as truncation, data-source status, or a bounded replacement for `All Available Captures`.

## Client/TCP protocol decision

**No Kismet-specific client/server TCP protocol is required.**

Repository inspection found `GET_KISMET_OBSERVATIONS` only in the abandoned planning documents, not in code. Do not add it. The existing `server_lib.py` queues, send locks, command matching, and prospective request-ID work are unrelated to central Kismet and should be improved only for separate protocol needs.

## Correlation and localization

MAC is the first correlation key. Match all available 802.11 address roles carefully; the same device may appear as source, destination, or transmitter depending on frame semantics. Randomized MACs, AP/BSSIDs, multicast addresses, and unknown transient devices remain separate evidence and must not be silently bound to an inventory device.

The server sensor’s RSSI is a single-location RF measurement. It can enrich a device investigation and complement client location assignment, but does not establish a device position by itself. Keep source provenance and sensor location explicit for future multi-sensor work.

## Implementation boundaries

- Do not copy raw packets to MySQL.
- Do not use remote client storage as a fallback.
- Do not expose raw payloads in API responses.
- Do not refactor parser logic until target schema/API facts are documented.
- Remove client Kismet lifecycle only after the server reader and its tests are proven, in a separate regression-tested cleanup phase.
