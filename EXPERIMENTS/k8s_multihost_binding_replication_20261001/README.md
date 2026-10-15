# MAPE-CAP-WS three-VM Kubernetes validation package

This package performs a targeted multi-host replication of the original N5 S1 binding-state study.

## What it tests

Whether the original application-level admission/ranking comparison persists when rack-a, rack-b and rack-c are Kubernetes nodes on three distinct VM/machine instances rather than Kind worker containers sharing one VM.

## Frozen source

Derived from `MAPE-CAP-WS_reproducibility_package_2026-09-26.zip`.

Source-package SHA-256:

`a116c491e6650716272acc4637c6ed4bf6448a426d35cd6cb6e2e9dbf9c3aa0a`

The package retains the original N5 enrollment snapshot, N5 protocol, primary/summary CSVs, frozen benchmark code, scenario library and planner implementation needed to reconstruct all 20 S1 cases.

## Design

- 3 Kubernetes/VM hosts: rack-a server, rack-b agent, rack-c agent.
- k3s/kubelet v1.33.1+k3s1 / upstream Kubernetes v1.33.1 on x86-64 Linux.
- All 20 original N5 S1 seeds.
- 3 methods: Affinity-Bytes, Affinity-Bytes+Admission, MAPE-CAP-WS.
- Original N5 method-order and bootstrap seed: 20260926.
- 40 s measured science cell.
- 60 science cells total.
- 2-seed × 3-method engineering pilot, excluded from analysis.
- Same frozen traffic, wireless states, shared-medium emulator and N5 endpoints.
- Original planner capacities and placements are replayed; small VMs do not redefine the planning problem.
- Benchmark Kubernetes reservations are 100 mCPU / 128 MiB per service for this execution-only follow-up.

## Execution

Read `00_START_HERE.md` first. After the k3s cluster and benchmark image are prepared, run from rack-a/server:

`bash RUN_MULTIHOST_VALIDATION.sh`

The final result archive is written under `results/run-*.zip`.

## Evidence boundary

This is multi-host Kubernetes evidence. It does not establish physical 60-GHz RF validity and does not imply that the Azure VMs reside on separate underlying physical servers.
