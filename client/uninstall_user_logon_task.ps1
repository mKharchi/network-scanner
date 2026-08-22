[CmdletBinding()]
param(
    [string]$TaskName = "NetworkClientUserAgent"
)

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
Write-Host "Removed '$TaskName'."
