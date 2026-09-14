# Kismet Runtime and Storage Contract

## Current verified state

The repository contains two different levels of evidence:

1. The client implementation only polls an expected directory for the newest `*.kismet` file. It does not prove that Kismet is installed, running, configured, capturing, or persisting data.
2. The standalone Linux pilot report records a successful Kismet `2026.09.0-e24ee9be2` capture using `wlp0s20f3mon`, producing an 86 MB `.kismet` SQLite database with 81,969 packets over 41.23 minutes.

The pilot is a feasibility result, not a deployment contract for the Windows-oriented managed client fleet. Phase 0 must produce deployment-specific evidence before this document can be marked verified.

## Runtime chain to establish

```text
Wireless adapter/driver
  -> capture interface and monitor capability
  -> Kismet process/service
  -> configured source
  -> Kismet runtime/API status
  -> rotated persistence or retained API history
  -> query component
```

The query component must be colocated with the sensor or have an explicitly secured, supported way to reach the source. A server directory that happens to contain a `.kismet` file is not sufficient evidence of client ownership.

## Persistence contract to record

For each supported deployment, record:

- Kismet version and capture driver;
- effective configuration and `log_prefix`/output setting;
- output directory and filesystem owner/permissions;
- filename and rotation pattern;
- whether files are SQLite `.kismet`, another database, PCAP/PCAP-NG, or API-only history;
- schema version and relevant tables;
- timestamp units, timezone, seconds/microseconds precision;
- source, destination, transmitter/BSSID, RSSI, frequency, channel, frame, datasource, and packet identity fields;
- WAL/journal/sidecar behavior while a file is active;
- how records become safely readable during capture;
- retention, rotation, deletion, and historical availability;
- behavior across Kismet restart and sensor reboot.

For the pilot's expected `.kismet` source, the relevant `packets` fields are `ts_sec`, `ts_usec`, `sourcemac`, `destmac`, `transmac`, `signal`, `frequency`, `packet_len`, `datasource`, `dlt`, `packet`, and `hash`. The `datasources` table provides source/interface metadata. These fields must be revalidated against the actual installed version rather than copied into production assumptions.

## API decision

Inspect the actual Kismet runtime API and authentication configuration during Phase 0. Use it for health/source status if it is available and secured. Use it for historical queries only if it exposes retained observations with all fields and precise time-window behavior required by the UI. Prefer local persistence for historical queries when the query component is colocated with the sensor and the schema/retention are proven. A combined model is acceptable:

```text
Kismet API -> process/source health
local Kismet persistence -> bounded historical observations
```

If the deployed version does not provide the expected SQLite schema or local access, stop and revise the query design before TCP implementation.

## Operational verification record

The completed prerequisite should attach evidence for:

- executable/package and version;
- running process/service and startup owner;
- effective source/interface configuration;
- capture-interface capabilities and permissions;
- Kismet logs and API/runtime status;
- controlled-capture start/end times and packet growth;
- sample current records and timestamps;
- schema inspection;
- file rotation and retention measurements;
- historical query after continued capture and restart;
- secure mapping from sensor data source to the authenticated network-scanner client.

## Consequence for Option A

Only after this contract is verified should the client query layer be specified as SQLite, API, or a combination. The later TCP flow remains bounded and on demand regardless of the selected local source:

```text
UI range -> server UTC bounds -> selected client/sensor
         -> verified Kismet source -> bounded observations -> server -> UI
```
