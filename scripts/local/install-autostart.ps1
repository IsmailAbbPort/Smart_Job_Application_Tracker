# One-time setup: register a logon task that brings the stack up in the background.
#
# This is the piece that makes ingestion independent of ever opening the UI. It is
# preferred over Docker Desktop's "start at login" toggle because it is scriptable
# and because it starts Docker Desktop itself rather than assuming it is up.
#
# Run with:  powershell -ExecutionPolicy Bypass -File install-autostart.ps1
#        or: powershell -ExecutionPolicy Bypass -File install-autostart.ps1 -Remove

param([switch]$Remove)

$ErrorActionPreference = 'Stop'

$taskName = 'JobTrackerAutostart'

if ($Remove) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "Removed the '$taskName' task."
    return
}

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = (Resolve-Path (Join-Path $here '..\..')).Path
$wrapper = Join-Path $here 'start-tracker-hidden.vbs'
if (-not (Test-Path $wrapper)) { throw "wrapper not found: $wrapper" }

# wscript with the .vbs shim, so no console flashes on the desktop at every logon.
$action = New-ScheduledTaskAction -Execute 'wscript.exe' `
    -Argument ('"{0}" --no-browser' -f $wrapper) -WorkingDirectory $repo
# A short delay: Docker Desktop and the network are both still settling at logon.
$trigger = New-ScheduledTaskTrigger -AtLogOn
$trigger.Delay = 'PT1M'
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Description 'Start the Job Tracker stack at logon (no UI)' -Force | Out-Null

Write-Host "Registered the '$taskName' logon task."
Write-Host 'Verify with:  Get-ScheduledTask JobTrackerAutostart'
Write-Host 'Test it now with:  Start-ScheduledTask JobTrackerAutostart'
