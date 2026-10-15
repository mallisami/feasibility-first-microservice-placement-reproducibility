#!/usr/bin/env python3
"""Generate the R1 paired-P95 forest plot from the frozen paired-statistics table."""
from pathlib import Path
import sys
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent))
import figure_style

figure_style.apply()

ROOT = Path(__file__).resolve().parents[2]
STATS = ROOT / "RESULTS" / "primary" / "v03-20260811T151500Z" / "derived" / "statistics" / "paired-statistics.csv"
OUT = ROOT / "PAPER" / "figures" / "v03"
ORDER = ["stable","persistent-degradation","partial-blockage","conflict-dense",
         "outage-with-fallback","recovery","bursty","hotspot","structural-workload-change"]
LABELS = {
    "stable":"Stable", "persistent-degradation":"Persistent degradation",
    "partial-blockage":"Partial blockage", "conflict-dense":"Conflict dense",
    "outage-with-fallback":"Outage fallback", "recovery":"Recovery",
    "bursty":"Bursty", "hotspot":"Hotspot",
    "structural-workload-change":"Structural workload change",
}

df = pd.read_csv(STATS)
d = df[(df.experiment=="R1") & (df.left_method=="BPlus-Exact")
       & (df.right_method=="Current") & (df.metric=="p95_ms")].copy()
d["ord"] = d["group"].map({g:i for i,g in enumerate(ORDER)})
d = d.sort_values("ord")
OUT.mkdir(parents=True, exist_ok=True)
d[["group","independent_replicate_n","paired_mean_difference","ci95_low","ci95_high",
   "effect_size_cohens_dz","raw_p_value_paired_t","robustness_wilcoxon_p",
   "adjusted_p_value_holm"]].to_csv(OUT/"r1_p95_forest_source.csv", index=False)

y = np.arange(len(d))
x = d.paired_mean_difference.to_numpy()
xerr = np.vstack([x-d.ci95_low.to_numpy(), d.ci95_high.to_numpy()-x])
fig, ax = plt.subplots(figsize=figure_style.FIGSIZE)
ax.errorbar(x, y, xerr=xerr, fmt="o", capsize=3, linewidth=1.1, color=figure_style.COLORS["blue"],
            ecolor=figure_style.COLORS["blue"])
ax.axvline(0, linestyle="--", linewidth=1, color="black")
ax.set_yticks(y)
ax.set_yticklabels([LABELS[g] for g in d["group"]])
ax.invert_yaxis()
ax.set_xlabel("Paired P95 difference, MAPE-CAP-WS Exact minus Current (ms)")
ax.set_title("R1 Online Boutique: paired P95 effects with 95% confidence intervals")
ax.grid(axis="x")
fig.text(0.5, 0.01,
         "Negative differences favor MAPE-CAP-WS Exact. All nine global Holm-adjusted p-values are 1.000.",
         ha="center", fontsize=figure_style.FONT_SIZE - 2)
fig.tight_layout(rect=[0, 0.08, 1, 1])
figure_style.save(fig, OUT / "r1_p95_forest.pdf")
