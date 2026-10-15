#!/usr/bin/env python3
"""Run the sequential checkpointed v0.3 Exact/LNS scalability matrix."""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))

from mape_cap_bplus.exact import ExactSolveError, solve_exact
from mape_cap_bplus.generators import generate_problem
from mape_cap_bplus.lns import robust_lns
from mape_cap_bplus.models import RiskConfig
from mape_cap_bplus.objective import evaluate_placement
from mape_cap_bplus.v03_evidence import atomic_write_csv, atomic_write_json, utc_now, write_manifest

SIZES = (6, 8, 10, 12, 16, 20, 24, 40, 50)
SEEDS = (1, 2, 3)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_root", type=Path)
    parser.add_argument("--exact-limit", type=float, default=10.0)
    parser.add_argument("--lns-limit", type=float, default=10.0)
    args = parser.parse_args()
    run_root = args.run_root.resolve()
    output = run_root / "raw" / "phase-4-r8-results.csv"
    checkpoint = run_root / "checkpoints" / "phase-4-r8.json"
    if output.exists():
        raise FileExistsError("final R8 evidence already exists")
    state = json.loads(checkpoint.read_text(encoding="utf-8")) if checkpoint.exists() else {"completed": [], "rows": []}
    completed, rows = set(state["completed"]), list(state["rows"])
    risk = RiskConfig(cvar_quantile=0.9, cvar_weight=1.5, relocation_weight=1.0, slo_slack_weight=1000.0)
    exact_reference: dict[tuple[int, int], dict] = {}

    for size in SIZES:
        for seed in SEEDS:
            # Each node holds eight CPU units; this topology stays feasible without inflating MILP arcs.
            nodes_per_rack = max(2, math.ceil(size / 18))
            problem = generate_problem(replica_count=size, rack_count=3, nodes_per_rack=nodes_per_rack,
                                       scenario_count=3, seed=seed)
            for method in ("Exact", "LNS"):
                run_id = f"r{size}:seed{seed}:{method}"
                if run_id in completed:
                    prior = next(row for row in rows if row["run_id"] == run_id)
                    if method == "Exact" and prior.get("status") in ("optimal", "incumbent-timeout"):
                        exact_reference[(size, seed)] = prior
                    continue
                started = time.perf_counter()
                try:
                    if method == "Exact":
                        placement, metadata = solve_exact(problem, risk, args.exact_limit, require_optimal=False)
                        evaluation = evaluate_placement(problem, placement, risk)
                        proven = bool(metadata["proven_optimal"])
                        row = {
                            "run_id": run_id, "replica_count": size, "seed": seed, "method": method,
                            "status": "optimal" if proven else "incumbent-timeout", "proven_optimal": proven,
                            "objective": evaluation.total_objective, "incumbent": evaluation.total_objective,
                            "lower_bound": metadata.get("mip_dual_bound"), "mip_gap": metadata.get("mip_gap"),
                            "timeout": not proven, "runtime_seconds": time.perf_counter() - started,
                            "memory_failure": False, "variable_count": metadata.get("variable_count"),
                            "constraint_count": metadata.get("constraint_count"), "feasible": evaluation.feasible,
                            "placement": json.dumps(placement, sort_keys=True), "solver_metadata": json.dumps(metadata, sort_keys=True),
                        }
                        exact_reference[(size, seed)] = row
                    else:
                        placement, metadata = robust_lns(problem, risk, seed=seed, iterations=80,
                            destroy_size=min(4, size), time_limit_seconds=args.lns_limit, local_iterations=10)
                        evaluation = evaluate_placement(problem, placement, risk)
                        reference = exact_reference.get((size, seed))
                        bound = float(reference["lower_bound"]) if reference and reference.get("lower_bound") not in (None, "", "nan") else math.nan
                        gap = ((evaluation.total_objective - bound) / abs(bound) * 100.0) if math.isfinite(bound) and bound != 0 else math.nan
                        log = metadata.get("iteration_log", [])
                        row = {
                            "run_id": run_id, "replica_count": size, "seed": seed, "method": method, "status": "complete",
                            "initial_solution": json.dumps(metadata.get("local_initialization"), sort_keys=True),
                            "iterations": metadata.get("iterations_completed"),
                            "convergence": json.dumps([{k: x.get(k) for k in ("iteration", "objective", "accepted")} for x in log]),
                            "restarts": 0, "best_objective": evaluation.total_objective, "objective": evaluation.total_objective,
                            "feasible": evaluation.feasible, "runtime_seconds": time.perf_counter() - started,
                            "exact_or_bound_gap_percent": gap, "evaluated_candidates": metadata.get("evaluated_candidates"),
                            "placement": json.dumps(placement, sort_keys=True), "solver_metadata": json.dumps(metadata, sort_keys=True),
                        }
                except MemoryError as exc:
                    row = {"run_id": run_id, "replica_count": size, "seed": seed, "method": method,
                           "status": "memory-failure", "memory_failure": True, "runtime_seconds": time.perf_counter() - started,
                           "error": str(exc)}
                except Exception as exc:
                    row = {"run_id": run_id, "replica_count": size, "seed": seed, "method": method,
                           "status": "failure", "memory_failure": False, "runtime_seconds": time.perf_counter() - started,
                           "error": str(exc)}
                rows.append(row)
                completed.add(run_id)
                atomic_write_json(checkpoint, {"updated_utc": utc_now(), "completed": sorted(completed), "rows": rows})
                print(f"[{len(completed)}/{len(SIZES) * len(SEEDS) * 2}] {run_id} {row['status']}", flush=True)

    atomic_write_csv(output, rows)
    atomic_write_json(checkpoint, {"completed_utc": utc_now(), "completed": sorted(completed), "row_count": len(rows)})
    ledger_path = run_root / "checkpoints" / "ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    unacceptable = [row for row in rows if row["status"] in ("failure", "memory-failure")]
    ledger["phases"]["phase-4-r8"] = "completed" if not unacceptable else "completed_with_failures"
    ledger["current_phase"] = "phase-5-r5-ns3"
    atomic_write_json(ledger_path, ledger)
    write_manifest(run_root, run_root / "manifests" / "run.sha256")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
