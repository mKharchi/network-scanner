# Phase 0 — Target Server Runtime Evidence

**Status:** PARTIAL PASS — runtime and short capture verified; deployment gate remains open.

**Date:** 2026-09-06

## Host and Kismet

- Host: `adonis-IdeaPad-5-15ITL05`
- OS: Ubuntu 26.04 LTS, kernel `7.0.0-30-generic`, x86_64
- Kismet: `2026.09.0-e24ee9be2`
- Executables: `/usr/local/bin/kismet`, `/usr/local/bin/kismet_server`, `/usr/local/bin/kismet_cap_linux_wifi`
- Startup owner: manual foreground launch; no systemd Kismet service was found
- Kismet was launched as root for the monitor-interface test

## Radio and connectivity

- Adapter: Intel Wi-Fi using `iwlwifi`
- Firmware: `77.f39cc7f9.0 QuZ-a0-hr-b0-77.u`
- Managed interface: `wlp0s20f3`
- Managed connection: SSID `SKILLS-CENTER`, channel 44
- Monitor interface: `wlp0s20f3mon`, created separately and passed to Kismet
- `iw list` advertises monitor-mode support
- The managed interface remained connected during the short capture
- NetworkManager was restored with:

```text
nmcli device set wlp0s20f3 managed true
```

## Successful short capture

Command shape:

```text
sudo kismet --confdir /home/adonis/kismet/conf --homedir /home/adonis \
  --no-ncurses --no-line-wrap -p /home/adonis/kismet -c wlp0s20f3mon
```

Kismet reported that `wlp0s20f3mon` was already in monitor mode, configured successfully, and launched the datasource. It detected multiple real wireless devices, including `B0:3C:DC:95:39:36`, `AC:71:2E:FA:88:3F`, and `36:EF:B9:6C:58:DA`.

Generated database:

```text
/home/adonis/kismet/Kismet-20260906-16-02-33-1.kismet
```

Verified database facts:

- Owner: `root:root`
- Packet count: `522`
- Packet timestamp range: `1788710554` through `1788710574`
- Datasource: `linuxwifi`, interface `wlp0s20f3mon`
- DLT: `127` radiotap
- Required fields present: timestamp seconds/microseconds, source/destination/transmitter MACs, signal, frequency, packet length, datasource, DLT, and packet blob

Kismet removed the monitor interface during shutdown; the later `iw dev ... del` returned `No such device`, which is expected cleanup behavior.

## Gate assessment

| Condition                                | Result       | Evidence or remaining gap                                  |
| ---------------------------------------- | ------------ | ---------------------------------------------------------- |
| Kismet installed and version recorded    | Pass         | Version and binaries verified                              |
| Capture interface and monitor mode       | Pass         | `iwlist` capability and successful monitor VIF capture     |
| Real frames and device activity          | Partial pass | Real packets and devices observed                          |
| Required 30-60 minute controlled capture | Blocked      | Only a short capture was run                               |
| Persistence format and required fields   | Partial pass | SQLite `.kismet` schema and fields verified                |
| Persistent storage mount and reserve     | Partial pass | Root filesystem, 114 GB available; no dedicated mount      |
| Service ownership and restart policy     | Blocked      | Manual launch only; no service unit                        |
| Least-privilege Kismet execution         | Blocked      | Test ran as root                                           |
| API binding and authentication           | Blocked      | HTTP server listened on `0.0.0.0:2501`; hardening required |
| Retention and rotation policy            | Blocked      | Target growth and cleanup policy not frozen                |

## Next evidence step

Run Kismet for at least 30 minutes with the monitor VIF while recording packet growth, known active device visibility, capture errors, database growth, and Wi-Fi continuity. Then define the non-root service owner, private/authenticated API binding, persistent storage policy, and restart/retention ownership before application implementation.

## Next steps and exit gates

1. **Repeat the controlled capture for 30-60 minutes.** Create `wlp0s20f3mon`, keep `wlp0s20f3` managed, launch Kismet against only the monitor interface, and record UTC start/end times, packet counts, database size, detected devices, representative fields, source errors, and Wi-Fi state.
2. **Verify historical reads during and after capture.** Open the generated `.kismet` database read-only while Kismet is running, check timestamp and MAC queries, stop Kismet cleanly, and confirm the closed database remains queryable. Record any WAL/journal or rotation behavior.
3. **Freeze the storage location.** Decide whether `/home/adonis/kismet` is an approved persistent location or map an approved high-capacity mount. Record filesystem capacity, ownership, ACLs, free-space reserve, and the configured Kismet output path.
4. **Define least-privilege startup.** Create or document the service account/group and capture capabilities required by Kismet and the capture helper. Repeat the capture without running the main Kismet process as root.
5. **Harden the management API.** Bind HTTP to localhost or an approved private address, verify authentication, and document whether the API is used for health, history, both, or neither. Do not expose port `2501` publicly.
6. **Define supervision and retention.** Choose systemd or another approved supervisor, document restart behavior, measure storage growth per hour, set retention/free-space rules, and define dry-run cleanup ownership. Never clean the active database or its journal files.
7. **Close the deployment gate.** Update this record and Phase 1/2 only when the long capture, safe historical reads, storage, privilege, API, supervision, and retention evidence is complete.
8. **Start application work only after the gate closes.** Begin Phase 3 with a read-only server-local source adapter contract. Then refactor `KismetInvestigationService`; do not add client Kismet commands, client storage, or a raw-observation MySQL table.

### Evidence to attach to the next run

```text
capture_start_utc:
capture_end_utc:
managed_interface_state:
monitor_interface_state:
kismet_version:
source_definition:
packet_count_start:
packet_count_end:
database_size_start_bytes:
database_size_end_bytes:
database_path:
known_device_macs_seen:
representative_timestamp_signal_frequency_fields:
capture_errors:
historical_read_while_active:
historical_read_after_shutdown:
rotation_or_wal_behavior:
wifi_connectivity_impact:
```
