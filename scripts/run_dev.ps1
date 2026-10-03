# scripts/run_dev.ps1
# Development launcher. Uses the local virtualenv if present.

$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $ProjectRoot

if (Test-Path ".\.venv\Scripts\python.exe") {
    $Py = ".\.venv\Scripts\python.exe"
} else {
    $Py = "python"
}

Write-Host "Using: $Py" -ForegroundColor Cyan
& $Py -m app.main