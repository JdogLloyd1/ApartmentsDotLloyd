# Windows PowerShell wrapper that mirrors the Makefile.
# Use when `make` is not installed. From the repo root:
#   ./make.ps1 install
#   ./make.ps1 run
#   ./make.ps1 test
#   ./make.ps1 up-local   # Sprint 7: docker compose up

[CmdletBinding()]
param(
  [Parameter(Position = 0)]
  [ValidateSet(
    'help', 'install', 'install-dev', 'lint', 'format', 'test', 'run', 'clean', 'venv',
    'build-local', 'up-local', 'down-local', 'logs-local', 'seed', 'refresh-all', 'smoke-e2e'
  )]
  [string]$Target = 'help'
)

$ErrorActionPreference = 'Stop'

$RepoRoot     = $PSScriptRoot
$AppRoot      = Join-Path $RepoRoot 'App V1 Dynamic'
$Backend      = Join-Path $AppRoot  'backend'
$ComposeFile  = Join-Path $AppRoot  'docker-compose.local.yml'
$VenvDir      = Join-Path $RepoRoot '.venv'
$Python       = Join-Path $VenvDir  'Scripts/python.exe'
$Pip          = Join-Path $VenvDir  'Scripts/pip.exe'

function Invoke-Compose {
  param([Parameter(ValueFromRemainingArguments = $true)]$Args)
  & docker compose -f $ComposeFile @Args
  if ($LASTEXITCODE -ne 0) { throw "docker compose $($Args -join ' ') failed with exit code $LASTEXITCODE" }
}

function Invoke-Venv {
  if (-not (Test-Path $Python)) {
    Write-Host "Creating virtual environment at $VenvDir"
    python -m venv $VenvDir
  }
}

function Invoke-Install {
  Invoke-Venv
  & $Pip install --upgrade pip
  & $Pip install -e "$Backend[dev,scraping,scheduling]"
}

function Invoke-Lint {
  Push-Location $Backend
  try {
    & $Python -m ruff check .
    if ($LASTEXITCODE -ne 0) { throw "ruff check failed" }
    & $Python -m ruff format --check .
    if ($LASTEXITCODE -ne 0) { throw "ruff format --check failed" }
  } finally { Pop-Location }
}

function Invoke-Format {
  Push-Location $Backend
  try {
    & $Python -m ruff format .
    & $Python -m ruff check --fix .
  } finally { Pop-Location }
}

function Invoke-Test {
  Push-Location $Backend
  try {
    & $Python -m pytest
    if ($LASTEXITCODE -ne 0) { throw "pytest failed" }
  } finally { Pop-Location }
}

function Invoke-Run {
  Push-Location $Backend
  try {
    & $Python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
  } finally { Pop-Location }
}

function Invoke-BuildLocal { Invoke-Compose 'build' '--no-cache' }

function Invoke-UpLocal {
  Invoke-Compose 'up' '-d' '--build'
  Write-Host ""
  Write-Host "Dashboard: http://localhost:8000/"
  Write-Host "Health:    http://localhost:8000/api/health"
}

function Invoke-DownLocal  { Invoke-Compose 'down' }
function Invoke-LogsLocal  { Invoke-Compose 'logs' '-f' '--tail=100' 'api' }

function Invoke-Seed       { Invoke-Compose 'exec' 'api' 'python' '-m' 'app.seed.loader' }
function Invoke-RefreshAll { Invoke-Compose 'exec' 'api' 'python' '-m' 'app.refresh_cli' }

function Invoke-SmokeE2E {
  Push-Location $Backend
  try {
    $env:E2E = '1'
    & $Python -m pytest tests/e2e -v
    if ($LASTEXITCODE -ne 0) { throw "E2E smoke failed" }
  } finally {
    Remove-Item Env:\E2E -ErrorAction SilentlyContinue
    Pop-Location
  }
}

function Invoke-Clean {
  if (Test-Path $VenvDir) { Remove-Item -Recurse -Force $VenvDir }
  Get-ChildItem -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
    ForEach-Object { Remove-Item -Recurse -Force $_.FullName }
  Get-ChildItem -Recurse -Directory -Filter '.pytest_cache' -ErrorAction SilentlyContinue |
    ForEach-Object { Remove-Item -Recurse -Force $_.FullName }
  Get-ChildItem -Recurse -Directory -Filter '.ruff_cache' -ErrorAction SilentlyContinue |
    ForEach-Object { Remove-Item -Recurse -Force $_.FullName }
  Get-ChildItem -Recurse -Directory -Filter '.mypy_cache' -ErrorAction SilentlyContinue |
    ForEach-Object { Remove-Item -Recurse -Force $_.FullName }
  Get-ChildItem -Path $Backend -Recurse -Filter '*.db' -ErrorAction SilentlyContinue |
    ForEach-Object { Remove-Item -Force $_.FullName }
}

function Invoke-Help {
  @"
Alewife Apartment Intelligence -- PowerShell targets

  help         Show this message
  venv         Create the local virtual environment (.venv)
  install      Install runtime + dev dependencies into .venv
  install-dev  Alias for install
  lint         Run ruff check + ruff format --check
  format       Auto-format with ruff
  test         Run pytest
  run          Start uvicorn in reload mode on port 8000
  clean        Remove caches, build artifacts, and the local SQLite DB

  Local Docker stack (Sprint 7):
  build-local  docker compose build --no-cache
  up-local     docker compose up -d --build  (dashboard on :8000)
  down-local   docker compose down
  logs-local   Tail the api container logs
  seed         Load buildings_seed.json into the running container's DB
  refresh-all  Run ORS + scrapers end-to-end inside the container
  smoke-e2e    E2E=1 pytest tests/e2e against http://localhost:8000
"@ | Write-Host
}

switch ($Target) {
  'help'        { Invoke-Help }
  'venv'        { Invoke-Venv }
  'install'     { Invoke-Install }
  'install-dev' { Invoke-Install }
  'lint'        { Invoke-Lint }
  'format'      { Invoke-Format }
  'test'        { Invoke-Test }
  'run'         { Invoke-Run }
  'clean'       { Invoke-Clean }
  'build-local' { Invoke-BuildLocal }
  'up-local'    { Invoke-UpLocal }
  'down-local'  { Invoke-DownLocal }
  'logs-local'  { Invoke-LogsLocal }
  'seed'        { Invoke-Seed }
  'refresh-all' { Invoke-RefreshAll }
  'smoke-e2e'   { Invoke-SmokeE2E }
}
