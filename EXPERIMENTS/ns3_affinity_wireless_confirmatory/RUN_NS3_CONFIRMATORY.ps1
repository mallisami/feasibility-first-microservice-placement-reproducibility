$ErrorActionPreference = "Stop"
$root = (Resolve-Path $PSScriptRoot).Path
Write-Host "Starting frozen ns-3/WiGig packet-level confirmatory experiment through WSL..."
$wslPath = (& wsl.exe wslpath -a -u $root).Trim()
if (-not $wslPath) { throw "Could not translate package path into WSL." }
& wsl.exe bash -lc "cd '$wslPath' && bash ./RUN_NS3_CONFIRMATORY_WSL.sh"
if ($LASTEXITCODE -ne 0) { throw "ns-3 confirmatory runner failed with exit code $LASTEXITCODE. See operator_logs inside the experiment directory." }
