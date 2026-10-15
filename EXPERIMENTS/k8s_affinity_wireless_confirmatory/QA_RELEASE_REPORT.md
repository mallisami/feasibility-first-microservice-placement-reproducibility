# Confirmatory Experiment Release QA Report

**Protocol:** `wireless-beyond-affinity-k8s-v1.1`  
**Repository role:** integrated into the MAPE-CAP B+ single-source-of-truth release  
**QA date:** 2026-09-15

## Status

**READY FOR EXTERNAL KUBERNETES EXECUTION, subject to target-machine Docker/WSL availability.**

The experiment contains no copied planner package, copied wireless-state table, superseded live protocol, amendment tree, nested prior release, or separate experiment-level SHA manifest. The repository root is the integrity authority.

## Canonical sources

- `implementation/code/mape_cap_bplus/` — authoritative B+ source imported directly at runtime.
- `RESULTS/calibration/external/ns3_simulation_backed_traces.csv` — authoritative wireless trace table.
- `RESULTS/post-manuscript/affinity-wireless-computational-confirmation-20260915/` — retained prospective computational mechanism confirmation.
- `EXPERIMENTS/k8s_affinity_wireless_confirmatory/protocol/LIVE_CONFIRMATORY_PROTOCOL_FROZEN.md` — the only authoritative live-confirmatory protocol.

## Pre-execution QA corrections incorporated into the single protocol

Before any live outcome, QA rejected the initial independent-pair `tc` approach because it could not impose the paper's single coupled `cg-shared` airtime budget. v1.1 uses one in-cluster shared-medium service. The same pre-execution freeze also records safe B+ abstention for proven-infeasible plans and uses scheduled offered requests as the primary denominator. These are incorporated directly into the canonical protocol rather than retained as competing amendment files.

## Automated checks expected before every run

The one-command launcher:

1. installs/checks pinned local Kind/kubectl and Python requirements;
2. verifies the entire SSOT SHA-256 manifest;
3. verifies experiment SSOT invariants and absence of duplicated/stale protocol/source copies;
4. runs the confirmatory pytest suite;
5. runs the scientific self-test;
6. reconstructs all 30 held-out planning instances;
7. performs Docker/Kubernetes preflight and cluster preparation;
8. executes/resumes the campaign;
9. regenerates analysis and validates the run-result manifest.

A live Kubernetes campaign cannot be executed in the ChatGPT container because Docker/Kind are unavailable there. External Docker Desktop, WSL networking, firewall, disk, image pull, or host resource failures therefore remain possible and are handled by explicit preflight/failure retention rather than silent protocol relaxation.
