# Operations and Troubleshooting

## First checks

```bash
systemctl status network-scanner-server.service --no-pager
systemctl status kismet-sensor.service --no-pager
ss -ltn | grep -E ':(5000|8080|2501)'
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8080/api/v1/sensors/wifi/health
```

On an endpoint, check `logs/client_service.log`, the Windows scheduled task or
service state, and `Test-NetConnection SERVER_IP -Port 5000`.

## Client does not register

1. Verify `SERVER_IP` and `SERVER_PORT` in `config/.env`.
2. Confirm the server TCP listener is bound to a reachable LAN address.
3. Check the server firewall for TCP `5000` from the private LAN.
4. Confirm only one client launcher is active on the PC.
5. Read the client's startup log for dependency, identity, or storage errors.

## API is unavailable

Check the application service separately from Kismet:

```bash
systemctl status network-scanner-server.service --no-pager
journalctl -u network-scanner-server.service -n 100 --no-pager
```

If TCP `5000` works but `8080` does not, inspect `API_HOST`, `API_PORT`, MySQL
startup, and port conflicts. Restart the application service after changing
`server/.env`.

## Kismet is degraded/offline

```bash
systemctl status kismet-sensor.service --no-pager
journalctl -u kismet-sensor.service -n 100 --no-pager
ip link show wlp0s20f3mon
curl http://127.0.0.1:8080/api/v1/sensors/wifi/health
```

The health payload separates process, monitor interface, readable/fresh source,
storage availability, and free-space reserve. If the monitor VIF is missing,
restart the service and verify it is recreated. Do not delete the active
capture database manually.

## Storage and retention

Run the retention script without `--apply` first:

```bash
python scripts/kismet_retention.py
```

Review active target, recent-write grace, sidecars, hold markers, age, and
free-space reserve. Keep dry-run enabled until a deletion policy has been
approved and recorded.

## Safe incident handling

- Preserve relevant action IDs, timestamps, logs, and capture filenames.
- Use investigation hold markers for Kismet files that must not be removed.
- Do not expose MySQL or the local API to the public Internet.
- For a failed update, keep the updater history and backup until recovery is
  confirmed.
- For quarantine failures, use local console access before attempting another
  isolation command.

