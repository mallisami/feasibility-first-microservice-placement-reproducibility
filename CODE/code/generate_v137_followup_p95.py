#!/usr/bin/env python3
"""Generate the v1.37 request-rich P95 figure directly from retained raw result.json files.

This script is intentionally provenance-first: it validates the frozen one-condition,
ten-pair evidence, writes the exact figure-source CSV, computes the paired mean/Student-t
95% CI, and renders the publication figure. No P95 values are hard-coded.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
import sys

import numpy as np
from scipy.stats import t as student_t
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent))
import figure_style

figure_style.apply()

ROOT = Path(__file__).resolve().parents[2]
RAW = (
    ROOT
    / "EXPERIMENTS"
    / "k8s_v137_followup_20260917"
    / "results"
    / "item4-r1-replication"
    / "raw"
    / "r1"
    / "confirmatory-persistent-severe"
)
OUT = ROOT / "PAPER" / "figures" / "v03"
OUT.mkdir(parents=True, exist_ok=True)
SOURCE_CSV = OUT / "v137_followup_p95_source.csv"
EXPECTED_CONDITION = "confirmatory-persistent-severe"
METHODS = ("Current", "BPlus-Exact")
EXPECTED_REPLICATES = tuple(range(1, 11))
MIN_SUCCESS = 1000


def load_cell(rep: int, method: str) -> tuple[dict, Path]:
    path = RAW / f"replicate-{rep:02d}" / method / "attempt-01" / "result.json"
    if not path.is_file():
        raise FileNotFoundError(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("condition") != EXPECTED_CONDITION:
        raise ValueError(f"{path}: unexpected condition {data.get('condition')!r}")
    if data.get("method") != method:
        raise ValueError(f"{path}: unexpected method {data.get('method')!r}")
    if data.get("accepted") is not True:
        raise ValueError(f"{path}: cell is not accepted")
    if not data.get("health", {}).get("healthy", False):
        raise ValueError(f"{path}: final workload health is not true")
    app = data.get("application", {})
    successes = int(app.get("successes", -1))
    minimum = int(data.get("minimum_completed_requests", MIN_SUCCESS))
    if successes < max(MIN_SUCCESS, minimum):
        raise ValueError(f"{path}: successes={successes} below gate={max(MIN_SUCCESS, minimum)}")
    p95 = float(app["p95_ms"])
    if not np.isfinite(p95):
        raise ValueError(f"{path}: non-finite p95_ms")
    return data, path


rows: list[dict] = []
for rep in EXPECTED_REPLICATES:
    cells = {}
    paths = {}
    for method in METHODS:
        cells[method], paths[method] = load_cell(rep, method)
    current = cells["Current"]["application"]
    mape = cells["BPlus-Exact"]["application"]
    rows.append(
        {
            "replicate": rep,
            "condition": EXPECTED_CONDITION,
            "current_p95_ms": float(current["p95_ms"]),
            "mape_cap_ws_p95_ms": float(mape["p95_ms"]),
            "mape_minus_current_ms": float(mape["p95_ms"]) - float(current["p95_ms"]),
            "current_successes": int(current["successes"]),
            "mape_cap_ws_successes": int(mape["successes"]),
            "current_raw_result": str(paths["Current"].relative_to(ROOT)),
            "mape_cap_ws_raw_result": str(paths["BPlus-Exact"].relative_to(ROOT)),
        }
    )

with SOURCE_CSV.open("w", newline="", encoding="utf-8") as fh:
    writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)

current = np.array([r["current_p95_ms"] for r in rows], dtype=float)
mape = np.array([r["mape_cap_ws_p95_ms"] for r in rows], dtype=float)
diff = mape - current
n = len(diff)
mean_diff = float(diff.mean())
sd_diff = float(diff.std(ddof=1))
critical = float(student_t.ppf(0.975, df=n - 1))
halfwidth = critical * sd_diff / np.sqrt(n)
ci_low, ci_high = mean_diff - halfwidth, mean_diff + halfwidth

# Frozen-evidence assertions: fail loudly if the source files no longer reproduce the paper.
if n != 10:
    raise AssertionError(f"Expected 10 matched pairs, found {n}")
if not np.all(mape < current):
    raise AssertionError("Expected MAPE-CAP-WS P95 to be lower in all ten matched pairs")
if not np.isclose(current.mean(), 481.4, atol=1e-9):
    raise AssertionError(f"Unexpected Current mean: {current.mean()}")
if not np.isclose(mape.mean(), 224.8, atol=1e-9):
    raise AssertionError(f"Unexpected MAPE-CAP-WS mean: {mape.mean()}")
if not np.isclose(mean_diff, -256.6, atol=1e-9):
    raise AssertionError(f"Unexpected paired mean difference: {mean_diff}")

order = np.argsort(current)
current_plot = current[order]
mape_plot = mape[order]

fig, ax = plt.subplots(figsize=figure_style.FIGSIZE)
x_cur, x_mape = 0, 1
for c, m in zip(current_plot, mape_plot):
    ax.plot([x_cur, x_mape], [c, m], color=figure_style.COLORS["gray"], linewidth=0.9, alpha=0.7, zorder=1)
ax.scatter([x_cur] * n, current_plot, color=figure_style.COLORS["orange"], s=45, zorder=2, label="Current")
ax.scatter([x_mape] * n, mape_plot, color=figure_style.COLORS["blue"], s=45, zorder=2, label="MAPE-CAP-WS Exact")
ax.scatter([x_cur], [current.mean()], color=figure_style.COLORS["orange"], s=140, marker="_", linewidths=2.5, zorder=3)
ax.scatter([x_mape], [mape.mean()], color=figure_style.COLORS["blue"], s=140, marker="_", linewidths=2.5, zorder=3)
ax.set_xticks([x_cur, x_mape])
ax.set_xticklabels(["Current", "MAPE-CAP-WS Exact"])
ax.set_xlim(-0.4, 1.4)
ax.set_ylabel("Replicate P95 latency (ms)")
ax.set_title("v1.37 follow-up: severe persistent degradation\n(10 matched replicates, MAPE-CAP-WS lower in all 10 pairs)")
ax.grid(axis="y")
fig.text(
    0.5,
    0.01,
    (
        f"Mean P95: Current {current.mean():.1f} ms, MAPE-CAP-WS Exact {mape.mean():.1f} ms; "
        f"paired difference {mean_diff:.1f} ms (95% CI {ci_low:.1f} to {ci_high:.1f} ms). "
        "Single condition, single host, secondary evidence."
    ),
    ha="center",
    fontsize=figure_style.FONT_SIZE - 2,
)
fig.tight_layout(rect=[0, 0.09, 1, 1])
figure_style.save(fig, OUT / "v137_followup_p95.pdf")

print(f"source_csv={SOURCE_CSV.relative_to(ROOT)}")
print(f"n_pairs={n}")
print(f"current_mean_ms={current.mean():.1f}")
print(f"mape_mean_ms={mape.mean():.1f}")
print(f"paired_mean_difference_ms={mean_diff:.1f}")
print(f"paired_95ci_ms=[{ci_low:.1f}, {ci_high:.1f}]")
print(f"minimum_successes={min(min(r['current_successes'], r['mape_cap_ws_successes']) for r in rows)}")
