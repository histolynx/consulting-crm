# Run the HIVE server quietly in the background (no console window), starting at Windows login.
#   scripts\install-server.ps1            register "HIVE Server" (at logon) and start it now
#   scripts\install-server.ps1 -Restart   restart it (e.g. after updating HIVE's code)
#   scripts\install-server.ps1 -Remove    stop and unregister it
# Then open http://127.0.0.1:8787 in Edge → ⋯ → Apps → "Install HIVE" → right-click the taskbar icon → Pin.
param([switch]$Remove, [switch]$Restart, [int]$Port = 8787)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$pyw = "$env:LOCALAPPDATA\hive\.venv\Scripts\pythonw.exe"
$name = 'HIVE Server'

function Stop-Hive {
    Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
}

if ($Remove) { Stop-Hive; Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue; Write-Host "Removed $name."; exit 0 }
if ($Restart) { Stop-Hive; Start-Sleep 1; Start-ScheduledTask -TaskName $name; Write-Host "Restarted $name."; exit 0 }
if (-not (Test-Path $pyw)) { throw "venv missing: run .\hive.ps1 -Setup first" }
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    throw "Port $Port is already in use (a HIVE window from hive.ps1?). Stop it first, then re-run."
}

$action = New-ScheduledTaskAction -Execute $pyw -Argument "-m hive serve --port $Port" -WorkingDirectory "$root\server"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings `
    -Description "HIVE local server on 127.0.0.1:$Port (log: %LOCALAPPDATA%\hive\server.log)" -Force | Out-Null
Start-ScheduledTask -TaskName $name
Start-Sleep 4
try { Invoke-RestMethod "http://127.0.0.1:$Port/api/health" | Out-Null; Write-Host "HIVE Server running on http://127.0.0.1:$Port and will start at every login." -ForegroundColor Green }
catch { Write-Warning "Task registered but the server didn't answer yet. Check $env:LOCALAPPDATA\hive\server.log" }
