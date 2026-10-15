#!/usr/bin/env python3
"""Generate the single-state/multi-state forest plot directly from retained evidence.

No publication estimate is hard-coded. Single-state rows are read from the active
corrected PRIMARY_RESULT.json files. Multi-state rows are recomputed from the
60-cell full campaign JSONL using the documented graph-level pairing and fixed
bootstrap seeds. A machine-readable source CSV is emitted beside the figure.
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

K8S_PRIMARY = ROOT / "EXPERIMENTS/k8s_affinity_wireless_confirmatory/results/run-20260920T045006Z/PRIMARY_RESULT.json"
NS3_PRIMARY = ROOT / "EXPERIMENTS/ns3_affinity_wireless_confirmatory/results/run-20260920T043724Z/PRIMARY_RESULT.json"
MULTI_RAW = ROOT / "EXPERIMENTS/k8s_affinity_wireless_confirmatory/results/full-multiscenario-20260920.jsonl"
SOURCE_CSV = OUT / "multiscenario_forest_source.csv"


def percentile_bootstrap(values: np.ndarray, n_resamples: int, seed: int):
    values = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    chunks = []
    remain = n_resamples
    while remain:
        m = min(5000, remain)
        idx = rng.integers(0, len(values), size=(m, len(values)))
        chunks.append(values[idx].mean(axis=1))
        remain -= m
    boot = np.concatenate(chunks)
    return float(values.mean()), float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975))


def load_primary(path: Path, platform: str):
    obj = json.loads(path.read_text(encoding="utf-8"))["primary"]
    if platform == "k8s":
        return (float(obj["mean_bplus_minus_affinity"]), float(obj["bootstrap95_low"]),
                float(obj["bootstrap95_high"]), int(obj["n_paired_held_out_graphs"]))
    return (float(obj["mean_difference_bplus_minus_affinity"]), float(obj["bootstrap95_low"]),
            float(obj["bootstrap95_high"]), int(obj["n_paired_graphs"]))


def load_multi_differences(path: Path):
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_seed = {}
    for row in rows:
        by_seed.setdefault(int(row["seed"]), {})[row["method"]] = row
    if len(by_seed) != 30:
        raise RuntimeError(f"expected 30 multi-state graph identities; found {len(by_seed)}")
    out = {}
    for seed in sorted(by_seed):
        pair = by_seed[seed]
        if set(pair) != {"Affinity-Bytes", "BPlus-Exact"}:
            raise RuntimeError(f"incomplete multi-state pair for seed {seed}: {sorted(pair)}")
        out[seed] = (float(pair["BPlus-Exact"]["composite_scheduled_completion_fraction"]) -
                     float(pair["Affinity-Bytes"]["composite_scheduled_completion_fraction"]))
    return out


k_mean, k_lo, k_hi, k_n = load_primary(K8S_PRIMARY, "k8s")
n_mean, n_lo, n_hi, n_n = load_primary(NS3_PRIMARY, "ns3")
diffs = load_multi_differences(MULTI_RAW)
all_vals = np.asarray([diffs[s] for s in sorted(diffs)], dtype=float)
post_vals = np.asarray([diffs[s] for s in sorted(diffs) if s >= 44007], dtype=float)
# All-30 reproduces the frozen multi-state analysis seed inherited from the K8s parent protocol.
a_mean, a_lo, a_hi = percentile_bootstrap(all_vals, 100000, 20260915)
# The read-only Gate-3 post-pilot sensitivity has its own archived fixed seed.
p_mean, p_lo, p_hi = percentile_bootstrap(post_vals, 100000, 20260920)

# Guard against silent provenance drift.
assert k_n == 30 and n_n == 30 and len(all_vals) == 30 and len(post_vals) == 24
assert np.isclose(k_mean, -0.011092569259027244)
assert np.isclose(n_mean, -0.021911589918623946)
assert np.isclose(a_mean, 0.005561766792510355)
assert np.isclose(p_mean, 0.0038685833997381216)

rows = [
    ("Kubernetes, single-state (n=30)", k_mean, k_lo, k_hi, "corrected primary", K8S_PRIMARY),
    ("ns-3, single-state (n=30)", n_mean, n_lo, n_hi, "corrected primary", NS3_PRIMARY),
    ("Kubernetes, multi-state, all graphs (n=30)", a_mean, a_lo, a_hi, "exploratory all-graph", MULTI_RAW),
    ("Kubernetes, multi-state, post-pilot (n=24)", p_mean, p_lo, p_hi, "post-pilot sensitivity", MULTI_RAW),
]

with SOURCE_CSV.open("w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["label", "n", "mean_bplus_minus_affinity", "bootstrap95_low", "bootstrap95_high", "evidence_class", "source"])
    for label, mean, lo, hi, eclass, src in rows:
        n = int(label.rsplit("n=", 1)[1].rstrip(")"))
        w.writerow([label, n, f"{mean:.12f}", f"{lo:.12f}", f"{hi:.12f}", eclass, src.relative_to(ROOT).as_posix()])

labels = [r[0] for r in rows]
x = np.array([r[1] for r in rows])
lo = np.array([r[2] for r in rows])
hi = np.array([r[3] for r in rows])
y = np.arange(len(rows))
xerr = np.vstack([x - lo, hi - x])

fig, ax = plt.subplots(figsize=figure_style.FIGSIZE)
colors = [figure_style.COLORS["orange"], figure_style.COLORS["orange"], figure_style.COLORS["blue"], figure_style.COLORS["blue"]]
for yi, xi, lo_i, hi_i, c in zip(y, x, lo, hi, colors):
    ax.errorbar([xi], [yi], xerr=[[xi - lo_i], [hi_i - xi]], fmt="o", capsize=3,
                linewidth=1.1, ecolor=c, color=c, markersize=6)
ax.axvline(0, linestyle="--", linewidth=1, color="black")
ax.set_yticks(y, labels)
ax.invert_yaxis()
ax.set_xlabel("Paired mean difference, MAPE-CAP-WS Exact - Affinity-Bytes")
ax.set_title("Single-state versus weighted multi-state application endpoints")
ax.grid(axis="x", alpha=0.25)
fig.text(0.5, 0.01,
         "Graph-level percentile-bootstrap 95% intervals. Multi-state all-graph inference is exploratory because the first\n"
         "six graphs controlled scale-up; the 24-graph post-pilot row is the untouched sensitivity subset.",
         ha="center", fontsize=figure_style.FONT_SIZE - 2)
fig.tight_layout(rect=[0, 0.12, 1, 1])
figure_style.save(fig, OUT / "multiscenario_forest.pdf")
print(f"saved {OUT / 'multiscenario_forest.pdf'}")
print(f"source {SOURCE_CSV}")
for r in rows:
    print(r[:4])
