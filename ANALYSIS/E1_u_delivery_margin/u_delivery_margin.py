#!/usr/bin/env python3
"""Deterministic reanalysis of existing E1 persistent-degradation cell results.
No simulation is run. The only stochastic operation is a seeded bootstrap of bin means.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd

BOOT_N = 20_000
BOOT_SEED = 20260926
BINS = [0.0, 0.5, 0.8, 0.9, 1.0, 1.1, 1.25, np.inf]
LABELS = ["(0,0.5]", "(0.5,0.8]", "(0.8,0.9]", "(0.9,1.0]", "(1.0,1.1]", "(1.1,1.25]", ">1.25"]


def boot_mean(y, seed):
    y = np.asarray(y, float)
    rng = np.random.default_rng(seed)
    means = y[rng.integers(0, len(y), size=(BOOT_N, len(y)))].mean(axis=1)
    return float(y.mean()), float(np.quantile(means, .025)), float(np.quantile(means, .975))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cell_results_csv", type=Path)
    ap.add_argument("output_dir", type=Path)
    args = ap.parse_args()
    out = args.output_dir.resolve(); out.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(args.cell_results_csv)
    required = {"cell_id", "seed", "group", "active_streams", "U", "D"}
    if not required.issubset(df.columns):
        raise ValueError(f"Expected columns {sorted(required)}")
    if len(df) != 627:
        raise ValueError(f"Expected 627 E1 cells; got {len(df)}")

    df = df.sort_values(["U", "seed", "cell_id"]).reset_index(drop=True)
    below95_le1 = df[(df.U <= 1.0) & (df.D < .95)].copy()
    above1_below95 = df[(df.U > 1.0) & (df.D < .95)].copy()
    below99 = df[df.D < .99].copy()

    anomaly = below95_le1.iloc[0] if len(below95_le1) == 1 else None
    first_load_below95 = above1_below95.iloc[0] if len(above1_below95) else None
    # The first D<0.99 cell overall is the known anomaly; the next is the load-associated onset.
    first_additional_below99 = below99.iloc[1] if len(below99) >= 2 else None

    df["U_bin"] = pd.cut(df.U, bins=BINS, labels=LABELS, right=True, include_lowest=False)
    bins = []
    for i, lab in enumerate(LABELS):
        y = df.loc[df.U_bin == lab, "D"].to_numpy(float)
        mean, lo, hi = boot_mean(y, BOOT_SEED + i)
        bins.append({"U_bin": lab, "n_cells": len(y), "mean_D": mean, "bootstrap_ci95_low": lo,
                     "bootstrap_ci95_high": hi, "bootstrap_resamples": BOOT_N, "bootstrap_seed": BOOT_SEED + i})
    pd.DataFrame(bins).to_csv(out / "u_delivery_binned_bootstrap.csv", index=False)
    df.to_csv(out / "u_delivery_cells_sorted.csv", index=False)

    thresholds = {
        "n_cells": int(len(df)),
        "n_U_le_1_D_below_0_95": int(len(below95_le1)),
        "documented_anomaly": None if anomaly is None else anomaly[required].to_dict() if False else {
            "cell_id": str(anomaly.cell_id), "seed": int(anomaly.seed), "group": str(anomaly.group),
            "active_streams": int(anomaly.active_streams), "U": float(anomaly.U), "D": float(anomaly.D)},
        "first_U_gt_1_with_D_below_0_95": None if first_load_below95 is None else {
            "cell_id": str(first_load_below95.cell_id), "seed": int(first_load_below95.seed),
            "group": str(first_load_below95.group), "active_streams": int(first_load_below95.active_streams),
            "U": float(first_load_below95.U), "D": float(first_load_below95.D)},
        "first_additional_D_below_0_99_after_documented_anomaly": None if first_additional_below99 is None else {
            "cell_id": str(first_additional_below99.cell_id), "seed": int(first_additional_below99.seed),
            "group": str(first_additional_below99.group), "active_streams": int(first_additional_below99.active_streams),
            "U": float(first_additional_below99.U), "D": float(first_additional_below99.D)},
        "interpretation_guardrail": "The U=0.353 anomaly means it is not literally true that every cell up to U=0.893 has D>=0.99. The 0.893 value is the first additional/load-associated sub-0.99 cell after that documented anomaly.",
        "note": "Reanalysis only; no new simulation.",
    }
    (out / "u_delivery_thresholds.json").write_text(json.dumps(thresholds, indent=2) + "\n")
    print(json.dumps(thresholds, indent=2))

if __name__ == "__main__":
    main()
