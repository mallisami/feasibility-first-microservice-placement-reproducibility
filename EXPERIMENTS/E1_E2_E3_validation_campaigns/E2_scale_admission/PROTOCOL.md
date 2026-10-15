# Protocol: locality-induced inadmissibility on larger instances (E2)

**Status:** written before any science seed of this study was solved. Record the hash of this folder before running. Seeds 99001-99002 are smoke seeds used for timing only and are not science data.

## Question

The controlled study uses 6-8 replicas on three one-node racks. Does byte-affinity placement still leave the declared shared-airtime region, despite an admissible alternative, on larger instances with several nodes per rack? And does the violation still arise from concentrating traffic on one rack pair?

## Design

| Size | Replicas | Nodes per rack | Move budget | Science seeds |
|---|---|---|---|---|
| n12 | 12 | 2 | 3 | 61001-61050 |
| n16 | 16 | 2 | 4 | 62001-62050 |
| n24 | 24 | 3 | 3 | 63001-63050 |

- Same generator, state library (conflict dense, partial blockage, persistent degradation), relocation economics, objective weights, load calibration rule and tie-breaks as the 150-graph study. Three racks are retained because the state library defines three.
- Loads 1.00, 1.10, 1.25 and 1.50; 1.25 is primary.
- Every placement reachable from the incumbent within the move budget is enumerated, so Affinity-Bytes, Affinity-Bytes+Admission and MAPE-CAP-WS selections are exact within that neighborhood. The move budget is a quarter of the replicas for n12 and n16; for n24 it is 3 because exhaustive enumeration at 6 moves is not tractable. This is a stated limit of the study, not a tuning choice, and it is fixed before any science seed is solved.
- `run_scale.py gate` must reproduce the published counts (7, 12, 24, 35 avoidable violations at loads 1.00-1.50) with this enumerator before the science run starts.
- Exclusions: invalid incumbent or zero incumbent utilization only; reported, never replaced.

## Outcomes (descriptive; fixed in advance)

1. **Primary:** per size at load 1.25, the number of graphs on which Affinity-Bytes is inadmissible while an admissible placement exists, with a Wilson 95% interval. The study supports persistence at a size if this count is non-zero; a zero count is reported as the mechanism not appearing at that size and move budget.
2. Which state and group each violation overloads (two-direction rack-pair group versus the multi-pair conflict-dense group).
3. On violating graphs with a rack-pair group overloaded, the share of cross-rack bytes on that pair under Affinity-Bytes and under Affinity-Bytes+Admission.
4. Headroom difference and identical-placement count for MAPE-CAP-WS versus Affinity-Bytes+Admission.

No significance test is attached to outcome 1: admission-constrained methods satisfy the constraint by construction.

## Boundary

Generated graphs, three racks, planning-model feasibility only. No packet or application execution. Selections are exact within the move budget, not globally optimal.
