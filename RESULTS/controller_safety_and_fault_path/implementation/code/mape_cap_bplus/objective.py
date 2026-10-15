"""Placement validation and risk-adjusted objective evaluation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .models import FlowSpec, LinkState, ProblemInstance, RiskConfig, Scenario, normalize_scenario_weights

Placement = Mapping[str, str]


@dataclass(frozen=True)
class PlacementEvaluation:
    feasible: bool
    reasons: tuple[str, ...]
    total_objective: float
    expected_delay_cost: float
    cvar_delay_cost: float
    relocation_cost: float
    slo_slack: float
    scenario_delay_costs: Mapping[str, float]
    scenario_airtime_by_group: Mapping[str, Mapping[str, float]]


def _weighted_cvar(values: Mapping[str, float], weights: Mapping[str, float], quantile: float) -> float:
    ordered = sorted(((float(values[k]), float(weights[k])) for k in values), key=lambda x: x[0])
    tail_mass = 1.0 - quantile
    remaining = tail_mass
    total = 0.0
    for value, weight in reversed(ordered):
        take = min(weight, remaining)
        total += value * take
        remaining -= take
        if remaining <= 1e-15:
            break
    if remaining > 1e-12:
        total += ordered[-1][0] * remaining
    return total / tail_mass


def link_for(scenario: Scenario, source_rack: str, destination_rack: str) -> LinkState:
    if source_rack == destination_rack:
        return LinkState(
            source_rack=source_rack,
            destination_rack=destination_rack,
            latency_ms=scenario.intra_rack_latency_ms,
            goodput_bps=scenario.intra_rack_goodput_bps,
            available=True,
            path_id="intra-rack-wired",
            conflict_group=None,
            provenance="declared-intra-rack",
        )
    try:
        return scenario.links[(source_rack, destination_rack)]
    except KeyError as exc:
        raise KeyError(
            f"scenario {scenario.scenario_id!r} is missing directed link "
            f"{source_rack!r}->{destination_rack!r}"
        ) from exc


def flow_delay_cost(flow: FlowSpec, link: LinkState) -> float:
    """Request-weighted latency exposure in request-ms-equivalent units."""
    return flow.requests_per_window * flow.criticality * link.latency_ms


def flow_airtime_seconds(flow: FlowSpec, link: LinkState) -> float:
    if link.goodput_bps <= 0:
        return float("inf")
    return flow.bits_per_window / link.goodput_bps


def evaluate_placement(problem: ProblemInstance, placement: Placement, risk: RiskConfig) -> PlacementEvaluation:
    risk.validate()
    reasons: list[str] = []
    nodes = problem.node_by_id
    replicas = problem.replica_by_id

    missing = sorted(set(replicas) - set(placement))
    extra = sorted(set(placement) - set(replicas))
    if missing:
        reasons.append(f"missing replica assignments: {missing}")
    if extra:
        reasons.append(f"unknown replica assignments: {extra}")
    if reasons:
        return PlacementEvaluation(False, tuple(reasons), float("inf"), float("inf"), float("inf"), float("inf"), float("inf"), {}, {})

    cpu_used = {n: 0.0 for n in nodes}
    mem_used = {n: 0.0 for n in nodes}
    groups_by_node: dict[str, set[str]] = {n: set() for n in nodes}
    for replica_id, node_id in placement.items():
        replica = replicas[replica_id]
        if node_id not in nodes:
            reasons.append(f"replica {replica_id} assigned to unknown node {node_id}")
            continue
        if node_id not in problem.allowed_nodes_for(replica_id):
            reasons.append(f"replica {replica_id} is not allowed on node {node_id}")
        cpu_used[node_id] += replica.cpu_request
        mem_used[node_id] += replica.memory_request_mb
        if replica.anti_affinity_group:
            if replica.anti_affinity_group in groups_by_node[node_id]:
                reasons.append(
                    f"anti-affinity group {replica.anti_affinity_group} repeated on node {node_id}"
                )
            groups_by_node[node_id].add(replica.anti_affinity_group)

    for node_id, node in nodes.items():
        if cpu_used[node_id] > node.cpu_capacity + 1e-9:
            reasons.append(f"CPU capacity exceeded on {node_id}")
        if mem_used[node_id] > node.memory_capacity_mb + 1e-9:
            reasons.append(f"memory capacity exceeded on {node_id}")

    # Never dereference invalid node assignments in the flow loop below.
    # Invalid candidate placements must be reported as infeasible, not crash
    # the evaluator with a KeyError.
    if reasons:
        return PlacementEvaluation(
            False,
            tuple(sorted(set(reasons))),
            float("inf"),
            float("inf"),
            float("inf"),
            0.0,
            0.0,
            {},
            {},
        )

    scenario_costs: dict[str, float] = {}
    scenario_airtime: dict[str, dict[str, float]] = {}
    expected_flow_latency: dict[str, float] = {f.flow_id: 0.0 for f in problem.flows}
    weights = normalize_scenario_weights(problem.scenarios)

    for scenario in problem.scenarios:
        total_delay = 0.0
        airtime_by_group: dict[str, float] = {}
        for flow in problem.flows:
            src_node = nodes[placement[flow.source_replica]]
            dst_node = nodes[placement[flow.destination_replica]]
            link = link_for(scenario, src_node.rack_id, dst_node.rack_id)
            if not link.available:
                reasons.append(
                    f"flow {flow.flow_id} uses unavailable path {src_node.rack_id}->{dst_node.rack_id} "
                    f"in scenario {scenario.scenario_id}"
                )
                continue
            total_delay += flow_delay_cost(flow, link)
            expected_flow_latency[flow.flow_id] += weights[scenario.scenario_id] * link.latency_ms
            if link.conflict_group:
                airtime_by_group[link.conflict_group] = (
                    airtime_by_group.get(link.conflict_group, 0.0) + flow_airtime_seconds(flow, link)
                )
        for group, used in airtime_by_group.items():
            budget = scenario.conflict_budgets_seconds.get(group)
            if budget is None:
                reasons.append(f"missing airtime budget for conflict group {group} in {scenario.scenario_id}")
            elif used > budget + 1e-12:
                reasons.append(
                    f"airtime budget {group} exceeded in {scenario.scenario_id}: {used:.6f}s > {budget:.6f}s"
                )
        scenario_costs[scenario.scenario_id] = total_delay
        scenario_airtime[scenario.scenario_id] = airtime_by_group

    slo_slack = 0.0
    for flow in problem.flows:
        if flow.max_expected_latency_ms is not None:
            slo_slack += max(0.0, expected_flow_latency[flow.flow_id] - flow.max_expected_latency_ms)

    relocations = 0
    relocation_cost = 0.0
    for replica_id, node_id in placement.items():
        current = problem.current_placement.get(replica_id)
        if current is not None and current != node_id:
            relocations += 1
            relocation_cost += problem.relocation_costs[replica_id].cost_units
    if problem.max_relocations is not None and relocations > problem.max_relocations:
        reasons.append(f"relocation budget exceeded: {relocations} > {problem.max_relocations}")

    if reasons:
        return PlacementEvaluation(False, tuple(sorted(set(reasons))), float("inf"), float("inf"), float("inf"), relocation_cost, slo_slack, scenario_costs, scenario_airtime)

    expected = sum(weights[sid] * value for sid, value in scenario_costs.items())
    cvar = _weighted_cvar(scenario_costs, weights, risk.cvar_quantile)
    total = (
        expected
        + risk.cvar_weight * cvar
        + risk.relocation_weight * relocation_cost
        + risk.slo_slack_weight * slo_slack
    )
    return PlacementEvaluation(True, (), total, expected, cvar, relocation_cost, slo_slack, scenario_costs, scenario_airtime)
