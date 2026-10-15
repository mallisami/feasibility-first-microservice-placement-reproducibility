# N5 — Live application visibility when the executed wireless state binds

**Freeze:** 2026-09-26, before any N5 application measurement.
**Evidence class:** prospectively frozen, single-host Kind (Azure VM) with the in-cluster
shared-airtime emulator. Not physical RF; not independent-host hardware.
**Parent harness:** `EXPERIMENTS/k8s_affinity_wireless_confirmatory` (AFF-K8S v1.1 + 2026-09-20
per-group medium). Frozen harness files are imported unchanged; only the cluster name, instance
calibration, enrollment rule, method set, executed state and endpoints below are new.

## Why
In AFF-K8S the emulator executed conflict-dense only, calibrated so that *Current* reached 1.25
there. 10 of the 11 graphs on which Affinity-Bytes was planned-inadmissible were within budget in
that executed state, and completion sat at ceiling. The live comparison therefore never exercised a
state in which the methods' admissibility differs. N5 executes that state.

## Questions
- **Q1 (admission effect):** when byte affinity oversubscribes the executed state's shared airtime,
  does enforcing admission (same affinity objective + admission constraints) change application
  latency and completion?
- **Q2 (ranking effect):** among admissible placements, does the MAPE-CAP-WS ranking differ from
  admission-constrained affinity at the application level?
- **Q3 (locality-induced regime, secondary):** where the incumbent is admissible but the affinity
  optimum is not, is relocating by affinity worse for the application than not relocating?

## Instances and calibration
Graphs from `generate_problem(replica_count=6, rack_count=3, nodes_per_rack=1, scenario_count=3,
decision_window_seconds=60)`, candidate seeds 55001, 55002, … in increasing order, mapped to the
three Kind workers as racks A/B/C exactly as `live_confirmatory.build_problem` does (node capacity
= 95% of allocatable). Planning states: conflict-dense, partial-blockage, persistent-degradation
(canonical CSV library, normalized weights). Load calibration follows the AFF-C convention: all
directed goodputs are scaled by one factor so that Current's **worst utilization over the three
planning states** equals the stratum target τ. Emulator rate guard 0.1–500 Mbit/s as frozen.

## Methods
1. **Current** — keep placement (stratum S2 only).
2. **Affinity-Bytes** — frozen `solve_affinity_bytes` (no wireless information).
3. **Affinity-Bytes+Admission** — same enumeration, objective and tie-break, restricted to
   placements that satisfy availability and conflict-group airtime in all three planning states.
4. **MAPE-CAP-WS** — frozen `solve_exact` (q=0.8, λ=1.5, μ=1, ξ=1000), `require_optimal=True`.

## Enrollment (depends on planning only; never on application outcomes)
- **S1 (primary), τ = 1.25:** enroll a seed iff Affinity-Bytes is planned-inadmissible and
  MAPE-CAP-WS returns a proven-optimal admissible placement. Enroll the first **20** such seeds.
- **S2 (secondary), τ = 1.00:** enroll a seed iff Current is admissible, Affinity-Bytes is
  inadmissible and MAPE-CAP-WS is admissible. Enroll the first **10** such seeds (screening stops
  at seed 57000 if fewer exist; the achieved n is reported).
Every screened seed and its planning outcome is written to `screening.csv`.

## Executed state
Per graph, the planning state in which the **Affinity-Bytes** placement attains its worst
conflict-group utilization (ties: planning-state order). All arms of that graph execute this same
state, with per-group duty fractions = budget/60 s, through the frozen per-group emulator.

## Cell procedure (frozen harness functions)
`apply_placement` → settle 5 s → `configure_and_run_for_scenario` for **40 s** → collect pod and
emulator metrics → health check. Method order per graph randomized with seed 20260926 + seed.
Infrastructure-only acceptance gates as AFF-K8S (non-zero attempts; medium saw traffic when
cross-rack flows exist; deployments healthy); ≤2 attempts per cell; no performance threshold is
used for acceptance.

## Endpoints (graph × method)
- **Primary: scheduled-request P95 latency (ms).** Latency vector = every attempted request's
  measured latency (errors included at their measured time) plus one entry of 3000 ms (the frozen
  HTTP timeout) for each scheduled request that was never attempted; nearest-rank P95.
  This prevents back-pressure from hiding congestion.
- **Co-primary: scheduled completion fraction** (frozen definition).
- Secondary: P50/P99, mean emulator queue wait, executed-state planned utilization, moves.

## Analysis
Unit = graph. Paired differences with 100,000-resample bootstrap 95% CI (seed 20260926) and
two-sided Wilcoxon signed-rank.
- **Primary (S1):** (a) Affinity+Admission − Affinity-Bytes, scheduled P95;
  (b) MAPE-CAP-WS − Affinity+Admission, scheduled P95. Holm across (a), (b).
- Co-primary completion contrasts reported with the same procedure (Holm within completion).
- Secondary (S2): all pairwise contrasts among the four methods, descriptive intervals only.
- Planned-vs-executed check: executed-state utilization of each arm reported per graph.

## Interpretation rules
- A null result is reported as such. It would indicate that, on this emulator, planning-level
  admissibility does not translate into application latency at the tested load.
- Enrollment enriches for planning discordance by design; results apply to graphs on which
  affinity is inadmissible, not to all graphs.
- No physical-RF, multi-host or production claim follows.

## Environment
Azure Standard_D4as_v5 (4 vCPU, 16 GiB), Ubuntu 24.04. Dedicated Kind cluster `rev-n5`
(kindest/node v1.33.1, same digest as AFF-K8S); benchmark image rebuilt from the frozen
Dockerfile as `mape-cap-confirm-bench:rev-n5`. Kind CLI v0.33.0 (AFF-K8S used v0.28.0;
recorded as a difference).

**Pre-execution amendment (2026-09-26, before any measurement):** three older Kind clusters on
the VM (`mape-cap-confirm`, `mcb-k137`, `e38`) are left running rather than stopped, to avoid
altering prior experiment environments; at inspection the VM 1-minute load average was 0.35 on
4 vCPUs. The 1-minute load average is recorded before and after every cell and reported.
