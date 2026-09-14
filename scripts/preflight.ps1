$ErrorActionPreference = "Stop"

Write-Host "Udyam MSME production preflight"
Write-Host "--------------------------------"

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { throw "Python is not installed or not on PATH." }

$pythonVersion = python --version
Write-Host "Python: $pythonVersion"

$version = python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
$parts = $version.Split(".")
if ([int]$parts[0] -lt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -lt 10)) {
    throw "Python 3.10+ is required."
}

$curl = Get-Command curl.exe -ErrorAction SilentlyContinue
if (-not $curl) { throw "curl.exe is not available on PATH." }
Write-Host "curl: OK"

if (-not (Test-Path ".env")) {
    Write-Warning ".env is missing. Create it from .env.example before production execution."
} else {
    $envContent = Get-Content ".env" -Raw
    if ($envContent -notmatch "(?m)^UDYAM_API_KEY=.+") {
        throw "UDYAM_API_KEY is missing from .env."
    }
    Write-Host ".env: API key entry found"
}

foreach ($directory in @("output", "checkpoints", "logs")) {
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    Write-Host "$directory`: ready"
}

python -m py_compile config.py udyam_extractor.py run_udyam.py
Write-Host "Python compile: PASS"

Write-Host "Preflight checks passed."
