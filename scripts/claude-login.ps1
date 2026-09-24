# Give HIVE's agent its OWN Claude login (e.g. the Claude account tied to your hive mailbox),
# separate from the account your everyday Claude Code uses.
#   scripts\claude-login.ps1            sign in (opens browser) and record the config dir in secrets.env
#   scripts\claude-login.ps1 -Status    show which account HIVE uses
#   scripts\claude-login.ps1 -Logout    sign HIVE's account out
param([switch]$Status, [switch]$Logout, [string]$ConfigDir = "$env:USERPROFILE\.hive\claude")
$ErrorActionPreference = 'Stop'
$exe = (Get-Command claude -ErrorAction SilentlyContinue).Source
if (-not $exe) {
    $exe = (Get-ChildItem "$env:USERPROFILE\.vscode\extensions\anthropic.claude-code-*\resources\native-binary\claude.exe" |
            Sort-Object { [version]($_.FullName -replace '.*claude-code-(\d+\.\d+\.\d+).*', '$1') } | Select-Object -Last 1).FullName
}
if (-not $exe) { throw "Claude Code CLI not found" }

New-Item -ItemType Directory -Force $ConfigDir | Out-Null
$env:CLAUDE_CONFIG_DIR = $ConfigDir
if ($Status) { & $exe auth status; exit $LASTEXITCODE }
if ($Logout) { & $exe auth logout; exit $LASTEXITCODE }

Write-Host "Signing HIVE into Claude (config dir: $ConfigDir)." -ForegroundColor Yellow
Write-Host "In the browser, choose the Claude account you want HIVE to use." -ForegroundColor Yellow
& $exe auth login
& $exe auth status

$secrets = "$env:USERPROFILE\.hive\secrets.env"
New-Item -ItemType Directory -Force (Split-Path $secrets) | Out-Null
if (-not (Test-Path $secrets)) { New-Item -ItemType File $secrets | Out-Null }
$lines = @(Get-Content $secrets | Where-Object { $_ -notmatch '^\s*HIVE_CLAUDE_CONFIG_DIR=' })
$lines += "HIVE_CLAUDE_CONFIG_DIR=$ConfigDir"
$lines | Set-Content -Encoding utf8 $secrets
Write-Host "Recorded HIVE_CLAUDE_CONFIG_DIR in $secrets. Restart HIVE to use this account." -ForegroundColor Green
