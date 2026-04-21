# Windows PowerShell wrapper that mirrors the Makefile.
# Use when `make` is not installed. From the repo root:
#   ./make.ps1 install
#   ./make.ps1 run
#   ./make.ps1 test

[CmdletBinding()]
param(
  [Parameter(Position = 0)]
  [ValidateSet('help', 'install', 'install-dev', 'lint', 'format', 'test', 'run', 'clean', 'venv')]
  [string]$Target = 'help'
)

$ErrorActionPreference = 'Stop'

$RepoRoot = $PSScriptRoot
$Backend = Join-Path $RepoRoot 'App V1 Dynamic/backend'
$VenvDir = Join-Path $RepoRoot '.venv'
$Python  = Join-Path $VenvDir 'Scripts/python.exe'
$Pip     = Join-Path $VenvDir 'Scripts/pip.exe'

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

  help        Show this message
  venv        Create the local virtual environment (.venv)
  install     Install runtime + dev dependencies into .venv
  install-dev Alias for install
  lint        Run ruff check + ruff format --check
  format      Auto-format with ruff
  test        Run pytest
  run         Start uvicorn in reload mode on port 8000
  clean       Remove caches, build artifacts, and the local SQLite DB
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
}
