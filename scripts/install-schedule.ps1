# Register (or -Remove) Windows scheduled tasks for HIVE:
#   "HIVE Sync"  hourly   -> python -m hive sync   (fetch mail, Claude ingest, push drafts, time gaps, git commit)
#   "HIVE Brief" 07:30    -> python -m hive brief  (Claude writes briefings/<today>.md)
# Runs as the current user, only when logged on. Output is appended to vault/.hive/scheduler.log.
param([switch]$Remove, [string]$BriefAt = '07:30')
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$py = "$env:LOCALAPPDATA\hive\.venv\Scripts\python.exe"
$log = "$root\vault\.hive\scheduler.log"

if ($Remove) {
    foreach ($n in 'HIVE Sync', 'HIVE Brief') { Unregister-ScheduledTask -TaskName $n -Confirm:$false -ErrorAction SilentlyContinue }
    Write-Host 'Removed HIVE scheduled tasks.'; exit 0
}
if (-not (Test-Path $py)) { throw "venv missing: run .\hive.ps1 -Setup first" }

function New-HiveAction([string]$cmd) {
    $arg = "-NoProfile -WindowStyle Hidden -Command `"`$env:PYTHONPATH='$root\server'; & '$py' -m hive $cmd *>> '$log'`""
    New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arg -WorkingDirectory $root
}
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
$hourly = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddHours((Get-Date).Hour + 1) -RepetitionInterval (New-TimeSpan -Hours 1)
$morning = New-ScheduledTaskTrigger -Daily -At $BriefAt

Register-ScheduledTask -TaskName 'HIVE Sync' -Action (New-HiveAction 'sync') -Trigger $hourly -Settings $settings -Description 'HIVE hourly mail sync + ingest' -Force | Out-Null
Register-ScheduledTask -TaskName 'HIVE Brief' -Action (New-HiveAction 'brief') -Trigger $morning -Settings $settings -Description 'HIVE morning briefing' -Force | Out-Null
Write-Host "Registered 'HIVE Sync' (hourly) and 'HIVE Brief' (daily $BriefAt). Log: $log"
