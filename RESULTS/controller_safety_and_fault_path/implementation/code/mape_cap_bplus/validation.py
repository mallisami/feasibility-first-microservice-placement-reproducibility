"""Semantic validation beyond JSON-schema shape checks."""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from .models import ProblemInstance
from .objective import link_for


def _finite_nonnegative(value: float, label: str, reasons: list[str], *, strictly_positive: bool = False) -> None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        reasons.append(f"{label} must be numeric")
        return
    if not math.isfinite(numeric):
        reasons.append(f"{label} must be finite")
    elif strictly_positive and numeric <= 0:
        reasons.append(f"{label} must be positive")
    elif not strictly_positive and numeric < 0:
        reasons.append(f"{label} must be non-negative")


def validate_problem(problem: ProblemInstance) -> tuple[bool, tuple[str, ...]]:
    reasons: list[str] = []
    _finite_nonnegative(problem.decision_window_seconds, "decision_window_seconds", reasons, strictly_positive=True)

    node_ids = [n.node_id for n in problem.nodes]
    replica_ids = [p.replica_id for p in problem.replicas]
    flow_ids = [f.flow_id for f in problem.flows]
    scenario_ids = [s.scenario_id for s in problem.scenarios]
    for label, values in (("node", node_ids), ("replica", replica_ids), ("flow", flow_ids), ("scenario", scenario_ids)):
        if any(not isinstance(value, str) or not value.strip() for value in values):
            reasons.append(f"{label} IDs must be non-empty strings")
    if len(node_ids) != len(set(node_ids)):
        reasons.append("node IDs must be unique")
    if len(replica_ids) != len(set(replica_ids)):
        reasons.append("replica IDs must be unique")
    if len(flow_ids) != len(set(flow_ids)):
        reasons.append("flow IDs must be unique")
    if len(scenario_ids) != len(set(scenario_ids)):
        reasons.append("scenario IDs must be unique")
    if not problem.nodes or not problem.replicas or not problem.scenarios:
        reasons.append("nodes, replicas, and scenarios must be non-empty")

    nodes = problem.node_by_id
    replicas = problem.replica_by_id
    for node in problem.nodes:
        _finite_nonnegative(node.cpu_capacity, f"node {node.node_id} CPU capacity", reasons, strictly_positive=True)
        _finite_nonnegative(node.memory_capacity_mb, f"node {node.node_id} memory capacity", reasons, strictly_positive=True)
    for replica in problem.replicas:
        _finite_nonnegative(replica.cpu_request, f"replica {replica.replica_id} CPU request", reasons, strictly_positive=True)
        _finite_nonnegative(replica.memory_request_mb, f"replica {replica.replica_id} memory request", reasons, strictly_positive=True)
        unknown_allowed = sorted(set(replica.allowed_nodes) - set(nodes))
        if unknown_allowed:
            reasons.append(f"replica {replica.replica_id} has unknown allowed nodes {unknown_allowed}")
    for flow in problem.flows:
        if flow.source_replica not in replicas or flow.destination_replica not in replicas:
            reasons.append(f"flow {flow.flow_id} references an unknown replica")
        _finite_nonnegative(flow.requests_per_window, f"flow {flow.flow_id} requests_per_window", reasons)
        _finite_nonnegative(flow.bits_per_window, f"flow {flow.flow_id} bits_per_window", reasons)
        _finite_nonnegative(flow.criticality, f"flow {flow.flow_id} criticality", reasons)
        if flow.max_expected_latency_ms is not None:
            _finite_nonnegative(flow.max_expected_latency_ms, f"flow {flow.flow_id} max_expected_latency_ms", reasons)

    if set(problem.current_placement) != set(replicas):
        reasons.append("current_placement must assign every replica exactly once")
    for replica_id, node_id in problem.current_placement.items():
        if node_id not in nodes:
            reasons.append(f"current placement for {replica_id} uses unknown node {node_id}")
        elif replica_id in replicas and node_id not in problem.allowed_nodes_for(replica_id):
            reasons.append(f"current placement for {replica_id} violates allowed_nodes")

    if set(problem.relocation_costs) != set(replicas):
        reasons.append("relocation_costs must define every replica")
    for replica_id, cost in problem.relocation_costs.items():
        if cost.replica_id != replica_id:
            reasons.append(f"relocation cost key {replica_id} does not match record replica_id {cost.replica_id}")
        _finite_nonnegative(cost.cost_units, f"relocation cost for {replica_id}", reasons)
        _finite_nonnegative(cost.expected_seconds, f"relocation duration for {replica_id}", reasons)
        _finite_nonnegative(cost.uncertainty_units, f"relocation uncertainty for {replica_id}", reasons)
    if problem.max_relocations is not None:
        if isinstance(problem.max_relocations, bool) or not isinstance(problem.max_relocations, int):
            reasons.append("max_relocations must be an integer or null")
        elif problem.max_relocations < 0:
            reasons.append("max_relocations must be non-negative")

    rack_ids = problem.rack_ids
    known_racks = set(rack_ids)
    for scenario in problem.scenarios:
        _finite_nonnegative(scenario.weight, f"scenario {scenario.scenario_id} weight", reasons)
        _finite_nonnegative(
            scenario.regime_duration_seconds,
            f"scenario {scenario.scenario_id} regime duration",
            reasons,
            strictly_positive=True,
        )
        _finite_nonnegative(scenario.intra_rack_latency_ms, f"scenario {scenario.scenario_id} intra-rack latency", reasons)
        _finite_nonnegative(
            scenario.intra_rack_goodput_bps,
            f"scenario {scenario.scenario_id} intra-rack goodput",
            reasons,
            strictly_positive=True,
        )
        for group, budget in scenario.conflict_budgets_seconds.items():
            _finite_nonnegative(budget, f"scenario {scenario.scenario_id} budget {group}", reasons)
            try:
                numeric_budget = float(budget)
            except (TypeError, ValueError):
                numeric_budget = float("nan")
            if math.isfinite(numeric_budget) and numeric_budget > problem.decision_window_seconds + 1e-9:
                reasons.append(
                    f"scenario {scenario.scenario_id} budget {group} exceeds decision window"
                )
        for key, declared_link in scenario.links.items():
            if key != (declared_link.source_rack, declared_link.destination_rack):
                reasons.append(
                    f"scenario {scenario.scenario_id} link key {key} does not match declared endpoints "
                    f"{declared_link.source_rack}->{declared_link.destination_rack}"
                )
            if declared_link.source_rack not in known_racks or declared_link.destination_rack not in known_racks:
                reasons.append(
                    f"scenario {scenario.scenario_id} contains link with unknown rack "
                    f"{declared_link.source_rack}->{declared_link.destination_rack}"
                )
        for src in rack_ids:
            for dst in rack_ids:
                try:
                    link = link_for(scenario, src, dst)
                except KeyError as exc:
                    reasons.append(str(exc))
                    continue
                _finite_nonnegative(link.latency_ms, f"scenario {scenario.scenario_id} latency {src}->{dst}", reasons)
                _finite_nonnegative(link.goodput_bps, f"scenario {scenario.scenario_id} goodput {src}->{dst}", reasons)
                if link.available and link.goodput_bps <= 0:
                    reasons.append(
                        f"scenario {scenario.scenario_id} available link {src}->{dst} must have positive goodput"
                    )
                if link.conflict_group and link.conflict_group not in scenario.conflict_budgets_seconds:
                    reasons.append(
                        f"scenario {scenario.scenario_id} link {src}->{dst} references undefined "
                        f"conflict group {link.conflict_group}"
                    )
    try:
        total_weight = sum(float(s.weight) for s in problem.scenarios)
    except (TypeError, ValueError):
        total_weight = float("nan")
    if not math.isfinite(total_weight) or total_weight <= 0:
        reasons.append("scenario weights must sum to a positive finite number")

    # Validate the current placement's static compute and anti-affinity semantics.
    cpu_used = {node_id: 0.0 for node_id in nodes}
    memory_used = {node_id: 0.0 for node_id in nodes}
    affinity_seen: dict[str, set[str]] = {node_id: set() for node_id in nodes}
    for replica_id, node_id in problem.current_placement.items():
        if replica_id not in replicas or node_id not in nodes:
            continue
        replica = replicas[replica_id]
        cpu_used[node_id] += replica.cpu_request
        memory_used[node_id] += replica.memory_request_mb
        if replica.anti_affinity_group:
            if replica.anti_affinity_group in affinity_seen[node_id]:
                reasons.append(
                    f"current placement repeats anti-affinity group {replica.anti_affinity_group} on {node_id}"
                )
            affinity_seen[node_id].add(replica.anti_affinity_group)
    for node_id, node in nodes.items():
        if cpu_used[node_id] > node.cpu_capacity + 1e-9:
            reasons.append(f"current placement exceeds CPU capacity on {node_id}")
        if memory_used[node_id] > node.memory_capacity_mb + 1e-9:
            reasons.append(f"current placement exceeds memory capacity on {node_id}")

    return not reasons, tuple(sorted(set(reasons)))


def validate_relocation_document(document: dict[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Validate timestamp ordering not expressible in the JSON schema."""
    reasons: list[str] = []
    event_ids: set[str] = set()
    for record in document.get("records", []):
        event_id = record.get("event_id", "<missing>")
        if event_id in event_ids:
            reasons.append(f"duplicate relocation event_id {event_id}")
        event_ids.add(event_id)
        try:
            started = datetime.fromisoformat(record["started_at"].replace("Z", "+00:00"))
            ready = datetime.fromisoformat(record["ready_at"].replace("Z", "+00:00"))
            removed = datetime.fromisoformat(record["old_removed_at"].replace("Z", "+00:00"))
        except (KeyError, ValueError) as exc:
            reasons.append(f"relocation event {event_id} has invalid timestamps: {exc}")
            continue
        if ready < started:
            reasons.append(f"relocation event {event_id} ready_at precedes started_at")
        if record.get("method") == "create-ready-remove" and removed < ready:
            reasons.append(f"relocation event {event_id} old_removed_at precedes ready_at")
        if record.get("method") == "stop-recreate" and removed < started:
            reasons.append(f"relocation event {event_id} old_removed_at precedes started_at")
    return not reasons, tuple(sorted(set(reasons)))


def validate_link_trace_document(document: dict[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Validate link-trace semantics that JSON Schema cannot express.

    This validator intentionally does not require a cluster document. Full
    rack-pair completeness is checked later by ``validate_problem`` after a
    trace is combined with a concrete cluster.
    """
    reasons: list[str] = []
    try:
        window = float(document.get("decision_window_seconds"))
    except (TypeError, ValueError):
        window = float("nan")
    if not math.isfinite(window) or window <= 0:
        reasons.append("decision_window_seconds must be positive and finite")

    scenario_ids: set[str] = set()
    total_weight = 0.0
    for scenario in document.get("scenarios", []):
        scenario_id = scenario.get("scenario_id", "<missing>")
        if scenario_id in scenario_ids:
            reasons.append(f"duplicate scenario_id {scenario_id}")
        scenario_ids.add(scenario_id)
        try:
            weight = float(scenario.get("weight"))
        except (TypeError, ValueError):
            weight = float("nan")
        if not math.isfinite(weight) or weight < 0:
            reasons.append(f"scenario {scenario_id} weight must be finite and non-negative")
        else:
            total_weight += weight

        budgets = scenario.get("conflict_budgets_seconds", {})
        for group, raw_budget in budgets.items():
            try:
                budget = float(raw_budget)
            except (TypeError, ValueError):
                budget = float("nan")
            if not math.isfinite(budget) or budget < 0:
                reasons.append(f"scenario {scenario_id} budget {group} must be finite and non-negative")
            elif math.isfinite(window) and budget > window + 1e-9:
                reasons.append(f"scenario {scenario_id} budget {group} exceeds decision window")

        seen_links: set[tuple[str, str]] = set()
        for link in scenario.get("links", []):
            source = link.get("source_rack", "")
            destination = link.get("destination_rack", "")
            pair = (source, destination)
            if pair in seen_links:
                reasons.append(f"scenario {scenario_id} contains duplicate directed link {source}->{destination}")
            seen_links.add(pair)
            if source == destination:
                reasons.append(
                    f"scenario {scenario_id} explicitly declares intra-rack link {source}->{destination}; "
                    "use the scenario intra-rack fields instead"
                )
            for field_name in ("latency_ms", "goodput_bps"):
                try:
                    value = float(link.get(field_name))
                except (TypeError, ValueError):
                    value = float("nan")
                if not math.isfinite(value) or value < 0:
                    reasons.append(
                        f"scenario {scenario_id} link {source}->{destination} {field_name} "
                        "must be finite and non-negative"
                    )
            if link.get("available"):
                try:
                    goodput = float(link.get("goodput_bps"))
                except (TypeError, ValueError):
                    goodput = float("nan")
                if not math.isfinite(goodput) or goodput <= 0:
                    reasons.append(
                        f"scenario {scenario_id} available link {source}->{destination} must have positive goodput"
                    )
            group = link.get("conflict_group")
            if group and group not in budgets:
                reasons.append(
                    f"scenario {scenario_id} link {source}->{destination} references undefined conflict group {group}"
                )

    if not scenario_ids:
        reasons.append("link trace must contain at least one scenario")
    if not math.isfinite(total_weight) or total_weight <= 0:
        reasons.append("scenario weights must sum to a positive finite number")
    return not reasons, tuple(sorted(set(reasons)))
