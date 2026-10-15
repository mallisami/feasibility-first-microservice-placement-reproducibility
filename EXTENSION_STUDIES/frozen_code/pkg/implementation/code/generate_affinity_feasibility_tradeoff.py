#!/usr/bin/env python3
"""Generate the controlled Affinity-Bytes vs MAPE-CAP-WS feasibility trade-off figure.

Source data are the frozen 150-graph computational-confirmation results at target load 1.25.
The figure displays exactly the 24 graph instances for which Affinity-Bytes is infeasible
while MAPE-CAP-WS Exact (legacy artifact name BPlus-Exact) remains feasible.
"""
from __future__ import annotations

from pathlib import Path
import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "RESULTS" / "post-manuscript" / "affinity-wireless-computational-confirmation-20260915" / "cell_results.csv"
OUT = REPO / "PAPER" / "figures" / "v03"
OUT.mkdir(parents=True, exist_ok=True)

# Preserve editable/searchable text with embedded TrueType fonts in the PDF.
plt.rcParams.update({
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
    "font.size": 9.0,
    "axes.titlesize": 9.5,
    "axes.labelsize": 9.0,
    "xtick.labelsize": 8.0,
    "ytick.labelsize": 8.0,
    "legend.fontsize": 8.0,
})

AFF = "Affinity-Bytes"
MAPE_ARTIFACT = "BPlus-Exact"
TARGET = 1.25


def load_discordant() -> pd.DataFrame:
    raw = pd.read_csv(DATA)
    selected = raw[
        np.isclose(raw["target_current_util"].astype(float), TARGET)
        & raw["method"].isin([AFF, MAPE_ARTIFACT])
    ].copy()

    # The frozen experiment contains 150 graph identities and two compared methods.
    if selected["instance_id"].nunique() != 150 or len(selected) != 300:
        raise RuntimeError("Unexpected frozen 1.25-load experiment cardinality")

    wide = selected.pivot(index="instance_id", columns="method")
    discordant_ids = wide.index[
        (wide["feasible"][MAPE_ARTIFACT].astype(bool))
        & (~wide["feasible"][AFF].astype(bool))
    ]
    if len(discordant_ids) != 24:
        raise RuntimeError(f"Expected 24 primary discordant graphs, found {len(discordant_ids)}")

    rows = []
    for instance_id in discordant_ids:
        a = selected[(selected["instance_id"] == instance_id) & (selected["method"] == AFF)].iloc[0]
        m = selected[(selected["instance_id"] == instance_id) & (selected["method"] == MAPE_ARTIFACT)].iloc[0]
        rows.append({
            "instance_id": instance_id,
            "cross_rack_bytes_Affinity-Bytes": float(a["cross_rack_bytes"]),
            "cross_rack_bytes_MAPE-CAP-WS-Exact": float(m["cross_rack_bytes"]),
            "worst_conflict_util_Affinity-Bytes": float(a["worst_conflict_util"]),
            "worst_conflict_util_MAPE-CAP-WS-Exact": float(m["worst_conflict_util"]),
        })
    df = pd.DataFrame(rows)
    df["paired_cross_rack_increase_pct"] = 100.0 * (
        df["cross_rack_bytes_MAPE-CAP-WS-Exact"] - df["cross_rack_bytes_Affinity-Bytes"]
    ) / df["cross_rack_bytes_Affinity-Bytes"]

    # Freeze the plotted order by increasing Affinity-Bytes conflict utilization.
    df = df.sort_values(["worst_conflict_util_Affinity-Bytes", "instance_id"]).reset_index(drop=True)
    df.insert(0, "plot_order", np.arange(1, len(df) + 1))

    # Scientific invariants asserted by the manuscript.
    if not (df["worst_conflict_util_Affinity-Bytes"] > 1.0).all():
        raise RuntimeError("Not all Affinity-Bytes discordant placements exceed the feasibility boundary")
    if not (df["worst_conflict_util_MAPE-CAP-WS-Exact"] <= 1.0).all():
        raise RuntimeError("A MAPE-CAP-WS discordant placement exceeds the feasibility boundary")
    return df


def main() -> None:
    df = load_discordant()
    source_csv = OUT / "affinity_feasibility_tradeoff_source.csv"
    df.to_csv(source_csv, index=False)

    x = df["plot_order"].to_numpy()
    aff_bytes = df["cross_rack_bytes_Affinity-Bytes"].to_numpy() / 1e9
    mape_bytes = df["cross_rack_bytes_MAPE-CAP-WS-Exact"].to_numpy() / 1e9
    aff_util = df["worst_conflict_util_Affinity-Bytes"].to_numpy()
    mape_util = df["worst_conflict_util_MAPE-CAP-WS-Exact"].to_numpy()

    # Colorblind-safe endpoints plus neutral connectors; marker shape preserves grayscale readability.
    c_aff = "#D55E00"
    c_mape = "#0072B2"
    c_pair = "#B8B8B8"

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10.2, 3.45), constrained_layout=True)

    for i in range(len(df)):
        ax1.plot([x[i], x[i]], [aff_bytes[i], mape_bytes[i]], color=c_pair, linewidth=0.65, zorder=1)
    ax1.scatter(x, aff_bytes, marker="x", s=29, linewidths=1.3, color=c_aff, label="Affinity-Bytes", zorder=3)
    ax1.scatter(x, mape_bytes, marker="o", s=26, facecolors="white", edgecolors=c_mape,
                linewidths=1.15, label="MAPE-CAP-WS Exact", zorder=3)
    ax1.set_xlim(0.3, 24.7)
    ax1.set_xlabel("Discordant graph instance")
    ax1.set_ylabel(r"Cross-rack traffic ($10^9$ bytes)")
    ax1.set_title("(a) Cross-rack communication", loc="left")
    ax1.legend(frameon=False, loc="upper left")
    ax1.text(0.98, 0.04, f"Mean paired increase: {df['paired_cross_rack_increase_pct'].mean():.1f}%",
             transform=ax1.transAxes, ha="right", va="bottom", fontsize=8.0)

    for i in range(len(df)):
        ax2.plot([x[i], x[i]], [aff_util[i], mape_util[i]], color=c_pair, linewidth=0.65, zorder=1)
    ax2.scatter(x, aff_util, marker="x", s=29, linewidths=1.3, color=c_aff, label="Affinity-Bytes", zorder=3)
    ax2.scatter(x, mape_util, marker="o", s=26, facecolors="white", edgecolors=c_mape,
                linewidths=1.15, label="MAPE-CAP-WS Exact", zorder=3)
    ax2.axhline(1.0, color="black", linestyle="--", linewidth=0.9, zorder=0)
    ax2.text(24.35, 1.008, "feasibility boundary", ha="right", va="bottom", fontsize=7.7)
    ax2.set_xlim(0.3, 24.7)
    ax2.set_ylim(0.60, 1.48)
    ax2.set_xlabel("Same graph instances")
    ax2.set_ylabel("Worst conflict-group utilization")
    ax2.set_title("(b) Shared-airtime feasibility", loc="left")
    ax2.text(0.98, 0.04, f"Mean: {aff_util.mean():.3f} -> {mape_util.mean():.3f}",
             transform=ax2.transAxes, ha="right", va="bottom", fontsize=8.0)

    for ax in (ax1, ax2):
        ax.grid(False)

    out_pdf = OUT / "affinity_feasibility_tradeoff.pdf"
    out_svg = OUT / "affinity_feasibility_tradeoff.svg"
    out_png = OUT / "affinity_feasibility_tradeoff.png"
    fig.savefig(out_pdf, bbox_inches="tight")
    fig.savefig(out_svg, bbox_inches="tight")
    fig.savefig(out_png, dpi=600, bbox_inches="tight")
    plt.close(fig)

    print(f"Wrote {out_pdf.relative_to(REPO)}")
    print(f"Wrote {source_csv.relative_to(REPO)}")
    print(f"discordant graphs={len(df)}")
    print(f"mean paired cross-rack increase={df['paired_cross_rack_increase_pct'].mean():.4f}%")
    print(f"mean conflict utilization={aff_util.mean():.6f}->{mape_util.mean():.6f}")


if __name__ == "__main__":
    main()
