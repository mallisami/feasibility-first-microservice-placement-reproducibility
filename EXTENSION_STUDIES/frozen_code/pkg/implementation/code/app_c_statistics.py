#!/usr/bin/env python3
"""Statistics for the APP_C (pipeline topology) campaign.

Reuses the same paired t-test logic from confirmatory_statistics.py
but on the APP_C campaign data.
"""
from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent

import sys
sys.path.insert(0, str(ROOT / "code"))
from confirmatory_statistics import paired_t_test, bonferroni_correction


def main() -> int:
    campaign_path = REPO / "RESULTS" / "supporting" / "raw" / "app_c_campaign.csv"
    if not campaign_path.exists():
        print("ERROR: app_c_campaign.csv not found")
        return 1

    rows: list[dict] = []
    with campaign_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    print(f"Loaded {len(rows)} APP_C campaign rows")

    cells: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        if row.get("status", "").startswith("complete") and row.get("objective"):
            try:
                obj = float(row["objective"])
                if math.isfinite(obj):
                    cells[row["network_condition"]][row["method"]].append(obj)
            except (ValueError, KeyError):
                pass

    comparisons_list = []
    bplus_method = "BPlus-Exact"
    baseline_methods = ["Current", "TrafficOnly-MAPE-CAP", "DeterministicNetworkAware", "BPlus-LNS"]

    for cond, method_data in sorted(cells.items()):
        bplus = method_data.get(bplus_method, [])
        for baseline_name in baseline_methods:
            baseline = method_data.get(baseline_name, [])
            n = min(len(bplus), len(baseline))
            if n < 2:
                comparisons_list.append({
                    "application": "APP_C",
                    "condition": cond,
                    "comparison": f"{bplus_method} vs {baseline_name}",
                    "n": n,
                    "error": "insufficient paired data",
                })
                continue
            result = paired_t_test(np.array(bplus[:n]), np.array(baseline[:n]))
            result["application"] = "APP_C"
            result["condition"] = cond
            result["comparison"] = f"{bplus_method} vs {baseline_name}"
            result["bplus_mean"] = round(float(np.mean(bplus[:n])), 2)
            result["baseline_mean"] = round(float(np.mean(baseline[:n])), 2)
            if float(np.mean(baseline[:n])) > 0:
                result["relative_improvement_pct"] = round(
                    (float(np.mean(baseline[:n])) - float(np.mean(bplus[:n])))
                    / float(np.mean(baseline[:n])) * 100, 2
                )
            comparisons_list.append(result)

    comparisons_list = bonferroni_correction(comparisons_list)

    cell_summaries = []
    for cond, method_data in sorted(cells.items()):
        cell_summary = {"application": "APP_C", "condition": cond, "methods": {}}
        for method, values in sorted(method_data.items()):
            arr = np.array(values)
            cell_summary["methods"][method] = {
                "n": len(values),
                "mean": round(float(np.mean(arr)), 2),
                "sd": round(float(np.std(arr, ddof=1)), 2) if len(arr) > 1 else 0,
            }
        cell_summaries.append(cell_summary)

    sig_count = sum(1 for c in comparisons_list if c.get("significant_at_005"))
    bonf_count = sum(1 for c in comparisons_list if c.get("bonferroni_significant"))

    report = {
        "analysis_type": "app-c-paired-comparisons",
        "evidence_type": "derived-confirmatory-statistics",
        "application": "APP_C",
        "topology": "pipeline-chain",
        "total_rows": len(rows),
        "total_comparisons": len(comparisons_list),
        "cell_summaries": cell_summaries,
        "paired_comparisons": comparisons_list,
        "summary": {
            "significant_at_005": sig_count,
            "bonferroni_significant": bonf_count,
            "total_comparisons": len(comparisons_list),
        },
    }

    output = REPO / "RESULTS" / "supporting" / "reproduced" / "app_c_statistics.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"\nAPP_C statistics: {len(comparisons_list)} comparisons, "
          f"{sig_count} significant, {bonf_count} after Bonferroni")
    print(f"Written to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
