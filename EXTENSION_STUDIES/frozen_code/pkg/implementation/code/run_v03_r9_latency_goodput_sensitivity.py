#!/usr/bin/env python3
"""Crossed latency x goodput robustness sweep (VALIDATION_PROTOCOL Stage G).

For each of the eight frozen effective wireless states used by R6
(RESULTS/calibration/external/ns3_simulation_backed_traces.csv), independently
cross low/nominal/high latency and goodput perturbations around the frozen
state (a 3x3 grid), holding outage (link availability) and airtime semantics
(conflict groups / conflict budgets) fixed, and record whether the B+
placement/relocation decision is stable across the crossed grid.

This experiment was listed as an explicit open item in
PAPER/SCIENTIFIC_COMPLETION_CHECKLIST.md ("execute crossed latency x goodput
robustness testing for the effective wireless-state abstraction") and has no
prior driver script; R5/S-E3 characterize simulator mechanisms but do not
perform this crossed sensitivity sweep.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT / "code"))

from mape_cap_bplus.exact import ExactSolveError, solve_exact
from mape_cap_bplus.models import LinkState, RiskConfig, Scenario
from mape_cap_bplus.objective import evaluate_placement
from mape_cap_bplus.r6_problem import build_instance
from mape_cap_bplus.v03_evidence import atomic_write_csv, atomic_write_json, sha256, utc_now, write_manifest

SOURCE_PATH = REPO / "RESULTS" / "calibration" / "external" / "ns3_simulation_backed_traces.csv"

# Low/nominal/high perturbation levels, applied independently to latency and
# goodput around each frozen effective state. Only available links are
# perturbed; outage (available=False, goodput=0) and airtime semantics
# (conflict_group / conflict_budgets_seconds) are preserved unchanged.
LATENCY_LEVELS = {"low": 0.85, "nominal": 1.0, "high": 1.15}
GOODPUT_LEVELS = {"low": 0.85, "nominal": 1.0, "high": 1.15}

METHODS = (
    ("ExpectedValue", RiskConfig(cvar_weight=0.0, relocation_weight=1.0, slo_slack_weight=1000.0)),
    ("BPlus-CVaR-0.90", RiskConfig(cvar_quantile=0.90, cvar_weight=1.5, relocation_weight=1.0, slo_slack_weight=1000.0)),
)


def load_source(path: Path) -> list[dict]:
    groups: dict[str, dict] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            group = groups.setdefault(row["scenario_id"], {
                "scenario_id": row["scenario_id"], "weight": float(row["weight"]), "links": [],
                "conflict_budgets_seconds": {}, "regime_duration_seconds": float(row["regime_duration_seconds"]),
            })
            conflict = row.get("conflict_group") or None
            if conflict and row.get("budget_seconds"):
                group["conflict_budgets_seconds"][conflict] = float(row["budget_seconds"])
            group["links"].append({
                "source_rack": row["source_rack"], "destination_rack": row["destination_rack"],
                "latency_ms": float(row["latency_ms"]), "goodput_bps": float(row["goodput_bps"]),
                "available": row["available"].strip().lower() == "true", "path_id": row["path_id"],
                "conflict_group": conflict, "provenance": row["provenance"],
            })
    if len(groups) < 8:
        raise ValueError("expected at least eight distinct frozen effective wireless states")
    return list(groups.values())


def perturbed_scenario(item: dict, latency_level: str, goodput_level: str) -> Scenario:
    latency_factor = LATENCY_LEVELS[latency_level]
    goodput_factor = GOODPUT_LEVELS[goodput_level]
    links = {}
    for raw in item["links"]:
        if raw["available"]:
            link = LinkState(
                raw["source_rack"], raw["destination_rack"], raw["latency_ms"] * latency_factor,
                raw["goodput_bps"] * goodput_factor, True, raw["path_id"], raw["conflict_group"],
                raw["provenance"] + f"+crossed-L{latency_level}-G{goodput_level}",
            )
        else:
            # Preserve outage semantics: an unavailable link stays unavailable
            # with zero goodput regardless of the (L, G) perturbation level.
            link = LinkState(
                raw["source_rack"], raw["destination_rack"], raw["latency_ms"], 0.0, False,
                raw["path_id"], raw["conflict_group"], raw["provenance"],
            )
        links[(link.source_rack, link.destination_rack)] = link
    return Scenario(
        scenario_id=f"{item['scenario_id']}:L{latency_level}:G{goodput_level}", weight=1.0, links=links,
        # Airtime semantics (per-conflict-group budgets) are held fixed across the grid.
        conflict_budgets_seconds=dict(item["conflict_budgets_seconds"]),
        regime_duration_seconds=float(item["regime_duration_seconds"]),
        metadata={"source_trace_id": item["scenario_id"], "latency_level": latency_level, "goodput_level": goodput_level},
    )


def evaluate_grid_point(item: dict, latency_level: str, goodput_level: str, method: str, risk: RiskConfig, time_limit: float) -> dict:
    scenario = perturbed_scenario(item, latency_level, goodput_level)
    problem = build_instance((scenario,))
    started = time.perf_counter()
    try:
        placement, metadata = solve_exact(problem, risk, time_limit)
        evaluation = evaluate_placement(problem, placement, risk)
        relocations = sum(placement[rid] != node for rid, node in problem.current_placement.items())
        return {
            "status": "complete", "runtime_seconds": time.perf_counter() - started,
            "feasible": evaluation.feasible, "total_objective": evaluation.total_objective,
            "expected_delay_cost": evaluation.expected_delay_cost, "cvar_delay_cost": evaluation.cvar_delay_cost,
            "relocation_cost": evaluation.relocation_cost, "slo_slack": evaluation.slo_slack,
            "relocations": relocations, "would_relocate": relocations > 0,
            "placement": json.dumps(placement, sort_keys=True), "solver_metadata": json.dumps(metadata, sort_keys=True),
        }
    except ExactSolveError as exc:
        return {
            "status": "infeasible", "runtime_seconds": time.perf_counter() - started,
            "feasible": False, "total_objective": None, "expected_delay_cost": None, "cvar_delay_cost": None,
            "relocation_cost": None, "slo_slack": None, "relocations": None, "would_relocate": None,
            "placement": "", "solver_metadata": "", "error": str(exc),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_root", type=Path)
    parser.add_argument("--time-limit", type=float, default=30.0)
    args = parser.parse_args()
    run_root = args.run_root.resolve()
    raw_root = run_root / "raw" / "phase-9-latency-goodput-sensitivity"
    output = run_root / "raw" / "phase-9-latency-goodput-index.csv"
    summary_output = run_root / "derived" / "phase-9-latency-goodput-stability.json"
    checkpoint = run_root / "checkpoints" / "phase-9-latency-goodput.json"
    if output.exists():
        raise FileExistsError("final latency x goodput sensitivity index exists; refusing to overwrite it")
    raw_root.mkdir(parents=True, exist_ok=True)
    (run_root / "derived").mkdir(parents=True, exist_ok=True)

    source = load_source(SOURCE_PATH)
    rows = []
    total = len(source) * len(LATENCY_LEVELS) * len(GOODPUT_LEVELS) * len(METHODS)
    for item in source:
        for method, risk in METHODS:
            nominal = evaluate_grid_point(item, "nominal", "nominal", method, risk, args.time_limit)
            for latency_level in LATENCY_LEVELS:
                for goodput_level in GOODPUT_LEVELS:
                    run_id = f"{item['scenario_id']}:{method}:L{latency_level}:G{goodput_level}"
                    result = nominal if (latency_level, goodput_level) == ("nominal", "nominal") else \
                        evaluate_grid_point(item, latency_level, goodput_level, method, risk, args.time_limit)
                    row = {
                        "run_id": run_id, "source_trace_id": item["scenario_id"], "method": method,
                        "latency_level": latency_level, "goodput_level": goodput_level,
                        "latency_factor": LATENCY_LEVELS[latency_level], "goodput_factor": GOODPUT_LEVELS[goodput_level],
                        "placement_matches_nominal": (result.get("placement") == nominal.get("placement")) if result["status"] == "complete" and nominal["status"] == "complete" else None,
                        "feasible_matches_nominal": result["feasible"] == nominal["feasible"],
                        "would_relocate_matches_nominal": result.get("would_relocate") == nominal.get("would_relocate"),
                        **result,
                    }
                    rows.append(row)
                    print(f"[{len(rows)}/{total}] {run_id} {result['status']}", flush=True)
        atomic_write_json(checkpoint, {"updated_utc": utc_now(), "rows": rows, "row_count": len(rows)})

    atomic_write_csv(output, rows)

    # Stability summary: for each (source_trace_id, method), fraction of the
    # 9 grid points whose placement / feasibility / relocate-decision match
    # the nominal (1.0, 1.0) grid point.
    stability: dict[str, dict] = {}
    for item in source:
        for method, _ in METHODS:
            key = f"{item['scenario_id']}:{method}"
            matched = [r for r in rows if r["source_trace_id"] == item["scenario_id"] and r["method"] == method]
            n = len(matched)
            stability[key] = {
                "source_trace_id": item["scenario_id"], "method": method, "grid_points": n,
                "placement_stability_rate": sum(1 for r in matched if r["placement_matches_nominal"]) / n if n else None,
                "feasibility_stability_rate": sum(1 for r in matched if r["feasible_matches_nominal"]) / n if n else None,
                "relocate_decision_stability_rate": sum(1 for r in matched if r["would_relocate_matches_nominal"]) / n if n else None,
            }
    overall = {
        "generated_utc": utc_now(), "source_path": str(SOURCE_PATH), "source_sha256": sha256(SOURCE_PATH),
        "latency_levels": LATENCY_LEVELS, "goodput_levels": GOODPUT_LEVELS,
        "per_state_per_method": stability,
        "overall_placement_stability_rate": sum(1 for r in rows if r["placement_matches_nominal"]) / len(rows),
        "overall_feasibility_stability_rate": sum(1 for r in rows if r["feasible_matches_nominal"]) / len(rows),
        "overall_relocate_decision_stability_rate": sum(1 for r in rows if r["would_relocate_matches_nominal"]) / len(rows),
        "row_count": len(rows),
    }
    atomic_write_json(summary_output, overall)
    atomic_write_json(checkpoint, {"completed_utc": utc_now(), "row_count": len(rows)})

    ledger_path = run_root / "checkpoints" / "ledger.json"
    if ledger_path.exists():
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        ledger.setdefault("phases", {})["phase-9-latency-goodput-sensitivity"] = "completed"
        atomic_write_json(ledger_path, ledger)
    write_manifest(run_root, run_root / "manifests" / "run.sha256")
    print(f"overall placement stability rate: {overall['overall_placement_stability_rate']:.3f}")
    print(f"overall relocate-decision stability rate: {overall['overall_relocate_decision_stability_rate']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
