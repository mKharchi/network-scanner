# Server Migration Guide

This guide covers moving the Network Scanner server from one machine to another
(e.g., from the development PC to the center's production server).

---

## 1. Pre-migration checklist

Run these steps on the **current (old) server** before touching the new machine.

### 1.1 Export the database

```bash
mysqldump -u scanner -p network_scanner > ~/network_scanner_backup_$(date +%F).sql
```

Copy the dump to the new machine or a shared location.

### 1.2 Export observation and storage data

```bash
# Network scan JSON files
tar czf ~/network_scans_backup_$(date +%F).tar.gz \
  /home/adonis/network-scanner/server/storage/network_scans/

# Kismet ML derived outputs (intervals, daily summaries, predictions)
tar czf ~/kismet_ml_backup_$(date +%F).tar.gz \
  /home/adonis/network-scanner/server/storage/kismet_ml/

# Trained ML models
tar czf ~/ml_models_backup_$(date +%F).tar.gz \
  /home/adonis/network-scanner/server/storage/models/
```

### 1.3 Note down key configuration values

From `server/.env`:
- `DB_USER`, `DB_PASSWORD`, `DB_NAME`
- `KISMET_CAPTURE_INTERFACE` (will likely differ on new machine — run `ip link` there)
- `NETWORK_SCAN_INTERFACE`, `NETWORK_SCAN_SUBNET`

---

## 2. Set up the new server machine

### 2.1 Install dependencies

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip mysql-server git build-essential
```

### 2.2 Clone / copy the repository

```bash
git clone <repo-url> ~/network-scanner
# or scp/rsync the folder from the old machine
```

### 2.3 Create the Python virtual environment

```bash
cd ~/network-scanner/server
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

### 2.4 Configure the database

```bash
sudo mysql -u root <<'SQL'
CREATE DATABASE IF NOT EXISTS network_scanner CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'scanner'@'localhost' IDENTIFIED BY 'scanner_password';
GRANT ALL PRIVILEGES ON network_scanner.* TO 'scanner'@'localhost';
FLUSH PRIVILEGES;
SQL

# Import the backup
mysql -u scanner -p network_scanner < ~/network_scanner_backup_YYYY-MM-DD.sql
```

### 2.5 Create `server/.env`

Use the template below — **only `server/.env` needs editing**, not any source file:

```env
SERVER_HOST=0.0.0.0
SERVER_PORT=5000
API_HOST=127.0.0.1
API_PORT=8080

DB_HOST=localhost
DB_PORT=3306
DB_NAME=network_scanner
DB_USER=scanner
DB_PASSWORD=<your-password>

NETWORK_SCAN_INTERFACE=<interface from ip link>
NETWORK_SCAN_SUBNET=<e.g. 172.16.0.0/16>

NETWORK_SCAN_STORAGE_DIR=~/network-scanner/server/storage/network_scans

# Kismet sensor — use machine-global paths (never ~ in systemd EnvironmentFile)
KISMET_CAPTURE_ROOT=/var/lib/kismet/captures
KISMET_CAPTURE_INTERFACE=<monitor interface from iw dev>
KISMET_MAIN_INTERFACE=<managed interface from ip link>
KISMET_HOMEDIR=/var/lib/kismet
KISMET_BINARY=/usr/local/bin/kismet
KISMET_CONF_DIR=/etc/kismet
KISMET_RETENTION_HOURS=48
KISMET_MIN_FREE_BYTES=5368709120
KISMET_HEALTH_STALE_SECONDS=300
KISMET_CLEANUP_DRY_RUN=true
KISMET_API_BIND_ADDRESS=127.0.0.1
KISMET_API_URL=http://127.0.0.1:2501
KISMET_API_USERNAME=<kismet admin user>
KISMET_API_PASSWORD=<kismet admin password>
KISMET_PRODUCTION_READY=true
```

> **Note**: All `~/...` paths automatically expand to the current user's home
> directory. No need to hardcode `/home/<username>/...`.

### 2.6 Restore observation data

```bash
mkdir -p ~/network-scanner/server/storage/network_scans
tar xzf ~/network_scans_backup_YYYY-MM-DD.tar.gz -C ~/network-scanner/server/storage/

mkdir -p ~/network-scanner/server/storage/kismet_ml
tar xzf ~/kismet_ml_backup_YYYY-MM-DD.tar.gz -C ~/network-scanner/server/storage/

mkdir -p ~/network-scanner/server/storage/models
tar xzf ~/ml_models_backup_YYYY-MM-DD.tar.gz -C ~/network-scanner/server/storage/
```

### 2.7 Install the systemd service

```bash
cd ~/network-scanner
sudo bash scripts/install_server_service.sh
sudo systemctl enable --now network-scanner-server.service
sudo systemctl status network-scanner-server.service --no-pager
```

Verify both ports are up:

```bash
ss -ltn | grep -E ':(5000|8080)'
curl http://127.0.0.1:8080/health
```

### 2.8 Install and configure Kismet (if this machine hosts the sensor)

Follow the Kismet installation guide for your distribution. Then create the
**machine-global** capture/conf directories (no per-user `~` paths):

```bash
# Creates /var/lib/kismet/captures and installs conf into /etc/kismet
sudo bash scripts/setup_kismet_storage.sh
```

```bash
# Install the sensor service (separate from server service)
sudo cp kismet-sensor.service.example /etc/systemd/system/kismet-sensor.service
# Edit EnvironmentFile / WorkingDirectory if the repo path differs, then:
sudo systemctl daemon-reload
sudo systemctl enable --now kismet-sensor.service
```

> **Do not use `~` in `server/.env` for Kismet paths.** systemd does not expand
> `~`, and the service runs as user `kismet` (home `/var/lib/kismet`), not your
> admin account. Always use absolute paths like `/var/lib/kismet/captures`.

---

## 3. Broadcast the new IP to all clients

Once the new server is running, push the new `SERVER_IP` to all connected clients
**while they are still connected to the old server**:

### Via the GUI

1. Open the dashboard → **Settings → Server Migration** (or **Actions → Bulk Action**).
2. Select action type `RECONFIGURE_CLIENT`.
3. Set `SERVER_IP` = new server's LAN IP.
4. Target: **All clients**.
5. Click **Execute**.

### Via the API

```bash
NEW_IP="10.0.0.5"  # replace with the new server's LAN IP

# Use the dedicated reconfigure endpoint — it expands targets=["all"]
# to every currently connected client. (POST /api/v1/actions with
# targets:["all"] does NOT expand "all" into client IDs.)
curl -X POST http://127.0.0.1:8080/api/v1/actions/reconfigure-clients \
  -H "Content-Type: application/json" \
  -d "{
    \"parameters\": {\"SERVER_IP\": \"${NEW_IP}\", \"SERVER_PORT\": \"5000\"},
    \"targets\": [\"all\"]
  }"
```

Each client will:
1. Receive the action over its existing TCP connection.
2. Atomically patch `config/.env` (only allowlisted keys; other keys preserved).
3. For `SERVER_IP` / `SERVER_PORT` only: soft-reconnect (close socket, reload
   dotenv, connect to the new server). Other keys trigger a process restart.

### What the allowed config keys are

Only keys in the allowlist are accepted by clients. The current allowlist is:

| Key | Purpose |
|---|---|
| `SERVER_IP` | New server LAN IP |
| `SERVER_PORT` | New server TCP port (default 5000) |
| `NETWORK_SCAN_INTERFACE` | Override active scan interface |
| `NETWORK_SCAN_SUBNET` | Override scan subnet |
| `DHCP_LISTEN_INTERFACE` | Override DHCP capture interface |
| `FORBIDDEN_PROCESS_SCAN_INTERVAL_SECONDS` | Policy scan interval |
| `PROCESS_SCAN_INTERVAL_SECONDS` | Process monitor interval |
| `QUARANTINE_MAX_DURATION_MINUTES` | Quarantine cap |
| `AUTO_ISOLATE_ON_ESCALATION` | Auto-isolate on policy breach |
| `SCREENSHOT_MAX_RESPONSE_BYTES` | Screenshot size cap |
| `NETWORK_NEIGHBOUR_HOSTNAME_LOOKUP_LIMIT` | Neighbour scan limit |

To add more keys, edit `_RECONFIGURE_ALLOWLIST` in `client/app/client_lib.py` and
ship a client update.

---

## 4. Verification after migration

```bash
# On new server — watch for re-registrations
sudo journalctl -u network-scanner-server.service -f

# From any client PC (PowerShell)
Test-NetConnection <NEW_IP> -Port 5000
```

Expected:
- All previously connected clients appear in the dashboard within ~30 seconds.
- Connection alerts fire for any clients that were offline during the migration window.
- Kismet interval timer continues on schedule (check `journalctl --user -u kismet-cycle.timer`).

---

## 5. Decommission the old server

Once all clients are confirmed connected to the new server:

```bash
# On old machine
sudo systemctl disable --now network-scanner-server.service
sudo systemctl disable --now kismet-sensor.service
```

The old machine's database and storage can be archived or deleted as needed.
