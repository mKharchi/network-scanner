# Linux Server Kismet Deployment and Runtime Gate

**Status:** BLOCKED pending access to the intended Linux server.

## Verified versus unavailable evidence

The workspace host is Windows. WSL is not installed, and no remote Linux host/session is accessible from this workspace. Therefore this investigation could not inspect the target server's executable, service, adapter, mount, configuration, process, or generated capture data. This is an **access boundary**, not evidence that Kismet is absent from the intended Linux server.

Historical evidence is available in `../KISMET_SENSOR_PILOT.md`: a Linux pilot used Kismet `2026.09.0-e24ee9be2`, `iwlwifi`, `wlp0s20f3mon`, ran for 41.23 minutes, observed 81,969 packets/104 devices, and produced an 86 MB `.kismet` file. Treat this as feasibility evidence only until the target server is inspected.

## Required target-server evidence

Run the following read-only evidence collection on the Linux server before code work. Preserve command output, relevant logs, and redacted configuration references in the phase record.

```text
1. Runtime: executable/package/version, service unit or container, process owner,
   startup policy, Kismet configuration path and effective log/output settings.
2. Radio: `iw dev`, `iw list`, interface link state, driver/firmware, chipset,
   supported monitor mode/bands/channels, and required Linux capabilities.
3. Source: configured Kismet datasource, source starts successfully, source remains
   active, and logs/API report ongoing packet or device activity.
4. Capture: controlled 30–60 minute test with known active devices; record UTC
   start/end, observed MACs, packet/device counts, frame/RSSI/frequency fields,
   errors, and normal-connectivity impact.
5. Persistence: generated files, schema/tables, journal/WAL behavior, rotation,
   read safety during capture, retention, and post-restart historical availability.
6. Storage: actual persistent mount and capacity; do not assume a Linux path for
   the project’s named `D:` capacity until it is mapped and verified.
```

## Radio deployment model

The Linux server is the sole sensor in the initial deployment. Prefer wired management connectivity plus a dedicated monitor-capable Wi-Fi adapter for capture. If one radio must provide connectivity and capture, validate that arrangement under load; otherwise use a dedicated USB/PCIe adapter. Adapter, driver, and monitor-mode behavior are deployment-specific and must be measured rather than inferred from the pilot.

## Process supervision and recovery

The target deployment must choose and document one owner, preferably the Linux service manager or an approved container supervisor. The owner must:

- start Kismet after boot and restart it after unexpected exit;
- run it with the minimum permissions needed for the configured capture source and persistent output;
- emit logs usable by health monitoring;
- expose a local/private health endpoint only if Kismet API authentication and binding are verified;
- report capture-source failure separately from normal empty observations.

The application must not start Kismet itself in the first implementation. It reads verified Kismet persistence or an approved local API and reports health state.

## Acceptance gate

The next phase may start only when all conditions are recorded for the **target Linux server**:

- Kismet version, installation source, effective configuration, and startup owner;
- actual Wi-Fi interface, driver/chipset, monitor capability, and permissions;
- controlled capture proving frames/devices increase over time;
- server-local persistent capture source and actual mount path;
- read-safe historical query path while Kismet runs;
- storage capacity, growth measurement, rotation, retention, and cleanup ownership;
- Kismet API role: health only, history only, both, or neither;
- access-control decisions for service/API/files.

If a dedicated adapter is needed, record it as a deployment blocker rather than changing application code around an unusable radio.
