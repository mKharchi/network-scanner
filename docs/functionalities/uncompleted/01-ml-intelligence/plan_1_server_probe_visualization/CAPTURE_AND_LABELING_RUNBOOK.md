# Capture and Labeling Runbook

1. Verify `GET /api/v1/sensors/wifi/health` reports a readable, fresh Kismet capture.
2. For broad discovery, allow channel hopping. For a controlled device session, set `KISMET_CAPTURE_SOURCE` in `server/.env` to the monitor interface plus `channel_hop=false,channel=<AP channel>`; for example `wlp0s20f3mon:channel_hop=false,channel=48`. Reinstall/reload the tracked sensor unit if it has changed, then restart Kismet.
3. Confirm the datasource reports the intended fixed channel before testing. Do not use a known device MAC as a filter: a randomized Probe Request will use a different source MAC.
4. Trigger a known scan on one device: forget/rejoin Wi-Fi, open Wi-Fi settings, or toggle Wi-Fi only on equipment you control.
5. Review `/network/wifi/probes` with `Probe Request` selected and a 5–15 minute lookback; record the exact UTC interval and observed randomized source MACs.
5. Export a manifest preview:

```bash
PYTHONPATH=server python3 server/export_probe_fingerprint_manifest.py \
  --physical-device-guid honor-x50 \
  --capture-session honor-x50-randomized-01 \
  --condition channel-1-wifi-scan \
  --mac-randomization \
  --start 2026-09-09T12:00:00Z \
  --end 2026-09-09T12:05:00Z \
  --dry-run
```

6. Check the preview. Remove `--dry-run` only when the capture condition and physical-device label are correct.
7. Train/evaluate only with groups and manifest records collected under controlled conditions. Never infer a ground-truth device label solely from a candidate signature.
