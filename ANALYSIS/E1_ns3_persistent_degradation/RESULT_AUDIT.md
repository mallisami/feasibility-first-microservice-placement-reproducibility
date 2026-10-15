# MAPE-CAP-WS E1 ns-3 persistent-degradation result audit

Run: `run-20261003T005802Z`
Protocol: `mape-cap-ws-ns3-pd-admission-v1.0`
Platform: 4-vCPU Ubuntu 24.04 LTS VM (Dockerized pinned IEEE 802.11ad/WiGig ns-3 simulator)

## Execution integrity
- 150 unselected controlled communication graphs evaluated.
- **627 primary unique rack-pair group cells** evaluated across 3 independent RNG seeds (1,881 primary group-cell runs), plus 60 boundary-sweep cells (12 traffic shapes × 5 utilization levels × 3 RNG seeds = 180 sweep runs), totaling **2,061 science simulations + 18 calibration runs** (2,079 total ns-3 runs).
- Zero protocol deviations recorded (`DEVIATIONS.md` states `No deviations.`).
- Exit code 0 (`RUN_ALL_EXIT_CODE.txt`).
- Full internal inventory verified (`POSTRUN_INVENTORY.txt`).

## Primary Hypothesis H1 (admission contrast over all graphs)
- Evaluated delivery fractions under persistent degradation:
  - Affinity-Bytes: 0.9780
  - Affinity-Bytes+Admission: 0.9994
  - MAPE-CAP-WS: 0.9992
- Admission contrast (Affinity-Bytes+Admission minus Affinity-Bytes):
  - Mean delivered fraction gain: **+0.02143** (95% graph-resampling bootstrap CI [+0.01209, +0.03207])
  - Graph-level delivery comparisons: higher on 24 graphs, lower on 0 graphs, tied on 126 graphs.
  - Statistical significance: one-sided Wilcoxon signed-rank test **p = 5.96e-08** (McNemar exact test **p = 1.53e-05**).
  - Graphs meeting the descriptive service threshold (delivered fraction >= 0.95):
    - Affinity-Bytes: 133 / 150 (88.7%)
    - Affinity-Bytes+Admission: 150 / 150 (100.0%)
    - MAPE-CAP-WS: 150 / 150 (100.0%)
    - Discordant pairs: 17 vs 0.
- **H1 status:** Supported under the frozen protocol decision rule (**True**).

## Hypothesis H2 (planner group utilization vs. packet-level delivery)
- 627 primary unique group cells evaluated:
  - Confusion matrix:
    - Predicted feasible and sustained (U <= 1.0, D >= 0.95): **602**
    - Predicted feasible, not sustained (U <= 1.0, D < 0.95): **1**
    - Predicted infeasible, but sustained (U > 1.0, D >= 0.95): **5**
    - Predicted infeasible and degraded (U > 1.0, D < 0.95): **19**
- Utilization breakdown:
  - U in (0, 0.5]: 401 cells, mean D = 0.9997, 1 below threshold
  - U in (0.5, 0.8]: 126 cells, mean D = 1.0000, 0 below threshold
  - U in (0.8, 0.9]: 39 cells, mean D = 0.9994, 0 below threshold
  - U in (0.9, 1.0]: 37 cells, mean D = 0.9967, 0 below threshold
  - U in (1.0, 1.1]: 12 cells, mean D = 0.9470, 7 below threshold
  - U in (1.1, 1.25]: 5 cells, mean D = 0.8260, 5 below threshold
  - U in (1.25, 9.0]: 7 cells, mean D = 0.7396, 7 below threshold

## Shared-airtime boundary sweep
- 12 two-direction traffic shapes evaluated at 50% airtime share (60 sweep cells × 3 RNG seeds = 180 simulations):
  - U = 0.8: mean D = 0.9997 (min 0.9966, 0 below threshold)
  - U = 0.9: mean D = 0.9999 (min 0.9983, 0 below threshold)
  - U = 1.0: mean D = 0.9852 (min 0.9622, 0 below threshold)
  - U = 1.1: mean D = 0.8962 (min 0.8709, 12 / 12 below threshold)
  - U = 1.2: mean D = 0.8270 (min 0.8097, 12 / 12 below threshold)

## Secondary ranking contrast
- Difference between MAPE-CAP-WS and Affinity-Bytes+Admission: -0.00016 (95% CI [-0.00064, +0.00036]).
- Supports the paper's mechanism decomposition: the primary operational benefit in the persistent-degradation state comes from hard admission under shared airtime, while risk-aware ranking provides no additional single-state packet-delivery advantage once admission is enforced.

## Scientific boundary
- Pinned construct validation in IEEE 802.11ad/WiGig ns-3 simulation. Each rack-pair group is modeled as a shared directional communication resource under persistent degradation. Does not constitute physical multi-rack RF deployment.
