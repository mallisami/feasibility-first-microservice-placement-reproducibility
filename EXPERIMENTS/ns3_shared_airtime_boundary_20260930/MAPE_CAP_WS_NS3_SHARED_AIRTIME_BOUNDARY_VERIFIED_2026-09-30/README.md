# MAPE-CAP-WS: ns-3 shared-airtime boundary validation

A frozen, model-aligned packet-level construct-validation extension. It reuses the pinned WiGig simulator and placement-derived traffic shapes from the existing reproducibility package.

The experiment has two stages:

1. calibrate the six DenseScenario stream positions independently under a full DTI;
2. expose one common CBAP equal to 25% of DTI and sweep normalized aggregate airtime utilization across 0.8, 1.0, and 1.2.

The simulator never receives a planner feasible/infeasible label. See the frozen protocol for the exact evidence boundary and analysis.

## Run

On Windows, open PowerShell in the package folder and execute:

```powershell
powershell -ExecutionPolicy Bypass -File .\RUN_SHARED_AIRTIME_BOUNDARY.ps1
```

The command is resumable. It performs all pre-execution gates, 18 solo calibration cells, 108 randomized science cells, and the frozen analysis. No pip packages are required by the runner.

## Main outputs

After successful completion, inspect `results/<run-id>/FINAL_REPORT.md`, `SUMMARY.json`, `shape_level_results.csv`, `science_cells.csv`, and `calibration_summary.csv`.

Do not edit the frozen protocol after inspecting scientific outcomes.

## Exact model alignment

The frozen planner `conflict-dense` state places all six directed rack-pair links in one `cg-shared` group with a 15 s budget over a 60 s planner window. Thus the experiment's shared DTI fraction is not post-hoc: `15/60 = 0.25`. See `canonical_inputs/model/MODEL_ALIGNMENT.json`.

Traffic begins at a fixed 2.0 s simulation time only if all six stations have remained associated for at least 250 ms and the shared resource has been configured. This avoids direct calls to protected ns-3 application lifecycle methods and keeps later deassociation in the measured service outcome.
