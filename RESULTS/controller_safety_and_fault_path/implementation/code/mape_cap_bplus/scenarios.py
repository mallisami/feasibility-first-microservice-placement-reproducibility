"""Controlled rack-level wireless-state scenarios and a reproducible demo instance."""
from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from .models import (
    FlowSpec,
    LinkState,
    NodeSpec,
    ProblemInstance,
    RelocationCost,
    ReplicaSpec,
    Scenario,
)


def _directed_complete_links(
    rack_delays_ms: dict[tuple[str, str], float],
    goodput_bps: float,
    conflict_group: str = "wireless-medium-1",
    path_id: str = "simulated-wireless",
    provenance: str = "controlled-generator",
) -> dict[tuple[str, str], LinkState]:
    return {
        pair: LinkState(
            source_rack=pair[0],
            destination_rack=pair[1],
            latency_ms=float(delay),
            goodput_bps=float(goodput_bps),
            available=True,
            path_id=path_id,
            conflict_group=conflict_group,
            provenance=provenance,
        )
        for pair, delay in rack_delays_ms.items()
    }


def symmetric_delays(ab: float, ac: float, bc: float) -> dict[tuple[str, str], float]:
    return {
        ("rack-a", "rack-b"): ab,
        ("rack-b", "rack-a"): ab,
        ("rack-a", "rack-c"): ac,
        ("rack-c", "rack-a"): ac,
        ("rack-b", "rack-c"): bc,
        ("rack-c", "rack-b"): bc,
    }


def controlled_scenario(
    scenario_id: str,
    ab_ms: float,
    ac_ms: float,
    bc_ms: float,
    *,
    weight: float = 1.0,
    goodput_bps: float = 1_000_000_000.0,
    budget_seconds: float = 0.20,
    regime_duration_seconds: float = 300.0,
    metadata: dict | None = None,
) -> Scenario:
    return Scenario(
        scenario_id=scenario_id,
        weight=weight,
        links=_directed_complete_links(symmetric_delays(ab_ms, ac_ms, bc_ms), goodput_bps),
        conflict_budgets_seconds={"wireless-medium-1": budget_seconds},
        regime_duration_seconds=regime_duration_seconds,
        metadata=metadata or {},
    )



def outage_scenario(
    scenario_id: str,
    *,
    failed_pairs: tuple[tuple[str, str], ...],
    fallback: bool,
    weight: float = 1.0,
    regime_duration_seconds: float = 300.0,
) -> Scenario:
    links = _directed_complete_links(symmetric_delays(8.0, 8.0, 8.0), 1_000_000_000.0)
    for pair in failed_pairs:
        if fallback:
            links[pair] = LinkState(
                source_rack=pair[0],
                destination_rack=pair[1],
                latency_ms=45.0,
                goodput_bps=100_000_000.0,
                available=True,
                path_id="wired-fallback",
                conflict_group=None,
                provenance="controlled-generator-fallback",
            )
        else:
            links[pair] = LinkState(
                source_rack=pair[0],
                destination_rack=pair[1],
                latency_ms=0.0,
                goodput_bps=0.0,
                available=False,
                path_id="unavailable",
                conflict_group=None,
                provenance="controlled-generator-outage",
            )
    return Scenario(
        scenario_id=scenario_id,
        weight=weight,
        links=links,
        conflict_budgets_seconds={"wireless-medium-1": 0.20},
        regime_duration_seconds=regime_duration_seconds,
        metadata={
            "class": "persistent-outage",
            "fallback": fallback,
            "failed_pairs": [list(pair) for pair in failed_pairs],
        },
    )

def build_demo_problem(scenarios: Iterable[Scenario] | None = None) -> ProblemInstance:
    nodes = (
        NodeSpec("node-a", "rack-a", cpu_capacity=4.0, memory_capacity_mb=4096),
        NodeSpec("node-b", "rack-b", cpu_capacity=4.0, memory_capacity_mb=4096),
        NodeSpec("node-c", "rack-c", cpu_capacity=4.0, memory_capacity_mb=4096),
    )
    replicas = (
        ReplicaSpec("ingress-0", "ingress", 2.0, 512, allowed_nodes=("node-a",)),
        ReplicaSpec("profile-0", "profile", 2.0, 512),
        ReplicaSpec("orders-0", "orders", 2.0, 512),
        ReplicaSpec("database-0", "database", 2.0, 1024, allowed_nodes=("node-c",)),
    )
    flows = (
        FlowSpec("ingress-profile", "ingress-0", "profile-0", 100, 15_000_000, 1.0, 20.0),
        FlowSpec("profile-orders", "profile-0", "orders-0", 60, 8_000_000, 1.0, 25.0),
        FlowSpec("orders-database", "orders-0", "database-0", 100, 15_000_000, 1.0, 20.0),
        FlowSpec("ingress-orders", "ingress-0", "orders-0", 20, 2_000_000, 0.8, 30.0),
    )
    if scenarios is None:
        scenarios = (
            controlled_scenario(
                "ab-preferred",
                ab_ms=2.0,
                ac_ms=30.0,
                bc_ms=15.0,
                metadata={"class": "persistent", "description": "rack A-B path is preferred"},
            ),
        )
    current = {
        "ingress-0": "node-a",
        "profile-0": "node-b",
        "orders-0": "node-b",
        "database-0": "node-c",
    }
    relocation_costs = {
        p.replica_id: RelocationCost(p.replica_id, cost_units=25.0, expected_seconds=20.0)
        for p in replicas
    }
    return ProblemInstance(
        instance_id="bplus-controlled-demo-v1",
        decision_window_seconds=60.0,
        nodes=nodes,
        replicas=replicas,
        flows=flows,
        scenarios=tuple(scenarios),
        current_placement=current,
        relocation_costs=relocation_costs,
        max_relocations=2,
        metadata={"evidence_type": "controlled-synthetic", "architecture": "hybrid-rack-level"},
    )


def scenario_family() -> tuple[Scenario, ...]:
    return (
        controlled_scenario(
            "homogeneous",
            8.0,
            8.0,
            8.0,
            metadata={"class": "sanity", "description": "all inter-rack paths identical"},
        ),
        controlled_scenario(
            "ab-preferred",
            2.0,
            30.0,
            15.0,
            metadata={"class": "persistent", "description": "rack A-B path preferred"},
        ),
        controlled_scenario(
            "ac-preferred",
            15.0,
            2.0,
            15.0,
            metadata={"class": "persistent", "description": "rack A-C path preferred"},
        ),
        controlled_scenario(
            "temporary-ab-degradation",
            25.0,
            8.0,
            8.0,
            regime_duration_seconds=10.0,
            metadata={"class": "negative-control", "description": "shorter than relocation time"},
        ),
        controlled_scenario(
            "conflict-dense",
            4.0,
            4.0,
            4.0,
            goodput_bps=200_000_000.0,
            budget_seconds=0.12,
            metadata={"class": "capacity", "description": "tight shared airtime budget"},
        ),
        outage_scenario(
            "persistent-ac-outage-no-fallback",
            failed_pairs=(("rack-a", "rack-c"), ("rack-c", "rack-a")),
            fallback=False,
        ),
        outage_scenario(
            "persistent-ac-outage-wired-fallback",
            failed_pairs=(("rack-a", "rack-c"), ("rack-c", "rack-a")),
            fallback=True,
        ),
        controlled_scenario(
            "prediction-error-pessimistic",
            12.0,
            20.0,
            12.0,
            metadata={
                "class": "prediction-error",
                "description": "predicted state is more pessimistic than the recovery state",
                "paired_actual_scenario": "recovery",
            },
        ),
        controlled_scenario(
            "recovery",
            4.0,
            4.0,
            4.0,
            metadata={"class": "recovery", "description": "post-degradation recovery"},
        ),
    )


def with_scenarios(problem: ProblemInstance, scenarios: Iterable[Scenario]) -> ProblemInstance:
    return replace(problem, scenarios=tuple(scenarios))
