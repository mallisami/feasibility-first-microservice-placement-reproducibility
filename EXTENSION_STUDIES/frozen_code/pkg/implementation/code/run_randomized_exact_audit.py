#!/usr/bin/env python3
"""Reproduce the randomized exact-vs-exhaustive verification audit.

This is verification evidence for the small-instance MILP implementation, not
an application-performance experiment.  It uses deterministic synthetic
instances and enumerates every allowed replica placement for each case.
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT / "code"))

from mape_cap_bplus.exact import solve_exact  # noqa: E402
from mape_cap_bplus.generators import generate_problem  # noqa: E402
from mape_cap_bplus.models import RiskConfig  # noqa: E402
from mape_cap_bplus.objective import evaluate_placement  # noqa: E402


def exhaustive_best(problem, risk: RiskConfig) -> tuple[float, int]:
    replicas = tuple(replica.replica_id for replica in problem.replicas)
    domains = [problem.allowed_nodes_for(replica_id) for replica_id in replicas]
    best = math.inf
    feasible = 0
    for assignment in itertools.product(*domains):
        placement = dict(zip(replicas, assignment))
        evaluation = evaluate_placement(problem, placement, risk)
        if not evaluation.feasible:
            continue
        feasible += 1
        if evaluation.total_objective < best:
            best = evaluation.total_objective
    return best, feasible


def run_audit(cases: int, seed: int) -> dict:
    if cases < 1:
        raise ValueError("cases must be positive")
    rng = random.Random(seed)
    records: list[dict] = []
    matches = 0
    for case in range(cases):
        scenario_count = rng.choice((1, 2, 3))
        instance_seed = rng.randrange(1, 10_000_000)
        problem = generate_problem(
            replica_count=4,
            rack_count=3,
            nodes_per_rack=1,
            scenario_count=scenario_count,
            seed=instance_seed,
        )
        risk = RiskConfig(
            cvar_quantile=rng.choice((0.75, 0.8, 0.9)),
            cvar_weight=rng.choice((0.0, 0.25, 1.0, 2.0)),
            relocation_weight=rng.choice((0.0, 0.5, 1.0, 5.0)),
            slo_slack_weight=rng.choice((0.0, 10.0, 1000.0)),
        )
        exact_placement, metadata = solve_exact(problem, risk, time_limit_seconds=30.0)
        exact_eval = evaluate_placement(problem, exact_placement, risk)
        exhaustive_objective, feasible_count = exhaustive_best(problem, risk)
        matched = math.isclose(
            exact_eval.total_objective,
            exhaustive_objective,
            rel_tol=1e-8,
            abs_tol=1e-8,
        )
        matches += int(matched)
        records.append(
            {
                "case": case,
                "instance_seed": instance_seed,
                "scenario_count": scenario_count,
                "risk": {
                    "cvar_quantile": risk.cvar_quantile,
                    "cvar_weight": risk.cvar_weight,
                    "relocation_weight": risk.relocation_weight,
                    "slo_slack_weight": risk.slo_slack_weight,
                },
                "feasible_placements": feasible_count,
                "exact_status": "optimal" if metadata.get("proven_optimal") else "unproven",
                "exhaustive_objective": exhaustive_objective,
                "exact_objective": exact_eval.total_objective,
                "matched": matched,
            }
        )
    return {
        "audit_type": "randomized-exact-vs-exhaustive-small-instance-verification",
        "seed": seed,
        "cases": cases,
        "matches": matches,
        "mismatches": cases - matches,
        "records": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=int, default=120)
    parser.add_argument("--seed", type=int, default=20260807)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO / "RESULTS" / "audit" / "reproduced" / "randomized_exact_vs_exhaustive_120_reproducible.json",
    )
    args = parser.parse_args()
    payload = run_audit(args.cases, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"matches={payload['matches']}/{payload['cases']} output={args.output}")
    return 0 if payload["mismatches"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
