# HIVE launcher.
#   .\hive.ps1            start on your real vault (./vault) and open the browser
#   .\hive.ps1 -Demo      (re)build the fictional demo vault and start on it (port 8788)
#   Everyday use: scripts\install-server.ps1 runs HIVE in the background at login; install it as an app from Edge.
#   .\hive.ps1 -Setup     create the venv + install hash-locked deps (first run)
#   .\hive.ps1 -Test      run the test suite
param([switch]$Demo, [switch]$Setup, [switch]$Test, [int]$Port = 0)
$ErrorActionPreference = 'Stop'
if ($Port -eq 0) { $Port = if ($Demo) { 8788 } else { 8787 } }  # demo gets its own port so it never clashes with the real HIVE
$root = $PSScriptRoot
$venv = "$env:LOCALAPPDATA\hive\.venv"
$py = "$venv\Scripts\python.exe"

if ($Setup -or -not (Test-Path $py)) {
    Write-Host "Creating venv at $venv (outside Google Drive) ..."
    python -m venv $venv
    & $py -m pip install --require-hashes --no-deps -r "$root\server\requirements.lock"
    if ($LASTEXITCODE -ne 0) { throw "dependency install failed" }
}
if ($Test) {
    Push-Location "$root\server"; & $py -m pytest -q -p no:cacheprovider; $code = $LASTEXITCODE; Pop-Location; exit $code
}
if ($Demo) {
    & $py "$root\scripts\make_demo.py"
    $env:HIVE_VAULT = "$env:LOCALAPPDATA\hive\demo-vault"
} else {
    Remove-Item Env:HIVE_VAULT -ErrorAction SilentlyContinue
}
$env:PYTHONPATH = "$root\server"
if (-not $Demo -and -not (Test-Path "$root\vault\CLAUDE.md")) {
    Write-Host "No vault yet: scaffolding ./vault from vault-template (its own private git repo) ..."
    & $py -m hive init
}
Start-Job -ScriptBlock { param($p) Start-Sleep 2; Start-Process "http://127.0.0.1:$p" } -ArgumentList $Port | Out-Null
Write-Host "HIVE on http://127.0.0.1:$Port  (Ctrl+C to stop)" -ForegroundColor Yellow
& $py -m hive serve --port $Port
