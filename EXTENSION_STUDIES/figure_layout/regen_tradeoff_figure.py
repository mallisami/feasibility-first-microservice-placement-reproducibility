#!/usr/bin/env python3
"""Re-plot the affinity feasibility trade-off figure with a clearer layout (2026-09-26).

Data and selection are unchanged: the 24 discordant graphs come from the original generator's
load_discordant() (implementation/code/generate_affinity_feasibility_tradeoff.py, imported, not
modified), which reads the frozen 150-graph results at load 1.25 and asserts the paper's invariants.
Only the layout changes: one legend above both panels (it no longer sits beside the first data
point) and the utilization mean moved to an empty corner (it no longer covers instance 18).
Output goes to PAPER/figures/v03 at the package root.
"""
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
M = HERE.parents[2]
sys.path.insert(0, str(M / "implementation" / "code"))
import generate_affinity_feasibility_tradeoff as g  # noqa: E402

OUT = M / "PAPER" / "figures" / "v03"  # package layout (executed version wrote to the working manuscript folder)


def main() -> None:
    df = g.load_discordant()
    df.to_csv(OUT / "affinity_feasibility_tradeoff_source.csv", index=False)
    x = df["plot_order"].to_numpy()
    aff_b = df["cross_rack_bytes_Affinity-Bytes"].to_numpy() / 1e9
    mape_b = df["cross_rack_bytes_MAPE-CAP-WS-Exact"].to_numpy() / 1e9
    aff_u = df["worst_conflict_util_Affinity-Bytes"].to_numpy()
    mape_u = df["worst_conflict_util_MAPE-CAP-WS-Exact"].to_numpy()
    c_aff, c_mape, c_pair = "#D55E00", "#0072B2", "#B8B8B8"

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10.2, 3.6), layout="constrained")
    for ax, a, m in ((ax1, aff_b, mape_b), (ax2, aff_u, mape_u)):
        for i in range(len(x)):
            ax.plot([x[i], x[i]], [a[i], m[i]], color=c_pair, linewidth=0.65, zorder=1)
        ax.scatter(x, a, marker="x", s=29, linewidths=1.3, color=c_aff, label="Affinity-Bytes", zorder=3)
        ax.scatter(x, m, marker="o", s=26, facecolors="white", edgecolors=c_mape, linewidths=1.15,
                   label="MAPE-CAP-WS Exact", zorder=3)
        ax.set_xlim(0.3, 24.7)
        ax.grid(False)
    ax1.set_xlabel("Discordant graph instance (ordered by Affinity-Bytes utilization)")
    ax1.set_ylabel(r"Cross-rack traffic ($10^9$ bytes)")
    ax1.set_title("(a) Cross-rack communication", loc="left")
    ax1.text(0.98, 0.04, f"Mean paired increase: {df['paired_cross_rack_increase_pct'].mean():.1f}%",
             transform=ax1.transAxes, ha="right", va="bottom", fontsize=8.0)
    ax2.axhline(1.0, color="black", linestyle="--", linewidth=0.9, zorder=0)
    ax2.text(24.35, 1.008, "feasibility boundary", ha="right", va="bottom", fontsize=7.7)
    ax2.set_ylim(0.60, 1.48)
    ax2.set_xlabel("Same graph instances")
    ax2.set_ylabel("Worst conflict-group utilization")
    ax2.set_title("(b) Shared-airtime feasibility", loc="left")
    ax2.text(0.02, 0.97, f"Mean: {aff_u.mean():.3f} → {mape_u.mean():.3f}",
             transform=ax2.transAxes, ha="left", va="top", fontsize=8.0)
    handles, labels = ax1.get_legend_handles_labels()
    fig.legend(handles, labels, loc="outside upper center", ncol=2, frameon=False, fontsize=8.0)
    for ext, kw in (("pdf", {}), ("svg", {}), ("png", {"dpi": 600})):
        fig.savefig(OUT / f"affinity_feasibility_tradeoff.{ext}", bbox_inches="tight", **kw)
    plt.close(fig)
    print(f"24 graphs; mean increase {df['paired_cross_rack_increase_pct'].mean():.4f}%; "
          f"util {aff_u.mean():.6f} -> {mape_u.mean():.6f}; written to {OUT}")


if __name__ == "__main__":
    main()
