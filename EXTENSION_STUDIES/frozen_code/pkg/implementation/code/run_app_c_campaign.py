#!/usr/bin/env python3
"""Third application topology (APP_C: pipeline/chain) confirmatory campaign.

APP_C represents a data-pipeline topology: ingress → preprocessor → enricher →
aggregator → writer → store. This is a linear chain (no mesh, no fan-out),
which tests whether B+ handles pipeline-style microservices differently.

Evidence type: confirmatory-external-derived-trace.
"""
from __future__ import annotations

import csv
import json
import random
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent

import sys
sys.path.insert(0, str(ROOT / "code"))

from mape_cap_bplus.models import (
    FlowSpec, LinkState, NodeSpec, ProblemInstance,
    RelocationCost, ReplicaSpec, RiskConfig, Scenario,
)
from mape_cap_bplus.exact import solve_exact, ExactSolveError
from mape_cap_bplus.lns import robust_lns
from mape_cap_bplus.heuristic import resource_greedy_placement
from mape_cap_bplus.objective import evaluate_placement
from mape_cap_bplus.generators import homogenize_network, single_scenario

EVIDENCE_TYPE = "confirmatory-external-derived-trace"
RACKS = ["rack-a", "rack-b", "rack-c"]
MEASURED_RELOCATION_MEAN_S = 4.062
MEASURED_RELOCATION_SD_S = 0.690

CONDITION_SCENARIOS = {
    "stable": ["nominal-los", "asymmetric-los", "recovery"],
    "persistent_degradation": ["persistent-degradation", "partial-blockage", "mixed-regime"],
    "outage_with_fallback": ["outage-with-fallback", "nominal-los", "mixed-regime"],
    "conflict_dense": ["conflict-dense", "partial-blockage", "persistent-degradation"],
}


def load_link_trace() -> dict[str, dict]:
    path = REPO / "RESULTS" / "calibration" / "external" / "ns3-simulation-traces-2026-08-08" / "link_trace.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    return {s["scenario_id"]: s for s in doc["scenarios"]}


def trace_to_scenario(trace: dict) -> Scenario:
    links: dict[tuple[str, str], LinkState] = {}
    budgets: dict[str, float] = {}
    for link in trace["links"]:
        pair = (link["source_rack"], link["destination_rack"])
        links[pair] = LinkState(
            source_rack=link["source_rack"],
            destination_rack=link["destination_rack"],
            latency_ms=link["latency_ms"],
            goodput_bps=link["goodput_bps"],
            available=link["available"],
            path_id=link["path_id"],
            conflict_group=link.get("conflict_group"),
            provenance=link["provenance"],
        )
    for group_name, budget_val in trace.get("conflict_budgets_seconds", {}).items():
        budgets[group_name] = budget_val
    return Scenario(
        scenario_id=trace["scenario_id"],
        weight=trace["weight"],
        links=links,
        conflict_budgets_seconds=budgets,
        intra_rack_latency_ms=trace.get("intra_rack_latency_ms", 0.2),
        intra_rack_goodput_bps=trace.get("intra_rack_goodput_bps", 100_000_000_000.0),
        regime_duration_seconds=trace.get("regime_duration_seconds", 300.0),
        metadata={"source": "derived-from-published-802.11ad-parameters"},
    )


def build_app_c_instance(
    scenarios: tuple[Scenario, ...],
    seed: int,
    decision_window_seconds: float = 60.0,
) -> ProblemInstance:
    """Pipeline/chain topology (8 replicas): ingress→preproc(x2)→enricher→aggregator(x2)→writer→store."""
    rng = random.Random(seed)
    nodes = tuple(NodeSpec(f"worker-{r}", r, 8.0, 16384.0) for r in RACKS)
    replicas = (
        ReplicaSpec("ingress-0", "ingress", 0.025, 16.0),
        ReplicaSpec("preproc-0", "preprocessor", 0.025, 16.0, anti_affinity_group="preprocessor"),
        ReplicaSpec("preproc-1", "preprocessor", 0.025, 16.0, anti_affinity_group="preprocessor"),
        ReplicaSpec("enricher-0", "enricher", 0.025, 16.0),
        ReplicaSpec("aggregator-0", "aggregator", 0.025, 16.0, anti_affinity_group="aggregator"),
        ReplicaSpec("aggregator-1", "aggregator", 0.025, 16.0, anti_affinity_group="aggregator"),
        ReplicaSpec("writer-0", "writer", 0.025, 16.0),
        ReplicaSpec("store-0", "store", 0.025, 16.0),
    )
    current = {r.replica_id: nodes[i % len(nodes)].node_id for i, r in enumerate(replicas)}
    base_rps = rng.uniform(50, 200)
    base_bytes = rng.uniform(2000, 50000)

    flows = (
        FlowSpec("f-ingress-pp0", "ingress-0", "preproc-0", base_rps, base_rps * base_bytes * 8, 1.5, 25.0),
        FlowSpec("f-ingress-pp1", "ingress-0", "preproc-1", base_rps, base_rps * base_bytes * 8, 1.5, 25.0),
        FlowSpec("f-pp0-enrich", "preproc-0", "enricher-0", base_rps, base_rps * base_bytes * 0.8 * 8, 1.25, 20.0),
        FlowSpec("f-pp1-enrich", "preproc-1", "enricher-0", base_rps, base_rps * base_bytes * 0.8 * 8, 1.25, 20.0),
        FlowSpec("f-enrich-agg0", "enricher-0", "aggregator-0", base_rps * 0.6, base_rps * 0.6 * base_bytes * 1.2 * 8, 1.0),
        FlowSpec("f-enrich-agg1", "enricher-0", "aggregator-1", base_rps * 0.4, base_rps * 0.4 * base_bytes * 1.2 * 8, 1.0),
        FlowSpec("f-agg0-writer", "aggregator-0", "writer-0", base_rps * 0.6, base_rps * 0.6 * base_bytes * 0.5 * 8, 1.5, 15.0),
        FlowSpec("f-agg1-writer", "aggregator-1", "writer-0", base_rps * 0.4, base_rps * 0.4 * base_bytes * 0.5 * 8, 1.5, 15.0),
        FlowSpec("f-writer-store", "writer-0", "store-0", base_rps, base_rps * base_bytes * 0.3 * 8, 1.75, 10.0),
    )

    relocation_costs = {
        r.replica_id: RelocationCost(
            r.replica_id,
            cost_units=MEASURED_RELOCATION_MEAN_S * 1000,
            expected_seconds=MEASURED_RELOCATION_MEAN_S,
            uncertainty_units=MEASURED_RELOCATION_SD_S * 1000,
            provenance="calibrated-from-kind-pilot-measurements",
        )
        for r in replicas
    }
    return ProblemInstance(
        instance_id=f"app-c-seed{seed}",
        decision_window_seconds=decision_window_seconds,
        nodes=nodes,
        replicas=replicas,
        flows=flows,
        scenarios=scenarios,
        current_placement=current,
        relocation_costs=relocation_costs,
        max_relocations=3,
        metadata={"application": "APP_C", "topology": "pipeline-chain", "seed": seed},
    )


def run_method(method: str, problem: ProblemInstance, risk: RiskConfig, seed: int) -> dict[str, Any]:
    started = time.perf_counter()
    meta: dict = {}
    try:
        if method == "Current":
            placement = dict(problem.current_placement)
        elif method == "TrafficOnly-MAPE-CAP":
            traffic_problem = homogenize_network(problem)
            traffic_risk = replace(risk, cvar_weight=0.0)
            placement, meta = solve_exact(traffic_problem, traffic_risk, time_limit_seconds=30.0)
        elif method == "DeterministicNetworkAware":
            det_problem = single_scenario(problem, 0)
            det_risk = replace(risk, cvar_weight=0.0)
            placement, meta = solve_exact(det_problem, det_risk, time_limit_seconds=30.0)
        elif method == "BPlus-LNS":
            placement, meta = robust_lns(
                problem, risk, seed=seed, iterations=40,
                destroy_size=min(4, len(problem.replicas)),
                time_limit_seconds=5.0, local_iterations=8,
            )
        elif method == "BPlus-Exact":
            placement, meta = solve_exact(problem, risk, time_limit_seconds=45.0)
        else:
            raise ValueError(f"unknown method {method}")
        runtime = time.perf_counter() - started
        status = "complete"
    except (ExactSolveError, ValueError) as exc:
        runtime = time.perf_counter() - started
        return {"status": "failure", "method": method, "error": str(exc), "runtime_seconds": runtime}

    evaluation = evaluate_placement(problem, placement, risk)
    if not evaluation.feasible:
        status = "complete-infeasible"

    for drop_key in ("iteration_log", "candidate_log"):
        if isinstance(meta, dict):
            meta.pop(drop_key, None)

    return {
        "status": status,
        "method": method,
        "objective": evaluation.total_objective,
        "expected_delay_cost": evaluation.expected_delay_cost,
        "cvar_delay_cost": evaluation.cvar_delay_cost,
        "relocation_cost": evaluation.relocation_cost,
        "slo_slack": evaluation.slo_slack,
        "feasible": evaluation.feasible,
        "runtime_seconds": runtime,
        "placement": placement,
        "solver_metadata": meta,
    }


def main() -> int:
    trace_db = load_link_trace()
    risk = RiskConfig(cvar_quantile=0.8, cvar_weight=1.5, relocation_weight=1.0, slo_slack_weight=1000.0)
    methods = ["Current", "TrafficOnly-MAPE-CAP", "DeterministicNetworkAware", "BPlus-LNS", "BPlus-Exact"]
    replicates = 30

    output_path = REPO / "RESULTS" / "supporting" / "reproduced" / "app_c_campaign.csv"
    checkpoint_path = REPO / "RESULTS" / "supporting" / "reproduced" / "app_c_checkpoint.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    completed_ids: set[str] = set()
    all_rows: list[dict] = []
    if checkpoint_path.exists():
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        completed_ids = set(checkpoint.get("completed", []))
    if output_path.exists():
        with output_path.open(newline="", encoding="utf-8") as f:
            all_rows = list(csv.DictReader(f))

    total = len(CONDITION_SCENARIOS) * len(methods) * replicates
    done = len(completed_ids)
    print(f"APP_C Campaign: {total} total runs, {done} completed, {total - done} remaining")

    for condition, scenario_ids in CONDITION_SCENARIOS.items():
        scenarios_raw = [trace_db[sid] for sid in scenario_ids if sid in trace_db]
        if not scenarios_raw:
            continue
        total_weight = sum(s["weight"] for s in scenarios_raw)
        scenarios = tuple(
            trace_to_scenario({**s, "weight": s["weight"] / total_weight})
            for s in scenarios_raw
        )

        for rep in range(1, replicates + 1):
            seed = hash(("APP_C", condition, rep)) % (2**31)
            problem = build_app_c_instance(scenarios, seed=seed)

            for method in methods:
                run_id = f"APP_C:{condition}:{method}:{rep}"
                if run_id in completed_ids:
                    continue

                result = run_method(method, problem, risk, seed=seed + hash(method) % 1000)
                row = {
                    "run_id": run_id,
                    "application": "APP_C",
                    "network_condition": condition,
                    "replicate": rep,
                    "instance_id": problem.instance_id,
                    "replica_count": len(problem.replicas),
                    "flow_count": len(problem.flows),
                    "scenario_count": len(problem.scenarios),
                    "evidence_type": EVIDENCE_TYPE,
                    **{k: (json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else v)
                       for k, v in result.items()},
                    "cvar_quantile": risk.cvar_quantile,
                    "cvar_weight": risk.cvar_weight,
                    "relocation_weight": risk.relocation_weight,
                }
                all_rows.append(row)
                completed_ids.add(run_id)
                done += 1

                if done % 50 == 0:
                    _save(output_path, checkpoint_path, all_rows, completed_ids)
                    print(f"  [{done}/{total}] checkpoint saved")

        print(f"  APP_C/{condition}: complete")

    _save(output_path, checkpoint_path, all_rows, completed_ids)
    print(f"\nAPP_C campaign complete: {len(all_rows)} total rows in {output_path}")
    return 0


def _save(output_path, checkpoint_path, rows, completed):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    fields = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    checkpoint_path.write_text(
        json.dumps({"completed": sorted(completed)}, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
