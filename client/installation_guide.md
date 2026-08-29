## Important architecture

The **client PCs do not need**:

- MySQL
- The server `.env`
- Port `3306`
- An inbound firewall rule
- The GUI port `8080`

Each client only makes an **outbound TCP connection** to the monitoring server on port `5000`.

You need to configure:

- `SERVER_IP` = the server’s LAN IP address
- `SERVER_PORT` = `5000`

---

# 1. On the server PC

Find the server’s local IPv4 address:

```powershell
ipconfig
```

Look for the active adapter, for example:

```text
IPv4 Address. . . . . . . . . . . : 192.168.1.10
```

Use that address as `SERVER_IP` on every client PC.

## Server `.env`

Keep this file on the **server only**:

```env
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=scanner
DB_PASSWORD=scanner_password
DB_NAME=network_scanner

SERVER_HOST=0.0.0.0
SERVER_PORT=5000

API_HOST=0.0.0.0
API_PORT=8080
```

Do not copy the server `.env` into the client folder.

## Allow client connections through Windows Firewall

Run PowerShell **as Administrator** on the server:

```powershell
New-NetFirewallRule `
  -DisplayName "Network Scanner Client TCP 5000" `
  -Direction Inbound `
  -Protocol TCP `
  -LocalPort 5000 `
  -Action Allow `
  -Profile Domain,Private `
  -RemoteAddress LocalSubnet
```

This allows clients on the local Windows Private/Domain network to connect.

For a specific subnet, use a narrower rule instead. For example, if your LAN is `192.168.1.0/24`:

```powershell
New-NetFirewallRule `
  -DisplayName "Network Scanner Client TCP 5000 LAN" `
  -Direction Inbound `
  -Protocol TCP `
  -LocalPort 5000 `
  -Action Allow `
  -Profile Domain,Private `
  -RemoteAddress 192.168.1.0/24
```

Do **not** open port `3306` to the LAN. MySQL should remain local to the server.

## Optional: allow remote GUI access

Only add this if you want to open the dashboard from another PC:

```powershell
New-NetFirewallRule `
  -DisplayName "Network Scanner GUI TCP 8080" `
  -Direction Inbound `
  -Protocol TCP `
  -LocalPort 8080 `
  -Action Allow `
  -Profile Domain,Private `
  -RemoteAddress LocalSubnet
```

Then open this from another PC:

```text
http://SERVER_IP:8080
```

For example:

```text
http://192.168.1.10:8080
```

Do not expose ports `5000` or `8080` directly to the public internet.

---

# 2. On each client PC

Extract the compressed `client` folder to a permanent location, for example:

```text
C:\NetworkScanner\client
```

Avoid placing it in `Downloads`, because the folder should not be moved after installing the scheduled task.

Open PowerShell and go to the extracted folder:

```powershell
cd C:\NetworkScanner\client
```

## Install Python

Check whether Python is available:

```powershell
python --version
```

Use Python 3.9 or newer.

If the command is not found, install Python from the official Python website and enable **Add Python to PATH** during installation.

## Create a virtual environment

```powershell
python -m venv .venv
```

Activate it:

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks script execution, run this once for your user account:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Then activate again:

```powershell
.\.venv\Scripts\Activate.ps1
```

## Install dependencies

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

The client requirements include:

- `psutil`
- `python-dotenv`
- `scapy`
- `Pillow`

---

# 3. Create the client `.env`

Create this file:

```text
C:\NetworkScanner\client\.env
```

Use the following content, replacing the IP address with the server’s LAN address:

```env
SERVER_IP=192.168.1.10
SERVER_PORT=5000
```

Optional configuration:

```env
NETWORK_NEIGHBOUR_HOSTNAME_LOOKUP_LIMIT=64
DHCP_LISTEN_INTERFACE=
NETWORK_SCAN_INTERFACE=
NETWORK_SCAN_SUBNET=

FORBIDDEN_PROCESS_SCAN_INTERVAL_SECONDS=600
PROCESS_SCAN_INTERVAL_SECONDS=10
PROCESS_ESCALATION_THRESHOLD=3
PROCESS_ESCALATION_WINDOW_SECONDS=120

SCREENSHOT_MAX_RESPONSE_BYTES=8388608
QUARANTINE_MAX_DURATION_MINUTES=60

AUTO_ISOLATE_ON_ESCALATION=0
```

For a normal installation, the only values you need to change are:

```env
SERVER_IP=YOUR_SERVER_LAN_IP
SERVER_PORT=5000
```

Example:

```env
SERVER_IP=192.168.1.10
SERVER_PORT=5000
```

Do not put these database values in the client `.env`:

```env
DB_HOST=
DB_PORT=
DB_USER=
DB_PASSWORD=
DB_NAME=
```

They are server-only settings.

---

# 4. Test connectivity before installing startup

From the client PC, test port `5000`:

```powershell
Test-NetConnection 192.168.1.10 -Port 5000
```

You should see:

```text
TcpTestSucceeded : True
```

If it returns `False`, check:

1. The server process is running.
2. `SERVER_IP` is correct.
3. Both PCs are on the same LAN or reachable network.
4. The server firewall rule exists.
5. Windows network profile is `Private` or `Domain`, not `Public`.
6. The server is listening on port `5000`.

On the server, check the listening port:

```powershell
Get-NetTCPConnection -LocalPort 5000 -State Listen
```

You can also test the client manually:

```powershell
.\.venv\Scripts\python.exe .\client.py
```

You should see startup messages indicating that the client connected and registered.

Press `Ctrl+C` to stop it.

---

# 5. Install the client to start automatically at user logon

The project includes:

```text
install_user_logon_task.ps1
```

The recommended mode is the per-user scheduled task because activity logs and screenshots require the signed-in user session.

From PowerShell in the client folder:

```powershell
.\install_user_logon_task.ps1 -PythonExecutable "$PWD\.venv\Scripts\pythonw.exe"
```

Start it immediately without logging out:

```powershell
Start-ScheduledTask -TaskName "NetworkClientUserAgent"
```

Check the task:

```powershell
Get-ScheduledTask -TaskName "NetworkClientUserAgent"
```

Check whether it is running:

```powershell
Get-ScheduledTaskInfo -TaskName "NetworkClientUserAgent"
```

Review the client log:

```powershell
Get-Content .\client_service.log -Wait
```

The client should connect to:

```text
192.168.1.10:5000
```

Replace the IP with your actual server IP.

---

# 6. Important: do not run two clients on the same PC

Do not run both:

- The legacy `NetworkClient` Windows service
- The `NetworkClientUserAgent` scheduled task

on the same machine. Otherwise the server may receive duplicate registrations from the same PC.

If the old service exists, stop and disable it from an elevated PowerShell:

```powershell
Stop-Service NetworkClient -ErrorAction SilentlyContinue
Set-Service NetworkClient -StartupType Disabled
```

Then use only:

```powershell
Start-ScheduledTask -TaskName "NetworkClientUserAgent"
```

---

# 7. Npcap requirement

For passive DHCP and packet capture on Windows, install **Npcap** on each client PC.

Npcap is a Windows driver, not a Python package. After installation, restart the PC if requested.

The client can still connect without packet capture, but DHCP/passive capture features may be unavailable.

For the first installation, you may need to run PowerShell or the client with Administrator privileges depending on the Npcap configuration and the capture feature being used.

---

# 8. Remove the client later

From the same client folder and user account:

```powershell
.\uninstall_user_logon_task.ps1
```

If the client is still running or the task was removed while the process stayed active:

```powershell
.\stop_windows_client.ps1
```

---

## Minimal deployment checklist

### Server

```powershell
# Check server IP
ipconfig

# Allow client TCP connections
New-NetFirewallRule `
  -DisplayName "Network Scanner Client TCP 5000" `
  -Direction Inbound `
  -Protocol TCP `
  -LocalPort 5000 `
  -Action Allow `
  -Profile Domain,Private `
  -RemoteAddress LocalSubnet
```

Server `.env`:

```env
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=scanner
DB_PASSWORD=scanner_password
DB_NAME=network_scanner
SERVER_HOST=0.0.0.0
SERVER_PORT=5000
API_HOST=0.0.0.0
API_PORT=8080
```

### Client

```powershell
cd C:\NetworkScanner\client
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Client `.env`:

```env
SERVER_IP=192.168.1.10
SERVER_PORT=5000
```

Test and install startup:

```powershell
Test-NetConnection 192.168.1.10 -Port 5000
.\.venv\Scripts\python.exe .\client.py
```

After stopping the manual test:

```powershell
.\install_user_logon_task.ps1 -PythonExecutable "$PWD\.venv\Scripts\pythonw.exe"
Start-ScheduledTask -TaskName "NetworkClientUserAgent"
```

The most important value to customize on every PC is:

```env
SERVER_IP=the-LAN-IP-of-your-server
```