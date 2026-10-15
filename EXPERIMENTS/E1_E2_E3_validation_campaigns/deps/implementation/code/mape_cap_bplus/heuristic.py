"""Feasible robust local-search foundation for larger instances."""
from __future__ import annotations

from dataclasses import asdict
from typing import Mapping

from .models import ProblemInstance, RiskConfig
from .objective import evaluate_placement


def resource_greedy_placement(problem: ProblemInstance) -> dict[str, str]:
    """Build a deterministic resource-feasible placement.

    This is a best-remaining-capacity greedy initializer, not a network-aware
    optimizer. Network feasibility is repaired separately.
    """
    remaining_cpu = {n.node_id: n.cpu_capacity for n in problem.nodes}
    remaining_mem = {n.node_id: n.memory_capacity_mb for n in problem.nodes}
    placement: dict[str, str] = {}
    max_cpu = max(n.cpu_capacity for n in problem.nodes)
    max_mem = max(n.memory_capacity_mb for n in problem.nodes)
    ordered = sorted(
        problem.replicas,
        key=lambda p: (p.cpu_request / max_cpu + p.memory_request_mb / max_mem, p.replica_id),
        reverse=True,
    )
    for replica in ordered:
        candidates = []
        for node_id in problem.allowed_nodes_for(replica.replica_id):
            if remaining_cpu[node_id] + 1e-9 < replica.cpu_request:
                continue
            if remaining_mem[node_id] + 1e-9 < replica.memory_request_mb:
                continue
            if replica.anti_affinity_group and any(
                problem.replica_by_id[p].anti_affinity_group == replica.anti_affinity_group
                and n == node_id
                for p, n in placement.items()
            ):
                continue
            candidates.append(node_id)
        if not candidates:
            raise ValueError(f"resource initializer could not place replica {replica.replica_id}")
        chosen = max(candidates, key=lambda n: (remaining_cpu[n], remaining_mem[n], n))
        placement[replica.replica_id] = chosen
        remaining_cpu[chosen] -= replica.cpu_request
        remaining_mem[chosen] -= replica.memory_request_mb
    return placement


# Backward-compatible alias retained for the frozen baseline comparison code.
first_fit = resource_greedy_placement


def find_feasible_start(
    problem: ProblemInstance,
    risk: RiskConfig,
    preferred: Mapping[str, str] | None = None,
    max_assignments: int = 100_000,
) -> dict[str, str]:
    """Find a placement feasible for compute, affinity, paths, and airtime.

    A bounded deterministic depth-first repair is used only to establish a
    valid starting point. It is intentionally separate from the final scalable
    large-neighbourhood planner required by Gate G8.
    """
    candidates: list[dict[str, str]] = []
    if preferred is not None:
        candidates.append(dict(preferred))
    try:
        candidates.append(resource_greedy_placement(problem))
    except ValueError:
        pass
    for candidate in candidates:
        if evaluate_placement(problem, candidate, risk).feasible:
            return candidate

    nodes = problem.node_by_id
    replicas = sorted(
        problem.replicas,
        key=lambda p: (len(problem.allowed_nodes_for(p.replica_id)), -(p.cpu_request + p.memory_request_mb / 1024.0), p.replica_id),
    )
    remaining_cpu = {node_id: node.cpu_capacity for node_id, node in nodes.items()}
    remaining_mem = {node_id: node.memory_capacity_mb for node_id, node in nodes.items()}
    affinity_seen: dict[str, set[str]] = {node_id: set() for node_id in nodes}
    placement: dict[str, str] = {}
    explored = 0

    def search(position: int) -> dict[str, str] | None:
        nonlocal explored
        if explored >= max_assignments:
            return None
        explored += 1
        if position == len(replicas):
            return dict(placement) if evaluate_placement(problem, placement, risk).feasible else None

        replica = replicas[position]
        preferred_node = problem.current_placement.get(replica.replica_id)
        domain = list(problem.allowed_nodes_for(replica.replica_id))
        domain.sort(key=lambda n: (n != preferred_node, -remaining_cpu[n], -remaining_mem[n], n))
        for node_id in domain:
            if remaining_cpu[node_id] + 1e-9 < replica.cpu_request:
                continue
            if remaining_mem[node_id] + 1e-9 < replica.memory_request_mb:
                continue
            group = replica.anti_affinity_group
            if group and group in affinity_seen[node_id]:
                continue
            placement[replica.replica_id] = node_id
            remaining_cpu[node_id] -= replica.cpu_request
            remaining_mem[node_id] -= replica.memory_request_mb
            if group:
                affinity_seen[node_id].add(group)
            result = search(position + 1)
            if result is not None:
                return result
            if group:
                affinity_seen[node_id].remove(group)
            remaining_cpu[node_id] += replica.cpu_request
            remaining_mem[node_id] += replica.memory_request_mb
            del placement[replica.replica_id]
        return None

    result = search(0)
    if result is None:
        raise ValueError(
            f"no feasible starting placement found within {max_assignments} search states"
        )
    return result


def robust_local_search(
    problem: ProblemInstance,
    risk: RiskConfig,
    initial_placement: Mapping[str, str] | None = None,
    max_iterations: int = 100,
):
    if max_iterations < 0:
        raise ValueError("max_iterations must be non-negative")
    current = find_feasible_start(problem, risk, initial_placement or problem.current_placement)
    current_eval = evaluate_placement(problem, current, risk)

    log: list[dict] = []
    replicas = tuple(p.replica_id for p in problem.replicas)
    for iteration in range(max_iterations):
        best = None
        best_eval = current_eval
        best_move = None

        # One-replica relocation neighbourhood.
        for replica_id in replicas:
            for node_id in problem.allowed_nodes_for(replica_id):
                if node_id == current[replica_id]:
                    continue
                candidate = dict(current)
                candidate[replica_id] = node_id
                evaluation = evaluate_placement(problem, candidate, risk)
                move = f"move:{replica_id}->{node_id}"
                log.append({
                    "iteration": iteration,
                    "move": move,
                    "feasible": evaluation.feasible,
                    "objective": evaluation.total_objective,
                    "accepted": False,
                    "reasons": list(evaluation.reasons),
                })
                if evaluation.feasible and evaluation.total_objective < best_eval.total_objective - 1e-9:
                    best = candidate
                    best_eval = evaluation
                    best_move = move

        # Pair-swap neighbourhood.
        for i, p in enumerate(replicas):
            for q in replicas[i + 1 :]:
                if current[p] == current[q]:
                    continue
                if current[q] not in problem.allowed_nodes_for(p) or current[p] not in problem.allowed_nodes_for(q):
                    continue
                candidate = dict(current)
                candidate[p], candidate[q] = current[q], current[p]
                evaluation = evaluate_placement(problem, candidate, risk)
                move = f"swap:{p}<->{q}"
                log.append({
                    "iteration": iteration,
                    "move": move,
                    "feasible": evaluation.feasible,
                    "objective": evaluation.total_objective,
                    "accepted": False,
                    "reasons": list(evaluation.reasons),
                })
                if evaluation.feasible and evaluation.total_objective < best_eval.total_objective - 1e-9:
                    best = candidate
                    best_eval = evaluation
                    best_move = move

        if best is None:
            break
        previous_objective = current_eval.total_objective
        current = best
        current_eval = best_eval
        log.append({
            "iteration": iteration,
            "move": best_move,
            "event": "accepted-best-neighbour",
            "feasible": True,
            "objective": current_eval.total_objective,
            "accepted": True,
            "improvement": previous_objective - current_eval.total_objective,
            "reasons": [],
        })

    return current, {"evaluation": asdict(current_eval), "candidate_log": log}
