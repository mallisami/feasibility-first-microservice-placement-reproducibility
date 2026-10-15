#!/usr/bin/env python3
"""Revision figures from N2/N3 outputs.

Fig. R1 (regime map): (a) admissibility vs load for Current, Affinity-Bytes and the
admission-constrained methods; (b) mean planning-state airtime headroom of the two admission-
constrained rankings. Fig. R2 (outage rotation, post hoc): graphs that remain admissible when
each rack pair fails, at load 1.25.

Palette follows the manuscript's existing figures (Okabe-Ito), with marker/line-style
redundancy so identity never relies on colour alone.
"""
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[2] / "PAPER" / "figures" / "rev"  # package layout: <root>/EXTENSION_STUDIES/2026-09-26/<study>/ -> <root>/PAPER (executed version wrote to the working manuscript folder)
OUT.mkdir(parents=True, exist_ok=True)

plt.rcParams.update({"pdf.fonttype": 42, "ps.fonttype": 42, "font.size": 9.0, "axes.titlesize": 9.5,
                     "axes.labelsize": 9.0, "xtick.labelsize": 8.0, "ytick.labelsize": 8.0,
                     "legend.fontsize": 7.8, "axes.spines.top": False, "axes.spines.right": False})
C_CUR, C_AFF, C_ADM, C_MAPE = "#7F7F7F", "#D55E00", "#009E73", "#0072B2"
INK2 = "#555555"


def regime_map():
    f = pd.read_csv(HERE / "fine_grid.csv")
    n = f.groupby(["target", "method"]).admissible.sum().unstack() / 150.0
    t = n.index.to_numpy()
    fig, (a, b) = plt.subplots(1, 2, figsize=(7.1, 2.75), constrained_layout=True)

    a.plot(t, n["Current"], color=C_CUR, ls="--", lw=1.6, label="Current (no action)")
    a.plot(t, n["Affinity-Bytes"], color=C_AFF, marker="x", ms=4, lw=1.6, markevery=2, label="Affinity-Bytes")
    a.plot(t, n["MAPE-CAP-WS"], color=C_MAPE, marker="o", ms=3.6, mfc="white", lw=1.6, markevery=2,
           label="Admission-constrained\n(any ranking)")
    gap = (n["Current"] >= 1.0 - 1e-9) & (n["Affinity-Bytes"] < 1.0)
    if gap.any():
        lo, hi = t[gap.to_numpy()].min(), t[gap.to_numpy()].max()
        a.axvspan(lo - 0.025, hi + 0.025, color="#E8E8E8", zorder=0, lw=0)
        a.annotate("locality-induced\ninadmissibility", xy=(hi, 0.955), xytext=(1.22, 0.60),
                   ha="left", va="center", fontsize=7.2, color=INK2,
                   arrowprops=dict(arrowstyle="-", color=INK2, lw=0.7))
    a.set_xlabel("Load τ (Current's worst conflict-group utilization)")
    a.set_ylabel("Fraction of 150 graphs admissible")
    a.set_ylim(-0.02, 1.05)
    a.set_title("(a) Admissibility under rising shared-airtime load", loc="left")
    a.legend(frameon=False, loc="lower left", bbox_to_anchor=(0.0, 0.18))

    adm = f[f.method.isin(["Affinity-Bytes+Admission", "MAPE-CAP-WS"]) & f.admissible.astype(bool)]
    h = adm.groupby(["target", "method"]).headroom.mean().unstack()
    b.plot(h.index, h["Affinity-Bytes+Admission"], color=C_ADM, marker="s", ms=3.4, lw=1.6, markevery=2,
           label="Affinity-Bytes+Admission")
    b.plot(h.index, h["MAPE-CAP-WS"], color=C_MAPE, marker="o", ms=3.6, mfc="white", lw=1.6, markevery=2,
           label="MAPE-CAP-WS")
    b.set_xlabel("Load τ (Current's worst conflict-group utilization)")
    b.set_ylabel("Mean airtime headroom (1 − U$_{max}$)")
    b.set_ylim(0, None)
    b.set_title("(b) Headroom retained among admissible placements", loc="left")
    b.legend(frameon=False, loc="upper right")
    for ax in (a, b):
        ax.grid(False)
    for ext in ("pdf", "png"):
        fig.savefig(OUT / f"regime_map.{ext}", dpi=600 if ext == "png" else None, bbox_inches="tight")
    plt.close(fig)
    src = n.join(h.add_prefix("headroom_"))
    src.to_csv(OUT / "regime_map_source.csv")


def outage_rotation():
    s = pd.read_csv(HERE / "n3b_outage_rotation_summary.csv")
    s = s[np.isclose(s.target, 1.25)].set_index("method")
    pairs = ["outage-ab-down", "outage-ac-down", "outage-bc-down"]
    labels = ["A–B down", "A–C down", "B–C down\n(library state)"]
    methods = [("Affinity-Bytes+Admission", "Affinity-Bytes+Admission", C_ADM, None),
               ("MAPE-CAP-WS Risk-off", "Risk-off (λ = 0)", "#BBBBBB", "///"),
               ("MAPE-CAP-WS", "MAPE-CAP-WS", C_MAPE, None)]
    x = np.arange(len(pairs))
    w = 0.26
    fig, ax = plt.subplots(figsize=(3.45, 2.6), constrained_layout=True)
    for i, (m, lab, col, hatch) in enumerate(methods):
        vals = s.loc[m, pairs].to_numpy(dtype=float)
        bars = ax.bar(x + (i - 1) * w, vals, w - 0.03, color=col, hatch=hatch, edgecolor="white", lw=0.6, label=lab)
        for bx, v in zip(bars, vals):
            ax.text(bx.get_x() + bx.get_width() / 2, v + 1.5, f"{int(v)}", ha="center", va="bottom", fontsize=6.8, color=INK2)
    ax.set_xticks(x, labels)
    ax.set_ylabel("Graphs admissible (of 150)")
    ax.set_ylim(0, 118)
    ax.set_yticks(range(0, 90, 20))
    ax.set_title("Withheld outage, rotated over rack pairs (τ = 1.25)", loc="left", fontsize=8.6)
    ax.legend(frameon=False, loc="upper left", fontsize=7.0, ncol=1, borderaxespad=0.1)
    ax.grid(False)
    for ext in ("pdf", "png"):
        fig.savefig(OUT / f"outage_rotation.{ext}", dpi=600 if ext == "png" else None, bbox_inches="tight")
    plt.close(fig)
    s.loc[[m for m, *_ in methods], pairs].to_csv(OUT / "outage_rotation_source.csv")


if __name__ == "__main__":
    regime_map()
    outage_rotation()
    print("figures written to", OUT)
