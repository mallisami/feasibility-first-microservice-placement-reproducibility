"""Slow-timescale dynamic campaign runner."""
from __future__ import annotations

from dataclasses import replace
from typing import Sequence

from .controller import PersistentRegimeDetector, accept_relocation
from .lns import robust_lns
from .models import ProblemInstance, RiskConfig, Scenario
from .objective import evaluate_placement


def run_dynamic_sequence(
    base_problem: ProblemInstance,
    sequence: Sequence[Scenario],
    risk: RiskConfig,
    *,
    minimum_persistent_windows: int = 3,
    uncertainty_margin: float = 10.0,
    seed: int = 1,
) -> list[dict]:
    if not sequence:
        raise ValueError("dynamic sequence cannot be empty")
    detector = PersistentRegimeDetector(minimum_persistent_windows=minimum_persistent_windows)
    placement = dict(base_problem.current_placement)
    current_regime = sequence[0].scenario_id
    observed: list[str] = []
    records: list[dict] = []

    for index, scenario in enumerate(sequence):
        observed.append(scenario.scenario_id)
        problem = replace(base_problem, scenarios=(replace(scenario, weight=1.0),), current_placement=dict(placement))
        current_eval = evaluate_placement(problem, placement, replace(risk, relocation_weight=0.0))
        expected_relocation = max(
            (cost.expected_seconds for replica_id, cost in problem.relocation_costs.items() if placement.get(replica_id) is not None),
            default=0.0,
        )
        decision = detector.evaluate(
            observed,
            current_regime,
            scenario.regime_duration_seconds,
            expected_relocation,
        )
        candidate = dict(placement)
        candidate_eval = current_eval
        accepted = False
        net_benefit = 0.0
        relocation_count = 0
        planner_runtime = 0.0
        reason = decision.reason
        if decision.should_replan:
            candidate, metadata = robust_lns(problem, risk, placement, seed=seed + index, iterations=25, time_limit_seconds=10.0)
            planner_runtime = metadata["runtime_seconds"]
            candidate_eval = evaluate_placement(problem, candidate, replace(risk, relocation_weight=0.0))
            moved_replicas = [
                replica_id for replica_id, node_id in candidate.items()
                if placement[replica_id] != node_id
            ]
            relocation_cost = sum(
                problem.relocation_costs[replica_id].cost_units
                for replica_id in moved_replicas
            )
            relocation_uncertainty = sum(
                problem.relocation_costs[replica_id].uncertainty_units
                for replica_id in moved_replicas
            )
            relocation_count = len(moved_replicas)
            total_uncertainty_margin = uncertainty_margin + relocation_uncertainty
            accepted, net_benefit, acceptance_reason = accept_relocation(
                current_eval.total_objective,
                candidate_eval.total_objective,
                risk.relocation_weight * relocation_cost,
                total_uncertainty_margin,
            )
            reason = f"{decision.reason}; {acceptance_reason}"
            if accepted:
                placement = dict(candidate)
                current_regime = scenario.scenario_id
        records.append(
            {
                "window_index": index,
                "scenario_id": scenario.scenario_id,
                "regime_duration_seconds": scenario.regime_duration_seconds,
                "should_replan": decision.should_replan,
                "accepted": accepted,
                "current_objective": current_eval.total_objective,
                "candidate_objective": candidate_eval.total_objective,
                "net_benefit": net_benefit,
                "relocation_count": relocation_count if accepted else 0,
                "relocation_uncertainty_units": relocation_uncertainty if decision.should_replan else 0.0,
                "base_uncertainty_margin": uncertainty_margin,
                "planner_runtime_seconds": planner_runtime,
                "reason": reason,
                "placement": dict(placement),
            }
        )
    return records
