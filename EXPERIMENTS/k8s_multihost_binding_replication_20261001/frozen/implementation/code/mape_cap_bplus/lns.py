"""Bounded large-neighbourhood search for scalable B+ experiments."""
from __future__ import annotations

from dataclasses import asdict
import itertools
import random
import time
from typing import Mapping

from .heuristic import find_feasible_start, robust_local_search
from .models import ProblemInstance, RiskConfig
from .objective import evaluate_placement


def _incident_weights(problem: ProblemInstance) -> dict[str, float]:
    weights = {replica.replica_id: 0.0 for replica in problem.replicas}
    for flow in problem.flows:
        weight = flow.requests_per_window * flow.criticality
        weights[flow.source_replica] += weight
        weights[flow.destination_replica] += weight
    return weights


def robust_lns(
    problem: ProblemInstance,
    risk: RiskConfig,
    initial_placement: Mapping[str, str] | None = None,
    *,
    seed: int = 1,
    iterations: int = 50,
    destroy_size: int = 3,
    max_neighbour_assignments: int = 20_000,
    time_limit_seconds: float = 30.0,
    local_iterations: int = 10,
):
    """Large-neighbourhood search with exact bounded subset enumeration.

    It is deterministic for a fixed seed. Each destroyed subset is repaired by
    enumerating its complete allowed-node Cartesian product up to the declared
    cap, while the remaining placement stays fixed.
    """
    if iterations < 0 or destroy_size < 1 or max_neighbour_assignments < 1 or time_limit_seconds <= 0 or local_iterations < 0:
        raise ValueError("invalid LNS control parameters")
    started = time.perf_counter()
    current = find_feasible_start(problem, risk, initial_placement or problem.current_placement)
    # Tighten with the simpler local search before large moves.
    current, local_meta = robust_local_search(problem, risk, current, max_iterations=local_iterations)
    current_eval = evaluate_placement(problem, current, risk)
    best = dict(current)
    best_eval = current_eval
    rng = random.Random(seed)
    weights = _incident_weights(problem)
    replica_ids = [replica.replica_id for replica in problem.replicas]
    log: list[dict] = []
    evaluated = 0

    for iteration in range(iterations):
        if time.perf_counter() - started >= time_limit_seconds:
            break
        ranked = sorted(replica_ids, key=lambda rid: (-weights[rid], rid))
        elite_count = max(destroy_size, len(ranked) // 2)
        # Alternate impact-biased and global diversification neighbourhoods.
        # The latter is essential when escaping a local optimum requires
        # simultaneously restoring some replicas and moving others.
        pool = ranked[:elite_count] if iteration % 2 == 0 else list(replica_ids)
        selected = set(rng.sample(pool, min(destroy_size, len(pool))))
        while len(selected) < min(destroy_size, len(replica_ids)):
            selected.add(rng.choice(replica_ids))
        selected_order = sorted(selected)
        domains = [problem.allowed_nodes_for(replica_id) for replica_id in selected_order]
        combinations = 1
        for domain in domains:
            combinations *= len(domain)
        if combinations > max_neighbour_assignments:
            # Deterministically reduce the subset until the repair is bounded.
            while len(selected_order) > 1 and combinations > max_neighbour_assignments:
                selected_order.pop()
                domains = [problem.allowed_nodes_for(replica_id) for replica_id in selected_order]
                combinations = 1
                for domain in domains:
                    combinations *= len(domain)

        iteration_best = None
        iteration_eval = best_eval
        candidate_count = 0
        for assignment in itertools.product(*domains):
            if time.perf_counter() - started >= time_limit_seconds:
                break
            candidate_count += 1
            if candidate_count > max_neighbour_assignments:
                break
            candidate = dict(best)
            for replica_id, node_id in zip(selected_order, assignment):
                candidate[replica_id] = node_id
            evaluation = evaluate_placement(problem, candidate, risk)
            evaluated += 1
            if evaluation.feasible and evaluation.total_objective < iteration_eval.total_objective - 1e-9:
                iteration_best = candidate
                iteration_eval = evaluation
        accepted = iteration_best is not None
        if accepted:
            best = iteration_best
            best_eval = iteration_eval
        log.append(
            {
                "iteration": iteration,
                "destroyed_replicas": selected_order,
                "candidate_count": candidate_count,
                "accepted": accepted,
                "objective": best_eval.total_objective,
            }
        )

    runtime = time.perf_counter() - started
    return best, {
        "method": "bounded-large-neighbourhood-search",
        "evaluation": asdict(best_eval),
        "runtime_seconds": runtime,
        "evaluated_candidates": evaluated,
        "iterations_completed": len(log),
        "seed": seed,
        "destroy_size": destroy_size,
        "local_initialization": local_meta["evaluation"],
        "iteration_log": log,
    }
