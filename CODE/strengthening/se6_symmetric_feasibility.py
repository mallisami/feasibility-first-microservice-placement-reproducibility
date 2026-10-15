#!/usr/bin/env python3
"""Post-process a completed S-E6 run with method-symmetric feasibility reporting.

All three placements were already evaluated by the same B+ objective/feasibility
function during execution. This script exposes those evaluations symmetrically
and computes paired replicate-level application differences without treating
requests as independent samples.
"""
from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import atomic_json, utc_now, write_manifest

METHOD_DIRS = {
    "Native": "Native",
    "External-NetworkOverhead": "External-NetworkOverhead",
    "BPlus-Exact": "BPlus-Exact",
}
METRICS = ["P95", "P99", "throughput_rps", "errors", "downtime"]


def _read_rows(root: Path) -> list[dict[str, Any]]:
    base = root / "raw" / "S-E6-external-scheduler"
    rows: list[dict[str, Any]] = []
    for condition_dir in sorted(p for p in base.iterdir() if p.is_dir() and p.name != "network-topologies"):
        for rep_dir in sorted(p for p in condition_dir.glob("replicate-*") if p.is_dir()):
            for method, dirname in METHOD_DIRS.items():
                path = rep_dir / dirname / "result.json"
                if not path.exists():
                    raise RuntimeError(f"missing S-E6 result: {path}")
                payload = json.loads(path.read_text(encoding="utf-8"))
                rows.append({
                    "condition": payload["condition"],
                    "replicate": int(payload["replicate"]),
                    "method": method,
                    "planning_feasible": bool(payload.get("planning_feasible")),
                    "planning_objective": payload.get("planning_objective"),
                    "accepted_evidence": bool(payload.get("accepted_evidence")),
                    "P50": payload.get("P50"),
                    "P95": payload.get("P95"),
                    "P99": payload.get("P99"),
                    "throughput_rps": payload.get("throughput_rps"),
                    "errors": payload.get("errors"),
                    "downtime": payload.get("downtime"),
                    "result_path": str(path.relative_to(root).as_posix()),
                })
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k) for k in fields})


def _num(x: Any) -> float | None:
    if x is None or x == "":
        return None
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except Exception:
        return None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("run_root", type=Path)
    args = p.parse_args()
    root = args.run_root.resolve()
    rows = _read_rows(root)

    expected = 9 * 5 * 3
    if len(rows) != expected:
        raise RuntimeError(f"expected {expected} S-E6 rows, found {len(rows)}")

    key_counts = defaultdict(int)
    for r in rows:
        key_counts[(r["condition"], r["replicate"], r["method"])] += 1
    if any(v != 1 for v in key_counts.values()) or len(key_counts) != expected:
        raise RuntimeError("S-E6 condition/replicate/method keys are not exactly one-to-one")

    feas_fields = ["condition", "replicate", "method", "planning_feasible", "planning_objective", "accepted_evidence", "result_path"]
    _write_csv(root / "derived" / "S-E6-symmetric-feasibility.csv", rows, feas_fields)

    summary_rows = []
    for method in METHOD_DIRS:
        subset = [r for r in rows if r["method"] == method]
        feasible = sum(bool(r["planning_feasible"]) for r in subset)
        accepted = sum(bool(r["accepted_evidence"]) for r in subset)
        summary_rows.append({
            "method": method,
            "n": len(subset),
            "planning_feasible_n": feasible,
            "planning_feasible_fraction": feasible / len(subset),
            "accepted_evidence_n": accepted,
            "accepted_evidence_fraction": accepted / len(subset),
        })
    _write_csv(root / "derived" / "S-E6-feasibility-summary.csv", summary_rows,
               ["method", "n", "planning_feasible_n", "planning_feasible_fraction", "accepted_evidence_n", "accepted_evidence_fraction"])

    index = {(r["condition"], r["replicate"], r["method"]): r for r in rows}
    pair_rows: list[dict[str, Any]] = []
    methods = list(METHOD_DIRS)
    conditions = sorted({r["condition"] for r in rows})
    for a, b in itertools.combinations(methods, 2):
        for condition in conditions:
            for rep in range(1, 6):
                ra = index[(condition, rep, a)]
                rb = index[(condition, rep, b)]
                out = {"condition": condition, "replicate": rep, "method_a": a, "method_b": b}
                for metric in METRICS:
                    va, vb = _num(ra.get(metric)), _num(rb.get(metric))
                    out[f"{metric}_a"] = va
                    out[f"{metric}_b"] = vb
                    out[f"delta_{metric}_a_minus_b"] = None if va is None or vb is None else va - vb
                pair_rows.append(out)
    pair_fields = ["condition", "replicate", "method_a", "method_b"]
    for metric in METRICS:
        pair_fields += [f"{metric}_a", f"{metric}_b", f"delta_{metric}_a_minus_b"]
    _write_csv(root / "derived" / "S-E6-paired-application-differences.csv", pair_rows, pair_fields)

    contrast_rows: list[dict[str, Any]] = []
    for a, b in itertools.combinations(methods, 2):
        for condition in conditions:
            subset = [r for r in pair_rows if r["method_a"] == a and r["method_b"] == b and r["condition"] == condition]
            for metric in METRICS:
                vals = [_num(r.get(f"delta_{metric}_a_minus_b")) for r in subset]
                vals = [v for v in vals if v is not None]
                contrast_rows.append({
                    "condition": condition,
                    "method_a": a,
                    "method_b": b,
                    "metric": metric,
                    "paired_n": len(vals),
                    "mean_delta_a_minus_b": statistics.mean(vals) if vals else None,
                    "sd_delta": statistics.stdev(vals) if len(vals) >= 2 else None,
                })
    _write_csv(root / "derived" / "S-E6-paired-contrast-summary.csv", contrast_rows,
               ["condition", "method_a", "method_b", "metric", "paired_n", "mean_delta_a_minus_b", "sd_delta"])

    payload = {
        "experiment": "S-E6",
        "status": "POSTPROCESS_COMPLETED",
        "completed_utc": utc_now(),
        "cells": len(rows),
        "paired_application_rows": len(pair_rows),
        "feasibility_is_symmetric": True,
        "same_planning_evaluator_used_for_all_methods": True,
        "independent_unit": "condition-level matched replicate",
        "request_level_pseudoreplication": False,
        "method_summary": summary_rows,
        "outputs": [
            "derived/S-E6-symmetric-feasibility.csv",
            "derived/S-E6-feasibility-summary.csv",
            "derived/S-E6-paired-application-differences.csv",
            "derived/S-E6-paired-contrast-summary.csv",
        ],
    }
    atomic_json(root / "derived" / "S-E6-postprocess-summary.json", payload)
    write_manifest(root)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
