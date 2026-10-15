#!/usr/bin/env python3
"""N4: solver scaling under a strict matched budget (see PROTOCOL_FROZEN.md). Resumable.

    python n4_runner.py [--pkg PATH] [--budget 30] [--sizes ...] [--seeds ...] [--out DIR]
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument("--pkg", type=Path, default=Path.home() / "revision_2026-09-26" / "pkg")
ap.add_argument("--budget", type=float, default=30.0)
ap.add_argument("--sizes", type=int, nargs="+", default=[10, 12, 16, 20, 24, 32, 40, 50, 75, 100])
ap.add_argument("--seeds", type=int, nargs="+", default=list(range(101, 111)))
ap.add_argument("--out", type=Path, default=HERE / "results")
ARGS = ap.parse_args()
sys.path.insert(0, str(ARGS.pkg / "implementation" / "code"))

from mape_cap_bplus.exact import ExactSolveError, solve_exact  # noqa: E402
from mape_cap_bplus.generators import generate_problem  # noqa: E402
from mape_cap_bplus.lns import robust_lns  # noqa: E402
from mape_cap_bplus.models import RiskConfig  # noqa: E402
from mape_cap_bplus.objective import evaluate_placement  # noqa: E402

RISK = RiskConfig(cvar_quantile=0.9, cvar_weight=1.5, relocation_weight=1.0, slo_slack_weight=1000.0)
OUT = ARGS.out
CSV = OUT / "n4_rows.csv"
FIELDS = ["run_id", "n", "seed", "arm", "status", "feasible", "objective", "lower_bound", "mip_gap",
          "proven_optimal", "runtime_seconds", "iterations_completed", "accepted_improvements",
          "evaluated_candidates", "variable_count", "constraint_count", "error", "utc"]


def done_ids() -> set[str]:
    if not CSV.exists():
        return set()
    with open(CSV, newline="", encoding="utf-8") as fh:
        return {r["run_id"] for r in csv.DictReader(fh)}


def append(row: dict) -> None:
    new = not CSV.exists()
    with open(CSV, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow(row)
        fh.flush()


def problem(n: int, seed: int):
    return generate_problem(replica_count=n, rack_count=3, nodes_per_rack=max(2, math.ceil(n / 18)),
                            scenario_count=3, seed=seed)


def run_arm(p, arm: str, seed: int) -> dict:
    n = len(p.replicas)
    t0 = time.perf_counter()
    if arm == "Exact":
        pl, meta = solve_exact(p, RISK, ARGS.budget, require_optimal=False)
        ev = evaluate_placement(p, pl, RISK)
        return {"status": "optimal" if meta.get("proven_optimal") else "incumbent", "feasible": ev.feasible,
                "objective": ev.total_objective, "lower_bound": meta.get("mip_dual_bound"), "mip_gap": meta.get("mip_gap"),
                "proven_optimal": bool(meta.get("proven_optimal")), "runtime_seconds": time.perf_counter() - t0,
                "variable_count": meta.get("variable_count"), "constraint_count": meta.get("constraint_count")}
    kw = dict(seed=seed, destroy_size=min(4, n), time_limit_seconds=ARGS.budget)
    if arm == "LNS-R8config":
        kw.update(iterations=80, local_iterations=10)
    else:  # LNS-noinit
        kw.update(iterations=10**6, local_iterations=0)
    pl, meta = robust_lns(p, RISK, **kw)
    ev = evaluate_placement(p, pl, RISK)
    log = meta.get("iteration_log", [])
    return {"status": "complete", "feasible": ev.feasible, "objective": ev.total_objective,
            "runtime_seconds": time.perf_counter() - t0, "iterations_completed": meta.get("iterations_completed"),
            "accepted_improvements": sum(1 for x in log if x.get("accepted")),
            "evaluated_candidates": meta.get("evaluated_candidates")}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "config.json").write_text(json.dumps({"budget": ARGS.budget, "sizes": ARGS.sizes, "seeds": ARGS.seeds,
                                                  "risk": RISK.__dict__}, indent=2), encoding="utf-8")
    done = done_ids()
    for n in ARGS.sizes:
        for seed in ARGS.seeds:
            arms = ["Exact", "LNS-noinit"] + (["LNS-R8config"] if n <= 50 else [])
            p = None
            for arm in arms:
                rid = f"n{n}:seed{seed}:{arm}"
                if rid in done:
                    continue
                p = p or problem(n, seed)
                row = {"run_id": rid, "n": n, "seed": seed, "arm": arm, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
                try:
                    row.update(run_arm(p, arm, seed))
                except MemoryError as exc:
                    row.update({"status": "memory-failure", "error": str(exc)})
                except ExactSolveError as exc:
                    # A time limit without any incumbent is a solver outcome, not an infrastructure failure.
                    status = "no-incumbent" if "time limit" in str(exc).lower() else "failure"
                    row.update({"status": status, "feasible": False, "error": str(exc),
                                "runtime_seconds": ARGS.budget})
                except Exception as exc:  # recorded, never silently dropped
                    row.update({"status": "failure", "error": f"{type(exc).__name__}: {exc}"})
                    traceback.print_exc()
                append(row)
                print(f"{rid:28s} {row.get('status')} obj={row.get('objective')} t={row.get('runtime_seconds', 0):.1f}s "
                      f"it={row.get('iterations_completed', '')}", flush=True)
    (OUT / "N4_DONE.json").write_text(json.dumps({"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}), encoding="utf-8")


if __name__ == "__main__":
    main()
