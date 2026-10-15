"""Full locally executable, checkpointed MAPE-CAP B+ campaign."""
from __future__ import annotations

from dataclasses import asdict, replace
import csv
from datetime import datetime, timezone
import json
from importlib import metadata as importlib_metadata
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from typing import Callable, Iterable

from .checkpoints import CampaignState, stable_json_hash, tree_hash
from .controller import PersistentRegimeDetector
from .dynamic import run_dynamic_sequence
from .exact import ExactSolveError, solve_exact
from .generators import (
    generate_problem,
    homogenize_network,
    scale_conflict_budgets,
    single_scenario,
    without_conflicts,
)
from .heuristic import resource_greedy_placement, robust_local_search
from .lns import robust_lns
from .models import ProblemInstance, RiskConfig
from .objective import evaluate_placement
from .scenarios import build_demo_problem, controlled_scenario, outage_scenario, scenario_family
from .serialization import write_json


EVIDENCE_TYPE = "controlled-synthetic-local-campaign"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_csv(path: Path, rows: Iterable[dict]) -> None:
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("\n", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, sort_keys=True) if isinstance(value, (dict, list, tuple)) else value for key, value in row.items()})


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _record(
    *,
    run_id: str,
    method: str,
    problem: ProblemInstance,
    risk: RiskConfig,
    placement: dict[str, str],
    runtime_seconds: float,
    status: str = "complete",
    notes: str = "",
    extra: dict | None = None,
) -> dict:
    evaluation = evaluate_placement(problem, placement, risk)
    effective_status = status
    if status == "complete" and not evaluation.feasible:
        effective_status = "complete-infeasible"
    row = {
        "run_id": run_id,
        "status": effective_status,
        "method": method,
        "instance_id": problem.instance_id,
        "replica_count": len(problem.replicas),
        "flow_count": len(problem.flows),
        "node_count": len(problem.nodes),
        "rack_count": len(problem.rack_ids),
        "scenario_count": len(problem.scenarios),
        "objective": evaluation.total_objective,
        "expected_delay_cost": evaluation.expected_delay_cost,
        "cvar_delay_cost": evaluation.cvar_delay_cost,
        "relocation_cost": evaluation.relocation_cost,
        "slo_slack": evaluation.slo_slack,
        "feasible": evaluation.feasible,
        "runtime_seconds": runtime_seconds,
        "cvar_quantile": risk.cvar_quantile,
        "cvar_weight": risk.cvar_weight,
        "relocation_weight": risk.relocation_weight,
        "slo_slack_weight": risk.slo_slack_weight,
        "placement": placement,
        "notes": notes,
        "evidence_type": EVIDENCE_TYPE,
    }
    if extra:
        row.update(extra)
    return row


def _run_method(method: str, problem: ProblemInstance, risk: RiskConfig, *, seed: int = 1, exact_limit: float = 45.0, lns_iterations: int = 30, lns_time_limit: float = 5.0, lns_destroy_size: int | None = None, lns_local_iterations: int = 8) -> dict:
    started = time.perf_counter()
    if method == "Current":
        placement = dict(problem.current_placement)
        meta = {}
    elif method == "ResourceGreedy":
        placement = resource_greedy_placement(problem)
        meta = {}
    elif method == "LocalSearch":
        placement, meta = robust_local_search(problem, risk, max_iterations=100)
    elif method == "LNS":
        placement, meta = robust_lns(
            problem, risk, seed=seed, iterations=lns_iterations,
            destroy_size=lns_destroy_size or min(4, len(problem.replicas)),
            time_limit_seconds=lns_time_limit,
            local_iterations=lns_local_iterations,
        )
    elif method == "Exact":
        placement, meta = solve_exact(problem, risk, time_limit_seconds=exact_limit)
    else:
        raise ValueError(f"unknown method {method}")
    runtime = time.perf_counter() - started
    if isinstance(meta, dict) and "iteration_log" in meta:
        meta = {key: value for key, value in meta.items() if key != "iteration_log"}
    if isinstance(meta, dict) and "candidate_log" in meta:
        meta = {key: value for key, value in meta.items() if key != "candidate_log"}
    return _record(
        run_id=f"{problem.instance_id}:{method}:{seed}",
        method=method,
        problem=problem,
        risk=risk,
        placement=placement,
        runtime_seconds=runtime,
        extra={"solver_metadata": meta},
    )


def _runtime_signature() -> dict:
    """Return stable runtime provenance for cheap environment/test checkpoints.

    This deliberately excludes timestamps. It is included in checkpoint
    fingerprints so moving the package to a different Python/platform/package
    environment cannot silently preserve a stale verification record.
    """
    packages: dict[str, str] = {}
    for module_name in ("numpy", "scipy", "jsonschema", "pandas", "matplotlib"):
        try:
            packages[module_name] = importlib_metadata.version(module_name)
        except Exception as exc:
            packages[module_name] = f"unavailable: {exc}"
    return {
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "packages": packages,
    }


def _environment_payload(root: Path) -> dict:
    packages: dict[str, str] = {}
    for module_name in ("numpy", "scipy", "jsonschema", "pandas", "matplotlib"):
        try:
            packages[module_name] = importlib_metadata.version(module_name)
        except Exception as exc:
            packages[module_name] = f"unavailable: {exc}"
    return {
        "generated_at": _utc_now(),
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "packages": packages,
        "root": str(root.resolve()),
        "evidence_boundary": "local controlled simulation; no Kubernetes, packet-level mmWave, or physical measurements",
    }


def _scenario_sanity_rows() -> list[dict]:
    risk = RiskConfig(cvar_weight=0.0, relocation_weight=0.0)
    rows: list[dict] = []
    for index, scenario in enumerate(scenario_family()):
        problem = build_demo_problem([scenario])
        for method in ("Current", "LNS", "Exact"):
            try:
                rows.append(_run_method(method, problem, risk, seed=100 + index, lns_iterations=10, lns_time_limit=1.0, lns_destroy_size=3, lns_local_iterations=3))
            except (ValueError, ExactSolveError) as exc:
                rows.append(
                    {
                        "run_id": f"{scenario.scenario_id}:{method}",
                        "status": "expected-or-diagnosed-failure",
                        "method": method,
                        "instance_id": problem.instance_id,
                        "scenario_id": scenario.scenario_id,
                        "feasible": False,
                        "error": str(exc),
                        "evidence_type": EVIDENCE_TYPE,
                    }
                )
        for row in rows[-3:]:
            row["scenario_id"] = scenario.scenario_id
            row["scenario_class"] = scenario.metadata.get("class", "")
    return rows


def _baseline_rows() -> list[dict]:
    # This fixed generated instance was selected before campaign execution
    # because traffic-only, nominal-network, and robust optima are distinct and
    # the robust optimum is strictly better under the full evaluation model.
    full_problem = generate_problem(replica_count=6, rack_count=3, nodes_per_rack=2, seed=10)
    full_risk = RiskConfig(cvar_quantile=0.8, cvar_weight=1.5, relocation_weight=1.0, slo_slack_weight=1000.0)
    rows: list[dict] = []
    rows.append(_run_method("Current", full_problem, full_risk))
    try:
        rows.append(_run_method("ResourceGreedy", full_problem, full_risk))
    except ValueError as exc:
        rows.append({"run_id": "baseline:ResourceGreedy", "status": "failure", "method": "ResourceGreedy", "error": str(exc), "evidence_type": EVIDENCE_TYPE})

    traffic_problem = homogenize_network(full_problem)
    traffic_risk = replace(full_risk, cvar_weight=0.0)
    traffic = _run_method("Exact", traffic_problem, traffic_risk, seed=11)
    traffic["method"] = "TrafficOnly-MAPE-CAP"
    traffic_eval = evaluate_placement(full_problem, traffic["placement"], full_risk)
    traffic.update({"objective": traffic_eval.total_objective, "expected_delay_cost": traffic_eval.expected_delay_cost,
                    "cvar_delay_cost": traffic_eval.cvar_delay_cost, "relocation_cost": traffic_eval.relocation_cost,
                    "slo_slack": traffic_eval.slo_slack, "feasible": traffic_eval.feasible,
                    "notes": "exact traffic-only formulation; evaluated under full B+ scenarios"})
    rows.append(traffic)

    deterministic_problem = single_scenario(full_problem, 0)
    deterministic = _run_method("Exact", deterministic_problem, replace(full_risk, cvar_weight=0.0), seed=12)
    deterministic["method"] = "DeterministicNetworkAware"
    det_eval = evaluate_placement(full_problem, deterministic["placement"], full_risk)
    deterministic.update({"objective": det_eval.total_objective, "expected_delay_cost": det_eval.expected_delay_cost,
                          "cvar_delay_cost": det_eval.cvar_delay_cost, "relocation_cost": det_eval.relocation_cost,
                          "slo_slack": det_eval.slo_slack, "feasible": det_eval.feasible,
                          "notes": "exact nominal-scenario formulation; evaluated under full B+ scenario ensemble"})
    rows.append(deterministic)

    robust_lns_row = _run_method("LNS", full_problem, full_risk, seed=13, lns_iterations=60, lns_time_limit=10.0, lns_destroy_size=4, lns_local_iterations=10)
    robust_lns_row["method"] = "BPlus-LNS"
    rows.append(robust_lns_row)
    exact = _run_method("Exact", full_problem, full_risk, seed=14)
    exact["method"] = "BPlus-Exact"
    rows.append(exact)
    return rows


def _ablation_rows() -> list[dict]:
    rows: list[dict] = []

    def paired(component: str, fixture: str, base: ProblemInstance, full_risk: RiskConfig, ablated_problem: ProblemInstance, ablated_risk: RiskConfig, seed: int) -> None:
        full = _run_method("Exact", base, full_risk, seed=seed)
        full["component"] = component
        full["variant"] = "Full-BPlus"
        full["fixture"] = fixture
        full["reference_objective"] = full["objective"]
        full["reference_feasible"] = full["feasible"]
        full["reference_delta_vs_full"] = 0.0
        rows.append(full)

        ablated = _run_method("Exact", ablated_problem, ablated_risk, seed=seed + 1)
        ablated["component"] = component
        ablated["variant"] = f"Without-{component}"
        ablated["fixture"] = fixture
        reference = evaluate_placement(base, ablated["placement"], full_risk)
        ablated["reference_objective"] = reference.total_objective
        ablated["reference_feasible"] = reference.feasible
        ablated["reference_delta_vs_full"] = (
            reference.total_objective - float(full["reference_objective"])
            if reference.feasible else float("inf")
        )
        rows.append(ablated)

    # Tail-risk/CVaR discriminating fixture.
    risk_problem = build_demo_problem([
        controlled_scenario("common", 2.0, 2.0, 2.0, weight=0.8),
        controlled_scenario("tail", 2.0, 10.0, 2.0, weight=0.2),
    ])
    risk_full = RiskConfig(0.8, 2.0, 0.0, 0.0)
    paired("CVaR", "tail-risk", risk_problem, risk_full, risk_problem, replace(risk_full, cvar_weight=0.0), 200)

    # Relocation-economics discriminating fixture.
    relocation_problem = build_demo_problem([controlled_scenario("ac", 15.0, 2.0, 15.0)])
    relocation_full = RiskConfig(0.9, 0.0, 100.0, 0.0)
    paired("RelocationCost", "high-relocation-cost", relocation_problem, relocation_full, relocation_problem, replace(relocation_full, relocation_weight=0.0), 210)

    # Conflict/airtime discriminating fixture.
    conflict_problem = build_demo_problem([
        controlled_scenario("tight", 1.0, 100.0, 1.0, goodput_bps=100_000_000.0, budget_seconds=0.12)
    ])
    conflict_full = RiskConfig(0.9, 0.0, 0.0, 0.0)
    paired("ConflictBudget", "tight-airtime", conflict_problem, conflict_full, without_conflicts(conflict_problem), conflict_full, 220)

    # Deterministic and traffic-only formulation discriminating fixture.
    network_problem = generate_problem(replica_count=6, rack_count=3, nodes_per_rack=2, seed=3)
    network_full = RiskConfig(0.8, 1.5, 1.0, 1000.0)
    paired("ScenarioRobustness", "generated-seed-3", network_problem, network_full, single_scenario(network_problem, 0), replace(network_full, cvar_weight=0.0), 230)
    paired("WirelessState", "generated-seed-3", network_problem, network_full, homogenize_network(network_problem), network_full, 240)
    return rows


def _sensitivity_rows() -> list[dict]:
    """Run discriminating parameter sweeps rather than objective-only scaling.

    Each block uses a fixture known a priori to change placement or feasibility
    over the declared range. This prevents a misleading sensitivity table in
    which every row has the same decision.
    """
    rows: list[dict] = []
    run_index = 0

    cvar_problem = build_demo_problem([
        controlled_scenario("common", 2.0, 2.0, 2.0, weight=0.8),
        controlled_scenario("tail", 2.0, 10.0, 2.0, weight=0.2),
    ])
    for cvar_weight in (0.0, 0.25, 0.5, 1.0, 2.0, 5.0):
        risk = RiskConfig(0.8, cvar_weight, 0.0, 0.0)
        result = _run_method("Exact", cvar_problem, risk, seed=300 + run_index)
        result["sensitivity"] = "cvar-weight"
        rows.append(result)
        run_index += 1

    relocation_problem = build_demo_problem([controlled_scenario("ac", 15.0, 2.0, 15.0)])
    for relocation_weight in (0.0, 1.0, 5.0, 25.0, 50.0, 100.0):
        risk = RiskConfig(0.9, 0.0, relocation_weight, 0.0)
        result = _run_method("Exact", relocation_problem, risk, seed=330 + run_index)
        result["sensitivity"] = "relocation-weight"
        rows.append(result)
        run_index += 1

    conflict_problem = build_demo_problem([
        controlled_scenario(
            "tight", 1.0, 100.0, 1.0,
            goodput_bps=100_000_000.0,
            budget_seconds=0.12,
        )
    ])
    for factor in (0.5, 0.75, 1.0, 1.5, 3.0, 5.0):
        adjusted = scale_conflict_budgets(conflict_problem, factor)
        risk = RiskConfig(0.9, 0.0, 0.0, 0.0)
        try:
            result = _run_method("Exact", adjusted, risk, seed=360 + run_index)
            result["sensitivity"] = "conflict-budget"
            result["budget_factor"] = factor
            rows.append(result)
        except ExactSolveError as exc:
            rows.append({
                "run_id": f"conflict-budget:{factor}",
                "status": "infeasible",
                "method": "Exact",
                "instance_id": adjusted.instance_id,
                "replica_count": len(adjusted.replicas),
                "flow_count": len(adjusted.flows),
                "node_count": len(adjusted.nodes),
                "rack_count": len(adjusted.rack_ids),
                "scenario_count": len(adjusted.scenarios),
                "feasible": False,
                "sensitivity": "conflict-budget",
                "budget_factor": factor,
                "error": str(exc),
                "evidence_type": EVIDENCE_TYPE,
            })
        run_index += 1
    return rows


def _scalability_rows() -> list[dict]:
    rows: list[dict] = []
    risk = RiskConfig(0.9, 0.75, 1.0, 1000.0)
    for replica_count in (6, 8, 12, 16, 20, 24, 32, 40, 50):
        for seed in (1, 2, 3):
            nodes_per_rack = max(2, (replica_count + 5) // 6)
            problem = generate_problem(replica_count=replica_count, rack_count=3, nodes_per_rack=nodes_per_rack, seed=seed)
            lns = _run_method("LNS", problem, risk, seed=seed, lns_iterations=8, lns_time_limit=1.0, lns_destroy_size=3, lns_local_iterations=2)
            lns["experiment"] = "scalability"
            rows.append(lns)
            if replica_count <= 8:
                try:
                    exact = _run_method("Exact", problem, risk, seed=seed, exact_limit=60.0)
                    exact["experiment"] = "scalability"
                    rows.append(exact)
                except ExactSolveError as exc:
                    rows.append({
                        "run_id": f"{problem.instance_id}:Exact:{seed}",
                        "status": "not-proven-within-limit",
                        "method": "Exact",
                        "instance_id": problem.instance_id,
                        "replica_count": replica_count,
                        "error": str(exc),
                        "experiment": "scalability",
                        "evidence_type": EVIDENCE_TYPE,
                    })
    # Add exact gaps wherever an exact row exists.
    exact_by_instance = {row["instance_id"]: row for row in rows if row.get("method") == "Exact" and row.get("status") == "complete"}
    for row in rows:
        exact = exact_by_instance.get(row.get("instance_id"))
        if row.get("method") == "LNS" and exact and float(exact["objective"]) > 0:
            row["exact_gap_percent"] = 100.0 * (float(row["objective"]) - float(exact["objective"])) / float(exact["objective"])
    return rows


def _dynamic_rows() -> list[dict]:
    baseline = controlled_scenario("baseline", 4.0, 10.0, 8.0, regime_duration_seconds=300.0)
    transient = controlled_scenario("temporary", 25.0, 5.0, 8.0, regime_duration_seconds=10.0, metadata={"class": "negative-control"})
    degraded = controlled_scenario("persistent-degraded", 25.0, 4.0, 12.0, regime_duration_seconds=300.0)
    recovery = controlled_scenario("recovery", 4.0, 10.0, 8.0, regime_duration_seconds=300.0)
    sequence = [baseline, baseline, transient, baseline, degraded, degraded, degraded, degraded, recovery, recovery, recovery]
    problem = build_demo_problem([baseline])
    risk = RiskConfig(0.9, 0.75, 1.0, 1000.0)
    return run_dynamic_sequence(problem, sequence, risk, minimum_persistent_windows=3, uncertainty_margin=10.0, seed=500)


def _supporting_output_root(root: Path) -> Path:
    """Return the journal-repository workspace for regenerated supporting full-local outputs."""
    return root.parent / "RESULTS" / "supporting" / "reproduced" / "full_campaign"


def _make_figures(root: Path) -> list[Path]:
    import matplotlib.pyplot as plt
    import pandas as pd

    results = _supporting_output_root(root)
    figures = _supporting_output_root(root) / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []

    baseline = pd.read_csv(results / "baselines.csv")
    baseline = baseline[(baseline["status"] == "complete") & baseline["objective"].map(lambda value: float(value) < float("inf"))]
    path = figures / "baseline_objective.png"
    plt.figure(figsize=(9, 5))
    plt.bar(baseline["method"], baseline["objective"])
    plt.ylabel("Risk-adjusted objective")
    plt.xticks(rotation=25, ha="right")
    plt.tight_layout()
    plt.savefig(path, dpi=180)
    plt.close()
    created.append(path)

    ablation = pd.read_csv(results / "ablations.csv")
    ablated = ablation[ablation["variant"] != "Full-BPlus"].copy()
    finite_penalties = [float(value) for value in ablated["reference_delta_vs_full"] if float(value) < float("inf")]
    cap = (max(finite_penalties) * 1.20) if finite_penalties else 1.0
    ablated["display_penalty"] = [float(value) if float(value) < float("inf") else cap for value in ablated["reference_delta_vs_full"]]
    path = figures / "ablation_reference_objective.png"
    plt.figure(figsize=(9, 5))
    bars = plt.bar(ablated["component"], ablated["display_penalty"])
    for bar, feasible in zip(bars, ablated["reference_feasible"]):
        if str(feasible).lower() != "true":
            plt.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), "infeasible", ha="center", va="bottom", rotation=90)
    plt.ylabel("Objective penalty after component removal")
    plt.xticks(rotation=25, ha="right")
    plt.tight_layout()
    plt.savefig(path, dpi=180)
    plt.close()
    created.append(path)

    scalability = pd.read_csv(results / "scalability.csv")
    lns = scalability[(scalability["method"] == "LNS") & (scalability["status"] == "complete")]
    grouped = lns.groupby("replica_count", as_index=False)["runtime_seconds"].mean()
    path = figures / "scalability_runtime.png"
    plt.figure(figsize=(8, 5))
    plt.plot(grouped["replica_count"], grouped["runtime_seconds"], marker="o")
    plt.xlabel("Replica count")
    plt.ylabel("Mean LNS runtime (seconds)")
    plt.tight_layout()
    plt.savefig(path, dpi=180)
    plt.close()
    created.append(path)

    dynamic = pd.read_csv(results / "dynamic_sequence.csv")
    path = figures / "dynamic_sequence.png"
    plt.figure(figsize=(9, 5))
    plt.plot(dynamic["window_index"], dynamic["current_objective"], marker="o", label="Current")
    plt.plot(dynamic["window_index"], dynamic["candidate_objective"], marker="x", label="Candidate")
    plt.xlabel("Orchestration window")
    plt.ylabel("Operating objective")
    plt.legend()
    plt.tight_layout()
    plt.savefig(path, dpi=180)
    plt.close()
    created.append(path)
    return created


def _report_text(root: Path) -> str:
    import pandas as pd

    results = _supporting_output_root(root)
    baseline = pd.read_csv(results / "baselines.csv")
    ablation = pd.read_csv(results / "ablations.csv")
    scalability = pd.read_csv(results / "scalability.csv")
    dynamic = pd.read_csv(results / "dynamic_sequence.csv")
    completed_baselines = baseline[baseline["status"] == "complete"].copy()
    minimum_baseline_objective = float(completed_baselines["objective"].min())
    best_methods = completed_baselines[
        (completed_baselines["objective"].astype(float) - minimum_baseline_objective).abs() <= 1e-9
    ]["method"].tolist()
    exact_small = scalability[(scalability["method"] == "Exact") & (scalability["status"] == "complete")]
    gaps = scalability[(scalability["method"] == "LNS") & scalability["exact_gap_percent"].notna()]
    accepted = int(dynamic["accepted"].astype(str).str.lower().eq("true").sum())
    transient_rows = dynamic[dynamic["scenario_id"] == "temporary"]
    transient_accepted = int(transient_rows["accepted"].astype(str).str.lower().eq("true").sum())
    infeasible_baselines = baseline[baseline["feasible"].astype(str).str.lower().eq("false")]["method"].tolist()
    sensitivity = pd.read_csv(results / "sensitivity.csv")
    sensitivity_decisions = {
        name: int(group["placement"].dropna().nunique())
        for name, group in sensitivity.groupby("sensitivity")
    }

    lines = [
        "# MAPE-CAP B+ Full Local Campaign Report",
        "",
        f"Generated: {_utc_now()}",
        "",
        "## Evidence boundary",
        "",
        "This report contains controlled synthetic and locally executed optimization evidence. It does **not** contain Kubernetes measurements, packet-level 802.11ad/ay evidence, or physical mmWave measurements.",
        "",
        "## Completed local campaign blocks",
        "",
        "- controlled scenario sanity checks;",
        "- resource, traffic-only, deterministic-network, robust B+, and exact baselines;",
        "- component ablations;",
        "- risk, relocation, and conflict-budget sensitivity;",
        "- LNS scalability with exact small-instance references;",
        "- slow-timescale dynamic negative-control and persistent-regime sequence;",
        "- checkpointed and hash-verified output generation.",
        "",
        "## Key local results",
        "",
        f"- Lowest baseline objective: **{', '.join(best_methods)}** ({minimum_baseline_objective:.3f}).",
        f"- Exact scalability references completed: **{len(exact_small)}**.",
        f"- Mean LNS exact gap on matched small instances: **{float(gaps['exact_gap_percent'].mean()) if len(gaps) else float('nan'):.3f}%**.",
        f"- Accepted dynamic relocations: **{accepted}**.",
        f"- Relocations accepted during the short transient negative control: **{transient_accepted}**.",
        f"- Infeasible baseline methods under the full constraints: **{', '.join(infeasible_baselines) if infeasible_baselines else 'none'}**.",
        f"- Unique decisions in sensitivity blocks: **{sensitivity_decisions}**.",
        "",
        "## Interpretation restriction",
        "",
        "These numbers verify software behaviour, optimization logic, ablation plumbing, and campaign reproducibility. They are not sufficient for final journal claims about real application latency, real pod-relocation economics, or mmWave performance.",
        "",
        "## Relationship to the primary v0.3 evidence",
        "",
        "This controlled campaign is retained as supporting evidence only. The journal-facing primary evidence is the frozen v0.3 R1--R8 campaign under RESULTS/primary/v03-20260811T151500Z/; supporting outputs are not pooled with the primary campaign.",
        "",
        "## Output index",
        "",
        "- `RESULTS/supporting/reproduced/full_campaign/scenario_sanity.csv`",
        "- `RESULTS/supporting/reproduced/full_campaign/baselines.csv`",
        "- `RESULTS/supporting/reproduced/full_campaign/ablations.csv`",
        "- `RESULTS/supporting/reproduced/full_campaign/sensitivity.csv`",
        "- `RESULTS/supporting/reproduced/full_campaign/scalability.csv`",
        "- `RESULTS/supporting/reproduced/full_campaign/dynamic_sequence.csv`",
        "- `RESULTS/supporting/reproduced/full_campaign/figures/*.png`",
        "- `RESULTS/supporting/reproduced/full_campaign/audit/campaign_state.json`",
        "- `RESULTS/supporting/reproduced/full_campaign/audit/full_campaign_environment.json`",
    ]
    return "\n".join(lines) + "\n"


class FullCampaign:
    def __init__(self, root: str | Path, *, force: bool = False):
        self.root = Path(root).resolve()
        self.force = force
        self.results = _supporting_output_root(self.root)
        self.audit = _supporting_output_root(self.root) / "audit"
        self.figures = _supporting_output_root(self.root) / "figures"
        self.state = CampaignState(self.audit / "campaign_state.json", root=self.root)
        self.code_fingerprint = tree_hash([self.root / "code", self.root / "config" / "campaign"], base=self.root)

    def _fingerprint(self, stage_id: str, parameters: dict | None = None, dependencies: Iterable[Path] = ()) -> str:
        return stable_json_hash(
            {
                "stage": stage_id,
                "code": self.code_fingerprint,
                "parameters": parameters or {},
                "dependencies": tree_hash(dependencies, base=self.root) if dependencies else "none",
                "version": (self.root / "VERSION").read_text(encoding="utf-8").strip(),
            }
        )

    def _stage(self, stage_id: str, outputs: list[Path], action: Callable[[], str | None], *, parameters: dict | None = None, dependencies: Iterable[Path] = ()):
        status, message = self.state.run_stage(
            stage_id,
            self._fingerprint(stage_id, parameters, dependencies),
            outputs,
            action,
            force=self.force,
        )
        print(f"[{status.upper():8}] {stage_id}: {message}")

    def run(self) -> None:
        self.results.mkdir(parents=True, exist_ok=True)
        self.audit.mkdir(parents=True, exist_ok=True)
        self.figures.mkdir(parents=True, exist_ok=True)

        env_path = self.audit / "full_campaign_environment.json"
        runtime_signature = _runtime_signature()
        self._stage(
            "00_environment",
            [env_path],
            lambda: (write_json(env_path, _environment_payload(self.root)) or "environment recorded"),
            parameters={"runtime": runtime_signature, "root": str(self.root)},
        )

        test_path = self.audit / "full_campaign_tests.txt"
        def run_tests():
            env = dict(os.environ)
            env["PYTHONPATH"] = str(self.root / "code")
            result = subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-s", str(self.root / "tests"), "-v"],
                cwd=self.root,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            test_path.write_text(result.stdout + "\n--- STDERR ---\n" + result.stderr, encoding="utf-8")
            if result.returncode != 0:
                raise RuntimeError("unit tests failed; see audit/full_campaign_tests.txt")
            return "all unit tests passed"
        self._stage(
            "01_tests",
            [test_path],
            run_tests,
            parameters={"runtime": runtime_signature},
            dependencies=[self.root / "tests"],
        )

        scenario_path = self.results / "scenario_sanity.csv"
        self._stage("02_scenario_sanity", [scenario_path], lambda: (_write_csv(scenario_path, _scenario_sanity_rows()) or "controlled scenario block completed"))

        baseline_path = self.results / "baselines.csv"
        self._stage("03_baselines", [baseline_path], lambda: (_write_csv(baseline_path, _baseline_rows()) or "baseline comparison completed"))

        ablation_path = self.results / "ablations.csv"
        self._stage("04_ablations", [ablation_path], lambda: (_write_csv(ablation_path, _ablation_rows()) or "ablation block completed"))

        sensitivity_path = self.results / "sensitivity.csv"
        self._stage("05_sensitivity", [sensitivity_path], lambda: (_write_csv(sensitivity_path, _sensitivity_rows()) or "sensitivity block completed"))

        scalability_path = self.results / "scalability.csv"
        self._stage("06_scalability", [scalability_path], lambda: (_write_csv(scalability_path, _scalability_rows()) or "scalability block completed"))

        dynamic_path = self.results / "dynamic_sequence.csv"
        self._stage("07_dynamic", [dynamic_path], lambda: (_write_csv(dynamic_path, _dynamic_rows()) or "dynamic sequence completed"))

        figure_paths = [
            self.figures / "baseline_objective.png",
            self.figures / "ablation_reference_objective.png",
            self.figures / "scalability_runtime.png",
            self.figures / "dynamic_sequence.png",
        ]
        self._stage(
            "08_figures",
            figure_paths,
            lambda: (_make_figures(self.root) and "figures generated"),
            dependencies=[baseline_path, ablation_path, scalability_path, dynamic_path],
        )

        report_path = _supporting_output_root(self.root) / "FULL_LOCAL_CAMPAIGN_REPORT.md"
        self._stage(
            "09_report",
            [report_path],
            lambda: (report_path.write_text(_report_text(self.root), encoding="utf-8") and "report generated"),
            dependencies=[baseline_path, ablation_path, sensitivity_path, scalability_path, dynamic_path],
        )

        index_path = self.audit / "full_campaign_output_index.json"
        def write_index():
            files = []
            for base in (self.results, self.figures):
                for path in sorted(base.rglob("*")):
                    if path.is_file():
                        files.append({"path": str(path.relative_to(self.root)), "size_bytes": path.stat().st_size})
            write_json(index_path, {"generated_at": _utc_now(), "files": files, "evidence_type": EVIDENCE_TYPE})
            return f"indexed {len(files)} campaign outputs"
        self._stage(
            "10_index",
            [index_path],
            write_index,
            dependencies=[
                report_path,
                scenario_path,
                baseline_path,
                ablation_path,
                sensitivity_path,
                scalability_path,
                dynamic_path,
                *figure_paths,
            ],
        )

    def status(self) -> list[dict]:
        return self.state.summary()
