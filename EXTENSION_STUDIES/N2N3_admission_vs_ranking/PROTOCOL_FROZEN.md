# N2/N3 — Admission versus ranking on the AFF-C graph set

**Freeze:** 2026-09-26, before any N2/N3 outcome is computed.
**Evidence class:** prospectively frozen controlled computation (offline). Not a live or RF experiment.
**Parent:** AFF-C (`RESULTS/post-manuscript/affinity-wireless-computational-confirmation-20260915/`),
whose instances, state library, relocation economics, load calibration and exhaustive selection
are reused unchanged. AFF-C outcomes were known when this protocol was written; N2/N3 add new
comparators and new (held-out) endpoints only.

## Questions
- **N2.** Once the scheduler enforces the same admission constraints (directed availability and
  aggregate conflict-group airtime), does the risk-aware ranking of MAPE-CAP-WS change the
  selected placement relative to admission-constrained byte affinity, and how (cross-rack bytes,
  airtime headroom, modeled delay exposure)?
- **N3.** Do placements selected on the three declared planning states remain admissible on
  library states withheld from planning, and does the ranking rule change that?

## Instances (unchanged from AFF-C)
150 graphs: 6 replicas seeds 11001–11050, 7 replicas 22001–22050, 8 replicas 33001–33050;
`generate_problem(rack_count=3, nodes_per_rack=1, scenario_count=3, decision_window_seconds=60)`;
relocation cost 4062 units / 4.062 s / uncertainty 690 per replica; generator relocation cap.
Exclusion rules as AFF-C (AFF-C excluded none).

## States
- Planning set Ω_plan (as AFF-C): conflict-dense, partial-blockage, persistent-degradation,
  weights normalized within the set, from `ns3_simulation_backed_traces.csv`.
- Held-out set Ω_ho: nominal-los, asymmetric-los, outage-with-fallback, recovery, mixed-regime
  (same CSV). Never visible to any method.

## Load
Payload (bits_per_window only) scaled so Current's worst planning-set utilization equals the
target. Primary grid (AFF-C): {0.50, 0.90, 1.00, 1.10, 1.25, 1.50}. Secondary fine grid for the
regime figure: 0.50 to 2.00 in steps of 0.05. The same scaled instance is shown to every method
and the same scale is applied when evaluating held-out states.

## Methods (all exhaustive over the AFF-C cluster-feasible placement set)
1. **Current** — keep placement.
2. **Affinity-Bytes** — min cross-rack bits; no wireless information (AFF-C comparator).
3. **Affinity-Bytes+Admission** — min cross-rack bits subject to availability and conflict-group
   airtime on every planning state. Ties: fewer moves, then lexicographic.
4. **MAPE-CAP-WS Risk-off** — MAPE-CAP-WS objective with CVaR weight 0 (expected delay +
   relocation + threshold slack) under the same admission constraints.
5. **MAPE-CAP-WS** — full objective, q = 0.8, λ = 1.5, μ = 1.0, ξ = 1000 (AFF-C setting).
If no admissible placement exists, methods 3–5 return "no admissible placement" (counted as
infeasible; not replaced by a fallback).

## Endpoints (per graph × target × method)
- planning-set admissibility; worst planning-set utilization U_max; headroom 1 − U_max;
- cross-rack bytes; moves; modeled expected delay and CVaR_0.8 (common evaluator, planning set);
- **held-out admissibility**: availability and airtime satisfied on all five Ω_ho states;
  per-state admissibility; worst held-out utilization.

## Primary analyses (two-sided; no direction pre-committed)
- **N2-P:** at target 1.25, paired graph-level difference MAPE-CAP-WS − Affinity+Admission in
  (a) headroom and (b) cross-rack bytes; Wilcoxon signed-rank, paired bootstrap 95% CI
  (100,000 resamples, seed 20260926). Also: fraction of graphs with identical placements.
- **N3-P:** at target 1.25, held-out admissibility MAPE-CAP-WS vs Affinity+Admission; exact
  two-sided McNemar on discordant graphs; paired bootstrap CI of the risk difference.
- Holm correction across the three primary tests (N2-P a, b; N3-P).

## Secondary
All other targets and methods; Risk-off vs full (isolates the CVaR term); per-state held-out
breakdown; size strata (6/7/8 replicas); the fine-grid regime curve, including the count of
graphs where Current is admissible but Affinity-Bytes is not ("locality-induced inadmissibility").

## Interpretation rules
- Planning-set admissibility of methods 3–5 is equal by construction; it is a correctness check,
  not a finding.
- A null N2/N3 result is reported as such and supports demoting risk-aware ranking to an optional
  layer; a favorable result supports it only for the declared, engineered state library.
- No physical-RF, application-level or production claim follows from N2/N3.

## Reproducibility
Script: `run_n2n3.py` (this directory). Outputs: `cell_results.csv`, `heldout_by_state.csv`,
`fine_grid.csv`, `primary_tests.json`, `provenance.json`, `SHA256SUMS.txt`.
