$ErrorActionPreference = "Stop"
$root = (Resolve-Path $PSScriptRoot).Path
$runner = Join-Path $root "EXPERIMENTS\k8s_affinity_wireless_confirmatory\RUN_CONFIRMATORY.ps1"
if (-not (Test-Path $runner)) { throw "Confirmatory runner not found: $runner" }
& powershell -ExecutionPolicy Bypass -File $runner
if ($LASTEXITCODE -ne 0) { throw "Confirmatory runner failed with exit code $LASTEXITCODE." }
