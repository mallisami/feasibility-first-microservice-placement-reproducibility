# Environments

## Offline (N2/N3/N3b, T4, all analyses)
WSL2 Ubuntu 24.04 on Windows 11. Python 3.12.3 with numpy 2.3.5, scipy 1.17.0 (HiGHS) and pandas 2.2.3. PYTHONHASHSEED=0.

## Azure VM (N5, N4)
- **Hardware and OS:**
  - Standard_D4as_v5 (4 vCPU AMD EPYC 7763, 16 GiB), East Asia zone 1.
  - Ubuntu 24.04.4 LTS, kernel 6.17.0-1022-azure.
- **Container tooling:**
  - Docker 29.1.3, Kind v0.33.0, kubectl v1.37.0.
  - N5 cluster `rev-n5`: 1 control plane and 3 workers, kindest/node v1.33.1, allocatable 4 CPU / ~15.6 GiB per node.
  - Benchmark image `mape-cap-confirm-bench:rev-n5`: image ID sha256:29a59c70e77b…, identical to the original `mape-cap-confirm-bench:2026-09-15`.
- **Python venv:** numpy 2.3.5, scipy 1.17.0, pandas 2.2.3 (full `pip freeze` in `vm_run/ENVIRONMENT_RECORD.txt`).
- **Run timeline:** N5 00:56–03:30 UTC, then N4 03:30–05:31 UTC, run strictly sequentially on 2026-09-26.
- **Host load:** three older idle Kind clusters were present. The 1-min load average around N5 cells was mean 1.5, max 3.9.
