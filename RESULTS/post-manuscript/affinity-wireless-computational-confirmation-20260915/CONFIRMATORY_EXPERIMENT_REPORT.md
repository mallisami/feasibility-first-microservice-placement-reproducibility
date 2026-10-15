# Prospectively Frozen Computational Confirmation Report

Date: 2026-09-15

## Status
The pre-specified controlled computational confirmation **supports the primary hypothesis**. This is independent generated-graph evidence using the frozen wireless-state library; it is not a live Kubernetes/ns-3/physical-RF confirmation.

The protocol and runner were SHA-256 frozen before outcome generation. The first execution stopped on the first instance because generated rack labels (`rack-0/1/2`) did not match frozen trace labels (`rack-a/b/c`). No result table had been produced. Only deterministic rack relabeling was corrected, documented, and re-hashed before the successful run. Hypothesis, seed blocks, methods, targets, endpoints, and statistics were unchanged.

## Pre-specified primary hypothesis
At a common congestion event where the pre-existing Current placement is calibrated to **125%** of its worst robust conflict-group airtime budget, B+ Exact will preserve wireless-feasible placement more often than the primary **Affinity-Bytes** comparator on previously unseen communication graphs.

## Design
- 150 previously unseen generated communication/resource instances.
- 50 each with 6, 7, and 8 replicas.
- Fixed seed blocks: 11001–11050, 22001–22050, 33001–33050.
- Generated wireless states and synthetic relocation costs were discarded.
- Frozen package states used: `conflict-dense`, `partial-blockage`, `persistent-degradation`.
- Frozen relocation coefficient: 4062 cost units (4.062 s pilot mean).
- Methods: Current, Affinity-Frequency, Affinity-Bytes, BPlus-Exact.
- Payload bits only were scaled so Current reached target robust worst-conflict utilization of 0.50, 0.90, 1.00, 1.10, 1.25, or 1.50. Request counts were held fixed.
- BPlus-Exact and affinity placements were chosen exhaustively over cluster-feasible placements within the same relocation cap.
- No instances were excluded.

## Primary result
At the pre-specified 1.25 target:

| Method | Feasible instances | Feasibility rate |
|---|---:|---:|
| BPlus-Exact | 150 / 150 | 100.0% |
| Affinity-Bytes | 126 / 150 | 84.0% |

Paired discordance:
- B+-only feasible: **24**
- Affinity-only feasible: **0**
- one-sided exact paired p = **5.96 × 10^-8**
- paired feasibility risk difference = **+16.0 percentage points**
- fixed-seed 100,000-resample paired bootstrap 95% CI = **+10.7 to +22.0 percentage points**

Therefore the pre-specified H1 is supported for this controlled computational evidence class.

## Replication across graph sizes
At the same primary target:

| Replicas | B+ feasible | Affinity-Bytes feasible | Difference | B+-only / Affinity-only |
|---:|---:|---:|---:|---:|
| 6 | 100% | 82% | +18 pp | 9 / 0 |
| 7 | 100% | 84% | +16 pp | 8 / 0 |
| 8 | 100% | 86% | +14 pp | 7 / 0 |

The direction therefore replicated across all three pre-specified graph-size strata rather than being driven by one size.

## Load-response result
Using the stronger Affinity-Bytes baseline:

| Current-calibrated target | B+ feasible | Affinity-Bytes feasible |
|---:|---:|---:|
| 0.50 | 100.0% | 100.0% |
| 0.90 | 100.0% | 99.3% |
| 1.00 | 100.0% | 95.3% |
| 1.10 | 100.0% | 92.0% |
| **1.25** | **100.0%** | **84.0%** |
| 1.50 | 95.3% | 72.0% |

The low-load specificity check passed: both methods were feasible on all 150 instances at 50% Current utilization. Separation grows as the pre-existing placement enters congestion.

## Mechanism: what was and was not confirmed
The primary **feasibility** mechanism was confirmed, but a stronger claim that B+ generally minimizes airtime utilization was **not** confirmed.

At the 1.00 target, among pairs where both methods are feasible, Affinity-Bytes generally has lower cross-rack bytes and lower worst conflict utilization. This is expected because it explicitly minimizes cross-rack traffic, while B+ optimizes delay risk and relocation economics subject to airtime as a hard feasibility constraint rather than minimizing airtime itself.

The scientifically important evidence is in the 24 primary discordant instances where Affinity-Bytes becomes infeasible but B+ remains feasible:
- Affinity-Bytes mean worst conflict utilization: **1.164** (116.4% of budget)
- B+ mean worst conflict utilization: **0.833** (83.3% of budget)
- mean reduction in worst utilization: **33.1 percentage points**
- B+ uses **26.6% more cross-rack bytes on average** (22.6% median increase)
- B+ uses at least as many cross-rack bytes as affinity in **24/24** discordant cases.

This is the key controlled mechanism result: **less cross-rack communication volume does not guarantee wireless feasibility**. A placement can send fewer bytes yet overload a low-goodput/shared-conflict path. B+ can accept more cross-rack traffic while mapping it onto a wireless-feasible set of paths.

## Correct scientific claim
The experiment supports:

> Under controlled, previously unseen communication graphs and frozen simulation-backed wireless states, explicit wireless-state/conflict-aware placement preserves robust airtime feasibility more often than byte-affinity placement during calibrated congestion events. In the discordant cases, B+ does so despite using more cross-rack communication, demonstrating that communication volume alone is insufficient to characterize wireless contention exposure.

It does **not** support:
- “B+ always reduces congestion.”
- “B+ minimizes airtime utilization.”
- “B+ reduces physical RF interference.”
- “B+ improves application latency/throughput.”
- “The tested saturation levels are measured production operating points.”

## Publication implication
This substantially strengthens the wireless-contention story, but it should be presented as controlled mechanism evidence unless independently repeated in a live or packet-level campaign. The strongest paper positioning is not generic congestion reduction; it is **value beyond communication affinity under heterogeneous wireless path capacity/conflict constraints**.

A decisive journal-level external validation would next run Current vs Affinity-Bytes vs B+ with the same pre-frozen endpoint definitions on an independent Kubernetes/ns-3 or physical testbed, retaining application metrics as downstream safety outcomes.
