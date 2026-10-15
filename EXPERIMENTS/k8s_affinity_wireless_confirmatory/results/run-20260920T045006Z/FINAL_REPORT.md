# Live Kubernetes Confirmatory Experiment Report

Run: `run-20260920T045006Z`

## Evidence boundary
Live Kubernetes on a dedicated three-worker Kind cluster with a deterministic in-cluster shared-medium emulator implementing the frozen directed-goodput and conflict-budget semantics. This is not physical 60-GHz/RF measurement.

## Primary hypothesis
B+ Exact achieves a higher scheduled-request completion fraction than Affinity-Bytes at the Current-calibrated 1.25 contention target.

Paired held-out graphs: **30**
Mean B+ − Affinity completion-fraction difference: **-0.0110926**
Bootstrap 95% CI: **[-0.030787, 0.000783663]**
One-sided Wilcoxon p: **0.863339**
Primary hypothesis supported: **False**

## Planned-feasibility mechanism
B+-only feasible graphs: **9**
Affinity-only feasible graphs: **0**
One-sided exact discordance p: **0.00195312**

## Summary

|   target | method         |   n |   mean_completion_fraction |   mean_attempt_fraction |   median_p95_ms |   mean_offered_util |   mean_successful_util |   mean_cross_rack_bytes |   mean_medium_requests |   mean_medium_errors |   mean_medium_modeled_airtime_s |   planned_feasible_rate |   abstention_rate |   mean_moves |
|---------:|:---------------|----:|---------------------------:|------------------------:|----------------:|--------------------:|-----------------------:|------------------------:|-----------------------:|---------------------:|--------------------------------:|------------------------:|------------------:|-------------:|
|     0.5  | Affinity-Bytes |   5 |                   1        |                1        |         62.098  |            0.266365 |               0.266365 |             1.66003e+07 |                518.8   |                    0 |                         2.66365 |                1        |         0         |      2       |
|     0.5  | BPlus-Exact    |   5 |                   1        |                1        |         69.1424 |            0.371755 |               0.371755 |             2.42705e+07 |                577.4   |                    0 |                         3.71755 |                1        |         0         |      1.6     |
|     0.5  | Current        |   5 |                   1        |                1        |        102.019  |            0.502586 |               0.502586 |             3.22302e+07 |                829     |                    0 |                         5.02586 |                1        |         0         |      0       |
|     1.25 | Affinity-Bytes |  30 |                   0.997747 |                0.997747 |        157.311  |            0.649853 |               0.649853 |             1.82388e+07 |                501.767 |                    0 |                         6.49853 |                0.633333 |         0         |      2       |
|     1.25 | BPlus-Exact    |  30 |                   0.986655 |                0.986655 |        171.735  |            0.722067 |               0.722067 |             2.13168e+07 |                540.133 |                    0 |                         7.22067 |                0.933333 |         0.0666667 |      2.03333 |
|     1.25 | Current        |  30 |                   0.834447 |                0.834447 |        683.916  |            1.00782  |               1.00782  |             2.86888e+07 |                695.8   |                    0 |                        10.0782  |                0        |         0         |      0       |

## Interpretation boundary
A favorable result supports value beyond byte affinity under the emulated wireless-capacity/conflict model. It does not establish physical RF interference reduction or universal superiority.