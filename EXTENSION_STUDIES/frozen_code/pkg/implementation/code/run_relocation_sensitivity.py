#!/usr/bin/env python3
"""Relocation cost & CVaR sensitivity sweep.

Uses exact solver to show how placement quality and relocation decisions
change as relocation weight and CVaR weight are varied. Each config
is evaluated across all 4 conditions with the APP_A topology.

Evidence type: controlled-synthetic-sensitivity.
"""
from __future__ import annotations

import csv
import json
import math
import time
from dataclasses import replace
from pathlib import Path

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
from mape_cap_bplus.objective import evaluate_placement

EVIDENCE_TYPE = "controlled-synthetic-sensitivity"
RACKS = ["rack-a", "rack-b", "rack-c"]
MEASURED_RELOCATION_MEAN_S = 4.062
MEASURED_RELOCATION_SD_S = 0.690

RELOCATION_WEIGHTS = [0.0, 0.25, 0.5, 1.0, 2.0, 4.0]
CVAR_WEIGHTS = [0.0, 0.5, 1.0, 1.5, 3.0, 6.0]

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


def build_instance(scenarios: tuple[Scenario, ...], seed: int) -> ProblemInstance:
    nodes = tuple(NodeSpec(f"worker-{r}", r, 8.0, 16384.0) for r in RACKS)
    replicas = (
        ReplicaSpec("frontend-0", "frontend", 0.025, 16.0, anti_affinity_group="frontend"),
        ReplicaSpec("frontend-1", "frontend", 0.025, 16.0, anti_affinity_group="frontend"),
        ReplicaSpec("api-0", "api", 0.025, 16.0, anti_affinity_group="api"),
        ReplicaSpec("api-1", "api", 0.025, 16.0, anti_affinity_group="api"),
        ReplicaSpec("database-0", "database", 0.025, 16.0),
        ReplicaSpec("cache-0", "cache", 0.025, 16.0),
    )
    current = {r.replica_id: nodes[i % len(nodes)].node_id for i, r in enumerate(replicas)}
    base_rps = 120.0
    base_bytes = 15000.0
    flows = (
        FlowSpec("f-fe0-api0", "frontend-0", "api-0", base_rps, base_rps * base_bytes * 8, 1.5, 30.0),
        FlowSpec("f-fe0-api1", "frontend-0", "api-1", base_rps * 0.5, base_rps * 0.5 * base_bytes * 8, 1.0),
        FlowSpec("f-fe1-api0", "frontend-1", "api-0", base_rps * 0.5, base_rps * 0.5 * base_bytes * 8, 1.0),
        FlowSpec("f-fe1-api1", "frontend-1", "api-1", base_rps, base_rps * base_bytes * 8, 1.5, 30.0),
        FlowSpec("f-api0-db", "api-0", "database-0", base_rps * 2, base_rps * 2 * base_bytes * 0.3 * 8, 1.25, 20.0),
        FlowSpec("f-api1-db", "api-1", "database-0", base_rps * 2, base_rps * 2 * base_bytes * 0.3 * 8, 1.25, 20.0),
        FlowSpec("f-api0-cache", "api-0", "cache-0", base_rps * 3, base_rps * 3 * base_bytes * 0.1 * 8, 0.75),
        FlowSpec("f-api1-cache", "api-1", "cache-0", base_rps * 3, base_rps * 3 * base_bytes * 0.1 * 8, 0.75),
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
        instance_id=f"sensitivity-seed{seed}",
        decision_window_seconds=60.0,
        nodes=nodes,
        replicas=replicas,
        flows=flows,
        scenarios=scenarios,
        current_placement=current,
        relocation_costs=relocation_costs,
        max_relocations=2,
        metadata={"application": "APP_A", "topology": "frontend-api-db", "seed": seed},
    )


def count_relocations(problem: ProblemInstance, placement: dict[str, str]) -> int:
    return sum(
        1 for rid, nid in placement.items()
        if problem.current_placement.get(rid) != nid
    )


def main() -> int:
    trace_db = load_link_trace()
    output_path = REPO / "RESULTS" / "supporting" / "reproduced" / "relocation_sensitivity.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    total = len(RELOCATION_WEIGHTS) * len(CVAR_WEIGHTS) * len(CONDITION_SCENARIOS)
    done = 0

    for condition, scenario_ids in CONDITION_SCENARIOS.items():
        scenarios_raw = [trace_db[sid] for sid in scenario_ids if sid in trace_db]
        total_weight = sum(s["weight"] for s in scenarios_raw)
        scenarios = tuple(
            trace_to_scenario({**s, "weight": s["weight"] / total_weight})
            for s in scenarios_raw
        )

        for reloc_w in RELOCATION_WEIGHTS:
            for cvar_w in CVAR_WEIGHTS:
                risk = RiskConfig(
                    cvar_quantile=0.8,
                    cvar_weight=cvar_w,
                    relocation_weight=reloc_w,
                    slo_slack_weight=1000.0,
                )
                problem = build_instance(scenarios, seed=42)
                started = time.perf_counter()
                try:
                    placement, meta = solve_exact(problem, risk, time_limit_seconds=30.0)
                    evaluation = evaluate_placement(problem, placement, risk)
                    elapsed = time.perf_counter() - started
                    relocs = count_relocations(problem, placement)

                    obj = evaluation.total_objective
                    if not math.isfinite(obj):
                        obj = -1.0

                    rows.append({
                        "condition": condition,
                        "relocation_weight": reloc_w,
                        "cvar_weight": cvar_w,
                        "objective": round(obj, 2),
                        "expected_delay_cost": round(evaluation.expected_delay_cost, 2),
                        "cvar_delay_cost": round(evaluation.cvar_delay_cost, 2),
                        "relocation_cost": round(evaluation.relocation_cost, 2),
                        "slo_slack": round(evaluation.slo_slack, 4),
                        "feasible": evaluation.feasible,
                        "relocations": relocs,
                        "runtime_seconds": round(elapsed, 3),
                        "status": "complete",
                        "evidence_type": EVIDENCE_TYPE,
                    })
                except (ExactSolveError, ValueError) as exc:
                    elapsed = time.perf_counter() - started
                    rows.append({
                        "condition": condition,
                        "relocation_weight": reloc_w,
                        "cvar_weight": cvar_w,
                        "objective": -1,
                        "expected_delay_cost": -1,
                        "cvar_delay_cost": -1,
                        "relocation_cost": -1,
                        "slo_slack": -1,
                        "feasible": False,
                        "relocations": -1,
                        "runtime_seconds": round(elapsed, 3),
                        "status": f"error: {exc}",
                        "evidence_type": EVIDENCE_TYPE,
                    })
                done += 1
                r = rows[-1]
                print(f"  [{done}/{total}] {condition} w_r={reloc_w} w_c={cvar_w}: "
                      f"obj={r['objective']} relocs={r['relocations']} ({r['status'][:20]})")

    fields = list(rows[0].keys())
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "evidence_type": EVIDENCE_TYPE,
        "grid": f"{len(RELOCATION_WEIGHTS)} reloc_weights x {len(CVAR_WEIGHTS)} cvar_weights x {len(CONDITION_SCENARIOS)} conditions",
        "total_configs": total,
        "relocation_weights": RELOCATION_WEIGHTS,
        "cvar_weights": CVAR_WEIGHTS,
        "conditions": list(CONDITION_SCENARIOS.keys()),
        "key_findings": [],
    }

    feasible_rows = [r for r in rows if r["status"] == "complete"]
    if feasible_rows:
        by_condition: dict[str, list] = {}
        for r in feasible_rows:
            by_condition.setdefault(r["condition"], []).append(r)

        for cond, cond_rows in by_condition.items():
            objs = [r["objective"] for r in cond_rows if r["objective"] > 0]
            relocs = [r["relocations"] for r in cond_rows]
            if objs:
                summary["key_findings"].append(
                    f"{cond}: obj range [{min(objs):.1f}, {max(objs):.1f}], "
                    f"relocs range [{min(relocs)}, {max(relocs)}]"
                )

        calibrated = [r for r in feasible_rows if r["relocation_weight"] == 1.0 and r["cvar_weight"] == 1.5]
        for r in calibrated:
            summary["key_findings"].append(
                f"Calibrated ({r['condition']}): obj={r['objective']}, relocs={r['relocations']}"
            )

    summary_path = REPO / "RESULTS" / "supporting" / "reproduced" / "relocation_sensitivity.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print(f"\nSensitivity sweep complete: {len(rows)} configs ({len(feasible_rows)} feasible)")
    print(f"Results: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
