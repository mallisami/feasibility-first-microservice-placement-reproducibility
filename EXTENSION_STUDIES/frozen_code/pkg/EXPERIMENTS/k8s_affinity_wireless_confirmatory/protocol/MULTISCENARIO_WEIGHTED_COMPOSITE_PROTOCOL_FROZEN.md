# Frozen Multi-Scenario Weighted-Composite Secondary Protocol — v1.0

**Freeze date:** 2026-09-20
**Protocol ID:** `wireless-beyond-affinity-k8s-multiscenario-v1.0`
**Parent protocol:** `wireless-beyond-affinity-k8s-v1.1` (`LIVE_CONFIRMATORY_PROTOCOL_FROZEN.md`) — this document does not amend, replace, or retune the parent protocol. It defines a separate, additive secondary endpoint on the same held-out graphs.
**Evidence class:** Kubernetes-executed mechanism confirmation, exploratory/post-hoc relative to the pre-registered v1.1 primary endpoint.

## Motivation and status

The v1.1 primary endpoint (`scheduled_completion_fraction` under the single `conflict-dense` scenario) did not support H1-LIVE (paired mean difference −0.011093, one-sided Wilcoxon p=0.863; see `AFF-K8S` in `PAPER/supplement.tex`). Post-hoc diagnosis identified a structural reason this specific endpoint could understate B+'s advantage: B+'s CVaR-robust planning objective is optimized against a weighted distribution of three frozen scenarios (`conflict-dense` 28.6%, `partial-blockage` 42.9%, `persistent-degradation` 28.6%, normalized), while the v1.1 live endpoint measures execution under only one of them.

This protocol is an **exploratory, post-hoc secondary analysis** constructed specifically to test that mechanistic hypothesis. It is disclosed as such: its endpoint definition was created after observing the v1.1 null result. It is reported alongside, and does not supersede, the pre-registered v1.1 primary result, which stands as executed and reported.

## Research question

Does B+'s exact-solver planning advantage (established by the controlled `AFF-C` feasibility study and the 9-to-0 discordant feasibility result within v1.1) translate into a higher composite scheduled-completion fraction than Affinity-Bytes when live performance is measured across the full weighted distribution of scenarios the CVaR-robust objective is optimized against, rather than only `conflict-dense`?

## Reused, frozen elements (unchanged from v1.1)

- The same 30 held-out six-replica graphs, seeds `44001`–`44030`.
- The same two methods compared for the primary secondary-endpoint contrast: `Affinity-Bytes` and `BPlus-Exact`.
- The same primary target (`1.25`), calibration procedure, and relocation economics.
- The same three frozen wireless scenarios and normalized weights (`conflict-dense`, `partial-blockage`, `persistent-degradation`).
- `plan_methods()` and `build_problem()` are reused unmodified (imported directly from `live_confirmatory.py`), including the 2026-09-20 abstention-fallback correction (see `operator_logs/IMPLEMENTATION_CORRECTION_2026-09-20-ABSTENTION-FALLBACK.md`), so `planner_abstained` disclosure is identical to v1.1.
- `Current` is not included in this secondary campaign; only the `BPlus-Exact` vs `Affinity-Bytes` contrast is measured, since that is the pre-registered primary comparison this endpoint is testing.

## Additive extension (new in this protocol)

The following functions were added to `live_confirmatory.py` (dated 2026-09-20) and do not modify `emulated_dense()`, `flow_configs()`, `configure_and_run()`, or `aggregate_metrics()`, which remain exactly as frozen for v1.1 and continue to be used by the v1.1 campaign unchanged:

- `scenario_by_id(problem, scenario_id)`
- `flow_configs_for_scenario(problem, placement, scenario)`
- `configure_and_run_for_scenario(problem, placement, run_id, seconds, scenario)`
- `aggregate_metrics_for_scenario(problem, placement, traffic, scenario)`
- `run_weighted_multi_scenario_cell(problem, placement, run_id_base, seconds_per_scenario)`

`wireless_medium.py` was generalized from a single global medium lock/duty-fraction pair to per-conflict-group locks and duty-fraction configuration (`_medium_locks: dict[str, threading.Lock]`, `_config["duty_fractions"]: dict[str, float]`), with full backward compatibility for the v1.1 single-scenario payload shape. This was verified functionally equivalent to the v1.1 single-group behavior via a standalone smoke test (fake destination server, scalar and dict configure payloads, per-group transmit routing, unconfigured-group rejection) before deployment to the live cluster.

## Per-cell measurement procedure

For a given held-out graph and a given method's placement:

1. apply the placement (`apply_placement`, identical to v1.1: `Recreate` strategy, require all deployments Ready, frozen settle interval);
2. for each of the three frozen scenarios in a fixed order (`conflict-dense`, `partial-blockage`, `persistent-degradation`):
   a. configure the shared-medium emulator's per-conflict-group duty fractions for that scenario (`configure_and_run_for_scenario`);
   b. run the measurement for the frozen per-scenario duration (40 s, identical to the v1.1 single-scenario measurement window);
   c. collect `scheduled_completion_fraction` for that scenario (`aggregate_metrics_for_scenario`);
3. combine the three per-scenario values into one composite endpoint using the same normalized weights `load_frozen_scenarios()` assigns for the CVaR-robust objective:

`composite_scheduled_completion_fraction = sum(weight_s * completion_s) / sum(weight_s)`

4. stop traffic (best-effort, identical teardown to v1.1).

## Pre-committed pilot gate

Following the same pre-registration discipline as the parent protocol, this endpoint was piloted before being scaled to the full 30-graph dataset:

- **Pilot subset:** seeds `44001`–`44006` (the first six seeds of the frozen v1.1 range, chosen before any multi-scenario data existed, no prior use in this secondary analysis).
- **Pilot decision rule, declared before running the pilot:** if the pilot's bootstrap 95% CI for the mean composite B+ minus Affinity difference excludes zero on the positive side, scale to the full 30-seed campaign; otherwise, report the pilot result as non-promising and stop without scaling.
- **Pilot result:** n=6, mean difference +0.01226, bootstrap 95% CI [+0.00029, +0.03198] (entirely positive), 3 wins / 3 ties / 0 losses, zero abstentions. The pre-declared gate was satisfied.
- **Technical dry run preceding the pilot:** one cell (seed 90001, outside both the pilot subset and the frozen 44001–44030 campaign range) was executed first, purely to validate the extension's mechanics end-to-end on the live cluster before committing pilot-subset data; this dry-run cell is not part of any reported statistic.

## Full campaign

Following the satisfied pilot gate, the full 30-seed campaign (seeds `44001`–`44030`, `BPlus-Exact` and `Affinity-Bytes`, 60 cells total) was executed to completion.

## Primary secondary-endpoint hypothesis

**H1-MULTI (exploratory):** across the full weighted scenario distribution, `BPlus-Exact` has a higher composite scheduled-completion fraction than `Affinity-Bytes` across the 30 held-out graphs.

Inference, identical statistical procedure to v1.1:

- paired B+ minus Affinity differences on `composite_scheduled_completion_fraction`;
- one-sided Wilcoxon signed-rank test, B+ > Affinity, alpha 0.05;
- fixed-seed 100,000-resample paired bootstrap 95% CI for the mean difference;
- reported both unstratified (all 30 graphs) and stratified excluding the graphs where the exact solver proves the CVaR-robust constraint infeasible (matching the v1.1 secondary-endpoint stratification).

## Result (see `PAPER/main.tex` §4.1 and `PAPER/supplement.tex` §AFF-K8S-MULTI for full reporting)

n=30 (all): mean +0.005562, bootstrap 95% CI [−0.003315, +0.014458], one-sided Wilcoxon p=0.0196.
n=28 (non-abstained): mean +0.006006, bootstrap 95% CI [+0.001710, +0.011651], one-sided Wilcoxon p=0.003823.

## Interpretation rule

This result, if favorable, supports the bounded statement that **B+'s modeled robust-feasibility advantage translates into a measurable live application-performance advantage once performance is measured across the actual weighted distribution of scenarios the placement objective optimizes against, even though it is not detectable under single-scenario measurement.** It does not retroactively alter the v1.1 primary result, which is reported as executed regardless of this secondary finding's direction. A null or unfavorable secondary result would likewise be retained and reported without reformulating this hypothesis further.

## Provenance

- Source: `EXPERIMENTS/k8s_affinity_wireless_confirmatory/src/live_confirmatory.py` (SHA-256 recorded in `operator_logs/`), `EXPERIMENTS/k8s_affinity_wireless_confirmatory/benchmark/wireless_medium.py`.
- Pilot data: `EXPERIMENTS/k8s_affinity_wireless_confirmatory/results/pilot-multiscenario-20260920.jsonl`.
- Full campaign data: `EXPERIMENTS/k8s_affinity_wireless_confirmatory/results/full-multiscenario-20260920.jsonl`.
- Execution host: Azure VM `mcb-k8s-v137`, same Kind cluster (`mape-cap-confirm`) as the v1.1 campaign.
