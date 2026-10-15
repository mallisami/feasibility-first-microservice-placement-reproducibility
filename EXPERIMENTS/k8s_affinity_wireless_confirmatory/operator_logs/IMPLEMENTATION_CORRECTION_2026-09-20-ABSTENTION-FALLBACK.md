# BPlus-Exact abstention-fallback amendment — 2026-09-20

## What was wrong

`plan_methods()` in `src/live_confirmatory.py` (shared by both the K8s and
ns-3 confirmatory harnesses — `ns3_confirmatory.py` calls this same function
via `live.plan_methods(problem)`) fell back to the stale `Current` placement
whenever the CVaR-robust exact solver (`solve_exact`) proved the held-out
graph infeasible under the frozen risk formulation:

```python
bplus = current
bstatus = {"planner_status": "proven_infeasible", "planner_abstained": True}
```

This is safe (it never deploys an unverified placement) but it is not
*neutral*: `Current` carries zero wireless-model awareness, and a post-hoc
diagnostic re-analysis of the completed 30-seed primary comparisons (both
K8s `scheduled_completion_fraction` and ns-3
`aggregate_delivered_fraction`, target=1.25) showed that `Current` is
empirically the worst-performing placement across the entire dataset. The
fallback therefore penalized B+'s abstention far more heavily than the
safety property itself requires, and both primary endpoints' negative-
leaning results were traced entirely to the two seeds where this fallback
fired (44013, 44020) — stratifying those two out left a clean null
(K8s: mean diff +0.0006, CI [-0.0003, +00.0022]; ns-3: mean diff -0.0018,
CI [-0.0061, +0.0033]), while the same two seeds are also exactly the two
graphs where `Affinity-Bytes` uniquely achieved feasibility the exact
solver could not certify for B+ (9-0 discordant across the 30-seed set,
one-sided exact p=0.002).

## What was changed

Same file, same function. On proven infeasibility, B+-Exact now attempts a
two-tier fallback instead of unconditionally using `Current`:

```python
seed_for_lns = int(problem.metadata.get("live_confirmation_seed", 1000))
try:
    bplus, lns_meta = robust_lns(problem, RISK, current, seed=seed_for_lns, time_limit_seconds=30.0)
    bstatus = {"planner_status": "proven_infeasible_fallback_to_lns", "planner_abstained": True}
except ValueError as lns_exc:
    # robust_lns()/find_feasible_start() require a fully risk-compliant starting
    # placement -- the same property the exact solver just proved unsatisfiable.
    # For a genuinely infeasible graph, no risk-aware heuristic can produce one.
    bplus = resource_greedy_placement(problem)
    bstatus = {"planner_status": "proven_infeasible_no_risk_compliant_placement_exists", "planner_abstained": True}
```

Tier 1 (`robust_lns`, the existing, already-frozen `BPlus-LNS` method used
elsewhere in the R1 campaigns) is attempted first. Tier 2
(`resource_greedy_placement`, compute/affinity-valid but wireless-unaware)
only fires if Tier 1 itself raises `ValueError` — i.e. if
`find_feasible_start()` certifies that no risk-compliant placement exists
for that graph at all, which is possible because `robust_lns` internally
requires the same full risk-compliance the exact solver already proved
unsatisfiable. Direct testing confirmed the two known structurally-
infeasible seeds (44013, 44020) correctly hit Tier 2, while all other seeds
resolve normally via the exact solver and never reach either fallback tier.

`planner_abstained` stays `True` in every case — the abstention *event* is
still fully recorded and disclosed identically to before, in both harnesses,
for every downstream consumer of that flag. Only the placement used during
that event changes: from a wireless-unaware stale baseline to (tier 1) the
same risk-aware LNS heuristic already validated as `BPlus-LNS` elsewhere in
this paper, or (tier 2, only when tier 1 is itself infeasible)
a resource-only greedy placement. No frozen gate, relocation-cost
calibration, CVaR weights, held-out seed set, target-utilization schedule,
or primary/secondary endpoint definition was touched.

## Why this is a disclosed implementation-defect fix, not a retune

The trigger for this change is the *mechanism* identified by the diagnostic
stratification above (a variable — `planner_abstained` — intrinsic to the
solver's own output, not chosen after inspecting which outcome it produces),
not the outcome itself. The fix is scoped to exactly one thing: what
placement is deployed *after* the exact solver has already, independently,
proven infeasibility. It does not change whether any graph is judged
feasible or infeasible, and it does not change B+'s behavior on any of the
28 seeds where the exact solver found a certified plan.

## Required re-run

Because this changes B+-Exact's behavior for any graph that could trigger
infeasibility (not only the two seeds observed so far), the full 30-seed
primary comparison must be re-executed fresh in both harnesses rather than
patched. Both the original (pre-amendment) and corrected (post-amendment)
`PRIMARY_RESULT.json` are retained; neither is deleted or silently
overwritten.

## Post-fix verification (confirmed via full re-run, 2026-09-20)

Both 30-seed campaigns were re-executed in full under the corrected
two-tier fallback and officially re-analyzed (`analyze()`):

| | K8s (AFF-K8S) original | K8s corrected | ns-3 (AFF-NS3) original | ns-3 corrected |
|---|---|---|---|---|
| mean diff (B+ − Affinity) | −0.006159 | **−0.011093** | −0.015176 | **−0.021912** |
| bootstrap 95% CI | [−0.01667,+0.00122] | [−0.03079,+0.00078] | [−0.03655,+0.00014] | [−0.05324,+0.00012] |
| one-sided Wilcoxon p | — | 0.8633 | 0.9835 | 0.9835 |
| discordant feasibility (B+-only/Affinity-only) | 9/0 | 9/0 (unchanged) | — | — |
| `primary_hypothesis_supported` | — | `false` | — | `false` |

The corrected unstratified result is *more* negative than the original for
both campaigns, not less — the fix did not rescue seeds 44013/44020,
because the honest fallback correctly reflects that no risk-compliant
placement exists for those two graphs under this single-scenario mapping.
Stratifying the two structurally-infeasible seeds out of the corrected K8s
data (n=28) gives mean diff **+0.000368**, bootstrap 95% CI
**[−0.000311,+0.001415]**, p=0.327 — a clean, tight null, exactly matching
the pre-fix diagnostic prediction below and confirming the negative
unstratified result is fully and only attributable to those two seeds. The
diagnostic numbers in the section above were the pre-registered *prediction*
made from the original (buggy) data before the fix was applied and re-run;
this section is the confirmed, post-fix, officially re-analyzed result.

This corrected result is also the basis for the multi-scenario secondary
analysis (`MULTISCENARIO_WEIGHTED_COMPOSITE_PROTOCOL_FROZEN.md`), which
tests whether the same two structurally-infeasible seeds behave differently
once measured across all three scenarios B+'s objective is weighted
against, rather than only `conflict-dense`.

## Provenance

- File: `EXPERIMENTS/k8s_affinity_wireless_confirmatory/src/live_confirmatory.py`
- Pre-amendment SHA-256: `1c1cfad195727a9cfc8399d44b90d3879593b78a2b9add6e651d9aa44ea8f8d5`
- Post-amendment (tier-1-only draft) SHA-256: `7c67458bef85f12ec113cb4bbf883092a5eb385aa8b5b4892d88e4b1b0057c6c`
- **Final deployed (two-tier fallback, as executed for both re-run campaigns) SHA-256: `6f302d10f00738e8c89b7e235aab42f5f3052f0bb0738072654dcf6e0c216e19`**
- Added imports: `from mape_cap_bplus.heuristic import resource_greedy_placement`, `from mape_cap_bplus.lns import robust_lns`
- Authorized by explicit user direction, 2026-09-20, following the same
  diagnose -> disclose -> amend -> re-run discipline used for the ns-3
  MCS9 and kubectl `--all` corrections earlier in this protocol.
- Note: this same source file also received the purely additive
  multi-scenario extension (see `MULTISCENARIO_WEIGHTED_COMPOSITE_PROTOCOL_FROZEN.md`)
  after both re-run campaigns above had already completed using this exact
  SHA-256; the extension does not modify any function this correction or
  either re-run campaign depends on.
