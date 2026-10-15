# Kubernetes Affinity-vs-Wireless Confirmatory Experiment

This directory is the **only executable live-confirmatory implementation** in the MAPE-CAP B+ single-source-of-truth repository. It compares `Current`, `Affinity-Bytes`, and `BPlus-Exact` on 30 held-out six-replica graphs in a three-worker Kind cluster.

## Canonical dependencies — do not copy or edit locally

The experiment imports the repository's authoritative sources directly:

- planner/model code: `../../implementation/code/mape_cap_bplus/`
- wireless trace table: `../../RESULTS/calibration/external/ns3_simulation_backed_traces.csv`
- prior prospective computational confirmation: `../../RESULTS/followup_validation/affinity-wireless-computational-confirmation-20260915/`

There is intentionally **no duplicated `mape_cap_bplus` package, copied wireless-trace CSV, superseded protocol, amendment file, or nested previous ZIP** in this experiment directory.

The single authoritative live protocol is:

`protocol/LIVE_CONFIRMATORY_PROTOCOL_FROZEN.md`

## Evidence boundary

The experiment uses real Kubernetes Deployments and real relocation/redeployment, but the wireless medium is a deterministic in-cluster implementation of the manuscript's shared-airtime abstraction. It is **not** a physical 60-GHz radio, MAC-collision, SINR, beamforming, or RF-interference experiment.

## Recommended environment

- Windows 10/11 with WSL2
- Docker Desktop running with WSL integration enabled
- Python 3.11+ inside WSL
- at least 4 GiB free disk space
- Internet access on first run for pinned binaries/images

The bootstrap installs package-local Kind v0.28.0 and kubectl v1.33.1 if needed. The Kind node image is digest-pinned.

## One command

Open PowerShell **in this directory** and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\RUN_CONFIRMATORY.ps1
```

Or from WSL/Linux:

```bash
bash ./RUN_CONFIRMATORY_WSL.sh
```

The launcher verifies the entire repository manifest first, verifies this experiment's SSOT structure, runs automated tests and the 30-seed offline planning audit, performs Docker/Kubernetes preflight, runs a smoke-prepared cluster path, executes/resumes the frozen campaign, analyzes results, and verifies the result manifest.

## Resume behavior

`results/CURRENT_RUN.txt` points to the active campaign. Do not delete it after an interruption. Re-run the same command. Accepted infrastructure-valid cells are not rerun; failed attempts remain preserved and are bounded by the frozen retry rule.

## Frozen primary endpoint

At Current-calibrated target utilization 1.25:

`scheduled_completion_fraction = successful_requests / expected_scheduled_requests`

Primary paired comparison: `BPlus-Exact - Affinity-Bytes`, one-sided Wilcoxon plus fixed-seed 100,000-resample paired bootstrap CI.

## Expected runtime

Approximately 2–4 hours on a healthy desktop, depending on Docker/WSL resources and rollout speed.

## Results

After completion, inspect:

- `results/<run-id>/PRIMARY_RESULT.json`
- `results/<run-id>/FINAL_REPORT.md`
- `results/<run-id>/analysis_cells.csv`
- `results/<run-id>/summary.csv`
- `results/<run-id>/SHA256SUMS.txt`
- `operator_logs/`

Do not alter seeds, methods, target utilization, method-order seed, measurement duration, retry rules, primary endpoint, risk/relocation weights, wireless traces, or shared-medium semantics after observing outcomes. Infrastructure-only fixes must be documented before resuming.
