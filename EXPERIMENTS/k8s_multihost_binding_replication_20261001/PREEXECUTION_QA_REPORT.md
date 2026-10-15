# Pre-execution QA report — multi-host k3s validation v1.1

## Scope

This report verifies the corrected release package before transfer to the three target VMs. It does not claim that a real three-node k3s execution has occurred in the artifact-building environment.

## Defects found and corrected during independent re-audit

- Corrected the release SHA-256 manifest to standard `sha256sum -c` format; the previous release incorrectly inserted file sizes between the hash and path.
- Corrected the k3s version gate: nodes installed as `v1.33.1+k3s1` are now checked against that exact kubelet build while upstream Kubernetes remains v1.33.1.
- Added per-node SHA-256 host machine-ID probes so rack-a/rack-b/rack-c must be backed by three distinct Linux VM/OS instances; raw machine IDs are never retained.
- Excluded `.venv`, private node-token material, local cluster.env, caches and runtime directories from setup provenance hashing.
- Added endpoint sanity checks for positive duration and impossible success counts.
- Increased minimum agent allocatable memory from 512 MiB to 768 MiB to preserve headroom above the worst frozen four-pod placement (4 × 128 MiB requests).

## Passed static/scientific checks

- Frozen science matrix is exactly 20 original N5 S1 seeds × 3 methods = 60 cells.
- Source reproducibility archive SHA-256 was independently verified as `a116c491e6650716272acc4637c6ed4bf6448a426d35cd6cb6e2e9dbf9c3aa0a`.
- The retained N5 enrollment/primary/summary files, benchmark/emulator code, experiment config, affinity solver and `live_confirmatory.py`, plus the ns-3 calibration trace are byte-identical to the authoritative files in that source archive.
- All 20 source cases reconstruct with Current worst utilization exactly tau=1.25 (tolerance 1e-8).
- Affinity-Bytes is inadmissible in all 20 reconstructed cases.
- Affinity-Bytes+Admission and MAPE-CAP-WS are admissible in all 20 reconstructed cases.
- Every reconstructed executed-state identity equals the source N5 enrollment snapshot.
- Frozen placements use 2–3 VM hosts per cell; the three-rack cluster itself spans rack-a/rack-b/rack-c.
- Execution-only reservations remain 100 mCPU / 128 MiB and do not alter planner placements.
- No latency/completion result is used as an infrastructure acceptance gate.
- Python entry points compile; shell entry points pass `bash -n`; release tests pass.
- The original N5 method-order and bootstrap seed 20260926 are retained. The primary/co-primary analysis matches the frozen N5 procedure: paired graph-level contrasts, 100,000-resample bootstrap CI, two-sided Wilcoxon, Holm within endpoint family.

## Mandatory runtime gates on target VMs

Science cannot start unless exactly three Ready nodes exist; rack labels and InternalIPs are unique; rack-a is server; kubelet build is v1.33.1+k3s1; server has >=1.8 CPU/3000 MiB allocatable; each agent has >=0.9 CPU/1200 MiB allocatable; all nodes are linux/amd64; no node reports MemoryPressure/DiskPressure/PIDPressure; the benchmark image starts locally on all nodes; host machine-ID hashes are all distinct; wireless-medium is healthy; and the six-cell engineering pilot completes using infrastructure-only acceptance criteria.

## Environment limitation

The artifact-building environment does not contain the user's three Azure VMs. Therefore real Flannel/Azure VNet routing, NSG rules, k3s image import and actual distributed traffic remain runtime checks on those machines. The runner fails closed if those prerequisites do not hold.

## Scientific boundary

A successful run addresses the previous single-VM Kubernetes limitation. It remains effective-wireless application validation, not physical 60-GHz RF validation, and does not imply that Azure placed the VMs on distinct underlying physical servers.
