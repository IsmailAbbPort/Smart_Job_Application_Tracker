# One-time setup: put a "Job Tracker" shortcut on the Desktop.
#
# PowerShell is fine here (unlike the launcher) because this is run by hand, once,
# and its failure mode is immediate and visible.
#
# The shortcut starts minimized rather than hidden: the launcher may take a couple
# of minutes on a cold Docker start, and if it fails the window has to still be
# there to read. Run with:  powershell -ExecutionPolicy Bypass -File install-shortcut.ps1

$ErrorActionPreference = 'Stop'

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = (Resolve-Path (Join-Path $here '..\..')).Path
$launcher = Join-Path $here 'start-tracker.cmd'
if (-not (Test-Path $launcher)) { throw "launcher not found: $launcher" }

$link = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Job Tracker.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($link)
$shortcut.TargetPath = $launcher
$shortcut.WorkingDirectory = $repo
$shortcut.Description = 'Start the Smart Job Application Tracker and open its UI'
$shortcut.WindowStyle = 7  # minimized
# No bundled .ico in the repo, so borrow the browser's (shell32 globe as a fallback).
$edge = Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'
if (Test-Path $edge) { $shortcut.IconLocation = "$edge,0" }
else { $shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,13" }
$shortcut.Save()

Write-Host "Created: $link"
Write-Host 'Double-click it to start the stack and open the UI in an app window.'
