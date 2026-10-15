# Current-manuscript derived analyses — 2026-10-13

These files synchronize the October 2026 TCC manuscript with the frozen reproducibility package. They are **post-processing/reanalysis only**; no scientific experiment was rerun and no row was fabricated.

## Source

All three analyses re-enumerate the frozen 150 AFF-C graph candidate sets using `EXTENSION_STUDIES/N2N3_admission_vs_ranking/run_n2n3.py`. Because the historical released `run_n2n3.py` resolves package paths incorrectly, this directory includes `run_n2n3_fixed.py`, an **analysis-local path-only compatibility copy**. The historical script is left byte-identical so the legacy-retention manifest remains valid. The compatibility copy was regression-tested against the archived N2/N3 `cell_results.csv`; the regenerated file was byte-identical.

## Outputs

### Critical admissible load
- `critical_load_analysis.py`
- `critical_load_results.csv`
- `critical_load_summary.csv`
- `critical_load_summary.json`

At the primary load, median `tau_c` is **1.917291** (Affinity-Bytes), **1.969212** (Affinity-Bytes+Admission), and **1.546287** (MAPE-CAP-WS). Mean admission change is **+0.091040**, 95% graph-resampling interval **[+0.056732,+0.128680]**; mean ranking change is **-0.432530**, interval **[-0.552680,-0.325686]**. The formal edge case is `tau_c=+infinity` when `U_max=0`.

### Admitted-set Pareto diagnostic
- `pareto_analysis.py`
- `pareto_points.csv`
- `pareto_summary.csv`
- `pareto_summary.json`

Across the 24 primary discordant graphs, the three-objective Pareto set over cross-rack bytes, expected exposure, and `U_max` has median size **3** (range **1–6**). Affinity-Bytes+Admission is nondominated on **24/24** graphs and MAPE-CAP-WS on **22/24**.

### Finite exact-penalty diagnostic
- `exact_penalty_bound.py`
- `exact_penalty_results.csv`
- `exact_penalty_summary.csv`
- `exact_penalty_summary.json`

Using `V(x)=max(0,U_max(x)-1)` at the primary load, `R_J/delta` has median **6.206678e6**, 10th–90th percentile range **1.582179e6–3.823043e7**, and full range **3.824619e5–1.027416e9** across 150 graphs. Absolute values depend on objective/violation scaling; the defensible result is the strong instance-to-instance variation.

## Recompute

From the package root, run either the one-pass engine:

```bash
python ANALYSIS/derived_diagnostics/recompute_derived_diagnostics.py . ANALYSIS/derived_diagnostics/_recomputed
```

or the individual convenience scripts:

```bash
python ANALYSIS/derived_diagnostics/critical_load_analysis.py
python ANALYSIS/derived_diagnostics/pareto_analysis.py
python ANALYSIS/derived_diagnostics/exact_penalty_bound.py
```

## Evidence boundary

These diagnostics support the generic **feasibility-first** analysis over the evaluated directional shared-airtime realization. They do not add physical 60-GHz validation or a full-planner transfer to a second application workload.
