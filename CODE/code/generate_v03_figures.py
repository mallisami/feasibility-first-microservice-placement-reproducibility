#!/usr/bin/env python3
"""Generate v0.3 result figures from the validated campaign."""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path

import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import figure_style

SYSTEM = Path(__file__).resolve().parents[1]
ROOT = SYSTEM.parent
PACKAGED = SYSTEM.name == "implementation" and (ROOT / "RESULTS").exists()
if PACKAGED:
    RUN = ROOT / "RESULTS" / "primary" / "v03-20260811T151500Z"
    FIGURES = ROOT / "PAPER" / "figures" / "v03"
else:
    RUN = SYSTEM / "results" / "v0.3" / "runs" / "v03-20260811T151500Z"
    FIGURES = ROOT / "01_PAPER" / "BPLUS_MANUSCRIPT" / "figures" / "v03"
DERIVED = RUN / "derived" / "regenerated"

COLORS = {"Baseline": figure_style.COLORS["gray"], "BPlus": figure_style.COLORS["blue"],
          "Exact": figure_style.COLORS["orange"], "LNS": figure_style.COLORS["green"]}


def load(name: str) -> list[dict[str, str]]:
    with (DERIVED / name).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def save(fig: plt.Figure, name: str) -> None:
    figure_style.save(fig, FIGURES / name)


def deathstar() -> None:
    data = load("r7-aggregate.csv")
    conditions = ["stable", "degradation", "conflict", "recovery"]
    metrics = [
        ("mean_throughput_rps", "Throughput (requests/s)", True, lambda d: float(d["workload"]["requests_per_second"])),
        ("mean_p99_ms", "P99 latency (ms)", False, lambda d: float(d["workload"]["latency"]["p99_ms"])),
        ("mean_errors", "Errors per replicate", False, lambda d: float(d["workload"]["total_errors"])),
        ("mean_downtime_seconds", "Downtime (s)", False, lambda d: float(d["probe"]["downtime_seconds"])),
    ]
    lookup = {(row["condition"], row["method"]): row for row in data}
    raw_lookup: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for path in sorted((RUN / "raw" / "r7").glob("*/replicate-*/*/result.json")):
        d = json.loads(path.read_text(encoding="utf-8"))
        if d.get("accepted"):
            raw_lookup[(d["condition"], d["method"])].append(d)
    fig, axes = plt.subplots(2, 2, figsize=figure_style.FIGSIZE)
    x = np.arange(len(conditions))
    width = 0.36
    jitter = np.linspace(-0.055, 0.055, 5)
    for ax, (field, ylabel, higher_better, raw_value) in zip(axes.flat, metrics):
        for offset, method in [(-width / 2, "Baseline"), (width / 2, "BPlus")]:
            values = [float(lookup[(condition, method)][field]) for condition in conditions]
            ax.bar(x + offset, values, width, label="FixedTarget" if method == "BPlus" else method,
                   color=COLORS[method], edgecolor="black", linewidth=0.5, alpha=0.82,
                   hatch="//" if method == "BPlus" else "")
            for ci, condition in enumerate(conditions):
                vals = [raw_value(d) for d in sorted(raw_lookup[(condition, method)], key=lambda z: int(z["replicate"]))]
                ax.scatter(np.full(len(vals), x[ci] + offset) + jitter[:len(vals)], vals,
                           s=12, color=COLORS[method], edgecolor="black", linewidth=0.25, zorder=3)
                if len(vals) > 1:
                    # Two-sided 95% Student-t interval for n=5 (df=4).
                    half_width = 2.776 * float(np.std(vals, ddof=1)) / math.sqrt(len(vals))
                    ax.errorbar(x[ci] + offset, float(np.mean(vals)), yerr=half_width,
                                fmt="none", ecolor="black", elinewidth=0.8,
                                capsize=2.2, capthick=0.8, zorder=4)
        ax.set_xticks(x)
        ax.set_xticklabels(["Stable", "Degradation", "Conflict", "Recovery"], rotation=18, ha="right")
        ax.set_ylabel(ylabel)
        ax.grid(axis="y")
        ax.text(0.99, 1.02, "higher is better" if higher_better else "lower is better",
                transform=ax.transAxes, ha="right", va="bottom", fontsize=figure_style.FONT_SIZE, color="#4B5563")
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, 0.945), ncol=2, frameon=False,
               fontsize=figure_style.FONT_SIZE)
    fig.suptitle("Official DeathStarBench: fixed-target relocation trade-offs", y=0.995, fontsize=figure_style.FONT_SIZE)
    fig.tight_layout(rect=(0, 0, 1, 0.88))
    save(fig, "deathstar_tradeoffs.pdf")


def relocation() -> None:
    data = load("r4-aggregate.csv")
    storage = ["emptydir", "persistent-volume", "application-replication"]
    labels = ["emptyDir", "Persistent volume", "App. replication"]
    means = {}
    for key in storage:
        group = [row for row in data if row["storage"] == key]
        means[key] = {
            "relocation": np.mean([float(row["mean_relocation_seconds"]) for row in group]),
            "downtime": np.mean([float(row["mean_downtime_seconds"]) for row in group]),
            "failed": np.mean([float(row["mean_failed_requests"]) for row in group]),
        }
    image = {}
    for key in ["cached", "uncached"]:
        group = [row for row in data if row["image_state"] == key]
        image[key] = np.mean([float(row["mean_relocation_seconds"]) for row in group])

    fig, axes = plt.subplots(1, 3, figsize=figure_style.FIGSIZE)
    x = np.arange(3)
    axes[0].bar(x, [means[k]["relocation"] for k in storage], color=figure_style.COLORS["blue"])
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(labels)
    axes[0].set_ylabel("Mean relocation time (s)")
    axes[1].bar(x, [means[k]["downtime"] for k in storage], color=figure_style.COLORS["orange"])
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(labels)
    axes[1].set_ylabel("Mean downtime (s)")
    axes[2].bar([0, 1], [image["cached"], image["uncached"]],
                color=[figure_style.COLORS["green"], figure_style.COLORS["navy"]])
    axes[2].set_xticks([0, 1])
    axes[2].set_xticklabels(["Cached", "Uncached"])
    axes[2].set_ylabel("Mean relocation time (s)")
    for ax in axes:
        ax.grid(axis="y")
        ax.tick_params(axis="x", labelsize=figure_style.FONT_SIZE, labelrotation=20)
        for tick in ax.get_xticklabels():
            tick.set_ha("right")
        ax.margins(x=0.10)
    fig.suptitle("Relocation disruption depends on storage and image state", y=1.02, fontsize=figure_style.FONT_SIZE)
    fig.tight_layout()
    save(fig, "relocation_matrix_summary.pdf")


def r5_service_period() -> None:
    with (DERIVED / "r5-effective-status.csv").open(newline="", encoding="utf-8") as stream:
        data = list(csv.DictReader(stream))
    durations = [1600, 3200, 6400]
    means = []
    seed_values = []
    for duration in durations:
        scenario = f"service-period-{duration}us"
        vals = []
        for row in data:
            if row["scenario"] != scenario or not row.get("goodput_timeseries"):
                continue
            series = json.loads(row["goodput_timeseries"])
            vals.append(float(np.mean([float(x["goodput_mbps"]) for x in series])))
        seed_values.append(vals)
        means.append(float(np.mean(vals)))
    xs = [1.6, 3.2, 6.4]
    fig, ax = plt.subplots(figsize=figure_style.FIGSIZE)
    line, = ax.plot(xs, means, marker="o", linewidth=1.8, label="three-seed mean", color=figure_style.COLORS["blue"])
    jitter = [-0.08, 0.0, 0.08]
    for x, vals in zip(xs, seed_values):
        ax.scatter([x + jitter[i] for i in range(len(vals))], vals, s=24,
                   color=line.get_color(), edgecolor="black", linewidth=0.35, alpha=0.8, zorder=3)
    ax.set_xlabel("Service-period duration (ms)")
    ax.set_ylabel("Simulator goodput (Mb/s)")
    ax.set_xticks(xs)
    ax.grid(axis="y")
    ax.set_title("R5: service-period allocation changes packet-level goodput")
    fig.tight_layout()
    save(fig, "r5_service_period_goodput.pdf")


def r6_uncertainty() -> None:
    data = load("r6-aggregate.csv")
    with (RUN / "raw" / "phase-3-r6-results.csv").open(newline="", encoding="utf-8") as stream:
        raw = list(csv.DictReader(stream))
    sizes = [3, 5, 10, 20, 50]
    methods = ["BPlus-CVaR", "Deterministic", "ExpectedValue", "Minimax"]
    labels = {"BPlus-CVaR": "MAPE-CAP-WS CVaR", "Deterministic": "Deterministic", "ExpectedValue": "Expected value", "Minimax": "Minimax"}
    fig, ax = plt.subplots(figsize=figure_style.FIGSIZE)
    markers = ["o", "s", "^", "D"]
    for method, marker in zip(methods, markers):
        values=[]
        raw_groups=[]
        for n in sizes:
            candidates=[x for x in data if x["method"]==method and x["probability_model"]=="empirical" and int(x["scenario_count"])==n]
            if method=="BPlus-CVaR":
                candidates=[x for x in candidates if x["quantile"]=="0.9"]
            values.append(float(candidates[0]["mean_tail_p95"]))
            rr=[x for x in raw if x["method"]==method and x["probability_model"]=="empirical" and int(x["scenario_count"])==n]
            if method=="BPlus-CVaR":
                rr=[x for x in rr if x["quantile"]=="0.9"]
            raw_groups.append(sorted([float(x["heldout_tail_p95"]) for x in rr], reverse=False))
        line, = ax.plot(sizes, values, marker=marker, label=labels[method], linewidth=1.5)
        for n, vals in zip(sizes, raw_groups):
            factors=np.linspace(0.96,1.04,len(vals)) if vals else []
            ax.scatter([n*f for f in factors], vals, s=13, color=line.get_color(),
                       edgecolor="black", linewidth=0.25, alpha=0.55, zorder=3)
    ax.set_xlabel("Generated training scenarios\n(max 5 source identities)")
    ax.set_ylabel("Maximum held-out planning cost")
    ax.set_xscale("log")
    ax.set_xticks(sizes)
    ax.set_xticklabels([str(x) for x in sizes])
    ax.grid(axis="y")
    ax.legend(frameon=False, fontsize=figure_style.FONT_SIZE, ncol=2)
    ax.set_title("R6: held-out source-identity robustness")
    fig.tight_layout()
    save(fig, "r6_uncertainty_tail.pdf")


def scalability() -> None:
    data = load("r8-aggregate.csv")
    with (RUN / "raw" / "phase-4-r8-results.csv").open(newline="", encoding="utf-8") as stream:
        raw = list(csv.DictReader(stream))
    sizes = [6, 8, 10, 12, 16, 20, 24, 40, 50]
    lookup = {(int(row["replica_count"]), row["method"]): row for row in data}
    exact_rt = [float(lookup[(size, "Exact")]["mean_runtime_seconds"]) for size in sizes]
    lns_rt = [float(lookup[(size, "LNS")]["mean_runtime_seconds"]) for size in sizes]
    pairs=defaultdict(dict)
    for row in raw:
        pairs[(int(row["replica_count"]), int(row["seed"]))][row["method"]]=row
    certified=[]
    timeout_gap=[]
    for size in sizes:
        cert=[]; tg=[]
        for seed in [1,2,3]:
            p=pairs[(size,seed)]
            if p["Exact"].get("proven_optimal")=="True":
                opt=float(p["Exact"]["objective"]); lv=float(p["LNS"]["objective"])
                cert.append((lv-opt)/abs(opt)*100 if opt else math.nan)
            elif p["Exact"].get("mip_gap") not in (None, ""):
                tg.append(float(p["Exact"]["mip_gap"])*100)
        certified.append(float(np.mean(cert)) if cert else math.nan)
        timeout_gap.append(float(np.mean(tg)) if tg else math.nan)
    fig, axes = plt.subplots(1, 2, figsize=figure_style.FIGSIZE)
    exact_line, = axes[0].plot(sizes, exact_rt, marker="o", label="Exact / incumbent", color=figure_style.COLORS["orange"])
    lns_line, = axes[0].plot(sizes, lns_rt, marker="s", label="LNS", color=figure_style.COLORS["green"])
    for method, line, factor_base in [("Exact", exact_line, 0.985), ("LNS", lns_line, 1.015)]:
        for size in sizes:
            vals=[float(row["runtime_seconds"]) for row in raw if int(row["replica_count"])==size and row["method"]==method]
            factors=np.linspace(factor_base-0.006, factor_base+0.006, len(vals))
            axes[0].scatter([size*f for f in factors], vals, s=11, color=line.get_color(),
                            edgecolor="black", linewidth=0.2, alpha=0.55, zorder=3)
    axes[0].set_xlabel("Replicas")
    axes[0].set_ylabel("Mean runtime (s)")
    axes[0].legend(frameon=False, fontsize=figure_style.FONT_SIZE)
    x=np.arange(len(sizes)); width=0.36
    axes[1].bar(x-width/2, [0 if math.isnan(v) else v for v in certified], width, label="Certified LNS gap",
                color=figure_style.COLORS["blue"])
    axes[1].bar(x+width/2, [0 if math.isnan(v) else v for v in timeout_gap], width, label="Exact timeout MIP gap",
                color=figure_style.COLORS["gray"])
    axes[1].set_xticks(x)
    axes[1].set_xticklabels([str(size) for size in sizes])
    axes[1].set_xlabel("Replicas")
    axes[1].set_ylabel("Gap (%)")
    axes[1].legend(frameon=False, fontsize=figure_style.FONT_SIZE)
    axes[1].text(0.02, 0.97, "Certified LNS bars use proven Exact seeds only", transform=axes[1].transAxes,
                 ha="left", va="top", fontsize=figure_style.FONT_SIZE)
    for ax in axes:
        ax.grid(axis="y")
    fig.suptitle("R8: runtime and status-aware solution quality", y=1.02, fontsize=figure_style.FONT_SIZE)
    fig.tight_layout()
    save(fig, "scalability_v03.pdf")


def main() -> int:
    figure_style.apply()
    deathstar()
    relocation()
    r5_service_period()
    r6_uncertainty()
    scalability()
    print(f"Generated v0.3 figures in {FIGURES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
