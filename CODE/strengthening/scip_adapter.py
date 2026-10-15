"""Optional SCIP adapter for the exact B+ linearized formulation.

This module is not part of the frozen v0.3 solver path. It exists only for the
post-review matched-budget MILP-heuristic experiment (S-MILP) and imports
pyscipopt lazily. It replaces the project's original Gurobi adapter (removed
2026-09-17 after this substitution completed successfully; see
IMPLEMENTATION_CORRECTION_2026-09-17-SCIP-SUBSTITUTION.md for the original
formulation's provenance): a Gurobi license was not available, so this
experiment uses SCIP (via PySCIPOpt, bundled build, no separate license)
instead, matching the same three modes (default, rins, feasibility-pump) via
SCIP's own separately-named heuristics of the same kind, applied to an
identical MILP formulation (same variables, objective, and constraints).
"""
from __future__ import annotations
from typing import Any

from mape_cap_bplus.models import ProblemInstance, RiskConfig, normalize_scenario_weights
from mape_cap_bplus.objective import evaluate_placement, flow_airtime_seconds, flow_delay_cost, link_for
from mape_cap_bplus.validation import validate_problem


def solve_scip(problem: ProblemInstance, risk: RiskConfig, time_limit: float, mode: str = "default") -> tuple[dict[str, str], dict[str, Any]]:
    try:
        import pyscipopt as scip
    except ImportError as exc:
        raise RuntimeError("pyscipopt is not installed; install it with `pip install pyscipopt`") from exc
    risk.validate(); valid, reasons = validate_problem(problem)
    if not valid: raise ValueError("invalid problem: " + "; ".join(reasons))
    if mode not in {"default", "rins", "feasibility-pump"}: raise ValueError(mode)
    nodes = [n.node_id for n in problem.nodes]; replicas = [r.replica_id for r in problem.replicas]
    weights = normalize_scenario_weights(problem.scenarios); node_by = problem.node_by_id; rep_by = problem.replica_by_id

    m = scip.Model(f"bplus-{problem.instance_id}-{mode}")
    m.hideOutput(); m.setParam("limits/time", float(time_limit)); m.setParam("randomization/randomseedshift", 1)
    m.setParam("emphasis/numerics", "off") if False else None
    if mode == "rins":
        m.setParam("heuristics/rins/freq", 1)
        m.setParam("heuristics/feaspump/freq", -1)
    elif mode == "feasibility-pump":
        m.setParam("heuristics/rins/freq", -1)
        m.setParam("heuristics/feaspump/freq", 1)
        m.setParam("heuristics/feaspump/maxsols", -1)
    # "default": leave SCIP's default heuristic schedule untouched.

    x = {(p, n): m.addVar(vtype="B", name=f"x[{p},{n}]") for p in replicas for n in nodes}
    y = {(f.flow_id, n, nn): m.addVar(vtype="B", name=f"y[{f.flow_id},{n},{nn}]") for f in problem.flows for n in nodes for nn in nodes}
    eta = m.addVar(lb=0.0, name="eta")
    u = {s.scenario_id: m.addVar(lb=0.0, name=f"u[{s.scenario_id}]") for s in problem.scenarios}
    slack = {f.flow_id: m.addVar(lb=0.0, name=f"slack[{f.flow_id}]") for f in problem.flows if f.max_expected_latency_ms is not None}

    for p in replicas:
        allowed = set(problem.allowed_nodes_for(p))
        for n in nodes:
            if n not in allowed: m.chgVarUb(x[p, n], 0.0)
    for f in problem.flows:
        for n in nodes:
            for nn in nodes:
                sr = node_by[n].rack_id; dr = node_by[nn].rack_id
                if any(not link_for(s, sr, dr).available for s in problem.scenarios): m.chgVarUb(y[f.flow_id, n, nn], 0.0)

    obj = 0
    for f in problem.flows:
        for n in nodes:
            for nn in nodes:
                coeff = sum(weights[s.scenario_id] * flow_delay_cost(f, link_for(s, node_by[n].rack_id, node_by[nn].rack_id)) for s in problem.scenarios)
                obj += coeff * y[f.flow_id, n, nn]
    for p in replicas:
        current = problem.current_placement[p]; cost = problem.relocation_costs[p].cost_units
        for n in nodes:
            if n != current: obj += risk.relocation_weight * cost * x[p, n]
    if risk.cvar_weight > 0:
        obj += risk.cvar_weight * eta; tail = 1 - risk.cvar_quantile
        for s in problem.scenarios: obj += risk.cvar_weight * weights[s.scenario_id] / tail * u[s.scenario_id]
    for fid, var in slack.items(): obj += risk.slo_slack_weight * var
    m.setObjective(obj, "minimize")

    for p in replicas: m.addCons(scip.quicksum(x[p, n] for n in nodes) == 1, name=f"assign[{p}]")
    for n in nodes:
        m.addCons(scip.quicksum(rep_by[p].cpu_request * x[p, n] for p in replicas) <= node_by[n].cpu_capacity, name=f"cpu[{n}]")
        m.addCons(scip.quicksum(rep_by[p].memory_request_mb * x[p, n] for p in replicas) <= node_by[n].memory_capacity_mb, name=f"mem[{n}]")
    groups = sorted({p.anti_affinity_group for p in problem.replicas if p.anti_affinity_group})
    for group in groups:
        members = [p.replica_id for p in problem.replicas if p.anti_affinity_group == group]
        for n in nodes: m.addCons(scip.quicksum(x[p, n] for p in members) <= 1, name=f"anti[{group},{n}]")
    for f in problem.flows:
        m.addCons(scip.quicksum(y[f.flow_id, n, nn] for n in nodes for nn in nodes) == 1, name=f"pair[{f.flow_id}]")
        for n in nodes:
            for nn in nodes:
                yy = y[f.flow_id, n, nn]; xs = x[f.source_replica, n]; xd = x[f.destination_replica, nn]
                m.addCons(yy <= xs); m.addCons(yy <= xd); m.addCons(yy >= xs + xd - 1)
    for s in problem.scenarios:
        for group, budget in s.conflict_budgets_seconds.items():
            terms = []
            for f in problem.flows:
                for n in nodes:
                    for nn in nodes:
                        link = link_for(s, node_by[n].rack_id, node_by[nn].rack_id)
                        if link.conflict_group == group and y[f.flow_id, n, nn].getUbOriginal() > 0:
                            val = flow_airtime_seconds(f, link)
                            if val != float("inf"): terms.append(val * y[f.flow_id, n, nn])
            if terms: m.addCons(scip.quicksum(terms) <= budget, name=f"air[{s.scenario_id},{group}]")
    if problem.max_relocations is not None:
        m.addCons(scip.quicksum(x[p, n] for p in replicas for n in nodes if n != problem.current_placement[p]) <= problem.max_relocations, name="max_reloc")
    for f in problem.flows:
        if f.max_expected_latency_ms is None: continue
        exp = scip.quicksum(sum(weights[s.scenario_id] * link_for(s, node_by[n].rack_id, node_by[nn].rack_id).latency_ms for s in problem.scenarios) * y[f.flow_id, n, nn] for n in nodes for nn in nodes)
        m.addCons(exp - slack[f.flow_id] <= f.max_expected_latency_ms, name=f"slo[{f.flow_id}]")
    if risk.cvar_weight > 0:
        for s in problem.scenarios:
            scen = scip.quicksum(flow_delay_cost(f, link_for(s, node_by[n].rack_id, node_by[nn].rack_id)) * y[f.flow_id, n, nn] for f in problem.flows for n in nodes for nn in nodes)
            m.addCons(scen - eta - u[s.scenario_id] <= 0, name=f"cvar[{s.scenario_id}]")

    m.optimize()
    if m.getNSols() <= 0: raise RuntimeError(f"SCIP produced no incumbent; status={m.getStatus()}")
    placement = {p: max(nodes, key=lambda n: m.getVal(x[p, n])) for p in replicas}
    evaluation = evaluate_placement(problem, placement, risk)
    if not evaluation.feasible: raise RuntimeError("SCIP incumbent failed semantic evaluator")
    meta = {
        "mode": mode, "status": m.getStatus(), "runtime_seconds": float(m.getSolvingTime()),
        "objective": float(m.getObjVal()), "best_bound": float(m.getDualbound()),
        "mip_gap": float(m.getGap()), "node_count": float(m.getNNodes()),
        "solution_count": int(m.getNSols()), "variable_count": int(m.getNVars()),
        "constraint_count": int(m.getNConss()), "scip_version": str(m.version()),
        "solver": "SCIP (via PySCIPOpt)", "substituted_for": "Gurobi (license unavailable)",
    }
    return placement, meta
