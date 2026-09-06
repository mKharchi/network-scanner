# Network Telemetry and Device Discovery Audit

**Audit date:** 2026-09-03  
**Scope:** Client packet observation, telemetry processing, device enrichment,
activity reporting, and server synchronization.  
**Basis:** Source-code and project-documentation review. This is not a live
packet-capture validation or a multi-hour soak test.

## Executive Summary

The telemetry feature is implemented and connected to the normal client
lifecycle. The effective client pipeline is:

```text
one selected interface
        |
        v
Scapy PacketObserver
        |
        +--> V1 daily metadata storage (always, unfiltered)
        |
        +--> CIDR scope filter
                |
                +--> per-protocol packet metadata files
                +--> bidirectional flow aggregation
                        |
                        +--> 15-minute per-device activity windows
                        +--> delta synchronization to the server

PassiveProtocolListener (separate consumer/listener)
        |
        +--> DHCP, mDNS, LLMNR, NBNS, SSDP, DNS/TLS evidence
                |
                +--> DeviceCorrelator
                        |
                        +--> 5-minute devices.json enrichment
```

The feature does **not** observe the whole network in the sense of seeing every
conversation between every device. Each client captures only traffic visible
to one local network interface. On an ordinary switched network this normally
includes traffic to or from the client, broadcast/multicast traffic, and other
frames delivered by the adapter, but not arbitrary unicast traffic exchanged
by two other hosts. Promiscuous mode or a mirrored network port is not enabled
by the `PacketObserver` code.

There is a second, narrower boundary: when a server-assigned CIDR scope is
configured, v2 packet files and flows retain an observation only when either
IP endpoint is inside that scope. The older V1 daily store still receives the
observation before this filter, so local V1 storage can contain more data than
the v2 telemetry sent through the reporting pipeline.

## What Is Implemented

### Capture and metadata extraction

- `client/app/client.py` starts one `PacketObserver`, one `FlowAggregator`, and
  one `TelemetryPacketWriter` for each client session.
- `client/app/packet_observer.py` calls Scapy `sniff(store=False, timeout=1)`.
  It selects `PACKET_OBSERVER_INTERFACE`, then
  `DHCP_LISTEN_INTERFACE`, then the interface discovered by
  `network_neighbour_collector.get_local_network()`.
- `client/app/packet_extractor.py` normalizes timestamps, MAC addresses, IP
  addresses, ports, packet length, protocol, TCP flags, direction, and selected
  protocol metadata.
- Payloads and complete raw packets are not retained by the normalized v2
  records. The extractor performs limited metadata parsing, including DHCP,
  DNS-family metadata, SSDP headers, NBNS names, and TLS ClientHello SNI/JA3
  where the relevant data is present in the observed packet.
- Capture errors are handled inside the observer. Missing Scapy, permissions,
  invalid interfaces, and transient capture errors are reported or logged
  rather than being allowed to crash the client.

### Local storage

The v2 tree is separate from the legacy V1 tree:

```text
client/storage/network_telemetry/<date>/
  packets/<protocol>.json
  flows.json
  devices.json
  activity/<window>.json
```

`telemetry_storage.RotatingJSONAppendStore` provides size-bounded numbered
rotation. The default maximum is documented as 50 MB and can be configured by
`TELEMETRY_FILE_MAX_BYTES`.

The V1 path remains:

```text
client/storage/passive_packets/<date>.json
```

`PacketObserver._handle_packet()` writes this V1 record first, regardless of
v2 scope. This preserves the older behavior but creates intentionally different
coverage between V1 local storage and v2 telemetry storage.

### Scope filtering

`client/app/scope_filter.py` implements:

```text
keep = (src_ip in any configured CIDR) OR (dst_ip in any configured CIDR)
```

The scope can come from `NETWORK_OBSERVATION_SCOPE`, persisted
`client/storage/scope_config.json`, or the server registration and
`SCOPE_ASSIGNED` messages. Scope changes are hot-applied without restarting
capture. An empty or unavailable scope is deliberately **fail-open** and keeps
the observation.

The filter runs after extraction and before the v2 packet writer and flow
aggregator. Consequently, out-of-scope records do not contribute to v2 flows
or activity windows, but they still enter V1 local storage.

### Flow and activity processing

`client/app/flow_aggregator.py`:

- merges both directions of a conversation using an unordered endpoint and
  protocol key;
- tracks packet and byte counts, sizes, direction, TCP flags, duration, and
  inter-arrival metrics;
- finalizes an in-memory flow after 45 seconds of idleness by default;
- flushes active flows on shutdown to rotating `flows.json` storage.

`client/app/activity_window_aggregator.py` runs every 15 minutes. It reads
finalized flows, matches flow endpoint MAC addresses to known device MACs, and
emits one record per known device. Devices without matching flows receive an
explicit `active: false` record with zero counters. The resulting window is
passed to `SyncManager`, which persists pending payloads and retries them until
the server acknowledges them.

### Device discovery and enrichment

Device discovery is not inferred from generic flow counts. It is supplied by
`client/app/passive_protocol_listener.py`, whose `DeviceCorrelator` tracks
evidence from:

- DHCP
- mDNS
- LLMNR
- NBNS
- SSDP
- DNS and TLS observations for supporting metadata/classification
- traffic observations for temporal behavior and traffic classification

The discovery listener uses this BPF filter:

```text
UDP: ports 53, 67, 68, 137, 1900, 5353, 5355
TCP: ports 53 and 443
```

This is narrower than the generic `PacketObserver`. It is intended to find
identity and discovery evidence, not to represent all application traffic.

`client/app/device_enrichment.py` snapshots the correlator every five minutes
and writes identity, presence, and discovery fields to `devices.json`. It does
not re-parse raw packet files and does not invent activity statistics. Existing
device records are preserved when a device is absent from one enrichment cycle.

### Client/server boundary

`client/app/sync_manager.py` uses explicit field allowlists. Normal telemetry
sync sends device identity/discovery plus compact activity-window summaries;
raw packets and full flow records are not included. The server merge service
validates the same boundary and deduplicates activity by device and
`window_id`.

Detailed flow records are available only through an explicit, bounded,
device-and-window query. `client/app/flow_query.py` reads local finalized flow
files, including rotated siblings, and caps responses at 10,000 records. Raw
packet files are not returned by this path.

## Answer: What Does a Client Observe?

### Capture coverage

The generic observer is broad at the protocol-classification level: it does
not install a BPF filter and can classify TCP, UDP, ICMP, ARP, IPv6, DHCP, DNS,
mDNS, LLMNR, NBNS, SSDP, TLS metadata, and other IP protocols when Scapy and
the operating system expose those packets to it.

It is **not** broad at the network-topology level:

1. It captures one selected interface only.
2. It sees only frames visible to that interface and the host capture stack.
3. A normal switched endpoint does not see unrelated host-to-host unicast.
4. No mirror/SPAN interface, network tap, gateway capture, or explicit
   promiscuous-mode configuration is established in the observer.
5. Visibility depends on the adapter, Windows capture provider/Npcap setup,
   permissions, interface selection, packet drops, and whether traffic is
   encrypted or segmented in a way that hides higher-level metadata.

Therefore the feature should be described as **distributed, client-local,
passive observation**, not full-network capture. Multiple clients can increase
coverage, and a mirrored port or gateway placement can change visibility, but
the current code does not make one client a complete network sensor.

### Scope coverage

When a CIDR assignment exists, v2 retains traffic associated with that scope
if either endpoint is in scope. This supports a distributed deployment where
different clients are responsible for different subnets. With no assignment,
the filter keeps all extracted observations, which is useful for development
and single-client deployments but is not a restrictive privacy boundary.

### Discovery coverage

The enrichment path observes only the supported discovery protocols and only
when their packets are visible on the selected interface. A device that emits
no supported discovery traffic, is behind an unseen segment, or is represented
only by traffic that cannot be correlated to its MAC may not receive rich
discovery fields.

## Findings and Risks

### High importance

**F1. “All network traffic” would be an incorrect product claim.** The code
captures one interface and does not configure a tap, mirror port, gateway, or
promiscuous mode. This is the primary coverage limitation.

**F2. V1 and v2 have different scope semantics.** V1 local daily storage is
written before scope filtering. Operators inspecting that directory may see
out-of-scope observations that never enter v2 flows, protocol files, activity
windows, or server sync.

### Medium importance

**F3. Discovery state is bounded.** `PassiveProtocolListener` and its
correlator use `MAX_OBSERVATIONS = 512`. A noisy or long-running client can
evict older evidence, which can reduce the richness of a later five-minute
snapshot.

**F4. Activity aggregation reads only the active flow file.**
`ActivityWindowAggregator._load_flows()` calls `RotatingJSONAppendStore.read_all()`.
The on-demand flow query explicitly reads rotated siblings, but the activity
window path does not. Once `flows.json` rotates, flows in numbered files may be
omitted from activity summaries. This can undercount activity on busy clients.

**F5. Higher-level protocol metadata is best effort.** TLS SNI/JA3 depends on
seeing a suitable ClientHello in one captured packet; there is no TCP stream
reassembly. DNS extraction focuses on the first question. IPv6 is classified,
but several higher-level enrichment paths are primarily IPv4-oriented.

**F6. Capture health is not equivalent to capture completeness.** The observer
logs aggregate counts but does not expose a packet-drop counter, capture
availability state, or an explicit server-side completeness indicator. A
running thread therefore does not prove that the adapter is seeing all
expected traffic.

### Lower importance / operational gaps

**F7. The project has focused tests but not a full end-to-end or multi-hour
soak test.** The progress documentation records 69 focused client tests and
server telemetry tests passing, while also recording remaining integration and
soak coverage gaps.

**F8. Documentation drift exists.** Earlier sections of
`docs/network_observation/v2-progress.md` describe enrichment and activity
integration as pending, while later entries and current `client.py` show those
services wired into the production loop. The later status and source code are
the current evidence.

## Recommended Verification Work

1. Fix `ActivityWindowAggregator._load_flows()` to include active and numbered
   rotated flow files, then add a regression test that places matching flows in
   both files.
2. Add a capture-health metric: selected interface, start failure reason,
   callback count, and packet-drop/error counters where the capture backend
   exposes them.
3. Run a controlled visibility test with traffic in three categories: traffic
   to/from the client, broadcast/multicast traffic, and unicast between two
   other switched hosts. Record what appears in V1, v2, and discovery outputs.
4. Test multiple interfaces and invalid/disconnected adapters on the supported
   Windows deployment, including the required Npcap permissions.
5. Run a multi-hour rotation and restart test to verify bounded disk usage,
   flow finalization, activity completeness, pending-sync recovery, and server
   deduplication.
6. Decide and document whether V1 out-of-scope local retention is intentional.
   If it is not, apply the same policy before V1 storage or remove the V1 path
   from deployments that require strict scope isolation.

## Source Evidence

- Capture lifecycle and interface selection: `client/app/client.py` and
  `client/app/packet_observer.py`.
- Metadata normalization: `client/app/packet_extractor.py`.
- Scope semantics: `client/app/scope_filter.py`.
- Discovery filter, parsers, and correlator: `client/app/passive_protocol_listener.py`.
- Identity/discovery snapshot: `client/app/device_enrichment.py`.
- Flow and activity aggregation: `client/app/flow_aggregator.py` and
  `client/app/activity_window_aggregator.py`.
- Storage and rotation: `client/app/telemetry_storage.py` and
  `client/app/telemetry_packet_writer.py`.
- Sync allowlists and retries: `client/app/sync_manager.py`.
- Feature design and implementation status:
  `docs/network_observation/v2.md` and
  `docs/network_observation/v2-progress.md`.
- Focused implementation tests: `client/tests/test_packet_observer.py`,
  `test_scope_filter.py`, `test_passive_protocol_listener.py`,
  `test_device_enrichment.py`, `test_flow_aggregator.py`, and
  `test_activity_window_aggregator.py`.