#!/usr/bin/env python3
"""Post-freeze offline sensitivity of the frozen R1 planning threshold and slack weight.

The script reconstructs each of the 270 frozen R1 B+ Exact planning instances from
archived R2 telemetry and the original problem builder. It then performs two
orthogonal sensitivity sweeps using the same exact MILP:

1. threshold sweep at the frozen xi=1000;
2. xi sweep at the frozen 500-ms planning threshold.

No Kubernetes/application measurement is rerun, and no application outcome is
used to select the tested values.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
from dataclasses import replace
from multiprocessing import Pool
from pathlib import Path
from typing import Any

from mape_cap_bplus.exact import solve_exact
from mape_cap_bplus.models import ProblemInstance, RiskConfig
from mape_cap_bplus.objective import evaluate_placement
from run_v03_r1 import build_problem, initial_placement

CONDITIONS = [
    "stable", "persistent-degradation", "partial-blockage", "conflict-dense",
    "outage-with-fallback", "recovery", "bursty", "hotspot",
    "structural-workload-change",
]
THRESHOLDS_MS = (10.0, 25.0, 50.0, 100.0, 250.0, 500.0)
XI_WEIGHTS = (0.0, 100.0, 1000.0, 10000.0)
BASE_THRESHOLD_MS = 500.0
BASE_XI = 1000.0
RUN_ROOT: Path | None = None


def _init_worker(run_root: str) -> None:
    global RUN_ROOT
    RUN_ROOT = Path(run_root)


def accepted_bplus_exact(run_root: Path, condition: str, replicate: int) -> dict[str, Any]:
    base = run_root / "raw" / "r1" / condition / f"replicate-{replicate:02d}" / "BPlus-Exact"
    paths: list[Path] = []
    if (base / "result.json").exists():
        paths.append(base / "result.json")
    paths.extend(sorted(base.glob("attempt-*/result.json")))
    for path in paths:
        row = json.loads(path.read_text(encoding="utf-8"))
        if row.get("accepted") and row.get("duration_seconds") == 20:
            return row
    raise FileNotFoundError(f"no accepted BPlus-Exact R1 result: {condition} rep {replicate}")


def with_threshold(problem: ProblemInstance, threshold_ms: float) -> ProblemInstance:
    flows = tuple(
        replace(flow, max_expected_latency_ms=threshold_ms if flow.max_expected_latency_ms is not None else None)
        for flow in problem.flows
    )
    return replace(problem, flows=flows, instance_id=f"{problem.instance_id}-thr{threshold_ms:g}")


def moves(problem: ProblemInstance, placement: dict[str, str]) -> int:
    return sum(1 for replica, node in placement.items() if problem.current_placement.get(replica) != node)


def _solve_one(task: tuple[str, int]) -> dict[str, Any]:
    if RUN_ROOT is None:
        raise RuntimeError("worker not initialized")
    condition, rep = task
    problem = build_problem(RUN_ROOT, condition, rep, initial_placement(condition, rep))
    frozen = accepted_bplus_exact(RUN_ROOT, condition, rep)
    frozen_placement = dict(frozen["placement"])
    base_risk = RiskConfig(0.8, 1.5, 1.0, BASE_XI)
    frozen_eval = evaluate_placement(problem, frozen_placement, base_risk)
    frozen_objective = float(frozen["planner"]["objective"])
    if not math.isclose(frozen_eval.total_objective, frozen_objective, rel_tol=1e-9, abs_tol=1e-6):
        raise RuntimeError(f"problem reconstruction objective mismatch: {condition} rep {rep}")
    nominal_moves = moves(problem, frozen_placement)

    variants = {(threshold, BASE_XI, "threshold") for threshold in THRESHOLDS_MS}
    variants |= {(BASE_THRESHOLD_MS, xi, "xi") for xi in XI_WEIGHTS}
    # collapse duplicate nominal point, retaining a joint label
    variants.discard((BASE_THRESHOLD_MS, BASE_XI, "threshold"))
    variants.discard((BASE_THRESHOLD_MS, BASE_XI, "xi"))
    variants.add((BASE_THRESHOLD_MS, BASE_XI, "nominal"))

    rows = []
    for threshold, xi, sweep in sorted(variants):
        p = with_threshold(problem, threshold)
        risk = RiskConfig(0.8, 1.5, 1.0, xi)
        placement, meta = solve_exact(p, risk, time_limit_seconds=10.0)
        ev = evaluate_placement(p, placement, risk)
        nmove = moves(p, placement)
        rows.append({
            "condition": condition,
            "replicate": rep,
            "sweep": sweep,
            "threshold_ms": threshold,
            "xi": xi,
            "feasible": ev.feasible,
            "placement_stable_vs_frozen": placement == frozen_placement,
            "action_stable_vs_frozen": (nmove > 0) == (nominal_moves > 0),
            "moves": nmove,
            "frozen_moves": nominal_moves,
            "objective": ev.total_objective,
            "expected_delay_cost": ev.expected_delay_cost,
            "cvar_delay_cost": ev.cvar_delay_cost,
            "relocation_cost": ev.relocation_cost,
            "slo_slack": ev.slo_slack,
            "positive_slack": ev.slo_slack > 1e-12,
            "proven_optimal": bool(meta.get("proven_optimal", False)),
        })
    return {
        "condition": condition,
        "replicate": rep,
        "frozen_objective": frozen_objective,
        "reconstructed_objective": frozen_eval.total_objective,
        "frozen_slo_slack": frozen_eval.slo_slack,
        "rows": rows,
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=min(4, os.cpu_count() or 1))
    args = parser.parse_args()
    run_root = args.run_root.resolve(); out = args.output_dir.resolve(); out.mkdir(parents=True, exist_ok=True)
    tasks = [(c, r) for c in CONDITIONS for r in range(1, 31)]
    with Pool(processes=args.workers, initializer=_init_worker, initargs=(str(run_root),)) as pool:
        results = list(pool.imap_unordered(_solve_one, tasks, chunksize=1))
    results.sort(key=lambda x: (CONDITIONS.index(x["condition"]), x["replicate"]))

    reproduction = [{k: r[k] for k in ("condition", "replicate", "frozen_objective", "reconstructed_objective", "frozen_slo_slack")} for r in results]
    rows = [row for r in results for row in r["rows"]]
    rows.sort(key=lambda r: (r["threshold_ms"], r["xi"], CONDITIONS.index(r["condition"]), r["replicate"]))
    write_csv(out / "r1_nominal_reconstruction.csv", reproduction)
    write_csv(out / "r1_threshold_xi_cell_results.csv", rows)

    points = sorted({(r["threshold_ms"], r["xi"]) for r in rows})
    summary = []
    condition_summary = []
    for threshold, xi in points:
        subset = [r for r in rows if r["threshold_ms"] == threshold and r["xi"] == xi]
        summary.append({
            "threshold_ms": threshold, "xi": xi, "cells": len(subset),
            "feasibility_rate": sum(bool(r["feasible"]) for r in subset) / len(subset),
            "placement_stability": sum(bool(r["placement_stable_vs_frozen"]) for r in subset) / len(subset),
            "action_stability": sum(bool(r["action_stable_vs_frozen"]) for r in subset) / len(subset),
            "positive_slack_fraction": sum(bool(r["positive_slack"]) for r in subset) / len(subset),
            "mean_moves": sum(float(r["moves"]) for r in subset) / len(subset),
            "mean_slo_slack_ms": sum(float(r["slo_slack"]) for r in subset) / len(subset),
        })
        for condition in CONDITIONS:
            ss = [r for r in subset if r["condition"] == condition]
            condition_summary.append({
                "condition": condition, "threshold_ms": threshold, "xi": xi, "cells": len(ss),
                "placement_stability": sum(bool(r["placement_stable_vs_frozen"]) for r in ss) / len(ss),
                "action_stability": sum(bool(r["action_stable_vs_frozen"]) for r in ss) / len(ss),
                "positive_slack_fraction": sum(bool(r["positive_slack"]) for r in ss) / len(ss),
                "mean_moves": sum(float(r["moves"]) for r in ss) / len(ss),
                "mean_slo_slack_ms": sum(float(r["slo_slack"]) for r in ss) / len(ss),
            })
    write_csv(out / "r1_threshold_xi_summary.csv", summary)
    write_csv(out / "r1_threshold_xi_condition_summary.csv", condition_summary)

    doc = {
        "analysis_type": "post-freeze offline sensitivity; exact R1 reconstruction; no Kubernetes rerun",
        "frozen_problem_reconstruction": {
            "cells": len(reproduction),
            "objective_matches": sum(math.isclose(float(r["frozen_objective"]), float(r["reconstructed_objective"]), rel_tol=1e-9, abs_tol=1e-6) for r in reproduction),
            "positive_nominal_slack_cells": sum(float(r["frozen_slo_slack"]) > 1e-12 for r in reproduction),
        },
        "base": {"threshold_ms": BASE_THRESHOLD_MS, "xi": BASE_XI, "cvar_q": 0.8, "cvar_weight": 1.5, "relocation_weight": 1.0},
        "threshold_sweep_at_xi_1000": THRESHOLDS_MS,
        "xi_sweep_at_threshold_500ms": XI_WEIGHTS,
        "summary": summary,
        "interpretation_boundary": "planning-formulation sensitivity only; application measurements are unchanged",
    }
    (out / "summary.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
