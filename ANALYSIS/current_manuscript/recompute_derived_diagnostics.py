#!/usr/bin/env python3
"""Recompute the October-2026 derived N2/N3 diagnostics from frozen package data.

Outputs
-------
critical_load_per_graph.csv
critical_load_summary.csv
pareto_per_discordant_graph.csv
pareto_summary.csv
penalty_threshold_per_graph.csv
penalty_threshold_summary.csv

This is deterministic apart from the explicitly seeded graph-resampling bootstrap.
It performs no new experiment; it re-enumerates the frozen AFF-C candidate sets using
exactly the package's N2/N3 generator/model code.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

PRIMARY = 1.25
BOOT_N = 100_000
BOOT_SEED = 20260926
EPS = 1e-12
METHODS = ["Affinity-Bytes", "Affinity-Bytes+Admission", "MAPE-CAP-WS"]


def load_n2n3(package_root: Path):
    script = Path(__file__).resolve().parent / "run_n2n3_fixed.py"
    if not script.exists():
        raise FileNotFoundError(script)
    spec = importlib.util.spec_from_file_location("mape_n2n3", script)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def boot_mean_ci(values, seed, n=BOOT_N):
    x = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    pieces = []
    left = n
    while left:
        m = min(5000, left)
        pieces.append(x[rng.integers(0, len(x), size=(m, len(x)))].mean(axis=1))
        left -= m
    b = np.concatenate(pieces)
    return float(x.mean()), float(np.quantile(b, 0.025)), float(np.quantile(b, 0.975))


def nondominated_mask(obj: np.ndarray) -> np.ndarray:
    keep = np.ones(len(obj), dtype=bool)
    for i in range(len(obj)):
        weak = np.all(obj <= obj[i] + EPS, axis=1)
        strict = np.any(obj < obj[i] - EPS, axis=1)
        dom = weak & strict
        dom[i] = False
        if np.any(dom):
            keep[i] = False
    return keep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("package_root", type=Path)
    ap.add_argument("output_dir", type=Path)
    args = ap.parse_args()
    root = args.package_root.resolve()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)

    m = load_n2n3(root)
    critical_rows, pareto_rows, penalty_rows = [], [], []

    for nrep, seeds in m.SEED_BLOCKS.items():
        for seed in seeds:
            p = m.base_problem(nrep, seed)
            rows = m.characterise(p)
            cur_key = tuple(sorted(p.current_placement.items()))
            cur = next(c for c in rows if c["key"] == cur_key)
            u0 = float(cur["u_plan"])
            factor = PRIMARY / u0
            selected = m.select(rows, cur_key, factor)

            crec = {"replica_count": nrep, "seed": seed, "primary_load": PRIMARY}
            for method in METHODS:
                c = selected[method]
                if c is None:
                    tc = math.nan
                    umax = math.nan
                else:
                    umax = float(c["u_plan"] * factor)
                    tc = math.inf if c["u_plan"] <= EPS else float(u0 / c["u_plan"])
                slug = method.lower().replace("+", "_plus_").replace("-", "_").replace(" ", "_")
                crec[f"{slug}_u_max"] = umax
                crec[f"{slug}_tau_c"] = tc
            critical_rows.append(crec)

            aff = selected["Affinity-Bytes"]
            adm = selected["Affinity-Bytes+Admission"]
            risk = selected["MAPE-CAP-WS"]
            discordant = bool(aff is not None and aff["u_plan"] * factor > 1.0 + EPS and adm is not None)
            if discordant:
                admissible = [c for c in rows if c["u_plan"] * factor <= 1.0 + EPS]
                objs = np.asarray([[c["bytes"] * factor, c["exp_delay"], c["u_plan"] * factor]
                                   for c in admissible], dtype=float)
                nd = nondominated_mask(objs)
                front_keys = {admissible[i]["key"] for i in np.where(nd)[0]}
                pareto_rows.append({
                    "replica_count": nrep,
                    "seed": seed,
                    "admitted_candidate_count": len(admissible),
                    "pareto_set_size": len(front_keys),
                    "affinity_plus_admission_nondominated": adm["key"] in front_keys,
                    "mape_cap_ws_nondominated": risk["key"] in front_keys,
                })

            J = np.asarray([c["obj_full"] for c in rows], dtype=float)
            V = np.maximum(0.0, np.asarray([c["u_plan"] * factor for c in rows], dtype=float) - 1.0)
            pos = V[V > EPS]
            if len(pos):
                rj = float(J.max() - J.min())
                delta = float(pos.min())
                penalty_rows.append({
                    "replica_count": nrep,
                    "seed": seed,
                    "objective_range_RJ": rj,
                    "minimum_positive_violation_delta": delta,
                    "sufficient_threshold_RJ_over_delta": rj / delta,
                })

    cdf = pd.DataFrame(critical_rows)
    pdf = pd.DataFrame(pareto_rows)
    qdf = pd.DataFrame(penalty_rows)
    cdf.to_csv(out / "critical_load_per_graph.csv", index=False)
    pdf.to_csv(out / "pareto_per_discordant_graph.csv", index=False)
    qdf.to_csv(out / "penalty_threshold_per_graph.csv", index=False)

    slugs = {mth: mth.lower().replace("+", "_plus_").replace("-", "_").replace(" ", "_") for mth in METHODS}
    csum = []
    for mth in METHODS:
        x = cdf[f"{slugs[mth]}_tau_c"].to_numpy(float)
        csum.append({"quantity": f"median_tau_c::{mth}", "estimate": float(np.median(x)), "ci_low": "", "ci_high": ""})
    da = cdf[f"{slugs['Affinity-Bytes+Admission']}_tau_c"].to_numpy(float) - cdf[f"{slugs['Affinity-Bytes']}_tau_c"].to_numpy(float)
    dr = cdf[f"{slugs['MAPE-CAP-WS']}_tau_c"].to_numpy(float) - cdf[f"{slugs['Affinity-Bytes+Admission']}_tau_c"].to_numpy(float)
    for name, d, seed in [("mean_delta_tau_c::admission_minus_affinity", da, BOOT_SEED),
                          ("mean_delta_tau_c::ranking_minus_admission", dr, BOOT_SEED + 1)]:
        mean, lo, hi = boot_mean_ci(d, seed)
        csum.append({"quantity": name, "estimate": mean, "ci_low": lo, "ci_high": hi})
    pd.DataFrame(csum).to_csv(out / "critical_load_summary.csv", index=False)

    psum = pd.DataFrame([
        {"quantity": "discordant_graph_count", "value": int(len(pdf))},
        {"quantity": "pareto_set_size_median", "value": float(pdf.pareto_set_size.median())},
        {"quantity": "pareto_set_size_min", "value": int(pdf.pareto_set_size.min())},
        {"quantity": "pareto_set_size_max", "value": int(pdf.pareto_set_size.max())},
        {"quantity": "affinity_plus_admission_nondominated_count", "value": int(pdf.affinity_plus_admission_nondominated.sum())},
        {"quantity": "mape_cap_ws_nondominated_count", "value": int(pdf.mape_cap_ws_nondominated.sum())},
    ])
    psum.to_csv(out / "pareto_summary.csv", index=False)

    x = qdf.sufficient_threshold_RJ_over_delta.to_numpy(float)
    qsum = pd.DataFrame([
        {"quantity": "graph_count", "value": int(len(x))},
        {"quantity": "median_RJ_over_delta", "value": float(np.median(x))},
        {"quantity": "p10_RJ_over_delta", "value": float(np.quantile(x, 0.10))},
        {"quantity": "p90_RJ_over_delta", "value": float(np.quantile(x, 0.90))},
        {"quantity": "min_RJ_over_delta", "value": float(np.min(x))},
        {"quantity": "max_RJ_over_delta", "value": float(np.max(x))},
    ])
    qsum.to_csv(out / "penalty_threshold_summary.csv", index=False)

    summary = {
        "critical_load_medians": {mth: float(np.median(cdf[f"{slugs[mth]}_tau_c"])) for mth in METHODS},
        "admission_delta_mean_ci95": boot_mean_ci(da, BOOT_SEED),
        "ranking_delta_mean_ci95": boot_mean_ci(dr, BOOT_SEED + 1),
        "pareto": {"discordant_graphs": int(len(pdf)), "median_size": float(pdf.pareto_set_size.median()),
                   "range": [int(pdf.pareto_set_size.min()), int(pdf.pareto_set_size.max())],
                   "affinity_plus_admission_nondominated": int(pdf.affinity_plus_admission_nondominated.sum()),
                   "mape_cap_ws_nondominated": int(pdf.mape_cap_ws_nondominated.sum())},
        "penalty_threshold": {"n": int(len(x)), "median": float(np.median(x)),
                              "p10": float(np.quantile(x, .10)), "p90": float(np.quantile(x, .90)),
                              "min": float(np.min(x)), "max": float(np.max(x))},
        "note": "Derived from frozen existing observations; no new experimental run.",
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    main()
