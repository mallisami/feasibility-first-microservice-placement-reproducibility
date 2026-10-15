"""Exact deterministic/robust single-window MILP reference model.

This is a small-instance reference implementation. It linearizes each directed
flow's source/destination node combination and supports expected delay, CVaR,
relocation penalties, per-flow expected-latency slack, resource constraints,
anti-affinity, and externally supplied conflict-group airtime budgets.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Dict, Tuple

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix

from .models import ProblemInstance, RiskConfig, normalize_scenario_weights
from .objective import evaluate_placement, flow_airtime_seconds, flow_delay_cost, link_for
from .validation import validate_problem


class ExactSolveError(RuntimeError):
    pass


def solve_exact(
    problem: ProblemInstance,
    risk: RiskConfig,
    time_limit_seconds: float = 60.0,
    *,
    require_optimal: bool = True,
):
    risk.validate()
    if not np.isfinite(time_limit_seconds) or time_limit_seconds <= 0:
        raise ValueError("time_limit_seconds must be a positive finite value")
    valid, reasons = validate_problem(problem)
    if not valid:
        raise ValueError("invalid problem: " + "; ".join(reasons))

    nodes = tuple(n.node_id for n in problem.nodes)
    replicas = tuple(p.replica_id for p in problem.replicas)
    flows = tuple(f.flow_id for f in problem.flows)
    node_by_id = problem.node_by_id
    replica_by_id = problem.replica_by_id
    weights = normalize_scenario_weights(problem.scenarios)

    index: Dict[Tuple, int] = {}
    names: list[Tuple] = []

    def add_var(key: Tuple) -> int:
        idx = len(names)
        index[key] = idx
        names.append(key)
        return idx

    for p in replicas:
        for n in nodes:
            add_var(("x", p, n))
    for f in flows:
        for n in nodes:
            for m in nodes:
                add_var(("y", f, n, m))
    eta_idx = add_var(("eta",))
    for scenario in problem.scenarios:
        add_var(("u", scenario.scenario_id))
    for flow in problem.flows:
        if flow.max_expected_latency_ms is not None:
            add_var(("slack", flow.flow_id))

    count = len(names)
    c = np.zeros(count, dtype=float)
    integrality = np.zeros(count, dtype=int)
    lb = np.zeros(count, dtype=float)
    ub = np.full(count, np.inf, dtype=float)

    for key, idx in index.items():
        if key[0] in {"x", "y"}:
            integrality[idx] = 1
            ub[idx] = 1.0

    # Disallow replica-node assignments outside declared affinity.
    for p in replicas:
        allowed = set(problem.allowed_nodes_for(p))
        for n in nodes:
            if n not in allowed:
                ub[index[("x", p, n)]] = 0.0

    # A node pair is infeasible if any robust scenario has no effective path.
    for flow in problem.flows:
        for n in nodes:
            for m in nodes:
                src_rack = node_by_id[n].rack_id
                dst_rack = node_by_id[m].rack_id
                if any(not link_for(s, src_rack, dst_rack).available for s in problem.scenarios):
                    ub[index[("y", flow.flow_id, n, m)]] = 0.0

    # Objective coefficients for expected delay and relocation.
    for flow in problem.flows:
        for n in nodes:
            for m in nodes:
                coeff = 0.0
                for scenario in problem.scenarios:
                    link = link_for(scenario, node_by_id[n].rack_id, node_by_id[m].rack_id)
                    coeff += weights[scenario.scenario_id] * flow_delay_cost(flow, link)
                c[index[("y", flow.flow_id, n, m)]] += coeff
    for p in replicas:
        current = problem.current_placement[p]
        relocation = problem.relocation_costs[p].cost_units
        for n in nodes:
            if n != current:
                c[index[("x", p, n)]] += risk.relocation_weight * relocation

    if risk.cvar_weight > 0:
        c[eta_idx] += risk.cvar_weight
        tail_mass = 1.0 - risk.cvar_quantile
        for scenario in problem.scenarios:
            c[index[("u", scenario.scenario_id)]] += (
                risk.cvar_weight * weights[scenario.scenario_id] / tail_mass
            )
    for flow in problem.flows:
        if flow.max_expected_latency_ms is not None:
            c[index[("slack", flow.flow_id)]] += risk.slo_slack_weight

    rows: list[dict[int, float]] = []
    lower: list[float] = []
    upper: list[float] = []

    def add_constraint(coeffs: dict[int, float], lo: float, hi: float) -> None:
        rows.append(coeffs)
        lower.append(lo)
        upper.append(hi)

    # Each replica exactly once.
    for p in replicas:
        add_constraint({index[("x", p, n)]: 1.0 for n in nodes}, 1.0, 1.0)

    # Resource capacities.
    for n in nodes:
        add_constraint(
            {index[("x", p, n)]: replica_by_id[p].cpu_request for p in replicas},
            -np.inf,
            node_by_id[n].cpu_capacity,
        )
        add_constraint(
            {index[("x", p, n)]: replica_by_id[p].memory_request_mb for p in replicas},
            -np.inf,
            node_by_id[n].memory_capacity_mb,
        )

    # Anti-affinity groups.
    groups = sorted({p.anti_affinity_group for p in problem.replicas if p.anti_affinity_group})
    for group in groups:
        members = [p.replica_id for p in problem.replicas if p.anti_affinity_group == group]
        for n in nodes:
            add_constraint({index[("x", p, n)]: 1.0 for p in members}, -np.inf, 1.0)

    # Pairwise placement linearization.
    for flow in problem.flows:
        f = flow.flow_id
        add_constraint(
            {index[("y", f, n, m)]: 1.0 for n in nodes for m in nodes},
            1.0,
            1.0,
        )
        for n in nodes:
            for m in nodes:
                y = index[("y", f, n, m)]
                xp = index[("x", flow.source_replica, n)]
                xq = index[("x", flow.destination_replica, m)]
                add_constraint({y: 1.0, xp: -1.0}, -np.inf, 0.0)
                add_constraint({y: 1.0, xq: -1.0}, -np.inf, 0.0)
                add_constraint({xp: 1.0, xq: 1.0, y: -1.0}, -np.inf, 1.0)

    # Airtime/conflict group budgets.
    for scenario in problem.scenarios:
        for group, budget in scenario.conflict_budgets_seconds.items():
            coeffs: dict[int, float] = {}
            for flow in problem.flows:
                for n in nodes:
                    for m in nodes:
                        link = link_for(scenario, node_by_id[n].rack_id, node_by_id[m].rack_id)
                        if link.conflict_group == group:
                            y_idx = index[("y", flow.flow_id, n, m)]
                            if ub[y_idx] == 0.0:
                                val = 0.0
                            else:
                                val = flow_airtime_seconds(flow, link)
                                if np.isinf(val):
                                    val = 1e9
                            coeffs[y_idx] = val
            if coeffs:
                add_constraint(coeffs, -np.inf, budget)

    # Maximum number of relocations.
    if problem.max_relocations is not None:
        coeffs = {}
        for p in replicas:
            current = problem.current_placement[p]
            for n in nodes:
                if n != current:
                    coeffs[index[("x", p, n)]] = 1.0
        add_constraint(coeffs, -np.inf, float(problem.max_relocations))

    # Per-flow expected-latency SLO with non-negative slack.
    for flow in problem.flows:
        if flow.max_expected_latency_ms is None:
            continue
        coeffs: dict[int, float] = {index[("slack", flow.flow_id)]: -1.0}
        for n in nodes:
            for m in nodes:
                expected_latency = sum(
                    weights[s.scenario_id]
                    * link_for(s, node_by_id[n].rack_id, node_by_id[m].rack_id).latency_ms
                    for s in problem.scenarios
                )
                coeffs[index[("y", flow.flow_id, n, m)]] = expected_latency
        add_constraint(coeffs, -np.inf, float(flow.max_expected_latency_ms))

    # CVaR excess constraints: scenario_cost - eta - u_s <= 0.
    if risk.cvar_weight > 0:
        for scenario in problem.scenarios:
            coeffs = {eta_idx: -1.0, index[("u", scenario.scenario_id)]: -1.0}
            for flow in problem.flows:
                for n in nodes:
                    for m in nodes:
                        link = link_for(scenario, node_by_id[n].rack_id, node_by_id[m].rack_id)
                        coeffs[index[("y", flow.flow_id, n, m)]] = flow_delay_cost(flow, link)
            add_constraint(coeffs, -np.inf, 0.0)

    matrix = lil_matrix((len(rows), count), dtype=float)
    for r, coeffs in enumerate(rows):
        for idx, value in coeffs.items():
            matrix[r, idx] = value
    constraint = LinearConstraint(matrix.tocsr(), np.asarray(lower), np.asarray(upper))

    result = milp(
        c=c,
        integrality=integrality,
        bounds=Bounds(lb, ub),
        constraints=constraint,
        options={"time_limit": float(time_limit_seconds), "presolve": True},
    )
    if result.x is None:
        raise ExactSolveError(f"MILP returned no solution: status={result.status}, message={result.message}")
    if require_optimal and (int(result.status) != 0 or not bool(result.success)):
        raise ExactSolveError(
            "MILP did not prove optimality; do not report the incumbent as exact: "
            f"status={result.status}, message={result.message}, "
            f"mip_gap={getattr(result, 'mip_gap', None)}"
        )

    placement = {}
    for p in replicas:
        chosen = max(nodes, key=lambda n: result.x[index[("x", p, n)]])
        placement[p] = chosen
    evaluation = evaluate_placement(problem, placement, risk)
    if not evaluation.feasible:
        raise ExactSolveError("solver returned semantically infeasible placement: " + "; ".join(evaluation.reasons))
    if not np.isclose(float(result.fun), evaluation.total_objective, rtol=1e-7, atol=1e-7):
        raise ExactSolveError(
            "solver/evaluator objective mismatch: "
            f"solver={float(result.fun)}, evaluator={evaluation.total_objective}"
        )

    metadata = {
        "solver": "scipy.optimize.milp/HiGHS",
        "status": int(result.status),
        "message": str(result.message),
        "solver_objective": float(result.fun),
        "mip_gap": float(getattr(result, "mip_gap", np.nan)),
        "mip_dual_bound": float(getattr(result, "mip_dual_bound", np.nan)),
        "mip_node_count": int(getattr(result, "mip_node_count", 0)),
        "proven_optimal": int(result.status) == 0 and bool(result.success),
        "placement_evaluation": asdict(evaluation),
        "variable_count": count,
        "constraint_count": len(rows),
    }
    return placement, metadata
