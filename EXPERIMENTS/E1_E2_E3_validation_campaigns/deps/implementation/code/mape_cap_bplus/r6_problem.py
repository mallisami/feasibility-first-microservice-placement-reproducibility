"""Problem construction shared by the v0.3 R6 out-of-sample experiment."""
from __future__ import annotations

from .models import FlowSpec, NodeSpec, ProblemInstance, RelocationCost, ReplicaSpec, Scenario


def build_instance(scenarios: list[Scenario] | tuple[Scenario, ...]) -> ProblemInstance:
    racks = ["rack-a", "rack-b", "rack-c"]
    nodes = tuple(NodeSpec(f"worker-{r}", r, 8.0, 16384.0) for r in racks)
    replicas = (
        ReplicaSpec("frontend-0", "frontend", 0.025, 16.0, anti_affinity_group="frontend"),
        ReplicaSpec("frontend-1", "frontend", 0.025, 16.0, anti_affinity_group="frontend"),
        ReplicaSpec("api-0", "api", 0.025, 16.0, anti_affinity_group="api"),
        ReplicaSpec("api-1", "api", 0.025, 16.0, anti_affinity_group="api"),
        ReplicaSpec("database-0", "database", 0.025, 16.0),
        ReplicaSpec("cache-0", "cache", 0.025, 16.0),
    )
    current = {replica.replica_id: nodes[i % len(nodes)].node_id for i, replica in enumerate(replicas)}
    base_rps = 120.0
    base_bytes = 15000.0
    flows = (
        FlowSpec("f-fe0-api0", "frontend-0", "api-0", base_rps, base_rps * base_bytes * 8, 1.5, 30.0),
        FlowSpec("f-fe0-api1", "frontend-0", "api-1", base_rps * 0.5, base_rps * 0.5 * base_bytes * 8, 1.0),
        FlowSpec("f-fe1-api0", "frontend-1", "api-0", base_rps * 0.5, base_rps * 0.5 * base_bytes * 8, 1.0),
        FlowSpec("f-fe1-api1", "frontend-1", "api-1", base_rps, base_rps * base_bytes * 8, 1.5, 30.0),
        FlowSpec("f-api0-db0", "api-0", "database-0", base_rps * 0.8, base_rps * 0.8 * base_bytes * 8, 1.2),
        FlowSpec("f-api1-db0", "api-1", "database-0", base_rps * 0.8, base_rps * 0.8 * base_bytes * 8, 1.2),
        FlowSpec("f-api0-ch0", "api-0", "cache-0", base_rps * 0.4, base_rps * 0.4 * base_bytes * 8, 1.0),
        FlowSpec("f-api1-ch0", "api-1", "cache-0", base_rps * 0.4, base_rps * 0.4 * base_bytes * 8, 1.0),
    )
    relocation_costs = {
        replica.replica_id: RelocationCost(replica.replica_id, 1000.0, 4.0)
        for replica in replicas
    }
    return ProblemInstance(
        instance_id="r6-cvar-comparison",
        decision_window_seconds=300.0,
        nodes=nodes,
        replicas=replicas,
        flows=flows,
        scenarios=tuple(scenarios),
        current_placement=current,
        relocation_costs=relocation_costs,
    )
