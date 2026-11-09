# One-time setup: register a logon task that brings the stack up in the background.
#
# This is the piece that makes ingestion independent of ever opening the UI. It is
# preferred over Docker Desktop's "start at login" toggle because it is scriptable
# and because it starts Docker Desktop itself rather than assuming it is up.
#
# Needs an ELEVATED PowerShell: registering a task in Task Scheduler's root folder
# is an admin operation, and a normal shell gets a bare "Access is denied"
# (0x80070005) from the COM layer with nothing saying why.
#
# Run with:  powershell -ExecutionPolicy Bypass -File install-autostart.ps1
#        or: powershell -ExecutionPolicy Bypass -File install-autostart.ps1 -Remove

param([switch]$Remove)

$ErrorActionPreference = 'Stop'

$taskName = 'JobTrackerAutostart'

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not (New-Object Security.Principal.WindowsPrincipal($identity)).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw ("This needs an elevated PowerShell (registering a scheduled task in the " +
        "root folder is an admin operation). Right-click PowerShell, Run as " +
        "administrator, then run this again.")
}

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

# Pinned to the user who is installing it, not left to default. This has to be run
# elevated, and if that elevation came from a different account (a separate admin
# user answering the UAC prompt) the task would otherwise be registered against
# that account and never fire at this one's logon. Interactive-only, so it needs no
# stored password and only runs while the user is actually signed in.
$principal = New-ScheduledTaskPrincipal -UserId $identity.Name -LogonType Interactive

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal `
    -Description 'Start the Job Tracker stack at logon (no UI)' -Force | Out-Null

Write-Host "Registered the '$taskName' logon task for $($identity.Name)."
Write-Host 'Verify with:  Get-ScheduledTask JobTrackerAutostart'
Write-Host 'Test it now with:  Start-ScheduledTask JobTrackerAutostart'
