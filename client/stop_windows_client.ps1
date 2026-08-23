[CmdletBinding()]
param(
    [string]$TaskName = "NetworkClientUserAgent",
    [string]$ServiceName = "NetworkClient"
)

$ErrorActionPreference = "Stop"
$clientDir = $PSScriptRoot

function Stop-IfPresent {
    param(
        [scriptblock]$Action,
        [string]$Description
    )

    try {
        & $Action
        Write-Host $Description
    } catch [Microsoft.Management.Infrastructure.CimException] {
        # The service or task does not exist on this computer.
    } catch [System.InvalidOperationException] {
        # The service is already stopped or the task is no longer registered.
    }
}

Stop-IfPresent {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    if ($task.State -eq "Running") {
        Stop-ScheduledTask -InputObject $task -ErrorAction Stop
    }
} "Stopped scheduled task '$TaskName'."

Stop-IfPresent {
    $service = Get-Service -Name $ServiceName -ErrorAction Stop
    if ($service.Status -ne "Stopped") {
        Stop-Service -Name $ServiceName -ErrorAction Stop
    }
} "Stopped service '$ServiceName'."

$escapedClientDir = [regex]::Escape($clientDir)
$clientProcesses = Get-CimInstance Win32_Process |
    Where-Object {
        $_.CommandLine -and
        $_.CommandLine -match $escapedClientDir -and
        $_.CommandLine -match "(client\.py|user_agent\.py|NetworkScannerClient\.exe)"
    }

foreach ($process in $clientProcesses) {
    Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
    Write-Host "Stopped client process PID $($process.ProcessId): $($process.Name)"
}
