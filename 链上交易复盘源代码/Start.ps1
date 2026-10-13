$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$importScript = Join-Path $root "deployment\import-demo-data.ps1"
$envFile = Join-Path $backend ".env"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker was not found. Install and start Docker Desktop first."
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm was not found. Install Node.js 20 or newer first."
}

$modelKey = Get-Content -LiteralPath $envFile |
    Where-Object { $_ -match '^LLM_API_KEY=' } |
    Select-Object -First 1
if (-not $modelKey -or $modelKey -eq "LLM_API_KEY=") {
    Write-Warning "LLM_API_KEY is empty. Cached cases remain available, but new analyses need a model key."
}

Write-Host "Starting backend services and restoring cached cases..."
& $importScript -ComposeDirectory $backend

Write-Host "Installing frontend dependencies..."
Push-Location $frontend
try {
    npm ci
    Write-Host "AttackPilot is available at http://localhost:5173"
    npm run dev
}
finally {
    Pop-Location
}
