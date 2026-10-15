# Live Kubernetes Confirmatory Experiment Report

Run: `run-20260916T051604Z`

## Evidence boundary
Live Kubernetes on a dedicated three-worker Kind cluster with a deterministic in-cluster shared-medium emulator implementing the frozen directed-goodput and conflict-budget semantics. This is not physical 60-GHz/RF measurement.

## Primary hypothesis
B+ Exact achieves a higher scheduled-request completion fraction than Affinity-Bytes at the Current-calibrated 1.25 contention target.

Paired held-out graphs: **30**
Mean B+ − Affinity completion-fraction difference: **-0.0061591**
Bootstrap 95% CI: **[-0.0166731, 0.00121948]**
One-sided Wilcoxon p: **0.887542**
Primary hypothesis supported: **False**

## Planned-feasibility mechanism
B+-only feasible graphs: **9**
Affinity-only feasible graphs: **0**
One-sided exact discordance p: **0.00195312**

## Summary

|   target | method         |   n |   mean_completion_fraction |   mean_attempt_fraction |   median_p95_ms |   mean_offered_util |   mean_successful_util |   mean_cross_rack_bytes |   mean_medium_requests |   mean_medium_errors |   mean_medium_modeled_airtime_s |   planned_feasible_rate |   abstention_rate |   mean_moves |
|---------:|:---------------|----:|---------------------------:|------------------------:|----------------:|--------------------:|-----------------------:|------------------------:|-----------------------:|---------------------:|--------------------------------:|------------------------:|------------------:|-------------:|
|     0.5  | Affinity-Bytes |   5 |                   0.997951 |                0.997951 |         66.1041 |            0.265775 |               0.265775 |             1.65651e+07 |                517.4   |                    0 |                         2.65775 |                1        |         0         |          2   |
|     0.5  | BPlus-Exact    |   5 |                   0.995579 |                0.995579 |         99.0555 |            0.369417 |               0.369417 |             2.41381e+07 |                574.8   |                    0 |                         3.69417 |                1        |         0         |          1.6 |
|     0.5  | Current        |   5 |                   0.998504 |                0.998504 |        118.373  |            0.501664 |               0.501664 |             3.21772e+07 |                827.6   |                    0 |                         5.01664 |                1        |         0         |          0   |
|     1.25 | Affinity-Bytes |  30 |                   0.997445 |                0.997445 |        170.121  |            0.649579 |               0.649579 |             1.82316e+07 |                501.433 |                    0 |                         6.49579 |                0.633333 |         0         |          2   |
|     1.25 | BPlus-Exact    |  30 |                   0.991286 |                0.991286 |        181.58   |            0.722704 |               0.722704 |             2.13442e+07 |                541.267 |                    0 |                         7.22704 |                0.933333 |         0.0666667 |          1.7 |
|     1.25 | Current        |  30 |                   0.828204 |                0.828204 |        686.337  |            0.999073 |               0.999073 |             2.84281e+07 |                689.5   |                    0 |                         9.99073 |                0        |         0         |          0   |

## Interpretation boundary
A favorable result supports value beyond byte affinity under the emulated wireless-capacity/conflict model. It does not establish physical RF interference reduction or universal superiority.