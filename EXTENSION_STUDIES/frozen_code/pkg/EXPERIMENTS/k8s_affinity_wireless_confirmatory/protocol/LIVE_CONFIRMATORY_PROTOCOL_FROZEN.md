# Frozen Live Kubernetes Confirmatory Protocol — v1.1

**Freeze date:** 2026-09-15  
**Protocol ID:** `wireless-beyond-affinity-k8s-v1.1`  
**Evidence class:** Kubernetes-executed mechanism confirmation using a deterministic shared-medium emulator derived from the frozen wireless airtime model.

## Research question

When a communication-affinity placement minimizes cross-rack bytes but ignores heterogeneous wireless link capacity and shared conflict-group occupancy, does B+ preserve a larger fraction of scheduled communication under a calibrated contention event?

## Claim boundary

This experiment does **not** claim physical 60-GHz/RF interference measurement. It tests the manuscript's directed-goodput plus shared-airtime abstraction in a real Kubernetes deployment. The final report must retain this boundary regardless of outcome.

## Pre-specified held-out instances

Thirty generated communication graphs are retained without outcome-based replacement:

- six replicas;
- three racks / three Kubernetes workers;
- held-out seeds `44001`–`44030`;
- the prior computational-confirmation blocks `11001`–`11050`, `22001`–`22050`, and `33001`–`33050` are excluded.

The repository generator contributes replicas, resource requests, current placement, flow rates and flow volumes only. Its generated wireless scenarios and relocation costs are discarded.

## Frozen wireless states and relocation economics

The B+ planner uses three simulation-backed scenarios from the current manuscript package:

- `conflict-dense`;
- `partial-blockage`;
- `persistent-degradation`.

Weights are normalized inside this three-state set. Relocation economics are frozen at:

- expected relocation time 4.062 s;
- relocation cost 4062 units per moved replica;
- uncertainty record 690 units;
- maximum relocations: the generated problem's frozen cap (two moves for these six-replica instances).

## Methods

1. **Current** — generated current placement.
2. **Affinity-Bytes** — exact minimization of cross-rack bytes subject to the same compute, memory, allowed-node, anti-affinity and relocation-count constraints. It receives no link goodput, latency, conflict group, airtime budget or CVaR information.
3. **BPlus-Exact** — exact SciPy/HiGHS B+ planner with `q=0.8`, CVaR weight 1.5, relocation weight 1.0 and SLO-slack weight 1000.

If B+ proves an instance infeasible, it safely abstains and executes the Current placement. The seed remains in the intention-to-treat B+ arm. Numerical failure or timeout is not an abstention and is not silently accepted.

## Capacity calibration

The communication graph remains unchanged. For each held-out seed, all directed wireless goodputs are multiplied by one common factor so that the **Current** placement reaches the target conflict-group utilization in the **same `conflict-dense` scenario executed by the live shared-medium emulator**. The B+ planner then evaluates all three frozen robust scenarios under that same common scaling.

- primary target: `1.25`;
- low-load specificity target: `0.50` for seeds `44001`–`44005` only.

This scaling is frozen before live outcomes. All three methods in a paired block use the same calibrated link matrix. Rates outside 0.10–500 Mbit/s are reported as calibration/infrastructure exclusions and are not replaced.

## Shared-medium execution model

The frozen `conflict-dense` state has one shared conflict group (`cg-shared`) with a 15 s airtime budget in a 60 s decision window.

For each cross-rack request:

1. the sender routes the request through the in-cluster `wireless-medium` service;
2. the service selects the directed goodput and latency associated with the source/destination rack pair;
3. modeled airtime is `payload_bits / directed_goodput_bps`;
4. all cross-rack requests serialize on one medium lock because they belong to `cg-shared`;
5. duty fraction is `15 / 60 = 0.25`;
6. serialized service time is `modeled_airtime / 0.25`;
7. propagation latency is applied after releasing the shared medium;
8. the payload is forwarded to the real destination Kubernetes service.

Therefore aggregate modeled airtime of 15 s per 60 s corresponds to 100% emulator utilization. Same-worker traffic bypasses the shared medium.

This mechanism is an executable implementation of the paper's conflict-budget abstraction, not a packet-level RF/MAC simulator.

## Kubernetes execution

The runner creates or reuses a dedicated Kind cluster with one control plane and three workers. Each microservice is a real Kubernetes Deployment. The wireless-medium service runs on the control-plane node so it does not consume the workers' placement capacity.

For each paired method/block:

1. stop residual benchmark traffic;
2. apply the target placement using `Recreate` Deployment strategy;
3. require all deployments Ready;
4. wait the frozen settle interval;
5. reset/configure the shared-medium emulator;
6. configure every sender for a common future start epoch;
7. run the primary measurement for 40 s after a 5 s synchronized-start delay;
8. collect sender metrics, receiver counts, medium metrics, placement and health;
9. retain infrastructure failures and retry at most twice;
10. never retry or reject a cell because its performance is unfavorable.

Method order is deterministically randomized from the frozen order seed.

## Primary hypothesis and endpoint

**H1-LIVE:** at the 1.25 Current-calibrated contention target, BPlus-Exact has a higher scheduled-request completion fraction than Affinity-Bytes across the 30 held-out graphs.

Per-cell primary endpoint:

`scheduled_completion_fraction = successful_requests / expected_scheduled_requests`

`expected_scheduled_requests` is determined only by the frozen per-flow rate and measurement duration.

Primary inference:

- paired B+ minus Affinity differences;
- one-sided Wilcoxon signed-rank test, B+ > Affinity, alpha 0.05;
- fixed-seed 100,000-resample paired bootstrap 95% CI for the mean difference.

## Secondary mechanism endpoints

- planned robust feasibility and worst conflict-group utilization;
- cross-rack offered/successful bytes;
- modeled offered/successful airtime utilization;
- shared-medium request count, errors, modeled airtime and serialized service demand;
- request P50/P95/P99 and mean latency;
- attempted/scheduled and successful/attempted fractions;
- relocation count and rollout time;
- low-load specificity at target 0.50.

Planned-feasibility discordance is secondary because B+ explicitly optimizes this constraint family.

## Interpretation rule

A favorable primary result plus the already frozen computational mechanism result supports the bounded statement that **byte-affinity alone can be insufficient when link capacity and shared-airtime contention are heterogeneous, while explicit wireless-state/conflict-aware placement can preserve more scheduled communication under the modelled contention regime**.

A null or unfavorable result is retained without reformulating the hypothesis.

## Incorporated pre-execution QA corrections (part of this canonical v1.1 protocol)

The following corrections were made **before any live confirmatory outcome was generated** and are incorporated here so that this file is the only authoritative live protocol. No separate superseded protocol or amendment file is required to execute or interpret the campaign.

1. **Safe planner abstention.** If `BPlus-Exact` proves a held-out instance infeasible under the frozen robust constraints and relocation cap, the B+ controller abstains and executes the block's `Current` placement. The seed remains in the intention-to-treat B+ arm with `planner_status = proven_infeasible`, `planner_abstained = true`, and `planned_feasible = false`. Solver timeout or numerical failure is not treated as abstention.
2. **Primary denominator.** The primary endpoint is `successful_requests / expected_scheduled_requests`, not `successful / attempted`. This prevents sender back-pressure from making severe congestion look artificially favorable by shrinking the denominator.
3. **Shared-medium fidelity.** A pre-execution v1.0 design based on independent per-rack-pair Linux `tc` qdiscs was rejected during QA because independent qdiscs cannot faithfully impose the paper's single coupled `cg-shared` airtime budget across all rack pairs. No v1.0 live outcome was generated. The frozen v1.1 runner therefore routes every cross-rack request through one in-cluster `wireless-medium` service using the shared-medium semantics specified above.

These corrections do not change the held-out seeds, methods, target utilizations, risk/relocation weights, wireless traces, method-order seed, measurement duration, statistical test, or claim boundary.
