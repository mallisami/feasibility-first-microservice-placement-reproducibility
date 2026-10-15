# START HERE — MAPE-CAP-WS ns-3 shared-airtime boundary validation

This package runs one focused experiment designed to strengthen the paper's physical/model-validity boundary **without physical 60-GHz hardware**.

## What it tests

It tests whether aggregate airtime demand predicts packet-level degradation in a pinned IEEE 802.11ad/WiGig simulation when six placement-derived traffic aggregates share only 25% of the DTI. ns-3 is not told whether a planner considered a case feasible.

## One command on Windows

Open PowerShell in this folder and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\RUN_SHARED_AIRTIME_BOUNDARY.ps1
```

Docker Desktop with WSL integration must be running. The first execution may need Internet access to build the pinned `ns3-wigig:v0.5` image. Before any science cell runs, the command performs a simulator smoke test and a full-DTI-versus-25%-DTI duty-effect gate. If either fails, execution stops.

## Before running

Read `protocol/SHARED_AIRTIME_BOUNDARY_PROTOCOL_FROZEN.md`. Do not change scientific parameters after looking at results.

## Output

The active run is written under `results/<run-id>/`. On completion, use:

- `FINAL_REPORT.md`
- `SUMMARY.json`
- `shape_level_results.csv`
- `science_cells.csv`
- `calibration_summary.csv`

If interrupted, rerun the same command; accepted cells are reused.

**Model alignment:** the frozen `conflict-dense` planner state uses one `cg-shared` group with a 15 s budget in a 60 s window, giving the experiment's 25% shared-resource fraction exactly (15/60).

**Traffic-start guard:** offered traffic begins at a frozen simulation time of 2.0 s only if all six STAs have been associated for at least 250 ms and the shared resource has already been configured. Later deassociation remains part of the measured delivery outcome.
