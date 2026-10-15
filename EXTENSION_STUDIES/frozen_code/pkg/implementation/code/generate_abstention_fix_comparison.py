#!/usr/bin/env python3
"""Generate the supplementary abstention-fallback diagnostic from retained summaries.

The all-graph bars are read from the original/corrected campaign PRIMARY_RESULT files.
The corrected committed/abstained strata are read from the executable post-hoc
seed-matched decomposition. No displayed estimate is hard-coded.
"""
from pathlib import Path
import csv
import json
import sys
import numpy as np
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent))
import figure_style

figure_style.apply()
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "PAPER" / "figures" / "v03"
OUT.mkdir(parents=True, exist_ok=True)

K8S_ORIG = ROOT / "EXPERIMENTS/k8s_affinity_wireless_confirmatory/results/run-20260916T051604Z/PRIMARY_RESULT.json"
K8S_POST = ROOT / "EXPERIMENTS/k8s_affinity_wireless_confirmatory/results/run-20260920T045006Z/PRIMARY_RESULT.json"
NS3_ORIG = ROOT / "EXPERIMENTS/ns3_affinity_wireless_confirmatory/results/run-20260916T134114Z/PRIMARY_RESULT.json"
NS3_POST = ROOT / "EXPERIMENTS/ns3_affinity_wireless_confirmatory/results/run-20260920T043724Z/PRIMARY_RESULT.json"
DECOMP = ROOT / "ANALYSIS/derived/posthoc_decomposition_summary.json"
SOURCE_CSV = OUT / "abstention_fix_comparison_source.csv"


def primary_mean(path: Path, field: str):
    return float(json.loads(path.read_text(encoding="utf-8"))["primary"][field])

orig = [primary_mean(K8S_ORIG, "mean_bplus_minus_affinity"),
        primary_mean(NS3_ORIG, "mean_difference_bplus_minus_affinity")]
corrected = [primary_mean(K8S_POST, "mean_bplus_minus_affinity"),
             primary_mean(NS3_POST, "mean_difference_bplus_minus_affinity")]
dec = json.loads(DECOMP.read_text(encoding="utf-8"))["postfix_campaign"]
strata = [
    ("K8s\ncommitted", float(dec["kubernetes"]["mean_committed"]), 28),
    ("K8s\nabstained", float(dec["kubernetes"]["mean_abstained"]), 2),
    ("ns-3\ncommitted", float(dec["ns3"]["mean_committed"]), 28),
    ("ns-3\nabstained", float(dec["ns3"]["mean_abstained"]), 2),
]
assert np.isclose(corrected[0], dec["kubernetes"]["mean_all"])
assert np.isclose(corrected[1], dec["ns3"]["mean_all"])

with SOURCE_CSV.open("w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["panel", "platform_or_stratum", "campaign", "n", "mean_difference", "source"])
    w.writerow(["all_graph", "Kubernetes", "original", 30, f"{orig[0]:.12f}", K8S_ORIG.relative_to(ROOT).as_posix()])
    w.writerow(["all_graph", "Kubernetes", "corrected", 30, f"{corrected[0]:.12f}", K8S_POST.relative_to(ROOT).as_posix()])
    w.writerow(["all_graph", "ns-3", "original", 30, f"{orig[1]:.12f}", NS3_ORIG.relative_to(ROOT).as_posix()])
    w.writerow(["all_graph", "ns-3", "corrected", 30, f"{corrected[1]:.12f}", NS3_POST.relative_to(ROOT).as_posix()])
    for label, value, n in strata:
        w.writerow(["corrected_stratum", label.replace("\n", " "), "corrected", n, f"{value:.12f}", DECOMP.relative_to(ROOT).as_posix()])

fig, axes = plt.subplots(1, 2, figsize=figure_style.FIGSIZE)
# Panel 1: all-graph primary means, original vs corrected.
groups = ["Kubernetes", "ns-3"]
x = np.arange(len(groups)); width = 0.32
ax = axes[0]
ax.bar(x - width / 2, orig, width=width, color=figure_style.COLORS["gray"], label="Original")
ax.bar(x + width / 2, corrected, width=width, color=figure_style.COLORS["blue"], label="Corrected")
ax.axhline(0, color="black", linewidth=0.8)
ax.set_xticks(x); ax.set_xticklabels(groups)
ax.set_ylabel("Paired mean difference,\nMAPE-CAP-WS minus Affinity")
ax.set_title("All-graph primary result", fontsize=figure_style.FONT_SIZE)
ax.legend(fontsize=figure_style.FONT_SIZE - 3, loc="lower left")
ax.grid(axis="y")

# Panel 2: corrected campaign stratification.
ax = axes[1]
labels = [s[0] for s in strata]; vals = [s[1] for s in strata]
bar_colors = [figure_style.COLORS["blue"], figure_style.COLORS["orange"], figure_style.COLORS["blue"], figure_style.COLORS["orange"]]
xb = np.arange(len(labels))
ax.bar(xb, vals, color=bar_colors)
ax.axhline(0, color="black", linewidth=0.8)
ax.set_xticks(xb); ax.set_xticklabels(labels, fontsize=figure_style.FONT_SIZE - 3)
ax.set_title("Corrected campaign,\nstratified by abstention (n=28/n=2)", fontsize=figure_style.FONT_SIZE)
ax.grid(axis="y")

fig.text(0.5, 0.01,
         "Left: original stale-Current fallback versus corrected two-tier fallback. Right: descriptive corrected strata;\n"
         "the two abstained graphs are retained in the all-graph primary estimates and are not removed from inference.",
         ha="center", fontsize=figure_style.FONT_SIZE - 2)
fig.tight_layout(rect=[0, 0.12, 1, 1])
figure_style.save(fig, OUT / "abstention_fix_comparison.pdf")
print(f"saved {OUT / 'abstention_fix_comparison.pdf'}")
print(f"source {SOURCE_CSV}")
