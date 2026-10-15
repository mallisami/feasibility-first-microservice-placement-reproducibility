#!/usr/bin/env python3
"""Run the full checkpointed B+ v0.3 R6 out-of-sample CVaR matrix."""
from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
import random
import sys
import time
from dataclasses import replace
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT / "code"))

from mape_cap_bplus.exact import ExactSolveError, solve_exact
from mape_cap_bplus.models import LinkState, RiskConfig, Scenario
from mape_cap_bplus.objective import evaluate_placement
from mape_cap_bplus.v03_evidence import atomic_write_csv, atomic_write_json, sha256, utc_now, write_manifest
from mape_cap_bplus.r6_problem import build_instance

METHODS = (("Deterministic", None), ("ExpectedValue", None), ("Minimax", None),
           ("BPlus-CVaR", 0.50), ("BPlus-CVaR", 0.80), ("BPlus-CVaR", 0.90), ("BPlus-CVaR", 0.95))
COUNTS = (3, 5, 10, 20, 50)
PROBABILITY_MODELS = ("equal", "empirical", "misspecified")


def load_source(path: Path) -> list[dict]:
    groups: dict[str, dict] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            group = groups.setdefault(row["scenario_id"], {
                "scenario_id": row["scenario_id"], "weight": float(row["weight"]), "links": [],
                "conflict_budgets_seconds": {}, "regime_duration_seconds": float(row["regime_duration_seconds"]),
            })
            conflict = row.get("conflict_group") or None
            if conflict and row.get("budget_seconds"):
                group["conflict_budgets_seconds"][conflict] = float(row["budget_seconds"])
            group["links"].append({
                "source_rack": row["source_rack"], "destination_rack": row["destination_rack"],
                "latency_ms": float(row["latency_ms"]), "goodput_bps": float(row["goodput_bps"]),
                "available": row["available"].strip().lower() == "true", "path_id": row["path_id"],
                "conflict_group": conflict, "provenance": row["provenance"],
            })
    if len(groups) < 8:
        raise ValueError("R6 requires at least eight distinct source trace identities")
    return list(groups.values())


def make_scenarios(source: list[dict], count: int, probability_model: str, seed: int) -> list[Scenario]:
    rng = random.Random(seed * 1009 + count)
    sampled = [source[index] for index in rng.sample(range(len(source)), min(count, len(source)))]
    while len(sampled) < count:
        sampled.append(rng.choice(source))
    raw_weights = []
    for item in sampled:
        if probability_model == "equal":
            raw_weights.append(1.0)
        elif probability_model == "empirical":
            raw_weights.append(float(item["weight"]))
        else:
            raw_weights.append(1.0 / max(float(item["weight"]), 1e-6))
    weight_total = sum(raw_weights)
    result = []
    for index, (item, raw_weight) in enumerate(zip(sampled, raw_weights)):
        jitter_rng = random.Random(seed * 1_000_003 + count * 101 + index)
        links = {}
        for raw in item["links"]:
            latency_factor = max(0.75, jitter_rng.gauss(1.0, 0.07))
            goodput_factor = max(0.70, jitter_rng.gauss(1.0, 0.08))
            link = LinkState(
                raw["source_rack"], raw["destination_rack"], raw["latency_ms"] * latency_factor,
                raw["goodput_bps"] * goodput_factor if raw["available"] else 0.0, raw["available"],
                raw["path_id"], raw["conflict_group"], raw["provenance"] + "+r6-controlled-jitter",
            )
            links[(link.source_rack, link.destination_rack)] = link
        result.append(Scenario(
            scenario_id=f"train-seed{seed}-n{count}-{index}-{item['scenario_id']}",
            weight=raw_weight / weight_total, links=links,
            conflict_budgets_seconds=dict(item["conflict_budgets_seconds"]),
            regime_duration_seconds=float(item["regime_duration_seconds"]),
            metadata={"source_trace_id": item["scenario_id"], "probability_model": probability_model},
        ))
    return result


def source_to_scenario(item: dict) -> Scenario:
    links = {}
    for raw in item["links"]:
        link = LinkState(raw["source_rack"], raw["destination_rack"], raw["latency_ms"], raw["goodput_bps"],
                         raw["available"], raw["path_id"], raw["conflict_group"], raw["provenance"])
        links[(link.source_rack, link.destination_rack)] = link
    return Scenario(item["scenario_id"], 1.0, links, dict(item["conflict_budgets_seconds"]),
                    regime_duration_seconds=float(item["regime_duration_seconds"]))


def solve_minimax(problem, time_limit: float):
    started = time.perf_counter()
    nodes = [node.node_id for node in problem.nodes]
    replicas = [replica.replica_id for replica in problem.replicas]
    best, best_score, evaluated = None, math.inf, 0
    single_risk = RiskConfig(cvar_weight=0.0, relocation_weight=1.0, slo_slack_weight=1000.0)
    for assignment in itertools.product(nodes, repeat=len(replicas)):
        if time.perf_counter() - started >= time_limit:
            break
        placement = dict(zip(replicas, assignment))
        scores = []
        feasible = True
        for scenario in problem.scenarios:
            single = replace(problem, scenarios=(replace(scenario, weight=1.0),))
            evaluation = evaluate_placement(single, placement, single_risk)
            if not evaluation.feasible:
                feasible = False
                break
            scores.append(evaluation.total_objective)
        evaluated += 1
        if feasible and max(scores) < best_score:
            best, best_score = placement, max(scores)
    if best is None:
        raise ExactSolveError("minimax found no feasible placement before its time limit")
    return best, {"solver": "complete-placement-enumeration", "worst_case_objective": best_score,
                  "evaluated_placements": evaluated, "proven_optimal": evaluated == len(nodes) ** len(replicas),
                  "runtime_seconds": time.perf_counter() - started}


def count_relocations(problem, placement: dict[str, str]) -> int:
    return sum(placement[rid] != node for rid, node in problem.current_placement.items())


def heldout_metrics(problem, placement, heldout: list[dict]) -> dict:
    values, slo, infeasible, by_regime = [], 0, 0, {}
    operating_risk = RiskConfig(cvar_weight=0.0, relocation_weight=0.0, slo_slack_weight=1000.0)
    for item in heldout:
        scenario = source_to_scenario(item)
        evaluation = evaluate_placement(replace(problem, scenarios=(scenario,)), placement, operating_risk)
        if not evaluation.feasible:
            infeasible += 1
            by_regime[item["scenario_id"]] = None
            continue
        values.append(evaluation.expected_delay_cost)
        by_regime[item["scenario_id"]] = evaluation.expected_delay_cost
        slo += int(evaluation.slo_slack > 0)
    ordered = sorted(values)
    tail_index = min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1) if ordered else 0
    return {"heldout_mean": mean(values) if values else math.inf, "heldout_tail_p95": ordered[tail_index] if ordered else math.inf,
            "heldout_worst": max(values) if values else math.inf, "heldout_slo_violations": slo,
            "heldout_infeasible": infeasible, "unseen_regime_performance": by_regime}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_root", type=Path)
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--time-limit", type=float, default=30.0)
    args = parser.parse_args()
    run_root = args.run_root.resolve()
    source_path = REPO / "RESULTS" / "calibration" / "external" / "ns3_simulation_backed_traces.csv"
    output = run_root / "raw" / "phase-3-r6-results.csv"
    checkpoint = run_root / "checkpoints" / "phase-3-r6.json"
    if output.exists():
        raise FileExistsError("final R6 raw evidence exists; refusing to overwrite it")
    state = json.loads(checkpoint.read_text(encoding="utf-8")) if checkpoint.exists() else {"completed": [], "rows": []}
    completed = set(state["completed"])
    rows = list(state["rows"])
    source = load_source(source_path)

    for seed in range(1, args.seeds + 1):
        shuffled = list(source)
        random.Random(seed).shuffle(shuffled)
        train_source, heldout = shuffled[:5], shuffled[5:]
        for count in COUNTS:
            for probability_model in PROBABILITY_MODELS:
                scenarios = make_scenarios(train_source, count, probability_model, seed)
                full_problem = build_instance(scenarios)
                for method, quantile in METHODS:
                    run_id = f"seed{seed}:{count}:{probability_model}:{method}:{quantile}"
                    if run_id in completed:
                        continue
                    started = time.perf_counter()
                    try:
                        if method == "Deterministic":
                            training_problem = replace(full_problem, scenarios=(replace(scenarios[0], weight=1.0),))
                            risk = RiskConfig(cvar_weight=0.0, relocation_weight=1.0, slo_slack_weight=1000.0)
                            placement, metadata = solve_exact(training_problem, risk, args.time_limit)
                        elif method == "ExpectedValue":
                            risk = RiskConfig(cvar_weight=0.0, relocation_weight=1.0, slo_slack_weight=1000.0)
                            placement, metadata = solve_exact(full_problem, risk, args.time_limit)
                        elif method == "Minimax":
                            risk = RiskConfig(cvar_weight=0.0, relocation_weight=1.0, slo_slack_weight=1000.0)
                            placement, metadata = solve_minimax(full_problem, args.time_limit)
                        else:
                            risk = RiskConfig(cvar_quantile=float(quantile), cvar_weight=1.5, relocation_weight=1.0, slo_slack_weight=1000.0)
                            placement, metadata = solve_exact(full_problem, risk, args.time_limit)
                        heldout_result = heldout_metrics(full_problem, placement, heldout)
                        row = {"run_id": run_id, "status": "complete", "seed": seed, "method": method,
                               "quantile": "" if quantile is None else quantile, "scenario_count": count,
                               "probability_model": probability_model, "train_trace_ids": json.dumps([x["scenario_id"] for x in train_source]),
                               "heldout_trace_ids": json.dumps([x["scenario_id"] for x in heldout]),
                               "relocations": count_relocations(full_problem, placement), "placement": json.dumps(placement, sort_keys=True),
                               "runtime_seconds": time.perf_counter() - started, "solver_metadata": json.dumps(metadata, sort_keys=True),
                               **{k: json.dumps(v, sort_keys=True) if isinstance(v, dict) else v for k, v in heldout_result.items()}}
                    except Exception as exc:
                        row = {"run_id": run_id, "status": "failure", "seed": seed, "method": method,
                               "quantile": "" if quantile is None else quantile, "scenario_count": count,
                               "probability_model": probability_model, "runtime_seconds": time.perf_counter() - started,
                               "error": str(exc)}
                    rows.append(row)
                    completed.add(run_id)
                    atomic_write_json(checkpoint, {"updated_utc": utc_now(), "completed": sorted(completed), "rows": rows,
                                                   "source_path": str(source_path), "source_sha256": sha256(source_path)})
                    print(f"[{len(completed)}/{args.seeds * len(COUNTS) * len(PROBABILITY_MODELS) * len(METHODS)}] {run_id} {row['status']}", flush=True)
    atomic_write_csv(output, rows)
    state = {"completed_utc": utc_now(), "completed": sorted(completed), "row_count": len(rows),
             "source_path": str(source_path), "source_sha256": sha256(source_path)}
    atomic_write_json(checkpoint, state)
    ledger_path = run_root / "checkpoints" / "ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["phases"]["phase-3-r6"] = "completed" if all(row["status"] == "complete" for row in rows) else "completed_with_failures"
    ledger["current_phase"] = "phase-4-r8"
    atomic_write_json(ledger_path, ledger)
    write_manifest(run_root, run_root / "manifests" / "run.sha256")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
