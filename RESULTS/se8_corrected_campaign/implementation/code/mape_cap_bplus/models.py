"""Typed system model for the MAPE-CAP B+ foundation.

The model deliberately operates at pod-replica and rack granularity. Wireless
conditions are externally supplied effective link states; no antenna,
beamforming, or physical-layer decisions are represented here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Mapping, Optional, Sequence


@dataclass(frozen=True)
class NodeSpec:
    node_id: str
    rack_id: str
    cpu_capacity: float
    memory_capacity_mb: float


@dataclass(frozen=True)
class ReplicaSpec:
    replica_id: str
    service_id: str
    cpu_request: float
    memory_request_mb: float
    allowed_nodes: tuple[str, ...] = ()
    anti_affinity_group: Optional[str] = None


@dataclass(frozen=True)
class FlowSpec:
    flow_id: str
    source_replica: str
    destination_replica: str
    requests_per_window: float
    bits_per_window: float
    criticality: float = 1.0
    max_expected_latency_ms: Optional[float] = None


@dataclass(frozen=True)
class LinkState:
    source_rack: str
    destination_rack: str
    latency_ms: float
    goodput_bps: float
    available: bool
    path_id: str
    conflict_group: Optional[str] = None
    provenance: str = "controlled-generator"


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    weight: float
    links: Mapping[tuple[str, str], LinkState]
    conflict_budgets_seconds: Mapping[str, float] = field(default_factory=dict)
    intra_rack_latency_ms: float = 0.2
    intra_rack_goodput_bps: float = 100_000_000_000.0
    regime_duration_seconds: float = 300.0
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RelocationCost:
    replica_id: str
    cost_units: float
    expected_seconds: float
    uncertainty_units: float = 0.0
    provenance: str = "placeholder-unmeasured"


@dataclass(frozen=True)
class RiskConfig:
    cvar_quantile: float = 0.90
    cvar_weight: float = 0.0
    relocation_weight: float = 1.0
    slo_slack_weight: float = 1_000.0

    def validate(self) -> None:
        values = {
            "cvar_quantile": self.cvar_quantile,
            "cvar_weight": self.cvar_weight,
            "relocation_weight": self.relocation_weight,
            "slo_slack_weight": self.slo_slack_weight,
        }
        if any(not math.isfinite(float(value)) for value in values.values()):
            raise ValueError("risk and penalty parameters must be finite")
        if not 0.0 < self.cvar_quantile < 1.0:
            raise ValueError("cvar_quantile must be strictly between 0 and 1")
        if self.cvar_weight < 0 or self.relocation_weight < 0 or self.slo_slack_weight < 0:
            raise ValueError("risk and penalty weights must be non-negative")


@dataclass(frozen=True)
class ProblemInstance:
    instance_id: str
    decision_window_seconds: float
    nodes: tuple[NodeSpec, ...]
    replicas: tuple[ReplicaSpec, ...]
    flows: tuple[FlowSpec, ...]
    scenarios: tuple[Scenario, ...]
    current_placement: Mapping[str, str]
    relocation_costs: Mapping[str, RelocationCost]
    max_relocations: Optional[int] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def node_by_id(self) -> dict[str, NodeSpec]:
        return {n.node_id: n for n in self.nodes}

    @property
    def replica_by_id(self) -> dict[str, ReplicaSpec]:
        return {p.replica_id: p for p in self.replicas}

    @property
    def rack_ids(self) -> tuple[str, ...]:
        return tuple(sorted({n.rack_id for n in self.nodes}))

    def allowed_nodes_for(self, replica_id: str) -> tuple[str, ...]:
        replica = self.replica_by_id[replica_id]
        return replica.allowed_nodes or tuple(n.node_id for n in self.nodes)


def normalize_scenario_weights(scenarios: Sequence[Scenario]) -> dict[str, float]:
    total = sum(float(s.weight) for s in scenarios)
    if total <= 0:
        raise ValueError("scenario weights must sum to a positive value")
    return {s.scenario_id: float(s.weight) / total for s in scenarios}
