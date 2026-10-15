# N4 — Solver scaling under a strict, matched budget

**Freeze:** 2026-09-26, before any N4 run.
**Evidence class:** prospectively frozen offline computation (Azure Standard_D4as_v5, run after
N5 completes so that no live measurement shares the CPU).
**Parent:** R8 (`run_v03_r8.py`): same generator, topology rule and risk configuration.

## Questions
1. Up to which size does the exact MILP prove optimality within a 30-s budget, and how large is
   its incumbent–bound gap beyond that?
2. Under the same budget, how close does LNS get to the best available bound?
3. Was the R8 LNS stall at 40–50 replicas caused by its configuration, i.e. by the pre-search
   local-search initialization consuming the budget? This is tested by a configuration-only
   variant; no algorithmic change is made.

## Instances
`generate_problem(replica_count=n, rack_count=3, nodes_per_rack=max(2, ceil(n/18)),
scenario_count=3, seed=s)` as in R8. Sizes n ∈ {10, 12, 16, 20, 24, 32, 40, 50, 75, 100};
seeds s ∈ {101, …, 110} (new; R8 used 1–3). Risk: q = 0.9, λ = 1.5, μ = 1, ξ = 1000 (R8).

## Arms (budget 30 s each, single-threaded HiGHS default settings)
- **Exact:** `solve_exact(..., time_limit_seconds=30, require_optimal=False)`.
- **LNS-R8config:** `robust_lns(iterations=80, destroy_size=min(4,n), local_iterations=10,
  time_limit_seconds=30)` — the published configuration at the matched budget. Run for
  n ≤ 50 only (the published R8 range).
- **LNS-noinit:** `robust_lns(iterations=10**6, destroy_size=min(4,n), local_iterations=0,
  time_limit_seconds=30)` — identical code; the pre-search local search is skipped and the
  iteration cap is removed so the budget is spent on neighbourhoods.
All arms start from the generator's current placement. The budget applies inside each solver as
implemented; measured wall-clock time (including initialization overrun) is recorded.

## Endpoints
Status (optimal / incumbent / no-incumbent / failure; "no-incumbent" = the exact solver reached
its time limit without any feasible solution, a solver outcome rather than an infrastructure
failure — label fixed after an engineering test at n=100 on 2026-09-26, before the campaign), objective, exact lower bound and MIP gap, wall-clock
runtime, LNS completed neighbourhoods and accepted improvements, feasibility.
- **Certified gap** = (J − J*)/|J*| only where Exact proves optimality.
- **Gap to bound** = (J − LB)/|LB| using the Exact lower bound otherwise (an upper bound on the
  true optimality gap).

## Analysis (descriptive per size; paired by seed)
- Exact proof rate and median MIP gap by n.
- Median certified gap / gap-to-bound of each LNS arm by n.
- Paired objective difference LNS-noinit − LNS-R8config for n ≤ 50 (Wilcoxon, two-sided).
- Median completed neighbourhoods by n and arm.

## Interpretation rules
Solution-quality statements are bounded by the certified or bound-based gaps; no approximation
guarantee is claimed. A configuration-only improvement does not constitute a new algorithm.
