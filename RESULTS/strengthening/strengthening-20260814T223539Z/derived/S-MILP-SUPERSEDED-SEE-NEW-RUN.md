# S-MILP moved — 2026-09-17

The original S-MILP derived summary (`S-MILP-summary.json`,
`S-MILP-matched-heuristics.csv`) and the 54 Gurobi-mode raw per-cell result
files (`raw/S-MILP-matched-heuristics/*_default.json`, `*_rins.json`,
`*_feasibility-pump.json`) were moved to
`_ARCHIVE_SUPERSEDED/original-gurobi-attempt-S-MILP-20260814/` at the
project root, since a valid Gurobi license was never obtained and the
codebase no longer depends on Gurobi at all (`gurobi_adapter.py` removed).

The 18 successful LNS raw result files remain in place here (`raw/S-MILP-matched-heuristics/*_LNS.json`)
since they never depended on Gurobi.

**The current S-MILP evidence is at:**
`RESULTS/gap-closure/smilp-scip-repower-20260917/` — 71/72 cells completed
using SCIP (via PySCIPOpt) in place of Gurobi. See
`implementation/strengthening/IMPLEMENTATION_CORRECTION_2026-09-17-SCIP-SUBSTITUTION.md`
for full provenance.
