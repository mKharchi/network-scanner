# Server-Side Kismet Probe Visualization

## Decision

The server-owned Linux Kismet sensor is the sole monitor-mode 802.11 capture source. Managed Windows clients do not capture monitor-mode frames.

Kismet capture databases remain the source of truth. The API opens them read-only, decodes only Probe Request and Probe Response metadata in memory, and never exposes raw frame bytes or plaintext SSIDs.

## Delivered Components

- `GET /api/v1/wifi/probes` returns bounded global probe observations and MAC-independent candidate fingerprint groups.
- The device-specific wireless investigation now uses the shared ML-safe parser and exposes decoded management metadata where available.
- The GUI route `/network/wifi/probes` supports review, filtering, auto-refresh, decoded detail, and JSON/CSV export.
- `server/export_probe_fingerprint_manifest.py` appends selected capture intervals to the controlled fingerprint manifest.
- Kismet health now includes a bounded recent management-frame probe summary.

## Boundaries

- No packet BLOB, PCAP body, or plaintext SSID is returned or stored in derived records.
- Candidate groups indicate feature similarity; they do not prove physical-device identity.
- Model training continues to use the versioned Phase 1 fingerprint schema and controlled manifest labels.
