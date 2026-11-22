# Start the demo with one command (Windows PowerShell). Builds whatever is missing, then serves everything on :8000.
# Usage:  powershell -ExecutionPolicy Bypass -File run.ps1        (add -Rebuild to rebuild the frontend)
param([switch]$Rebuild)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

function Assert-Ok($what) { if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)" } }

Set-Location "$root\backend"
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating Python environment..."
    if (Get-Command py -ErrorAction SilentlyContinue) { py -3 -m venv .venv } else { python -m venv .venv }
    Assert-Ok "venv"
    .\.venv\Scripts\python -m pip install -r requirements.txt
    Assert-Ok "pip install"
}
if ($Rebuild -or -not (Test-Path "$root\frontend\dist\index.html")) {
    Write-Host "Building frontend..."
    Push-Location "$root\frontend"
    npm install
    Assert-Ok "npm install"
    npm run build
    Assert-Ok "npm run build"
    Pop-Location
}
Write-Host ""
Write-Host "Demo running at http://localhost:8000   (Ctrl+C to stop)"
.\.venv\Scripts\python -m uvicorn app.main:app --port 8000
