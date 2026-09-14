# Passive Observation Contract

## Boundary

This contract applies only to observations retained by `PassiveProtocolListener`.
It is not an extension of `client/neighbourhood.py`, does not write daily-neighbourhood
files, and does not create `NETWORK_NEIGHBOURS` messages.

The later report envelope supplies the reporting client identity. An individual
observation therefore does not contain `source_client`.

## Normalized Observation

```json
{
  "protocol": "mdns",
  "observed_at": "2026-08-22T14:30:00+00:00",
  "first_observed_at": "2026-08-22T14:20:00+00:00",
  "seen_count": 3,
  "observation_kind": "response",
  "ip_address": "172.16.0.102",
  "mac_address": "E4:FD:45:BA:8B:96",
  "hostname": "desktop.local",
  "service_type": "_ipp._tcp.local",
  "service_name": "Office Printer._ipp._tcp.local",
  "service_port": 631,
  "raw_fields": {"txt": {"ty": "LaserJet"}}
}
```

Required fields are `protocol`, `observed_at`, `first_observed_at`, and a
positive `seen_count`. `protocol` is one of `mdns`, `llmnr`, `nbns`, or `ssdp`.
All other fields are optional and omitted rather than guessed.

## Field Rules

| Field | Validation and meaning |
| --- | --- |
| `observation_kind` | `query`, `response`, `announcement`, `search`, or `advertisement` |
| `ip_address` | Source or record-derived IPv4/IPv6 address, never a multicast destination |
| `mac_address` | Uppercase, colon-delimited unicast MAC; optional when Ethernet is unavailable |
| `hostname`, `device_name`, `service_type`, `service_name`, `device_type`, `vendor`, `model` | Protocol-advertised text, maximum 255 characters |
| `service_port` | Integer from 1 through 65535, normally an mDNS SRV port |
| `server` | SSDP `SERVER` header, maximum 512 characters |
| `location` | SSDP `LOCATION` header, maximum 2,048 characters; retained but never requested |
| `raw_fields` | Bounded protocol-specific metadata after allowlist filtering |

Text is trimmed and rejected when empty or containing NUL, carriage-return, or
newline characters. IPs are validated with `ipaddress` and reject unspecified,
loopback, multicast, or reserved addresses. Link-local addresses remain valid.

## Protocol Mapping

| Protocol | Normalized fields | Allowed `raw_fields` |
| --- | --- | --- |
| mDNS | `hostname`, `service_type`, `service_name`, `service_port`, `ip_address` | `record_types`, bounded DNS-SD TXT pairs, `target` |
| LLMNR | `observation_kind`, `hostname`, `ip_address` | `record_types` |
| NBNS | `observation_kind`, `hostname`, `ip_address`, optional `mac_address` | `name_type`, `record_types` |
| SSDP | `observation_kind`, `ip_address`, `device_type`, `server`, `location` | `usn`, `cache_control`, `host`, `man` |

`raw_fields` permits at most 16 keys. Keys are limited to 64 characters, string
values to 512 characters, nested maps to 16 entries, and the serialized object
to 4 KiB. Unknown headers and DNS records are not retained by default.

## Buffer and Deduplication

The listener keeps at most 512 normalized observations in memory. It neither
persists them nor transmits them at capture time.

| Protocol | Stable deduplication key |
| --- | --- |
| mDNS | `protocol`, `service_name` or `hostname`, `service_type`, `ip_address`, `service_port` |
| LLMNR | `protocol`, `observation_kind`, `hostname`, `ip_address` |
| NBNS | `protocol`, `observation_kind`, `hostname`, `ip_address` |
| SSDP | `protocol`, `observation_kind`, `raw_fields.usn`, `device_type`, `location`, `ip_address` |

Missing key components use an empty value, but an observation with no hostname,
service identity, device type, `USN`, or IP address is discarded. This prevents
anonymous packet noise from consuming the bounded buffer.

For an existing key, the listener updates `observed_at`, increments `seen_count`,
and fills only previously absent fields. If full, it evicts the oldest observation.
Observations remain independent protocol evidence: this phase does not merge
mDNS, SSDP, DHCP, or ARP records by IP or MAC.

## Report Snapshot

A later `GET_PASSIVE_NEIGHBOURHOOD` command receives a copy of the buffer,
sorted by newest `observed_at`. The report envelope, not this contract, adds the
reporter identity and response timestamp.

