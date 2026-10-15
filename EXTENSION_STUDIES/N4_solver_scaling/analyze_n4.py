"""N4 pre-registered descriptive analysis (PROTOCOL_FROZEN.md, section "Analysis").

Usage: python analyze_n4.py <n4_rows.csv> <out_dir>
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import wilcoxon

rows = pd.read_csv(sys.argv[1])
OUT = Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)

ex = rows[rows.arm == "Exact"].set_index(["n", "seed"])
out = []
for arm in ("LNS-R8config", "LNS-noinit"):
    a = rows[rows.arm == arm].set_index(["n", "seed"])
    j = a.join(ex[["status", "objective", "lower_bound", "proven_optimal"]], rsuffix="_ex")
    opt = j.proven_optimal_ex.fillna(False).astype(bool)
    j["certified_gap"] = np.where(opt, (j.objective - j.objective_ex) / j.objective_ex.abs(), np.nan)
    j["gap_to_bound"] = np.where(~opt & j.lower_bound_ex.notna(),
                                 (j.objective - j.lower_bound_ex) / j.lower_bound_ex.abs(), np.nan)
    j["beats_exact_incumbent"] = np.where(~opt & j.objective_ex.notna(), j.objective < j.objective_ex, np.nan)
    j["arm"] = arm
    out.append(j.reset_index())
lns = pd.concat(out)
lns.to_csv(OUT / "n4_lns_gaps.csv", index=False)

e = rows[rows.arm == "Exact"].copy()
e["proven"] = e.proven_optimal.fillna(False).astype(bool)
exact_tab = e.groupby("n").agg(
    seeds=("seed", "size"), proven=("proven", "sum"),
    incumbent=("status", lambda s: int((s == "incumbent").sum())),
    no_incumbent=("status", lambda s: int((s == "no-incumbent").sum())),
    failure=("status", lambda s: int((s == "failure").sum())),
    median_mip_gap=("mip_gap", "median"), max_mip_gap=("mip_gap", "max"),
    median_runtime_s=("runtime_seconds", "median"), median_vars=("variable_count", "median")).reset_index()
exact_tab.to_csv(OUT / "n4_exact_by_n.csv", index=False)

lns_tab = lns.groupby(["arm", "n"]).agg(
    runs=("seed", "size"), feasible=("feasible", "sum"),
    median_certified_gap=("certified_gap", "median"), max_certified_gap=("certified_gap", "max"),
    median_gap_to_bound=("gap_to_bound", "median"),
    beats_exact_incumbent=("beats_exact_incumbent", "sum"),
    median_neighbourhoods=("iterations_completed", "median"),
    median_accepted=("accepted_improvements", "median"),
    median_runtime_s=("runtime_seconds", "median"), max_runtime_s=("runtime_seconds", "max")).reset_index()
lns_tab.to_csv(OUT / "n4_lns_by_n.csv", index=False)

pr = []
for n in sorted(rows.n.unique()):
    if n > 50:
        continue
    w = rows[rows.n == n].pivot(index="seed", columns="arm", values="objective")
    d = (w["LNS-noinit"] - w["LNS-R8config"]).dropna()
    nz = d[d != 0]
    pr.append({"n": int(n), "pairs": int(len(d)), "median_diff": float(d.median()),
               "median_rel_diff": float(((w["LNS-noinit"] - w["LNS-R8config"]) / w["LNS-R8config"].abs()).median()),
               "noinit_better": int((d < 0).sum()), "r8_better": int((d > 0).sum()),
               "wilcoxon_p": float(wilcoxon(nz).pvalue) if len(nz) > 0 else 1.0})
pd.DataFrame(pr).to_csv(OUT / "n4_noinit_vs_r8.csv", index=False)

pd.set_option("display.width", 250, "display.max_columns", 30)
print(exact_tab.to_string(index=False))
print(lns_tab.to_string(index=False))
print(pd.DataFrame(pr).to_string(index=False))
print(rows[rows.status == "failure"][["run_id", "error"]].to_string(index=False))
