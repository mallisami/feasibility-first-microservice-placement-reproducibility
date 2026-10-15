"""Deterministic exact byte-affinity baseline for the live confirmatory experiment.

The comparator deliberately has no wireless-state, goodput, conflict-group, airtime,
or CVaR information.  It minimizes cross-rack bytes subject to the same node-resource,
allowed-node, anti-affinity, and maximum-relocation constraints as B+.
"""
from __future__ import annotations

import itertools
from typing import Mapping

from mape_cap_bplus.models import ProblemInstance


def move_count(problem: ProblemInstance, placement: Mapping[str, str]) -> int:
    return sum(int(problem.current_placement[r] != n) for r, n in placement.items())


def cluster_feasible(problem: ProblemInstance, placement: Mapping[str, str]) -> bool:
    nodes = problem.node_by_id
    replicas = problem.replica_by_id
    if set(placement) != set(replicas):
        return False
    cpu = {n: 0.0 for n in nodes}
    mem = {n: 0.0 for n in nodes}
    groups = {n: set() for n in nodes}
    for rid, nid in placement.items():
        if nid not in nodes or nid not in problem.allowed_nodes_for(rid):
            return False
        rep = replicas[rid]
        cpu[nid] += rep.cpu_request
        mem[nid] += rep.memory_request_mb
        if rep.anti_affinity_group:
            if rep.anti_affinity_group in groups[nid]:
                return False
            groups[nid].add(rep.anti_affinity_group)
    if problem.max_relocations is not None and move_count(problem, placement) > problem.max_relocations:
        return False
    return all(
        cpu[n] <= nodes[n].cpu_capacity + 1e-12
        and mem[n] <= nodes[n].memory_capacity_mb + 1e-12
        for n in nodes
    )


def cross_rack_bits(problem: ProblemInstance, placement: Mapping[str, str]) -> float:
    nodes = problem.node_by_id
    total = 0.0
    for flow in problem.flows:
        src_rack = nodes[placement[flow.source_replica]].rack_id
        dst_rack = nodes[placement[flow.destination_replica]].rack_id
        if src_rack != dst_rack:
            total += float(flow.bits_per_window)
    return total


def enumerate_cluster_feasible(problem: ProblemInstance):
    replicas = tuple(r.replica_id for r in problem.replicas)
    allowed = tuple(problem.allowed_nodes_for(r) for r in replicas)
    for assignment in itertools.product(*allowed):
        placement = dict(zip(replicas, assignment))
        if cluster_feasible(problem, placement):
            yield placement


def solve_affinity_bytes(problem: ProblemInstance) -> tuple[dict[str, str], dict]:
    """Return the exact byte-affinity optimum with deterministic tie breaking."""
    node_rank = {n.node_id: i for i, n in enumerate(sorted(problem.nodes, key=lambda x: x.node_id))}
    replica_order = tuple(sorted(r.replica_id for r in problem.replicas))
    best = None
    count = 0
    for placement in enumerate_cluster_feasible(problem):
        count += 1
        key = (
            cross_rack_bits(problem, placement),
            move_count(problem, placement),
            tuple(node_rank[placement[r]] for r in replica_order),
        )
        if best is None or key < best[0]:
            best = (key, dict(placement))
    if best is None:
        raise RuntimeError("Affinity-Bytes found no cluster-feasible placement")
    key, placement = best
    return placement, {
        "solver": "deterministic-enumeration",
        "cluster_feasible_placements_enumerated": count,
        "cross_rack_bits": float(key[0]),
        "moves": int(key[1]),
        "wireless_information_visible": False,
    }
