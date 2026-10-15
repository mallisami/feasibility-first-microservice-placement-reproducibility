# R5 rerun/repair selection audit

This audit reconstructs the publication selection rule from the frozen original R5 index and the deterministic effective-R5 output. It creates no new ns-3 observations.

- Original cells: **63** (45 complete, 18 failed).
- Append-only replacements: **18**, mapped one-for-one to the same predeclared scenario/seed identities.
- Final effective matrix: **63/63**.
- Unaffected original-only scenarios: **15** / 21 (**45** cells).

## Selection rule

For each predeclared scenario/seed, use the original run if complete; otherwise use an append-only successful retry/repair mapped to the same scenario and seed. Original failures remain retained. Repair acceptance is based on successful execution and expected output structure/positive communication streams, not on achieving a favorable throughput magnitude.

## Inference boundary

Unrepaired original cells independently cover LoS/distance, partial/full blockage and recovery, beam training/refinement, multi-service-period scheduling, dense interference, and spatial sharing. The service-period-duration quantitative trend, traffic-allocation scenarios, and four-link spatial-sharing cell rely on repaired executions and must be labeled accordingly.

The repair families and acceptance gates are documented in `r5_rerun_audit_cells.csv`; original failure records remain in the primary raw archive.
