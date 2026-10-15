#!/usr/bin/env python3
"""Audit and statistically summarize a completed strict S-E6 run.

The independent unit is the matched condition-level replicate.  HTTP requests
within a cell are not treated as replicates.  This analysis is intentionally
kept separate from the frozen primary family and the earlier strengthening
campaign because the strict three-method S-E6 run was completed later.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import statistics
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import atomic_json, utc_now, write_manifest
from se6_external_support import DEFAULT_SCHEDULER_NAME, SCHEDULER_IMAGE, SCHEDULER_PLUGINS_VERSION

METHOD_DIRS = {
    "Native": "Native",
    "External-NetworkOverhead": "External-NetworkOverhead",
    "BPlus-Exact": "BPlus-Exact",
}
PAIR_ORDER = [
    ("Native", "External-NetworkOverhead"),
    ("Native", "BPlus-Exact"),
    ("External-NetworkOverhead", "BPlus-Exact"),
]
ANALYZED_METRICS = ("P95", "P99", "errors")
EXPECTED_METHOD_ORDERS = [
    ["Native", "External-NetworkOverhead", "BPlus-Exact"],
    ["External-NetworkOverhead", "BPlus-Exact", "Native"],
    ["BPlus-Exact", "Native", "External-NetworkOverhead"],
    ["Native", "BPlus-Exact", "External-NetworkOverhead"],
    ["External-NetworkOverhead", "Native", "BPlus-Exact"],
]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _verify_manifest(root: Path) -> tuple[int, list[str]]:
    path = root / "manifests" / "run.sha256"
    errors: list[str] = []
    checked = 0
    if not path.exists():
        return 0, ["missing manifests/run.sha256"]
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            expected, rel = line.split("  ", 1)
        except ValueError:
            errors.append(f"malformed manifest line: {line[:120]}")
            continue
        target = root / Path(rel)
        if not target.is_file():
            errors.append(f"manifest target missing: {rel}")
        elif _sha256(target) != expected:
            errors.append(f"manifest hash mismatch: {rel}")
        checked += 1
    return checked, errors


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _betacf(a: float, b: float, x: float) -> float:
    # Continued fraction for the incomplete beta function (Numerical Recipes).
    max_iter, eps, fpmin = 300, 3.0e-14, 1.0e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) <= eps:
            return h
    raise ArithmeticError("incomplete-beta continued fraction did not converge")


def _regularized_beta(x: float, a: float, b: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
                     + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def _paired_t(values_a: list[float], values_b: list[float]) -> dict[str, float | int]:
    differences = [b - a for a, b in zip(values_a, values_b)]
    n = len(differences)
    mean = statistics.mean(differences)
    sd = statistics.stdev(differences)
    if sd == 0.0:
        t_stat = 0.0 if mean == 0.0 else math.copysign(math.inf, mean)
        p_raw = 1.0 if mean == 0.0 else 0.0
        dz = 0.0 if mean == 0.0 else math.copysign(math.inf, mean)
    else:
        t_stat = mean / (sd / math.sqrt(n))
        x = (n - 1) / ((n - 1) + t_stat * t_stat)
        p_raw = _regularized_beta(x, (n - 1) / 2.0, 0.5)
        dz = mean / sd
    return {
        "paired_n": n,
        "mean_difference_b_minus_a": mean,
        "sd_difference": sd,
        "paired_cohen_dz": dz,
        "t": t_stat,
        "df": n - 1,
        "p_raw": p_raw,
    }


def _holm(p_values: list[float]) -> list[float]:
    order = sorted(range(len(p_values)), key=p_values.__getitem__)
    adjusted = [1.0] * len(p_values)
    running = 0.0
    for rank, index in enumerate(order):
        running = max(running, min(1.0, (len(p_values) - rank) * p_values[index]))
        adjusted[index] = running
    return adjusted


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows({key: row.get(key) for key in fields} for row in rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_root", type=Path)
    args = parser.parse_args()
    root = args.run_root.resolve()
    raw = root / "raw" / "S-E6-external-scheduler"
    errors: list[str] = []
    warnings: list[str] = []

    manifest_entries, manifest_errors = _verify_manifest(root)
    errors.extend(manifest_errors)
    status = _read_json(root / "S-E6-only-status.json")
    summary = _read_json(root / "derived" / "S-E6-summary.json")
    post = _read_json(root / "derived" / "S-E6-postprocess-summary.json")
    install = _read_json(root / "logs" / "S-E6-environment" / "external-scheduler-install.json")
    smoke = _read_json(raw / "scheduler-smoke-test.json")

    if status.get("status") != "COMPLETED" or status.get("runner_exit_code") != 0 or status.get("postprocess_exit_code") != 0:
        errors.append("wrapper status is not a clean COMPLETED/0/0 result")
    if summary.get("status") != "COMPLETED" or summary.get("cells") != 135 or not summary.get("all_evidence_accepted"):
        errors.append("runner summary does not certify 135 accepted cells")
    if summary.get("fallback_allowed") is not False or summary.get("results_append_only") is not True:
        errors.append("strict no-fallback/append-only policy not certified")
    if not smoke.get("passed") or smoke.get("scheduler_name") != DEFAULT_SCHEDULER_NAME:
        errors.append("external-scheduler smoke test did not pass with the pinned scheduler name")
    if (install.get("scheduler_plugins_version") != SCHEDULER_PLUGINS_VERSION
            or install.get("scheduler_image") != SCHEDULER_IMAGE
            or not install.get("networkoverhead_verified_in_config")):
        errors.append("pinned external scheduler version/image/profile verification failed")
    if not post.get("feasibility_is_symmetric") or not post.get("same_planning_evaluator_used_for_all_methods"):
        errors.append("method-symmetric feasibility post-processing is not certified")

    rows: list[dict[str, Any]] = []
    conditions = list(summary.get("conditions", []))
    for condition in conditions:
        for replicate in range(1, 6):
            for method, dirname in METHOD_DIRS.items():
                path = raw / condition / f"replicate-{replicate:02d}" / dirname / "result.json"
                if not path.is_file():
                    errors.append(f"missing result cell: {path.relative_to(root).as_posix()}")
                    continue
                payload = _read_json(path)
                payload["_method"] = method
                payload["_path"] = path.relative_to(root).as_posix()
                rows.append(payload)

    keys = Counter((r.get("condition"), r.get("replicate"), r.get("_method")) for r in rows)
    if len(rows) != 135 or len(keys) != 135 or any(count != 1 for count in keys.values()):
        errors.append("result matrix is not exactly 9 conditions x 5 replicates x 3 methods")

    for row in rows:
        method = row["_method"]
        if not row.get("accepted_evidence") or not row.get("health", {}).get("healthy"):
            errors.append(f"unaccepted/unhealthy cell: {row['_path']}")
        if (_num(row.get("application", {}).get("requests")) or 0.0) <= 0.0:
            errors.append(f"cell has no accepted requests: {row['_path']}")
        for metric in ANALYZED_METRICS:
            if _num(row.get(metric)) is None:
                errors.append(f"missing/nonfinite {metric}: {row['_path']}")
        if method == "Native" and row.get("scheduler") != "Native":
            errors.append(f"native identity mismatch: {row['_path']}")
        elif method == "External-NetworkOverhead":
            if (row.get("scheduler") != method or row.get("scheduler_name") != DEFAULT_SCHEDULER_NAME
                    or row.get("scheduler_version") != SCHEDULER_PLUGINS_VERSION
                    or row.get("scheduler_image") != SCHEDULER_IMAGE):
                errors.append(f"external scheduler identity mismatch: {row['_path']}")
        elif method == "BPlus-Exact":
            if row.get("scheduler") != method or not row.get("independent_feasibility_evaluation"):
                errors.append(f"B+ identity/evaluation mismatch: {row['_path']}")

    index = {(r["condition"], int(r["replicate"]), r["_method"]): r for r in rows}
    order_mismatches: list[str] = []
    for condition in conditions:
        for replicate in range(1, 6):
            actual = sorted(
                METHOD_DIRS,
                key=lambda method: datetime.fromisoformat(index[(condition, replicate, method)]["completed_utc"].replace("Z", "+00:00")),
            )
            expected = EXPECTED_METHOD_ORDERS[replicate - 1]
            if actual != expected:
                order_mismatches.append(f"{condition}/replicate-{replicate:02d}: {actual}")
    if order_mismatches:
        errors.append("observed completion order does not match counterbalancing: " + "; ".join(order_mismatches))

    completeness = {
        metric: sum(_num(row.get(metric)) is not None for row in rows)
        for metric in ("P50", "P95", "P99", "throughput_rps", "errors", "downtime")
    }
    if completeness["throughput_rps"] == 0:
        warnings.append("throughput_rps is unreported in all 135 cells and is excluded from inference")
    if completeness["downtime"] == 0:
        warnings.append("downtime is unreported in all 135 cells and is excluded from inference")

    condition_rows: list[dict[str, Any]] = []
    for condition in conditions:
        for method in METHOD_DIRS:
            subset = [index[(condition, replicate, method)] for replicate in range(1, 6)]
            condition_rows.append({
                "condition": condition,
                "method": method,
                "n": 5,
                "mean_P95_ms": statistics.mean(float(row["P95"]) for row in subset),
                "mean_P99_ms": statistics.mean(float(row["P99"]) for row in subset),
                "mean_errors": statistics.mean(float(row["errors"]) for row in subset),
                "planning_feasible_n": sum(bool(row.get("planning_feasible")) for row in subset),
                "accepted_evidence_n": sum(bool(row.get("accepted_evidence")) for row in subset),
            })

    tests: list[dict[str, Any]] = []
    for condition in conditions:
        for method_a, method_b in PAIR_ORDER:
            for metric in ANALYZED_METRICS:
                values_a = [float(index[(condition, replicate, method_a)][metric]) for replicate in range(1, 6)]
                values_b = [float(index[(condition, replicate, method_b)][metric]) for replicate in range(1, 6)]
                row = {
                    "family": "S-E6 strict three-method completion",
                    "condition": condition,
                    "metric": metric,
                    "method_a": method_a,
                    "method_b": method_b,
                    "mean_a": statistics.mean(values_a),
                    "mean_b": statistics.mean(values_b),
                }
                row.update(_paired_t(values_a, values_b))
                tests.append(row)
    adjusted = _holm([float(row["p_raw"]) for row in tests])
    for row, p_holm in zip(tests, adjusted):
        row["p_holm_se6_family"] = p_holm
        row["holm_significant_0_05"] = p_holm < 0.05

    condition_path = root / "derived" / "S-E6-condition-summary.csv"
    statistics_path = root / "derived" / "S-E6-paired-statistics.csv"
    _write_csv(condition_path, condition_rows, [
        "condition", "method", "n", "mean_P95_ms", "mean_P99_ms", "mean_errors",
        "planning_feasible_n", "accepted_evidence_n",
    ])
    _write_csv(statistics_path, tests, [
        "family", "condition", "metric", "method_a", "method_b", "paired_n",
        "mean_a", "mean_b", "mean_difference_b_minus_a", "sd_difference",
        "paired_cohen_dz", "t", "df", "p_raw", "p_holm_se6_family", "holm_significant_0_05",
    ])

    feasibility = {
        method: {
            "n": sum(row["_method"] == method for row in rows),
            "feasible_n": sum(row["_method"] == method and bool(row.get("planning_feasible")) for row in rows),
        }
        for method in METHOD_DIRS
    }
    external_bplus = [row for row in tests if row["method_a"] == "External-NetworkOverhead" and row["method_b"] == "BPlus-Exact"]
    condition_lookup = {(row["condition"], row["method"]): row for row in condition_rows}
    bplus_lower_p95 = sum(
        condition_lookup[(condition, "BPlus-Exact")]["mean_P95_ms"]
        < condition_lookup[(condition, "External-NetworkOverhead")]["mean_P95_ms"]
        for condition in conditions
    )
    audit = {
        "experiment": "S-E6 strict three-method completion",
        "run_id": root.name,
        "audited_utc": utc_now(),
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "warnings": warnings,
        "manifest_entries_verified_before_audit_outputs": manifest_entries,
        "cells": len(rows),
        "conditions": len(conditions),
        "replicates_per_condition_method": 5,
        "methods": list(METHOD_DIRS),
        "accepted_evidence_n": sum(bool(row.get("accepted_evidence")) for row in rows),
        "actual_method_order_matches_counterbalancing": not order_mismatches,
        "external_scheduler": {
            "implementation": install.get("implementation"),
            "version": install.get("scheduler_plugins_version"),
            "image": install.get("scheduler_image"),
            "profile_verified": install.get("networkoverhead_verified_in_config"),
            "smoke_test_passed": smoke.get("passed"),
        },
        "metric_completeness_n_of_135": completeness,
        "feasibility_under_common_bplus_evaluator": feasibility,
        "statistical_analysis": {
            "independent_unit": "matched condition-level replicate",
            "metrics": list(ANALYZED_METRICS),
            "pairwise_tests": len(tests),
            "holm_family": "S-E6 strict three-method completion only; separate from primary and earlier strengthening families",
            "holm_significant_0_05": sum(bool(row["holm_significant_0_05"]) for row in tests),
            "minimum_raw_p": min(float(row["p_raw"]) for row in tests),
            "minimum_holm_p": min(float(row["p_holm_se6_family"]) for row in tests),
            "bplus_lower_sample_mean_p95_than_external_conditions": bplus_lower_p95,
            "external_vs_bplus_tests": len(external_bplus),
        },
        "outputs": [
            condition_path.relative_to(root).as_posix(),
            statistics_path.relative_to(root).as_posix(),
            "derived/S-E6-validation-audit.json",
        ],
    }
    atomic_json(root / "derived" / "S-E6-validation-audit.json", audit)
    write_manifest(root)
    print(json.dumps(audit, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
