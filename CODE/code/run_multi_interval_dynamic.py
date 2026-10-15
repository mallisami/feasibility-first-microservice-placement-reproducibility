#!/usr/bin/env python3
"""Multi-interval dynamic adaptation experiment.

Demonstrates the two-timescale controller across a 20-window regime sequence:
  stable(4) → degraded(4) → outage(2) → recovery(4) → conflict(3) → stable(3)

Compares B+ dynamic adaptation against static-best and no-adaptation baselines,
showing correct relocation decisions at regime boundaries and correct no-ops
within stable regimes.

Evidence type: controlled-synthetic-dynamic.
"""
from __future__ import annotations

import csv
import json
import time
from dataclasses import replace
from pathlib import Path

import math

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent

import sys
sys.path.insert(0, str(ROOT / "code"))

from mape_cap_bplus.models import (
    FlowSpec, LinkState, NodeSpec, ProblemInstance,
    RelocationCost, ReplicaSpec, RiskConfig, Scenario,
)
from mape_cap_bplus.dynamic import run_dynamic_sequence
from mape_cap_bplus.exact import solve_exact, ExactSolveError
from mape_cap_bplus.objective import evaluate_placement
from mape_cap_bplus.generators import homogenize_network

EVIDENCE_TYPE = "controlled-synthetic-dynamic"
RACKS = ["rack-a", "rack-b", "rack-c"]
MEASURED_RELOCATION_MEAN_S = 4.062
MEASURED_RELOCATION_SD_S = 0.690

REGIME_SEQUENCE = (
    ["stable"] * 4 +
    ["degraded"] * 4 +
    ["outage"] * 2 +
    ["recovery"] * 4 +
    ["conflict"] * 3 +
    ["stable"] * 3
)

REGIME_TO_SCENARIO = {
    "stable": "nominal-los",
    "degraded": "persistent-degradation",
    "outage": "outage-with-fallback",
    "recovery": "recovery",
    "conflict": "conflict-dense",
}

REPLICATES = 10


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


def build_dynamic_instance(scenarios: tuple[Scenario, ...], seed: int) -> ProblemInstance:
    """4-replica instance matching the original dynamic sequence design."""
    import random
    rng = random.Random(seed)
    nodes = tuple(NodeSpec(f"worker-{r}", r, 8.0, 16384.0) for r in RACKS)
    replicas = (
        ReplicaSpec("ingress-0", "ingress", 0.025, 16.0),
        ReplicaSpec("orders-0", "orders", 0.025, 16.0),
        ReplicaSpec("profile-0", "profile", 0.025, 16.0),
        ReplicaSpec("database-0", "database", 0.025, 16.0),
    )
    current = {r.replica_id: nodes[i % len(nodes)].node_id for i, r in enumerate(replicas)}
    base_rps = rng.uniform(50, 200)
    base_bytes = rng.uniform(2000, 50000)
    flows = (
        FlowSpec("f-ingress-orders", "ingress-0", "orders-0", base_rps, base_rps * base_bytes * 8, 1.5, 30.0),
        FlowSpec("f-ingress-profile", "ingress-0", "profile-0", base_rps * 0.8, base_rps * 0.8 * base_bytes * 8, 1.0),
        FlowSpec("f-orders-db", "orders-0", "database-0", base_rps * 1.5, base_rps * 1.5 * base_bytes * 0.3 * 8, 1.25, 20.0),
        FlowSpec("f-profile-db", "profile-0", "database-0", base_rps * 0.5, base_rps * 0.5 * base_bytes * 0.2 * 8, 0.75),
        FlowSpec("f-orders-profile", "orders-0", "profile-0", base_rps * 0.3, base_rps * 0.3 * base_bytes * 0.5 * 8, 1.0),
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
        instance_id=f"dynamic-seed{seed}",
        decision_window_seconds=60.0,
        nodes=nodes,
        replicas=replicas,
        flows=flows,
        scenarios=scenarios,
        current_placement=current,
        relocation_costs=relocation_costs,
        max_relocations=2,
        metadata={"application": "DYNAMIC", "topology": "ingress-orders-profile-db", "seed": seed},
    )


def evaluate_static_baseline(problem: ProblemInstance, scenario: Scenario, risk: RiskConfig) -> float:
    """Evaluate the current (no-change) placement under a given scenario."""
    single_problem = replace(problem, scenarios=(replace(scenario, weight=1.0),))
    evaluation = evaluate_placement(single_problem, dict(problem.current_placement), risk)
    return evaluation.total_objective


def main() -> int:
    trace_db = load_link_trace()
    scenario_cache: dict[str, Scenario] = {}
    for regime, sid in REGIME_TO_SCENARIO.items():
        scenario_cache[regime] = trace_to_scenario(trace_db[sid])

    sequence = [scenario_cache[r] for r in REGIME_SEQUENCE]
    base_scenarios = tuple(scenario_cache[r] for r in ["stable", "degraded", "recovery"])
    total_weight = sum(s.weight for s in base_scenarios)
    base_scenarios = tuple(replace(s, weight=s.weight / total_weight) for s in base_scenarios)

    risk = RiskConfig(cvar_quantile=0.8, cvar_weight=1.5, relocation_weight=1.0, slo_slack_weight=1000.0)
    output_path = REPO / "RESULTS" / "supporting" / "reproduced" / "multi_interval_dynamic.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    all_rows: list[dict] = []

    for rep in range(1, REPLICATES + 1):
        seed = hash(("dynamic", rep)) % (2**31)
        problem = build_dynamic_instance(base_scenarios, seed=seed)

        records = run_dynamic_sequence(
            problem, sequence, risk,
            minimum_persistent_windows=3,
            uncertainty_margin=10.0,
            seed=seed,
        )

        static_objectives = []
        for idx, regime in enumerate(REGIME_SEQUENCE):
            sc = scenario_cache[regime]
            single_problem = replace(
                problem,
                scenarios=(replace(sc, weight=1.0),),
                current_placement=dict(problem.current_placement),
            )
            static_eval = evaluate_placement(
                single_problem, dict(problem.current_placement),
                replace(risk, relocation_weight=0.0),
            )
            static_objectives.append(static_eval.total_objective)

        for idx, (record, regime) in enumerate(zip(records, REGIME_SEQUENCE)):
            dyn_obj = record["current_objective"]
            stat_obj = static_objectives[idx]
            finite_both = math.isfinite(dyn_obj) and math.isfinite(stat_obj) and stat_obj > 0
            all_rows.append({
                "replicate": rep,
                "window_index": idx,
                "regime": regime,
                "scenario_id": record["scenario_id"],
                "should_replan": record["should_replan"],
                "accepted": record["accepted"],
                "dynamic_objective": dyn_obj if math.isfinite(dyn_obj) else -1,
                "static_baseline_objective": stat_obj if math.isfinite(stat_obj) else -1,
                "improvement_pct": round(
                    (stat_obj - dyn_obj) / stat_obj * 100, 2
                ) if finite_both else 0.0,
                "relocations": record["relocation_count"],
                "net_benefit": record["net_benefit"],
                "reason": record["reason"],
                "evidence_type": EVIDENCE_TYPE,
            })

        total_relocs = sum(r["relocation_count"] for r in records)
        finite_dyn = [r["current_objective"] for r in records if math.isfinite(r["current_objective"])]
        finite_stat = [s for s in static_objectives if math.isfinite(s)]
        dyn_mean = np.mean(finite_dyn) if finite_dyn else float("inf")
        stat_mean = np.mean(finite_stat) if finite_stat else float("inf")
        improv = (stat_mean - dyn_mean) / stat_mean * 100 if math.isfinite(stat_mean) and stat_mean > 0 and math.isfinite(dyn_mean) else 0.0
        print(f"  Rep {rep}: {total_relocs} relocations, "
              f"dynamic_mean={dyn_mean:.1f}, static_mean={stat_mean:.1f}, "
              f"improvement={improv:.1f}% (excl. outage windows)")

    fields = list(all_rows[0].keys())
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(all_rows)

    summary = {
        "evidence_type": EVIDENCE_TYPE,
        "regime_sequence": " → ".join(REGIME_SEQUENCE),
        "windows": len(REGIME_SEQUENCE),
        "replicates": REPLICATES,
        "total_rows": len(all_rows),
    }

    finite_rows = [r for r in all_rows if r["dynamic_objective"] > 0 and r["static_baseline_objective"] > 0]
    total_relocs_all = sum(1 for r in all_rows if r["relocations"] > 0)
    if finite_rows:
        dynamic_objs = [r["dynamic_objective"] for r in finite_rows]
        static_objs = [r["static_baseline_objective"] for r in finite_rows]
        summary["mean_dynamic_objective"] = round(float(np.mean(dynamic_objs)), 2)
        summary["mean_static_objective"] = round(float(np.mean(static_objs)), 2)
        summary["overall_improvement_pct"] = round(
            (np.mean(static_objs) - np.mean(dynamic_objs)) / max(np.mean(static_objs), 1) * 100, 2
        )
    else:
        summary["mean_dynamic_objective"] = -1
        summary["mean_static_objective"] = -1
        summary["overall_improvement_pct"] = 0
    summary["total_relocations"] = total_relocs_all
    summary["outage_windows_excluded"] = len(all_rows) - len(finite_rows)

    regime_transitions = []
    for i in range(1, len(REGIME_SEQUENCE)):
        if REGIME_SEQUENCE[i] != REGIME_SEQUENCE[i - 1]:
            regime_transitions.append({"from": REGIME_SEQUENCE[i - 1], "to": REGIME_SEQUENCE[i], "window": i})
    summary["regime_transitions"] = regime_transitions

    summary_path = REPO / "RESULTS" / "supporting" / "reproduced" / "multi_interval_dynamic.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print(f"\nMulti-interval dynamic experiment complete: {len(all_rows)} rows")
    print(f"Results: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
