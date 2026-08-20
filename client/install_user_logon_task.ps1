[CmdletBinding()]
param(
    [string]$PythonExecutable = "pythonw.exe",
    [string]$TaskName = "NetworkClientUserAgent"
)

$ErrorActionPreference = "Stop"
$clientDir = $PSScriptRoot
$entryPoint = Join-Path $clientDir "user_agent.py"

if (-not (Test-Path -LiteralPath $entryPoint -PathType Leaf)) {
    throw "Could not find the user-agent entry point: $entryPoint"
}

# Resolve this while the installer is running in the intended user's session.
# A full executable path is stored in the task so it does not depend on PATH
# when Task Scheduler later starts it at logon.
$pythonCommand = Get-Command $PythonExecutable -ErrorAction Stop
$pythonPath = $pythonCommand.Source
$userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

$action = New-ScheduledTaskAction `
    -Execute $pythonPath `
    -Argument ('"{0}"' -f $entryPoint) `
    -WorkingDirectory $clientDir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $userId
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal `
    -UserId $userId `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Network Scanner client running in the signed-in user's session." `
    -Force | Out-Null

Write-Host "Installed '$TaskName' for $userId."
Write-Host "It will start at the next sign-in. To start it now, run:"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
