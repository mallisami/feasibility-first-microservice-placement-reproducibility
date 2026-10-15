$ErrorActionPreference = "Stop"
$root = (Resolve-Path $PSScriptRoot).Path
Write-Host "Running confirmatory campaigns SEQUENTIALLY. Do not run the Kubernetes and ns-3 campaigns concurrently on the same host."
& powershell -ExecutionPolicy Bypass -File (Join-Path $root "RUN_CONFIRMATORY.ps1")
if ($LASTEXITCODE -ne 0) { throw "Kubernetes confirmatory campaign failed." }
& powershell -ExecutionPolicy Bypass -File (Join-Path $root "RUN_NS3_CONFIRMATORY.ps1")
if ($LASTEXITCODE -ne 0) { throw "ns-3/WiGig packet-level confirmatory campaign failed." }
Write-Host "Both confirmatory campaigns completed. Review each experiment's PRIMARY_RESULT.json and FINAL_REPORT.md."
