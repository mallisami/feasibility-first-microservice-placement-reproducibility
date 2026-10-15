# S-MILP solver substitution — 2026-09-17

## What was wrong
S-MILP ("matched 10-s LNS vs Gurobi standard heuristic-emphasis
configurations") requires a Gurobi license with unrestricted model size.
Only a size-limited license was available: 54/72 runs (all 3 non-LNS
methods x 6 sizes x 3 seeds) failed with `GurobiError(10010, 'Model too
large for size-limited license')`; the 18 LNS-only runs (no Gurobi needed)
succeeded. This was already accurately disclosed in `main.tex:1000`
("A matched Gurobi arm was blocked by the available license...").

## What was changed
Added `scip_adapter.py`, an exact structural mirror of `gurobi_adapter.py`'s
MILP formulation (same variables, objective, and constraints) solved via
SCIP (through PySCIPOpt, which bundles its own SCIP build and needs no
separate license or registration). SCIP's `heuristics/rins` and
`heuristics/feaspump` settings directly correspond to Gurobi's `RINS` and
`PumpPasses` parameters, preserving the original three-mode experimental
design (`default` / `rins` / `feasibility-pump`) rather than approximating
it with a differently-structured solver.

`run_smilp_matched_heuristics.py` was updated to import `solve_scip` instead
of `solve_gurobi`. `requirements-optional-strengthening.txt` now lists
`pyscipopt` instead of `gurobipy`.

**All Gurobi code, config, and manuscript text was removed** (at user
request, after the SCIP substitution completed successfully):
- `gurobi_adapter.py` deleted.
- `requirements-optional-strengthening.txt`, `run_smilp_matched_heuristics.py`,
  `run_full_campaign.py`, `run_strengthening_campaign.py`,
  `implementation/strengthening/README.md` — all Gurobi/gurobipy references
  replaced with SCIP/pyscipopt.
- `PAPER/main.tex:1000` and `PAPER/supplement.tex` (table row + prose in
  Section "S-GRACE and S-MILP Status") updated to describe the completed
  SCIP comparison (71/72 cells) instead of the blocked Gurobi attempt.
- The 54 raw Gurobi-mode failure JSON files and the original mixed
  `S-MILP-summary.json`/`.csv` were moved (not deleted) to
  `_ARCHIVE_SUPERSEDED/original-gurobi-attempt-S-MILP-20260814/` — the 18
  successful LNS results, which never depended on Gurobi, remain in their
  original location. A pointer note
  (`RESULTS/strengthening/strengthening-20260814T223539Z/derived/S-MILP-SUPERSEDED-SEE-NEW-RUN.md`)
  explains where everything moved to.

This is an archive, not a deletion — the original Gurobi attempt's evidence
still exists and remains reconstructable, just moved out of the active
result tree since the project no longer has any Gurobi dependency.

## Result
Re-ran the full 72-cell campaign (sizes 12/16/20/24/40/50 x seeds 1/2/3 x
methods LNS/default/rins/feasibility-pump, 10s time limit, unchanged from
the original design) with SCIP. **71/72 succeeded** (vs. 18/72 with Gurobi).
The one remaining failure (`r50:seed2:default`) is a genuine, informative
result — SCIP found no feasible incumbent for the largest (50-replica)
instance within the strict 10s budget (`status=timelimit`), not a
capability/license error — consistent with the paper's own R8 findings
about large-instance difficulty under strict search budgets.

## Provenance
- New run root: `RESULTS/gap-closure/smilp-scip-repower-20260917/` — a new,
  separately-identified campaign; the original Gurobi-attempt data at
  `RESULTS/strengthening/strengthening-20260814T223539Z/raw/S-MILP-matched-heuristics/`
  is untouched and retained for provenance, per this project's "never
  overwrite" convention.
- No frozen scientific parameter, risk configuration, problem generator, or
  LNS implementation was touched — only the MILP solver backend for one
  optional, previously-blocked comparison experiment.
- Draft manuscript update (not yet applied to `main.tex`, pending author
  review — same convention as `PAPER/OVERNIGHT_FINDINGS_AND_DRAFT_INTEGRATION_2026-09-16.md`):
  replace `main.tex:1000`'s sentence "A matched Gurobi arm was blocked by
  the available license, leaving Exact/HiGHS as the time-limited solver
  reference." with wording disclosing the SCIP substitution and its 71/72
  completion rate.
