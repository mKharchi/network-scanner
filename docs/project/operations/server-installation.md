# Linux Server Installation

This guide installs the Python server, MySQL schema, application supervisor,
and optional server-owned Kismet sensor. It is written for the current Linux
PC profile but identifies values that must change on a future sensor.

## 1. Prepare the host

Install Python, MySQL, build tools required by the selected dependencies, and
Git. Create a deployment copy of the repository:

```bash
cd /home/adonis/network-scanner
python3 -m venv server/.venv
server/.venv/bin/python -m pip install -r server/requirements.txt
```

Create the `network_scanner` MySQL database/user and keep the password only in
`server/.env`. Initialize the schema with the repository's normal database
startup path or by applying `server/scripts.sql` with the database
administrator.

## 2. Configure the server

Create `server/.env` with values for the target host:

```env
SERVER_HOST=172.16.1.238
SERVER_PORT=5000
API_HOST=127.0.0.1
API_PORT=8080
DB_HOST=localhost
DB_PORT=3306
DB_NAME=network_scanner
DB_USER=scanner
DB_PASSWORD=<local-secret>
```

Set the Kismet values only when the host has a monitor-capable adapter. Do not
copy the current PC's interface names to another machine without checking
`ip link` and `iw dev`.

## 3. Install the application supervisor

The repository's `network-scanner-server.service.example` runs the TCP server
and REST API in non-interactive mode:

```bash
sudo install -m 0644 network-scanner-server.service.example \
  /etc/systemd/system/network-scanner-server.service
sudo systemctl daemon-reload
sudo systemctl enable --now network-scanner-server.service
sudo systemctl status network-scanner-server.service --no-pager
```

Verify:

```bash
ss -ltn | grep -E ':(5000|8080)'
curl http://127.0.0.1:8080/health
```

The TCP listener must be reachable from endpoint PCs. Keep REST `127.0.0.1`
unless a secured private proxy is deliberately configured.

## 4. Install Kismet on a Linux sensor

Follow the distribution/Kismet installation procedure, then identify the
managed interface and create a test monitor interface. The current deployment
uses:

```text
KISMET_MAIN_INTERFACE=wlp0s20f3
KISMET_CAPTURE_INTERFACE=wlp0s20f3mon
KISMET_CAPTURE_ROOT=/home/adonis/kismet
KISMET_HOMEDIR=/var/lib/kismet
KISMET_CONF_DIR=/home/adonis/kismet/conf
```

Create the service account and directories according to your distribution.
Install `kismet-sensor.service` only after confirming paths and permissions.
Install `kismet_site.conf.example` as `kismet_site.conf`, bind Kismet to
localhost, and create/test the Kismet administrator account before disabling
first-run credential creation.

The completed current profile runs Kismet with `User=kismet`, `Group=kismet`,
`SupplementaryGroups=netdev`, `CAP_NET_ADMIN`, `CAP_NET_RAW`,
`NoNewPrivileges=true`, and read/write access limited to capture/runtime
paths.

## 5. Verify startup and data

```bash
sudo systemctl status kismet-sensor.service --no-pager
curl http://127.0.0.1:8080/api/v1/sensors/wifi/health
bash scripts/phase10_post_reboot_check.sh
```

Record the adapter, Kismet version, capture path, file growth, free space,
retention policy, and service owner before approving production.

