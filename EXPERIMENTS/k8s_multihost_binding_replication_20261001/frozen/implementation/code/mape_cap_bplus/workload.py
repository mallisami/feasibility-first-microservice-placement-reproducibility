"""Service-level workload windows and deterministic replica-flow expansion."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .models import FlowSpec, ReplicaSpec


@dataclass(frozen=True)
class ServiceTraffic:
    traffic_id: str
    source_service: str
    destination_service: str
    requests_per_window: float
    bits_per_window: float
    criticality: float = 1.0
    max_expected_latency_ms: float | None = None


@dataclass(frozen=True)
class WorkloadWindow:
    window_id: str
    operation_mix: Mapping[str, float]
    traffic: tuple[ServiceTraffic, ...]
    duration_seconds: float


def expand_service_traffic(
    replicas: Sequence[ReplicaSpec],
    traffic: Sequence[ServiceTraffic],
    routing_weights: Mapping[str, Mapping[str, float]] | None = None,
) -> tuple[FlowSpec, ...]:
    """Expand service traffic into replica-to-replica flows.

    Routing weights are normalized independently for source and destination
    services. Equal splitting is used when weights are omitted. This is a
    declared static routing abstraction, not a model of kube-proxy internals.
    """
    by_service: dict[str, list[str]] = {}
    for replica in replicas:
        by_service.setdefault(replica.service_id, []).append(replica.replica_id)
    for members in by_service.values():
        members.sort()

    def distribution(service_id: str) -> dict[str, float]:
        members = by_service.get(service_id, [])
        if not members:
            raise ValueError(f"service {service_id!r} has no replicas")
        declared = dict((routing_weights or {}).get(service_id, {}))
        unknown = set(declared) - set(members)
        if unknown:
            raise ValueError(f"routing weights for {service_id} reference unknown replicas: {sorted(unknown)}")
        if declared:
            if any(value < 0 for value in declared.values()) or sum(declared.values()) <= 0:
                raise ValueError(f"routing weights for {service_id} must be non-negative and sum positive")
            total = sum(declared.get(member, 0.0) for member in members)
            return {member: declared.get(member, 0.0) / total for member in members}
        return {member: 1.0 / len(members) for member in members}

    expanded: list[FlowSpec] = []
    for item in traffic:
        source_distribution = distribution(item.source_service)
        destination_distribution = distribution(item.destination_service)
        for source_replica, source_fraction in source_distribution.items():
            for destination_replica, destination_fraction in destination_distribution.items():
                fraction = source_fraction * destination_fraction
                if fraction <= 0:
                    continue
                expanded.append(
                    FlowSpec(
                        flow_id=f"{item.traffic_id}:{source_replica}->{destination_replica}",
                        source_replica=source_replica,
                        destination_replica=destination_replica,
                        requests_per_window=item.requests_per_window * fraction,
                        bits_per_window=item.bits_per_window * fraction,
                        criticality=item.criticality,
                        max_expected_latency_ms=item.max_expected_latency_ms,
                    )
                )
    return tuple(expanded)
