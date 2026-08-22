[CmdletBinding()]
param(
    [string]$TaskName = "NetworkClientUserAgent",
    [ValidateRange(1, 60)]
    [int]$StopTimeoutSeconds = 15
)

$ErrorActionPreference = "Stop"
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop

# Removing a scheduled task prevents future starts but can leave its current
# pythonw.exe instance running. Stop and confirm that instance exits first.
if ($task.State -eq "Running") {
    Stop-ScheduledTask -InputObject $task -ErrorAction Stop
    $deadline = (Get-Date).AddSeconds($StopTimeoutSeconds)

    do {
        Start-Sleep -Milliseconds 500
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    } while ($task.State -eq "Running" -and (Get-Date) -lt $deadline)

    if ($task.State -eq "Running") {
        throw "'$TaskName' is still running after $StopTimeoutSeconds seconds. It was not removed."
    }
}

Unregister-ScheduledTask -InputObject $task -Confirm:$false -ErrorAction Stop
Write-Host "Removed '$TaskName'."
