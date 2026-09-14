# Fresh Client Installation

This is the recommended installation for a PC that does not yet have the
current client layout. Endpoint PCs need Python and an outbound route to the
server; they do not need MySQL, port `3306`, REST port `8080`, or Kismet.

## 1. Place the client

Use a permanent path such as:

```text
C:\NetworkScanner\client
```

The installed layout should include:

```text
client\
├── app\             # current replaceable application
├── config\          # machine-specific .env
├── logs\
├── storage\
├── updater\
├── user_agent.py
└── client.py
```

Do not place an installed client in Downloads or a temporary extraction path.

## 2. Install Python and dependencies

PowerShell:

```powershell
cd C:\NetworkScanner\client
python --version
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r .\app\requirements.txt
```

If PowerShell blocks activation:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

## 3. Configure the server target

Create `C:\NetworkScanner\client\config\.env`:

```env
SERVER_IP=192.168.1.10
SERVER_PORT=5000
```

Add optional collection/policy values only when needed. Never put database
credentials or server `.env` content on the client.

## 4. Test before installing startup

On the client:

```powershell
Test-NetConnection 192.168.1.10 -Port 5000
.\venv\Scripts\python.exe .\client.py
```

Confirm the client registers in the server GUI/API, then stop the foreground
process with `Ctrl+C`.

## 5. Install automatic user-session startup

Use the signed-in user task when screenshots, browser activity, or Recent-file
data are required:

```powershell
.\install_user_logon_task.ps1 `
  -PythonExecutable "$PWD\venv\Scripts\pythonw.exe"
Start-ScheduledTask -TaskName "NetworkClientUserAgent"
Get-ScheduledTaskInfo -TaskName "NetworkClientUserAgent"
```

Review `logs\client_service.log`. Do not run the legacy Windows service and
the user-session task simultaneously for one endpoint.

## 6. Optional machine service

`client/service.py` is a `pywin32` service wrapper for machine-wide operation.
Use it only when the deployment does not need the interactive user's profile,
or when the service/user-agent split has been deliberately designed and
tested. The user-session task remains the default for the complete feature set.

