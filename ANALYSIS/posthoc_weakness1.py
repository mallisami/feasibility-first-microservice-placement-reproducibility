#!/usr/bin/env python3
"""
ANALYSIS/posthoc_weakness1.py
Executable standard-library post-hoc analysis script for MAPE-CAP B+ confirmatory campaigns.

As documented in Online Resource 1 (supplement.tex §S-4 / Table 10 and Table 11) and main.tex §4.1:
- Reads the accepted analysis tables from the Kubernetes and ns-3 confirmatory campaigns.
- Computes the graph-level paired method differences (B+ minus Affinity-Bytes).
- Performs the exploratory decomposition into committed (28 graphs) and abstained (2 graphs: 44013, 44020) strata.
- Verifies exact arithmetic agreement with published point estimates.
- Emits seed-matched CSVs and machine-readable summary JSON under ANALYSIS/derived/.
"""

import csv
import json
import math
import sys
from pathlib import Path

# Resolve repository root
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DERIVED_DIR = SCRIPT_DIR / "derived"
DERIVED_DIR.mkdir(parents=True, exist_ok=True)

# Locate candidate run directories for Kubernetes and ns-3
K8S_BASE = REPO_ROOT / "EXPERIMENTS" / "k8s_affinity_wireless_confirmatory" / "results"
NS3_BASE = REPO_ROOT / "EXPERIMENTS" / "ns3_affinity_wireless_confirmatory" / "results"

# Fallback paths if lowercase
if not K8S_BASE.exists():
    K8S_BASE = REPO_ROOT / "experiments" / "k8s_affinity_wireless_confirmatory" / "results"
if not NS3_BASE.exists():
    NS3_BASE = REPO_ROOT / "experiments" / "ns3_affinity_wireless_confirmatory" / "results"

K8S_RUN_ORIG = K8S_BASE / "run-20260916T051604Z"
K8S_RUN_POST = K8S_BASE / "run-20260920T045006Z"

NS3_RUN_ORIG = NS3_BASE / "run-20260916T134114Z"
NS3_RUN_POST = NS3_BASE / "run-20260920T043724Z"


def load_k8s_table(csv_path: Path):
    if not csv_path.exists():
        raise FileNotFoundError(f"Kubernetes analysis table missing: {csv_path}")
    with open(csv_path, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    # Filter for primary evaluation target 1.25
    t125 = [r for r in rows if math.isclose(float(r["target"]), 1.25, rel_tol=1e-5)]
    by_seed = {}
    for r in t125:
        seed = int(r["seed"])
        method = r["method"]
        cf = float(r["completion_fraction"])
        abstained = r["planner_abstained"].strip().lower() in ("true", "1")
        if seed not in by_seed:
            by_seed[seed] = {}
        by_seed[seed][method] = {
            "completion_fraction": cf,
            "planner_abstained": abstained,
            "scheduled": int(r.get("expected_scheduled", 0)),
            "successful": int(r.get("successful", 0)),
        }
    return by_seed


def load_ns3_table(csv_path: Path):
    if not csv_path.exists():
        raise FileNotFoundError(f"ns-3 analysis table missing: {csv_path}")
    with open(csv_path, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    t125 = [r for r in rows if math.isclose(float(r["target"]), 1.25, rel_tol=1e-5)]
    by_seed_method = {}
    for r in t125:
        seed = int(r["seed"])
        method = r["method"]
        df = float(r["aggregate_delivered_fraction"])
        achieved = float(r.get("aggregate_achieved_mbps", 0.0))
        offered = float(r.get("aggregate_offered_mbps", 0.0))
        abstained = r["planner_abstained"].strip().lower() in ("true", "1")
        key = (seed, method)
        if key not in by_seed_method:
            by_seed_method[key] = {
                "dfs": [], "achieved": [], "offered": [], "abstained": abstained
            }
        by_seed_method[key]["dfs"].append(df)
        by_seed_method[key]["achieved"].append(achieved)
        by_seed_method[key]["offered"].append(offered)

    seeds = sorted(set(k[0] for k in by_seed_method.keys()))
    res = {}
    for s in seeds:
        res[s] = {}
        for m in ("BPlus-Exact", "Affinity-Bytes", "Current"):
            entry = by_seed_method.get((s, m))
            if entry:
                res[s][m] = {
                    "delivered_fraction": sum(entry["dfs"]) / len(entry["dfs"]),
                    "achieved_mbps": sum(entry["achieved"]) / len(entry["achieved"]),
                    "offered_mbps": sum(entry["offered"]) / len(entry["offered"]),
                    "planner_abstained": entry["abstained"],
                }
    return res


def compute_decomposition(paired_data: dict, value_key: str):
    seeds = sorted(paired_data.keys())
    rows = []
    for s in seeds:
        bplus = paired_data[s]["BPlus-Exact"][value_key]
        aff = paired_data[s]["Affinity-Bytes"][value_key]
        diff = bplus - aff
        abstained = paired_data[s]["BPlus-Exact"]["planner_abstained"]
        rows.append({
            "seed": s,
            "bplus_value": bplus,
            "affinity_value": aff,
            "difference": diff,
            "planner_abstained": abstained,
            "stratum": "abstained" if abstained else "committed",
        })

    all_diffs = [r["difference"] for r in rows]
    comm_diffs = [r["difference"] for r in rows if not r["planner_abstained"]]
    abst_diffs = [r["difference"] for r in rows if r["planner_abstained"]]

    mean_all = sum(all_diffs) / len(all_diffs)
    mean_comm = sum(comm_diffs) / len(comm_diffs)
    mean_abst = sum(abst_diffs) / len(abst_diffs) if abst_diffs else 0.0

    contrib_comm = sum(comm_diffs) / len(all_diffs)
    contrib_abst = sum(abst_diffs) / len(all_diffs)

    return {
        "rows": rows,
        "summary": {
            "n_total": len(all_diffs),
            "n_committed": len(comm_diffs),
            "n_abstained": len(abst_diffs),
            "mean_all": mean_all,
            "mean_committed": mean_comm,
            "mean_abstained": mean_abst,
            "contribution_committed": contrib_comm,
            "contribution_abstained": contrib_abst,
            "abstention_seeds": {r["seed"]: r["difference"] for r in rows if r["planner_abstained"]},
        }
    }


def write_csv(filepath: Path, rows: list, fieldnames: list):
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    print("=== Running ANALYSIS/posthoc_weakness1.py ===")

    # 1. Kubernetes Original (pre-2026-09-20)
    k8s_orig_data = load_k8s_table(K8S_RUN_ORIG / "analysis_cells.csv")
    k8s_orig_decomp = compute_decomposition(k8s_orig_data, "completion_fraction")
    k8s_orig_csv = DERIVED_DIR / "kubernetes_seed_matched_decomposition_original.csv"
    write_csv(k8s_orig_csv, k8s_orig_decomp["rows"], ["seed", "bplus_value", "affinity_value", "difference", "planner_abstained", "stratum"])
    print(f"Emitted: {k8s_orig_csv.relative_to(REPO_ROOT)}")

    # Check assertions for Table 10 Kubernetes:
    # All: -0.006159; Committed: +0.000583; Abstained: -0.100555
    k_s = k8s_orig_decomp["summary"]
    assert math.isclose(k_s["mean_all"], -0.006159, abs_tol=1e-4), f"K8s orig all mismatch: {k_s['mean_all']}"
    assert math.isclose(k_s["mean_committed"], +0.000583, abs_tol=1e-4), f"K8s orig comm mismatch: {k_s['mean_committed']}"
    assert math.isclose(k_s["mean_abstained"], -0.100555, abs_tol=1e-4), f"K8s orig abst mismatch: {k_s['mean_abstained']}"
    print("  ✓ Verified Table 10 Kubernetes point estimates")

    # 2. ns-3 Original (pre-2026-09-20)
    ns3_orig_data = load_ns3_table(NS3_RUN_ORIG / "analysis_cells.csv")
    ns3_orig_decomp = compute_decomposition(ns3_orig_data, "delivered_fraction")
    ns3_orig_csv = DERIVED_DIR / "ns3_seed_matched_decomposition_original.csv"
    write_csv(ns3_orig_csv, ns3_orig_decomp["rows"], ["seed", "bplus_value", "affinity_value", "difference", "planner_abstained", "stratum"])
    print(f"Emitted: {ns3_orig_csv.relative_to(REPO_ROOT)}")

    # Check assertions for Table 10 ns-3:
    # All: -0.015176; Committed: -0.001756; Abstained: -0.203059
    n_s = ns3_orig_decomp["summary"]
    assert math.isclose(n_s["mean_all"], -0.015176, abs_tol=1e-4), f"ns-3 orig all mismatch: {n_s['mean_all']}"
    assert math.isclose(n_s["mean_committed"], -0.001756, abs_tol=1e-4), f"ns-3 orig comm mismatch: {n_s['mean_committed']}"
    assert math.isclose(n_s["mean_abstained"], -0.203059, abs_tol=1e-4), f"ns-3 orig abst mismatch: {n_s['mean_abstained']}"
    print("  ✓ Verified Table 10 ns-3 point estimates")

    # 3. Kubernetes Post-Fix (corrected 2026-09-20)
    k8s_post_data = load_k8s_table(K8S_RUN_POST / "analysis_cells.csv")
    k8s_post_decomp = compute_decomposition(k8s_post_data, "completion_fraction")
    k8s_post_csv = DERIVED_DIR / "kubernetes_seed_matched_decomposition_postfix.csv"
    write_csv(k8s_post_csv, k8s_post_decomp["rows"], ["seed", "bplus_value", "affinity_value", "difference", "planner_abstained", "stratum"])
    print(f"Emitted: {k8s_post_csv.relative_to(REPO_ROOT)}")

    # Check assertions for Table 11 Kubernetes:
    # All: -0.011093; Committed: +0.000368; Abstained: -0.171542
    kp_s = k8s_post_decomp["summary"]
    assert math.isclose(kp_s["mean_all"], -0.011093, abs_tol=1e-4), f"K8s post all mismatch: {kp_s['mean_all']}"
    assert math.isclose(kp_s["mean_committed"], +0.000368, abs_tol=1e-4), f"K8s post comm mismatch: {kp_s['mean_committed']}"
    assert math.isclose(kp_s["mean_abstained"], -0.171542, abs_tol=1e-4), f"K8s post abst mismatch: {kp_s['mean_abstained']}"
    print("  ✓ Verified Table 11 Kubernetes point estimates")

    # 4. ns-3 Post-Fix (corrected 2026-09-20)
    ns3_post_data = load_ns3_table(NS3_RUN_POST / "analysis_cells.csv")
    ns3_post_decomp = compute_decomposition(ns3_post_data, "delivered_fraction")
    ns3_post_csv = DERIVED_DIR / "ns3_seed_matched_decomposition_postfix.csv"
    write_csv(ns3_post_csv, ns3_post_decomp["rows"], ["seed", "bplus_value", "affinity_value", "difference", "planner_abstained", "stratum"])
    print(f"Emitted: {ns3_post_csv.relative_to(REPO_ROOT)}")

    # Check assertions for Table 11 ns-3 against the active corrected campaign:
    # All: -0.021912; Committed: -0.001756; Abstained: -0.304092
    np_s = ns3_post_decomp["summary"]
    assert math.isclose(np_s["mean_all"], -0.021912, abs_tol=1e-4), f"ns-3 post all mismatch: {np_s['mean_all']}"
    assert math.isclose(np_s["mean_committed"], -0.001756, abs_tol=1e-4), f"ns-3 post comm mismatch: {np_s['mean_committed']}"
    assert math.isclose(np_s["mean_abstained"], -0.304092, abs_tol=1e-4), f"ns-3 post abst mismatch: {np_s['mean_abstained']}"
    print("  ✓ Verified Table 11 ns-3 point estimates")

    # 5. Emit summary JSON
    summary_json = {
        "metadata": {
            "title": "Post-Hoc Graph-Level Decomposition of B+ versus Affinity Confirmatory Campaigns",
            "reference": "Electronic Supplementary Material (supplement.tex §S-4, Table 10 and Table 11)",
            "primary_target": 1.25,
            "held_out_seeds_count": 30,
        },
        "original_campaign": {
            "kubernetes": k8s_orig_decomp["summary"],
            "ns3": ns3_orig_decomp["summary"],
        },
        "postfix_campaign": {
            "kubernetes": k8s_post_decomp["summary"],
            "ns3": ns3_post_decomp["summary"],
        },
    }

    summary_file = DERIVED_DIR / "posthoc_decomposition_summary.json"
    summary_file.write_text(json.dumps(summary_json, indent=2), encoding="utf-8")
    print(f"Emitted: {summary_file.relative_to(REPO_ROOT)}")

    print("\nAll post-hoc decompositions successfully generated and verified against manuscript point estimates!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
