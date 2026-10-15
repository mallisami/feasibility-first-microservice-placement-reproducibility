# Final report: packet-level execution of the persistent-degradation state

Protocol `mape-cap-ws-ns3-pd-admission-v1.0`; 150 unselected graphs; 627 unique group cells x 3 RNG runs.

## H1 (primary): admission contrast over all graphs
Mean delivered fraction: Affinity-Bytes 0.9780, Affinity-Bytes+Admission 0.9994, MAPE-CAP-WS 0.9992.
Admission minus affinity: **+0.02143** (95% graph-resampling interval [+0.01209, +0.03207]); higher on 24, lower on 0, tied on 126 graphs; one-sided Wilcoxon p = 5.96e-08.
H1 supported under the stated rule: **True**.
Graphs with delivered fraction >= 0.95: Affinity-Bytes 133/150, Affinity-Bytes+Admission 150/150, MAPE-CAP-WS 150/150; discordant pairs 17 vs 0.

## H2: planner group utilization versus packet-level delivery (unique group cells)
Confusion: {'predicted_ok_and_sustained': 602, 'predicted_ok_not_sustained': 1, 'predicted_violation_but_sustained': 5, 'predicted_violation_not_sustained': 19}.

| U range | cells | mean D | min D | D below threshold |
|---|---|---|---|---|
| (0, 0.5] | 401 | 0.9997 | 0.9007 | 1 |
| (0.5, 0.8] | 126 | 1.0 | 1.0 | 0 |
| (0.8, 0.9] | 39 | 0.9994 | 0.9851 | 0 |
| (0.9, 1.0] | 37 | 0.9967 | 0.952 | 0 |
| (1.0, 1.1] | 12 | 0.947 | 0.9058 | 7 |
| (1.1, 1.25] | 5 | 0.826 | 0.7861 | 5 |
| (1.25, 9] | 7 | 0.7396 | 0.6694 | 7 |

## Boundary sweep: 12 two-direction shapes at the 50% share

| U | shapes | mean D | min D | D below threshold |
|---|---|---|---|---|
| 0.8 | 12 | 0.9997 | 0.9966 | 0 |
| 0.9 | 12 | 0.9999 | 0.9983 | 0 |
| 1.0 | 12 | 0.9852 | 0.9622 | 0 |
| 1.1 | 12 | 0.8962 | 0.8709 | 12 |
| 1.2 | 12 | 0.8270 | 0.8097 | 12 |

## Secondary: ranking after admission
MAPE-CAP-WS minus Affinity-Bytes+Admission: -0.00016 (interval [-0.00064, +0.00036]).

## Evidence boundary
Packet-level construct evidence in a pinned IEEE 802.11ad/WiGig simulator. Each rack-pair group is simulated as its own shared resource, as the persistent-degradation state declares; interference between groups, physical RF behavior and the appropriateness of the 30-s budget for a real fabric are not tested.
