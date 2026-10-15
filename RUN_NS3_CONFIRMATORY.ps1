$ErrorActionPreference = "Stop"
$root = (Resolve-Path $PSScriptRoot).Path
$runner = Join-Path $root "EXPERIMENTS\ns3_affinity_wireless_confirmatory\RUN_NS3_CONFIRMATORY.ps1"
if (-not (Test-Path $runner)) { throw "ns-3 confirmatory runner not found: $runner" }
& powershell -ExecutionPolicy Bypass -File $runner
if ($LASTEXITCODE -ne 0) { throw "ns-3 confirmatory runner failed with exit code $LASTEXITCODE." }
