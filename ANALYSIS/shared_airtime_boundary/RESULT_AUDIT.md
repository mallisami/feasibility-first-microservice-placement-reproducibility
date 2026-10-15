# MAPE-CAP-WS shared-airtime ns-3 result audit

Run: `run-20260930T163137Z`
Protocol: `mape-cap-ws-ns3-shared-airtime-boundary-v1.1`

## Execution integrity
- 18/18 calibration cells accepted.
- 108/108 science cells accepted.
- All 126 cells were accepted on attempt 1.
- SHA-256 manifest verification passed for the run archive contents.
- Every science cell reports six associated stations and `traffic_started=1` before measurement.
- Science cells use duty fraction 0.25; calibration cells use full DTI (1.0).
- Science association lead before traffic: 1.893935684 to 1.995870197 s, above the frozen 0.25 s guard.
- No fatal/error/assert/abort/failure strings were found in accepted-cell simulator logs.
- Re-running the released analysis code on the accepted cell JSON files reproduced `SUMMARY.json`, `science_cells.csv`, and `shape_level_results.csv` byte-for-byte.

## Primary preregistered result
Mean shape-level aggregate delivered fraction:
- U=0.8: 0.943939 (bootstrap 95% CI 0.898714 to 0.982026)
- U=1.0: 0.885492 (bootstrap 95% CI 0.812700 to 0.952845)
- U=1.2: 0.751413 (bootstrap 95% CI 0.694886 to 0.803339)

Primary paired contrast, U=1.2 minus U=0.8:
- mean difference: -0.192527
- median difference: -0.175738
- bootstrap 95% CI: -0.215877 to -0.173116
- 12/12 traffic shapes have lower delivery at U=1.2 than at U=0.8.

Mean aggregate achieved throughput plateaus as load rises:
- U=0.8: 408.07 Mb/s achieved for 432.30 Mb/s offered
- U=1.0: 478.51 Mb/s achieved for 540.38 Mb/s offered
- U=1.2: 487.26 Mb/s achieved for 648.46 Mb/s offered

## Important calibration qualification
The frozen descriptive threshold D >= 0.95 yields TP=14, FP=10, FN=0, TN=12 when U<=1 is treated as planner-feasible and U>1 as planner-infeasible. Thus all 12 U=1.2 shape-level cases are below 0.95, but 10 of the 24 U<=1 shape-level cases also fall below 0.95.

The mismatch is strongly traffic-shape/concurrency dependent:
- 2 active streams: mean D = 0.999995 / 0.986334 / 0.828142 at U=0.8 / 1.0 / 1.2
- 5 active streams: mean D = 0.903620 / 0.781744 / 0.675561
- 6 active streams: mean D = 0.808223 / 0.688165 / 0.596640

Therefore the experiment supports the aggregate shared-airtime construct and independent packet-level saturation/degradation as utilization increases, but it does not establish U=1 as a universally sufficient packet-feasibility threshold. MAC contention and traffic-shape effects create service loss below the nominal boundary for denser simultaneous traffic.

## Claim boundary recommended for the paper
Defensible: independent packet-level construct validation shows that increasing normalized aggregate load on the shared WiGig resource produces consistent service degradation, with all evaluated U=1.2 traffic shapes worse than their matched U=0.8 cases.

Do not claim: perfect feasibility classification at U=1, physical 60-GHz rack-level validation, or deployment-independent calibration of the planner airtime budget.

## Reviewer-risk effect
This materially strengthens G1 because the packet simulator does not consume the planner feasibility outcome and the preregistered primary contrast is strongly in the expected direction. Residual risk remains around exact calibration and physical external validity. The observed concurrency dependence should be disclosed rather than hidden; it reinforces treating conflict-group budgets/goodputs as effective deployment-specific parameters rather than universal physical constants.
