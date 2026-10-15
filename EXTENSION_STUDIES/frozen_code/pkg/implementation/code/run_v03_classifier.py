#!/usr/bin/env python3
"""Compare and freeze v0.3 regime classifiers on independent noisy traces."""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))

from mape_cap_bplus.v03_evidence import atomic_write_csv, atomic_write_json, utc_now, write_manifest

REGIMES = ("stable", "degradation", "blockage", "conflict", "outage", "recovery")
BASE = {
    "stable": (2.0, 0.1, 1.0, 0.05),
    "degradation": (15.0, 1.5, 1.0, 0.25),
    "blockage": (35.0, 8.0, 1.0, 0.35),
    "conflict": (22.0, 3.0, 1.0, 0.90),
    "outage": (90.0, 40.0, 0.0, 1.00),
    "recovery": (6.0, 0.4, 1.0, 0.10),
}


def make_trace(seed: int, windows_per_regime: int) -> list[dict]:
    rng = random.Random(seed)
    rows = []
    for regime in REGIMES:
        latency, loss, availability, conflict = BASE[regime]
        for offset in range(windows_per_regime):
            # Boundary windows deliberately mix adjacent states to test delay/noise handling.
            boundary = 0.70 if offset == 0 and rows else 1.0
            rows.append({
                "seed": seed,
                "window": len(rows),
                "truth": regime,
                "latency_ms": max(0.1, latency * boundary + rng.gauss(0, 1.8)),
                "loss_percent": max(0.0, loss * boundary + rng.gauss(0, 0.45)),
                "availability": availability,
                "conflict_ratio": min(1.0, max(0.0, conflict * boundary + rng.gauss(0, 0.06))),
            })
    return rows


def raw_label(row: dict, scale: float = 1.0) -> str:
    if row["availability"] < 0.5 or row["loss_percent"] >= 25.0 * scale:
        return "outage"
    if row["conflict_ratio"] >= 0.68 * scale:
        return "conflict"
    if row["latency_ms"] >= 27.0 * scale or row["loss_percent"] >= 5.0 * scale:
        return "blockage"
    if row["latency_ms"] >= 10.0 * scale or row["loss_percent"] >= 1.0 * scale:
        return "degradation"
    if row["latency_ms"] >= 3.5 * scale or row["loss_percent"] >= 0.35 * scale:
        return "recovery"
    return "stable"


def hysteresis(trace: list[dict], scale: float) -> list[str]:
    labels, current = [], "stable"
    for row in trace:
        candidate = raw_label(row, scale)
        if candidate == "stable" and current not in ("stable", "recovery") and row["latency_ms"] > 7.0 * scale:
            candidate = current
        current = candidate
        labels.append(current)
    return labels


def ewma(trace: list[dict], alpha: float) -> list[str]:
    smoothed = None
    labels = []
    for row in trace:
        keys = ("latency_ms", "loss_percent", "availability", "conflict_ratio")
        if smoothed is None:
            smoothed = {key: row[key] for key in keys}
        else:
            smoothed = {key: alpha * row[key] + (1 - alpha) * smoothed[key] for key in keys}
        labels.append(raw_label({**row, **smoothed}))
    return labels


def persistent_change_point(trace: list[dict], persistence: int) -> list[str]:
    labels, current, candidate, count = [], "stable", None, 0
    for row in trace:
        observed = raw_label(row)
        if observed == current:
            candidate, count = None, 0
        elif observed == candidate:
            count += 1
        else:
            candidate, count = observed, 1
        if candidate is not None and count >= persistence:
            current, candidate, count = candidate, None, 0
        labels.append(current)
    return labels


def metrics(trace: list[dict], predicted: list[str]) -> dict:
    truth = [row["truth"] for row in trace]
    accuracy = sum(a == b for a, b in zip(truth, predicted)) / len(truth)
    truth_transitions = {i for i in range(1, len(truth)) if truth[i] != truth[i - 1]}
    predicted_transitions = {i for i in range(1, len(predicted)) if predicted[i] != predicted[i - 1]}
    false_triggers = len([i for i in predicted_transitions if not any(abs(i - j) <= 2 for j in truth_transitions)])
    delays = []
    missed = 0
    starts = [0] + sorted(truth_transitions)
    for start in starts:
        target = truth[start]
        end = next((x for x in starts if x > start), len(truth))
        found = next((i for i in range(start, end) if predicted[i] == target), None)
        if found is None:
            missed += 1
        else:
            delays.append(found - start)
    noise_relocations = len(predicted_transitions - truth_transitions)
    return {
        "accuracy": accuracy,
        "false_triggers": false_triggers,
        "missed_regimes": missed,
        "detection_delay_windows": mean(delays) if delays else math.inf,
        "noise_relocations": noise_relocations,
    }


def configurations() -> list[tuple[str, str, float | int]]:
    result = []
    result.extend(("hysteresis", f"threshold-scale-{scale}", scale) for scale in (0.85, 1.0, 1.15))
    result.extend(("ewma", f"alpha-{alpha}", alpha) for alpha in (0.25, 0.5, 0.75))
    result.extend(("persistence-change-point", f"persistence-{p}", p) for p in (2, 3, 4))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_root", type=Path)
    parser.add_argument("--seeds", type=int, default=18)
    parser.add_argument("--windows", type=int, default=7)
    args = parser.parse_args()
    run_root = args.run_root.resolve()
    output = run_root / "raw" / "phase-2-classifier-results.csv"
    freeze = run_root / "derived" / "phase-2-classifier-freeze.json"
    if output.exists() or freeze.exists():
        raise FileExistsError("classifier outputs already exist; use a new v0.3 run root")
    if args.seeds < 3 or args.windows < 5:
        raise ValueError("at least 3 seeds and 5 windows per regime are required")

    rows = []
    for method, config_id, value in configurations():
        per_seed = []
        for seed in range(1, args.seeds + 1):
            trace = make_trace(seed, args.windows)
            if method == "hysteresis":
                prediction = hysteresis(trace, float(value))
            elif method == "ewma":
                prediction = ewma(trace, float(value))
            else:
                prediction = persistent_change_point(trace, int(value))
            result = metrics(trace, prediction)
            per_seed.append(result)
            rows.append({"method": method, "configuration": config_id, "seed": seed, "windows_per_regime": args.windows, **result})
        atomic_write_json(
            run_root / "checkpoints" / f"phase-2-{method}-{config_id}.json",
            {"completed_utc": utc_now(), "seeds": args.seeds, "summary": {k: mean(x[k] for x in per_seed) for k in per_seed[0]}},
        )

    atomic_write_csv(output, rows)
    grouped = []
    for method, config_id, _ in configurations():
        matches = [row for row in rows if row["method"] == method and row["configuration"] == config_id]
        summary = {key: mean(float(row[key]) for row in matches) for key in ("accuracy", "false_triggers", "missed_regimes", "detection_delay_windows", "noise_relocations")}
        summary["score"] = summary["accuracy"] - 0.02 * summary["false_triggers"] - 0.04 * summary["missed_regimes"] - 0.01 * summary["detection_delay_windows"] - 0.01 * summary["noise_relocations"]
        grouped.append({"method": method, "configuration": config_id, **summary})
    selected = sorted(grouped, key=lambda x: (-x["score"], -x["accuracy"], x["detection_delay_windows"], x["method"], x["configuration"]))[0]
    atomic_write_json(freeze, {
        "campaign_version": "B+ v0.3",
        "frozen_utc": utc_now(),
        "selection_rule": "max accuracy - .02 false triggers - .04 missed - .01 delay - .01 noise relocations; deterministic tie-break",
        "selected": selected,
        "all_configurations": grouped,
        "regimes": list(REGIMES),
        "independent_seeds": args.seeds,
        "windows_per_regime": args.windows,
    })
    ledger_path = run_root / "checkpoints" / "ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["phases"]["phase-0-audit"] = "completed"
    ledger["phases"]["phase-1-correctness"] = "completed"
    ledger["phases"]["phase-2-classifier"] = "completed"
    ledger["current_phase"] = "phase-3-r6"
    atomic_write_json(ledger_path, ledger)
    write_manifest(run_root, run_root / "manifests" / "run.sha256")
    print(json.dumps(selected, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
