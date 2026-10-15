# ns-3/WiGig Affinity-vs-Wireless Packet-Level Confirmation

Run: `run-20260920T043724Z`

Protocol: `wireless-beyond-affinity-ns3-v1.1`

## Evidence boundary
Packet-level IEEE 802.11ad/WiGig Q-D DenseScenario cross-check. Six directed rack-pair aggregates are mapped to six fixed STAs contending at one DMG AP. This is not physical hardware and is not claimed to reproduce a full three-rack RF geometry.

## Primary hypothesis
At the frozen 1.25 offered-load target, B+ Exact has a higher graph-level delivered offered-traffic fraction than Affinity-Bytes.

Paired graphs: **30**
Mean B+ - Affinity difference: **-0.0219116**
Bootstrap 95% CI: **[-0.0532438, 0.000120778]**
One-sided Wilcoxon p: **0.983531**
Primary hypothesis supported: **False**

## Summary

|   target | method         |   n_graphs |   mean_delivered_fraction |   median_delivered_fraction |   mean_achieved_mbps |   mean_configured_mbps |   mean_active_streams |
|---------:|:---------------|-----------:|--------------------------:|----------------------------:|---------------------:|-----------------------:|----------------------:|
|     0.5  | Affinity-Bytes |         30 |                  0.999194 |                    0.999989 |              464.73  |                465.161 |               3.3     |
|     0.5  | BPlus-Exact    |         30 |                  0.998562 |                    1        |              575.027 |                575.69  |               2.7     |
|     0.5  | Current        |         30 |                  0.998071 |                    0.999973 |              898.271 |                900     |               5.46667 |
|     1.25 | Affinity-Bytes |         30 |                  0.994022 |                    1        |             1153.34  |               1162.9   |               3.3     |
|     1.25 | BPlus-Exact    |         30 |                  0.97211  |                    0.99998  |             1370.2   |               1436.22  |               4.13333 |
|     1.25 | Current        |         30 |                  0.791566 |                    0.791766 |             1782.32  |               2250     |               5.46667 |

## Interpretation boundary
A favorable result supports packet-level contention robustness beyond byte affinity under this fixed dense WiGig mapping. It does not establish physical RF interference reduction, a hardware result, or universal superiority.
