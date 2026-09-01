# Windows Server Setup Verification

**Platform:** Windows  
**Server:** Python-based (api_server.py)  
**Storage:** `server/storage/packages/`

---

## Pre-Test Verification Checklist

Run these checks before starting Milestone F testing:

### 1. Verify Package Storage Directory Exists

```powershell
# Check if server/storage/packages directory exists
Test-Path "C:\Users\merou\OneDrive\Desktop\network-scanner\server\storage\packages"
# Should return: True

# If False, create it:
New-Item -ItemType Directory -Force -Path "C:\Users\merou\OneDrive\Desktop\network-scanner\server\storage\packages"
```

### 2. Verify Server Is Running

```powershell
# Check if server process is running
Get-Process | Where-Object {$_.ProcessName -like "*python*"} | Select-Object ProcessName, Id

# Or check if port 8080 is listening
netstat -ano | findstr :8080
# Should show something like: TCP    0.0.0.0:8080    0.0.0.0:0    LISTENING    <PID>
```

### 3. Verify Server Responds

```powershell
# Test server health endpoint
curl "http://localhost:8080/health"
# Expected: JSON response with server status

# Test supported actions endpoint
curl "http://localhost:8080/api/v1/actions?types=1"
# Expected: JSON with supported_actions array including "UPDATE_CLIENT"
```

### 4. Verify Test Client Is Running

On the test PC:
```powershell
# Check if client process is running
Get-Process | Where-Object {$_.ProcessName -like "*client*"}

# Or check client logs
Get-Content "C:\path\to\client\logs\client.log" -Tail 20
# Should show recent heartbeat entries
```

### 5. Verify Network Connectivity

On the test PC, ping the server:
```powershell
ping <SERVER_IP>
# Should show responses with <1ms latency (if local network)

# Test connection to server API
curl "http://<SERVER_IP>:8080/health"
# Should return HTTP 200
```

### 6. Verify Storage Permissions

```powershell
# Check that the storage directory is writable
$testFile = "C:\Users\merou\OneDrive\Desktop\network-scanner\server\storage\packages\test.txt"
"test" | Out-File -FilePath $testFile -Force
if (Test-Path $testFile) {
    Remove-Item $testFile
    Write-Host "✓ Storage directory is writable"
} else {
    Write-Host "✗ Storage directory is NOT writable - check permissions"
}
```

---

## Quick Diagnostics Commands

### Monitor Server Logs (PowerShell)

```powershell
# If server is outputting logs to console, you'll see them in the terminal
# Or check for log files:
Get-ChildItem -Path "C:\Users\merou\OneDrive\Desktop\network-scanner\server\logs" -ErrorAction SilentlyContinue | 
  Select-Object -Last 5

# Monitor a specific log in real-time (if using file logging):
Get-Content "C:\Users\merou\OneDrive\Desktop\network-scanner\server\logs\api.log" -Wait -Tail 20
```

### Monitor Uploaded Packages

```powershell
# Watch packages as they're uploaded
Get-ChildItem -Path "C:\Users\merou\OneDrive\Desktop\network-scanner\server\storage\packages" -Recurse

# Count uploaded packages
(Get-ChildItem -Path "C:\Users\merou\OneDrive\Desktop\network-scanner\server\storage\packages" -Recurse | 
  Where-Object {$_.Extension -eq ".zip"}).Count
```

### Check Package File Details

```powershell
# Get info on a specific package
Get-Item "C:\Users\merou\OneDrive\Desktop\network-scanner\server\storage\packages\client-update-2.0.0.zip" | 
  Select-Object Name, Length, LastWriteTime, @{Name="Size(MB)";Expression={[math]::Round($_.Length/1MB,2)}}
```

---

## Common Windows Server Issues

### Issue: "Access Denied" When Uploading Package

**Symptom:** Package upload returns 403 Forbidden

**Check:**
```powershell
# Verify folder exists
Test-Path "C:\Users\merou\OneDrive\Desktop\network-scanner\server\storage\packages"

# Check folder permissions
icacls "C:\Users\merou\OneDrive\Desktop\network-scanner\server\storage\packages"

# Verify Python process has write permissions
# (Usually True if running with user account that owns the folder)
```

**Fix:**
```powershell
# Grant write permissions to current user (if needed)
icacls "C:\Users\merou\OneDrive\Desktop\network-scanner\server\storage\packages" /grant $env:USERNAME":F" /T
```

### Issue: Server Not Listening on Port 8080

**Symptom:** Connection refused when trying to curl http://localhost:8080

**Check:**
```powershell
# Verify port is available
netstat -ano | findstr :8080

# Verify server process is running
Get-Process -Name python | Where-Object {$_.CommandLine -like "*api_server*"}
```

**Fix:**
1. Restart the server process
2. Or change port in api_server.py if 8080 is in use

### Issue: Package Upload Succeeds But File Doesn't Appear

**Symptom:** API returns success but file not in `server/storage/packages/`

**Check:**
```powershell
# Verify directory path in api_server.py matches actual path
# Verify path is not a relative path (Windows relative paths can be tricky)

# Check if there's a temp directory:
Get-ChildItem -Path "C:\Users\merou\OneDrive\Desktop\network-scanner\server\storage" -Recurse
```

**Fix:** Ensure api_server.py uses absolute Windows paths (C:\... not relative paths)

---

## Pre-Test Checklist (Before Running Scenarios)

Run all these checks and confirm ✓ before starting testing:

- [ ] `Test-Path "server\storage\packages"` returns True
- [ ] Server process is running (check with Get-Process)
- [ ] `curl http://localhost:8080/health` returns 200
- [ ] `curl http://localhost:8080/api/v1/actions?types=1` includes "UPDATE_CLIENT"
- [ ] `ping <SERVER_IP>` succeeds (from test PC)
- [ ] `curl http://<SERVER_IP>:8080/health` returns 200 (from test PC)
- [ ] Can write to `server/storage/packages/` (test with dummy file)
- [ ] Test client is running and version is registered on server

**All checkmarks:** Ready to start Milestone F testing

---

## Restart Server Safely

```powershell
# 1. Stop the server process
Stop-Process -Name python -Force

# 2. Wait a moment
Start-Sleep -Seconds 2

# 3. Restart the server
cd "C:\Users\merou\OneDrive\Desktop\network-scanner\server"
python api_server.py
# Should start listening on port 8080
```

---

## Environment Variables (If Needed)

If you need to set custom paths in Windows, you can use:

```powershell
# Set storage path environment variable (if api_server.py reads it)
$env:STORAGE_PATH = "C:\Users\merou\OneDrive\Desktop\network-scanner\server\storage"

# Or in api_server.py startup:
$env:SERVER_PORT = "8080"
python api_server.py
```

---

**Last Updated:** September 1, 2026  
**Platform:** Windows Server  
**Status:** Ready for testing
