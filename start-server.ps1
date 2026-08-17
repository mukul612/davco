<#
.SYNOPSIS
    Starts the Dimensional Layout Generator web application.

.DESCRIPTION
    - Creates (or reuses) a Python virtual environment in .venv\
    - Installs/updates dependencies from requirements.txt
    - Loads configuration from .env (copied from .env.example if missing)
    - Verifies the Claude Code CLI is installed and reachable
    - Starts the FastAPI app with uvicorn

.PARAMETER Public
    Bind to 0.0.0.0 instead of the configured APP_HOST, so other computers
    on the local network can reach it (see README.md "Team Access" for the
    full picture, including the firewall rule you'll need to add yourself).

.EXAMPLE
    .\start-server.ps1

.EXAMPLE
    .\start-server.ps1 -Public
#>
param(
    [switch]$Public
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "=== Dimensional Layout Generator ===" -ForegroundColor Cyan

# --- 1. Find a real Python (not the Windows Store alias stub) ---
function Resolve-WorkingPython {
    $candidates = New-Object System.Collections.Generic.List[string]
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and (Test-Path $cmd.Source) -and (Get-Item $cmd.Source).Length -gt 0) {
        $candidates.Add($cmd.Source)
    }
    Get-ChildItem -Path "$env:LOCALAPPDATA\Programs\Python" -Filter "python.exe" -Recurse -ErrorAction SilentlyContinue |
        ForEach-Object { $candidates.Add($_.FullName) }
    foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
    throw "No working Python interpreter found. Install Python 3.10+ from python.org (not the Microsoft Store) and try again."
}

$systemPython = Resolve-WorkingPython
Write-Host "Using base Python: $systemPython"

# --- 2. Create/reuse a virtual environment ---
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Creating virtual environment in .venv\ ..."
    & $systemPython -m venv (Join-Path $PSScriptRoot ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Failed to create virtual environment." }
}

Write-Host "Installing/updating dependencies (this can take a minute the first time) ..."
& $venvPython -m pip install --quiet --upgrade pip
& $venvPython -m pip install --quiet -r (Join-Path $PSScriptRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Failed to install dependencies from requirements.txt." }

# --- 3. Configuration ---
$envFile = Join-Path $PSScriptRoot ".env"
if (-not (Test-Path $envFile)) {
    Write-Host "No .env found -- copying .env.example. Edit .env to customize settings." -ForegroundColor Yellow
    Copy-Item (Join-Path $PSScriptRoot ".env.example") $envFile
}

Write-Host "Loading configuration from .env ..."
Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    if ($line -eq "" -or $line.StartsWith("#")) { return }
    $parts = $line -split "=", 2
    if ($parts.Count -eq 2) {
        $name = $parts[0].Trim()
        $value = $parts[1].Trim()
        if ($value -ne "") {
            [System.Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
}

# --- 4. Verify the claude CLI is available (needed for the interpretation step) ---
$claudeCmd = Get-Command claude -ErrorAction SilentlyContinue
if (-not $claudeCmd) {
    Write-Host ""
    Write-Host "WARNING: 'claude' CLI was not found on PATH." -ForegroundColor Yellow
    Write-Host "The app will start, but drawing analysis will fail until Claude Code" -ForegroundColor Yellow
    Write-Host "is installed and authenticated on this machine (run 'claude' once from" -ForegroundColor Yellow
    Write-Host "a terminal and sign in, or set ANTHROPIC_API_KEY in .env)." -ForegroundColor Yellow
    Write-Host ""
} else {
    Write-Host "Found claude CLI: $($claudeCmd.Source)"
}

# --- 5. Verify master templates exist ---
foreach ($tmpl in @("Blank Supplier DIM.xlsx", "Blank Customer DIM.xlsx")) {
    $p = Join-Path $PSScriptRoot "templates_layout\$tmpl"
    if (-not (Test-Path $p)) {
        Write-Host "WARNING: missing template: $p" -ForegroundColor Yellow
    }
}

# --- 6. Start the server ---
$host_ = if ($Public) { "0.0.0.0" } else { $env:APP_HOST }
if (-not $host_) { $host_ = "127.0.0.1" }
$port = if ($env:APP_PORT) { $env:APP_PORT } else { "8000" }

Write-Host ""
Write-Host "Starting server at http://$($host_):$port ..." -ForegroundColor Green
if ($Public) {
    Write-Host "Bound to 0.0.0.0 -- reachable from other computers on the network" -ForegroundColor Yellow
    Write-Host "IF a Windows Firewall rule allows it. See README.md 'Team Access'." -ForegroundColor Yellow
}
Write-Host "Press CTRL+C to stop." -ForegroundColor Gray
Write-Host ""

& $venvPython -m uvicorn app.main:app --host $host_ --port $port
