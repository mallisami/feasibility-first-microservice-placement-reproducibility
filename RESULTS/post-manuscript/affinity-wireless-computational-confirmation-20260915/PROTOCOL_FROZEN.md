# Frozen Protocol — Communication Affinity vs Wireless-Aware Placement

Freeze date: 2026-09-15
Evidence class: prospectively frozen **controlled computational confirmation**, informed by the earlier post-hoc exploratory mechanism experiment.

## Scope boundary
This experiment is not a live Kubernetes campaign, an ns-3 rerun, or a physical-RF experiment. It tests the placement mechanism on previously unseen generated communication graphs using the frozen simulation-backed wireless-state library and measured relocation-cost coefficient from the current MAPE-CAP B+ package. Results may confirm a controlled mechanism claim, not a physical interference or application-performance claim.

## Research hypothesis
Primary H1: Under a common congestion event in which the pre-existing Current placement is calibrated to 125% of its worst robust conflict-group airtime budget, B+ Exact will preserve wireless-feasible placement on a larger fraction of previously unseen instances than a strong communication-affinity baseline that minimizes cross-rack bytes without wireless-state/conflict knowledge.

Mechanism expectation (secondary): At the capacity boundary (Current calibrated to 100%), B+ may use more cross-rack bytes than the affinity baseline while achieving lower worst conflict-group utilization. This would show that minimizing communication volume and minimizing wireless contention exposure are not equivalent objectives.

## Independent instances
Use the repository generator `mape_cap_bplus.generators.generate_problem` only for replicas, resource demands, current placement, and communication graphs. Do not use its synthetic wireless scenarios or synthetic relocation costs.

Three fixed graph-size strata, 50 instances each (150 total):
- 6 replicas: seeds 11001–11050
- 7 replicas: seeds 22001–22050
- 8 replicas: seeds 33001–33050

No outcome-based seed replacement is allowed. Any invalid/excluded instance is reported and not replaced.

## Frozen wireless state
Replace generated scenarios with the current package's simulation-backed states:
- conflict-dense
- partial-blockage
- persistent-degradation

Use their frozen scenario weights normalized within this three-state set, directed goodput/latency, conflict groups, and airtime budgets.

## Frozen relocation economics
For every replica use the package's pilot coefficient:
- expected relocation time = 4.062 s
- relocation cost = 4062 cost units
- uncertainty record = 690 units

Keep the generator's frozen max-relocation cap.

## Methods
1. Current — retain current placement.
2. Affinity-Frequency — among cluster-feasible placements within the relocation cap, minimize cross-rack request count. No wireless state, goodput, conflict group, airtime budget, or CVaR information is visible to this method.
3. Affinity-Bytes — **primary comparator**. Same constraints as above, but minimize cross-rack bits. This is the stronger congestion-relevant affinity comparator.
4. BPlus-Exact — exhaustively enumerate cluster-feasible placements and select the feasible placement with minimum frozen B+ objective under the scaled wireless instance. Risk configuration: q=0.8, CVaR weight=1.5, relocation weight=1.0, SLO-slack weight=1000.

All ties use deterministic secondary ordering: fewer relocations, then lexicographic placement.

## Load calibration
For each independent instance compute the Current placement's worst conflict-group utilization under the unscaled problem. Uniformly scale **bits_per_window only** for every flow so Current reaches each target:
- 0.50
- 0.90
- 1.00
- 1.10
- 1.25 (**primary target**)
- 1.50

Requests per window are held fixed. This isolates wireless airtime/payload pressure from request-frequency changes in the delay objective. The same scaled instance is presented to every method.

## Endpoints
Primary endpoint:
- paired wireless feasibility at target 1.25 (`worst conflict-group utilization <= 1` in every frozen scenario).

Primary statistical test:
- one-sided exact paired discordance/binomial test (McNemar-equivalent on discordant pairs), BPlus-Exact > Affinity-Bytes, alpha=0.05.
- report feasibility risk difference BPlus minus Affinity-Bytes with fixed-seed 100,000-resample paired bootstrap 95% CI.

Secondary endpoints:
- feasibility at all other targets;
- worst conflict-group utilization;
- airtime headroom = 1 - worst utilization;
- cross-rack bytes;
- relocations;
- graph-size-stratified results.

Secondary paired mechanism tests at target 1.00, restricted to pairs where both methods are feasible:
- BPlus minus Affinity-Bytes worst-utilization difference;
- BPlus minus Affinity-Bytes cross-rack-byte difference;
- Wilcoxon signed-rank p-values are descriptive secondary inference and do not change H1.

## Sanity / specificity checks
- At target 0.50, both BPlus-Exact and Affinity-Bytes should normally remain feasible; unexpected failures are reported, not hidden.
- Results must be reported separately for 6-, 7-, and 8-replica strata to expose topology/size dependence.
- Affinity-Frequency is secondary; H1 is not switched to whichever affinity baseline performs worse.

## Exclusions
Exclude only if:
- the generated problem has no valid current placement,
- Current has zero base conflict utilization (calibration undefined), or
- no cluster-feasible placement exists under the frozen non-airtime constraints.
No exclusion may depend on B+ or affinity outcomes.

## Interpretation rule
A positive H1 supports only this claim:
> Under controlled, previously unseen communication graphs and frozen wireless states, explicit wireless-state/conflict-aware placement can preserve robust airtime feasibility more often than byte-affinity placement during a calibrated congestion event.

It does not establish measured RF interference reduction, physical 60-GHz behavior, or application-level performance improvement.
