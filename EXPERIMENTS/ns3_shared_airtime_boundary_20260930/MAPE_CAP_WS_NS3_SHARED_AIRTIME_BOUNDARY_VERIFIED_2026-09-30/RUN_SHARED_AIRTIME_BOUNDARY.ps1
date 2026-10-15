$ErrorActionPreference = "Stop"
$root = (Resolve-Path $PSScriptRoot).Path
Write-Host "Starting frozen ns-3/WiGig shared-airtime boundary validation through WSL..."
$wslPath = (& wsl.exe wslpath -a -u $root).Trim()
if (-not $wslPath) { throw "Could not translate package path into WSL." }
& wsl.exe bash -lc "cd '$wslPath' && bash ./RUN_SHARED_AIRTIME_BOUNDARY_WSL.sh"
if ($LASTEXITCODE -ne 0) { throw "Boundary-validation runner failed with exit code $LASTEXITCODE. See operator_logs and results inside the package." }
