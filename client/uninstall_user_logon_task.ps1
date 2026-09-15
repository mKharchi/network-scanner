[CmdletBinding()]
param(
    [string]$TaskName = "NetworkClientUserAgent",
    [ValidateRange(1, 60)]
    [int]$StopTimeoutSeconds = 15
)

$ErrorActionPreference = "Stop"
$clientDir = $PSScriptRoot
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop

# Removing a scheduled task prevents future starts but does NOT kill the
# already-running pythonw.exe. Stop the task, then force-kill matching client
# processes from this install directory (same behavior as stop_windows_client.ps1).
if ($task.State -eq "Running") {
    Stop-ScheduledTask -InputObject $task -ErrorAction Stop
    $deadline = (Get-Date).AddSeconds($StopTimeoutSeconds)

    do {
        Start-Sleep -Milliseconds 500
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    } while ($task.State -eq "Running" -and (Get-Date) -lt $deadline)

    if ($task.State -eq "Running") {
        Write-Warning "'$TaskName' is still marked Running after $StopTimeoutSeconds seconds; killing processes anyway."
    }
}

$escapedClientDir = [regex]::Escape($clientDir)
$clientProcesses = Get-CimInstance Win32_Process |
    Where-Object {
        $_.CommandLine -and
        $_.CommandLine -match $escapedClientDir -and
        $_.CommandLine -match "(client\.py|user_agent\.py|NetworkScannerClient\.exe)"
    }

foreach ($process in $clientProcesses) {
    Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    Write-Host "Stopped client process PID $($process.ProcessId): $($process.Name)"
}

Unregister-ScheduledTask -InputObject $task -Confirm:$false -ErrorAction Stop
Write-Host "Removed '$TaskName'."
