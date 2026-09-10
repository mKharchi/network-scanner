# Kismet Probe Scanner — Output JSON Schema

Version: `kismet-probe-scanner-v1`

The CLI (`python -m tools.kismet_probe_scanner`) writes one JSON document to
stdout.  The schema is stable across invocations; all consumers must tolerate
`null` values for optional fields.

---

## Top-level document

```jsonc
{
  "status": { /* ScanStatus — always present */ },
  "latest_probe": { /* ProbeRecord — null when no probe found */ }
}
```

---

## `status` object

| Field | Type | Description |
|---|---|---|
| `scanner_version` | string | Identifies the schema generation: `"kismet-probe-scanner-v1"` |
| `capture_files_scanned` | integer | Number of `.kismet` files opened |
| `total_rows_scanned` | integer | Total packet rows read across all files |
| `found` | boolean | `true` when `latest_probe` is populated |
| `no_result_reason` | string \| null | Human-readable explanation when `found` is `false` |
| `rejected_captures` | `{filename: reason}` | Files that could not be opened or had missing columns |
| `degraded_captures` | `{filename: reason}` | Files opened in immutable/snapshot mode due to a journal |
| `truncated_captures` | `{filename: reason}` | Files where the scan budget was exhausted before EOF |

---

## `latest_probe` object

> All fields are metadata-only.  Raw packet bytes and plaintext SSIDs are **never** emitted.

### Identity

| Field | Type | Description |
|---|---|---|
| `observation_id` | string | 24-hex deterministic ID (SHA-256 of file+rowid+timestamp+hash+source) |
| `timestamp` | string | UTC ISO-8601 capture timestamp |
| `epoch_sec` | integer | Unix epoch seconds |
| `epoch_usec` | integer | Microsecond sub-second component |
| `scanner_version` | string | Embedded schema version |

### Address roles

| Field | Type | Description |
|---|---|---|
| `source_mac` | string \| null | Normalized `XX:XX:XX:XX:XX:XX` source address |
| `destination_mac` | string \| null | Normalized destination address |
| `transmitter_mac` | string \| null | Normalized transmitter address |
| `bssid` | string \| null | Parsed BSSID from frame (null for broadcast probes) |
| `destination_kind` | `"broadcast"` \| `"multicast"` \| `"unicast"` \| `"unknown"` | Destination classification |
| `is_randomized_mac` | boolean | True when the locally-administered-address (LAA) bit is set in `source_mac` |

### Frame identity

| Field | Type | Description |
|---|---|---|
| `frame_type` | string | Always `"Management"` for probe records |
| `frame_subtype` | string | Always `"Probe Request"` for probe records |
| `sequence_number` | integer \| null | 802.11 sequence number |
| `retry` | boolean \| null | Retry bit from the frame control field |
| `power_management` | boolean \| null | Power-management bit |

### RF

| Field | Type | Description |
|---|---|---|
| `signal_dbm` | number \| null | Received signal strength in dBm |
| `frequency_khz` | number \| null | Channel centre frequency in kHz (Kismet native unit) |
| `channel` | integer \| null | Wi-Fi channel number derived from `frequency_khz` |
| `packet_length` | integer \| null | Frame length in bytes (from Kismet column) |

### IE / capability features (fingerprinting inputs)

| Field | Type | Description |
|---|---|---|
| `ie_tag_sequence` | integer[] | Ordered list of IE tag numbers present in the probe |
| `supported_rates_mbps` | number[] | Supported rates in Mbps (deduplicated, sorted) |
| `vendor_ouis` | string[] | Vendor OUI strings from tag 221, e.g. `["0050F2"]` |
| `ht_capabilities_digest` | string \| null | SHA-256 hex prefix of the raw HT capabilities IE body |
| `vht_capabilities_digest` | string \| null | SHA-256 hex prefix of the raw VHT capabilities IE body |
| `he_capabilities_digest` | string \| null | SHA-256 hex prefix of the raw HE capabilities IE body |
| `wmm_capabilities_present` | boolean | True when Microsoft WMM vendor IE (00:50:F2 type 2) is present |
| `rsn_capabilities_present` | boolean | True when RSN (tag 48) IE is present |
| `ssid_present` | boolean | True when an SSID IE (tag 0) is present |
| `ssid_length` | integer \| null | Byte length of the SSID IE body (0 = hidden/wildcard) |
| `ssid_hidden` | boolean | True when `ssid_length == 0` |

### Provenance

| Field | Type | Description |
|---|---|---|
| `fingerprint_signature` | string | 16-hex SHA-256 over IE features (no MAC address input) |
| `capture_file` | string | Basename of the `.kismet` file where this probe was found |
| `sensor` | string \| null | Kismet datasource name from the packet row |

---

## Example output

```json
{
  "status": {
    "scanner_version": "kismet-probe-scanner-v1",
    "capture_files_scanned": 2,
    "total_rows_scanned": 1842,
    "found": true,
    "no_result_reason": null,
    "rejected_captures": {},
    "degraded_captures": {},
    "truncated_captures": {}
  },
  "latest_probe": {
    "observation_id": "a3f1d2e4b5c6a7b8c9d0e1f2",
    "timestamp": "2026-09-10T11:04:22.000000+00:00",
    "epoch_sec": 1757491462,
    "epoch_usec": 0,
    "source_mac": "02:AA:BB:CC:DD:EE",
    "destination_mac": "FF:FF:FF:FF:FF:FF",
    "transmitter_mac": "02:AA:BB:CC:DD:EE",
    "bssid": null,
    "destination_kind": "broadcast",
    "is_randomized_mac": true,
    "frame_type": "Management",
    "frame_subtype": "Probe Request",
    "sequence_number": 42,
    "retry": false,
    "power_management": false,
    "signal_dbm": -67.0,
    "frequency_khz": 2412000.0,
    "channel": 1,
    "packet_length": 64,
    "ie_tag_sequence": [0, 1, 50, 45, 221, 48],
    "supported_rates_mbps": [1.0, 2.0, 5.5, 11.0],
    "vendor_ouis": ["0050F2"],
    "ht_capabilities_digest": "1122aabb",
    "vht_capabilities_digest": null,
    "he_capabilities_digest": null,
    "wmm_capabilities_present": true,
    "rsn_capabilities_present": true,
    "ssid_present": true,
    "ssid_length": 0,
    "ssid_hidden": true,
    "fingerprint_signature": "abcd1234ef567890",
    "capture_file": "Kismet-2026-09-10-00-00-00-1.kismet",
    "sensor": "wlp0s20f3mon",
    "scanner_version": "kismet-probe-scanner-v1"
  }
}
```
