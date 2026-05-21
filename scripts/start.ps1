# start.ps1 — start backend + frontend dev servers
# Run from the repo root: .\scripts\start.ps1

$Root    = Split-Path $PSScriptRoot -Parent
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$Venv    = Join-Path $Backend ".venv\Scripts\Activate.ps1"

# Activate virtualenv if not already active
if (-not $env:VIRTUAL_ENV) {
    if (Test-Path $Venv) {
        Write-Host "Activating venv..." -ForegroundColor Cyan
        & $Venv
    } else {
        Write-Error "No venv found at $Venv. Run: python -m venv backend\.venv && backend\.venv\Scripts\pip install -r backend\requirements.txt"
        exit 1
    }
}

# Load .env.local so ANTHROPIC_API_KEY etc. are available to uvicorn
$EnvFile = Join-Path $Root ".env.local"
if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match '^\s*([^#][^=]+)=(.*)$') {
            [System.Environment]::SetEnvironmentVariable($Matches[1].Trim(), $Matches[2].Trim(), 'Process')
        }
    }
    Write-Host "Loaded $EnvFile" -ForegroundColor Cyan
}

# Start backend in a new window so logs stay separate
Write-Host "Starting backend (uvicorn :8000)..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$Backend'; uvicorn main:app --reload --port 8000"

# Give uvicorn a moment to bind before Vite starts proxying
Start-Sleep -Seconds 2

# Start frontend in this window
Write-Host "Starting frontend (vite :5173)..." -ForegroundColor Cyan
Set-Location $Frontend
npm run dev
