# Third-party provenance

## DeathStarBench
A minimal exact subset required for R7 is vendored under `CODE/kubernetes/deathstarbench/` from commit:

`6ecb09706140f8730b5385c08f1386c654c3c526`

The full Git checkout supplied in the recovery material is not shipped because it duplicated source/history and was not needed by the runner after the exact required files were exported.

## ns-3/WiGig
The supplied working source required by the R5 Docker build is retained under `CODE/kubernetes/simulator/wigig-module/`. Duplicate Git-object provenance was removed from the reviewer-facing package.
