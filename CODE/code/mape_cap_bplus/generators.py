"""Deterministic synthetic problem generators and controlled ablations."""
from __future__ import annotations

from dataclasses import replace
import random
from typing import Iterable

from .models import FlowSpec, LinkState, NodeSpec, ProblemInstance, RelocationCost, ReplicaSpec, Scenario


def _rack_pairs(racks: list[str]):
    for source in racks:
        for destination in racks:
            if source != destination:
                yield source, destination


def generate_problem(
    *,
    replica_count: int,
    rack_count: int = 3,
    nodes_per_rack: int = 1,
    scenario_count: int = 3,
    seed: int = 1,
    decision_window_seconds: float = 60.0,
) -> ProblemInstance:
    """Create a reproducible feasible rack-level placement instance.

    The generator is designed for algorithmic/scalability evidence, not as a
    physical wireless trace model. Generated records are labelled accordingly.
    """
    if replica_count < 4:
        raise ValueError("replica_count must be at least 4")
    if rack_count < 2 or nodes_per_rack < 1 or scenario_count < 1:
        raise ValueError("invalid topology or scenario count")
    rng = random.Random(seed)
    racks = [f"rack-{index}" for index in range(rack_count)]
    nodes: list[NodeSpec] = []
    for rack in racks:
        for node_index in range(nodes_per_rack):
            nodes.append(NodeSpec(f"node-{rack.split('-')[-1]}-{node_index}", rack, 8.0, 16384.0))

    replicas: list[ReplicaSpec] = []
    for index in range(replica_count):
        cpu = rng.choice([0.5, 1.0, 1.5])
        memory = rng.choice([256.0, 512.0, 1024.0])
        replicas.append(ReplicaSpec(f"replica-{index}", f"service-{index}", cpu, memory))

    # Feasible balanced current placement.
    current = {replica.replica_id: nodes[index % len(nodes)].node_id for index, replica in enumerate(replicas)}

    flows: list[FlowSpec] = []
    edges: set[tuple[int, int]] = set()
    # Directed ring guarantees connectivity.
    for index in range(replica_count):
        edges.add((index, (index + 1) % replica_count))
    extra_edges = max(replica_count, int(replica_count * 1.5))
    while len(edges) < replica_count + extra_edges:
        source = rng.randrange(replica_count)
        destination = rng.randrange(replica_count)
        if source != destination:
            edges.add((source, destination))
    for flow_index, (source, destination) in enumerate(sorted(edges)):
        requests = float(rng.randint(20, 180))
        bytes_per_request = float(rng.randint(2_000, 80_000))
        flows.append(
            FlowSpec(
                f"flow-{flow_index}",
                replicas[source].replica_id,
                replicas[destination].replica_id,
                requests,
                requests * bytes_per_request * 8.0,
                criticality=rng.choice([0.75, 1.0, 1.25, 1.5]),
                max_expected_latency_ms=rng.choice([None, 20.0, 30.0, 40.0]),
            )
        )

    scenarios: list[Scenario] = []
    for scenario_index in range(scenario_count):
        links: dict[tuple[str, str], LinkState] = {}
        budgets: dict[str, float] = {}
        for source, destination in _rack_pairs(racks):
            group = f"source-{source}"
            budgets[group] = decision_window_seconds * 0.75
            base = 3.0 + 3.0 * abs(int(source.split('-')[-1]) - int(destination.split('-')[-1]))
            jitter = rng.uniform(-1.0, 5.0)
            degraded = 12.0 if scenario_index == scenario_count - 1 and rng.random() < 0.25 else 0.0
            goodput = rng.choice([500_000_000.0, 1_000_000_000.0, 2_000_000_000.0])
            links[(source, destination)] = LinkState(
                source,
                destination,
                max(0.5, base + jitter + degraded),
                goodput,
                True,
                "synthetic-effective-wireless",
                group,
                "deterministic-synthetic-generator",
            )
        scenarios.append(
            Scenario(
                f"scenario-{scenario_index}",
                1.0 / scenario_count,
                links,
                budgets,
                regime_duration_seconds=300.0,
                metadata={"evidence_type": "controlled-synthetic", "seed": seed},
            )
        )

    relocation_costs = {
        replica.replica_id: RelocationCost(
            replica.replica_id,
            cost_units=float(rng.randint(10, 50)),
            expected_seconds=float(rng.randint(8, 30)),
            uncertainty_units=float(rng.randint(1, 10)),
            provenance="synthetic-placeholder-not-measured",
        )
        for replica in replicas
    }
    return ProblemInstance(
        instance_id=f"generated-r{replica_count}-k{rack_count}-s{seed}",
        decision_window_seconds=decision_window_seconds,
        nodes=tuple(nodes),
        replicas=tuple(replicas),
        flows=tuple(flows),
        scenarios=tuple(scenarios),
        current_placement=current,
        relocation_costs=relocation_costs,
        max_relocations=max(2, replica_count // 3),
        metadata={"evidence_type": "controlled-synthetic", "seed": seed, "generator": "v0.2"},
    )


def homogenize_network(problem: ProblemInstance, latency_ms: float = 10.0, goodput_bps: float = 1_000_000_000.0) -> ProblemInstance:
    scenarios: list[Scenario] = []
    for scenario in problem.scenarios:
        links = {
            pair: replace(
                link,
                latency_ms=latency_ms,
                goodput_bps=goodput_bps,
                available=True,
                path_id="homogeneous-traffic-only",
                conflict_group=None,
                provenance="ablation-transform",
            )
            for pair, link in scenario.links.items()
        }
        scenarios.append(replace(scenario, links=links, conflict_budgets_seconds={}))
    return replace(problem, scenarios=tuple(scenarios), metadata={**problem.metadata, "ablation": "traffic-only"})


def without_conflicts(problem: ProblemInstance) -> ProblemInstance:
    scenarios = []
    for scenario in problem.scenarios:
        links = {pair: replace(link, conflict_group=None) for pair, link in scenario.links.items()}
        scenarios.append(replace(scenario, links=links, conflict_budgets_seconds={}))
    return replace(problem, scenarios=tuple(scenarios), metadata={**problem.metadata, "ablation": "no-conflict"})


def single_scenario(problem: ProblemInstance, scenario_index: int = 0) -> ProblemInstance:
    scenario = problem.scenarios[scenario_index]
    return replace(problem, scenarios=(replace(scenario, weight=1.0),), metadata={**problem.metadata, "ablation": "deterministic"})


def scale_conflict_budgets(problem: ProblemInstance, factor: float) -> ProblemInstance:
    if factor <= 0:
        raise ValueError("budget factor must be positive")
    scenarios = tuple(
        replace(s, conflict_budgets_seconds={key: value * factor for key, value in s.conflict_budgets_seconds.items()})
        for s in problem.scenarios
    )
    return replace(problem, scenarios=scenarios, metadata={**problem.metadata, "budget_factor": factor})


def replace_scenarios(problem: ProblemInstance, scenarios: Iterable[Scenario]) -> ProblemInstance:
    return replace(problem, scenarios=tuple(scenarios))
