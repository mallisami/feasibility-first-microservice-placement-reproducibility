"""Tests for the locally verifiable MAPE-CAP B+ foundation."""
from __future__ import annotations

import itertools
import json
import math
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))

from mape_cap_bplus.controller import PersistentRegimeDetector, accept_relocation  # noqa: E402
from mape_cap_bplus.exact import ExactSolveError, solve_exact  # noqa: E402
from mape_cap_bplus.heuristic import robust_local_search  # noqa: E402
from mape_cap_bplus.io import InputValidationError, load_experiment  # noqa: E402
from mape_cap_bplus.models import RiskConfig  # noqa: E402
from mape_cap_bplus.objective import evaluate_placement  # noqa: E402
from mape_cap_bplus.scenarios import build_demo_problem, controlled_scenario, outage_scenario  # noqa: E402
from mape_cap_bplus.validation import validate_link_trace_document, validate_problem, validate_relocation_document  # noqa: E402


def exhaustive_best(problem, risk):
    best = float("inf")
    best_placements = []
    replicas = tuple(p.replica_id for p in problem.replicas)
    domains = [problem.allowed_nodes_for(p) for p in replicas]
    for assignment in itertools.product(*domains):
        placement = dict(zip(replicas, assignment))
        evaluation = evaluate_placement(problem, placement, risk)
        if not evaluation.feasible:
            continue
        if evaluation.total_objective < best - 1e-9:
            best = evaluation.total_objective
            best_placements = [placement]
        elif abs(evaluation.total_objective - best) <= 1e-9:
            best_placements.append(placement)
    return best, best_placements


class BPlusFoundationTests(unittest.TestCase):
    def test_versioned_json_experiment_loads(self):
        problem, risk = load_experiment(
            ROOT / "config" / "examples" / "experiment.example.json",
            ROOT / "config" / "schemas",
        )
        self.assertEqual(problem.instance_id, "bplus-controlled-demo-from-json")
        self.assertEqual(tuple(s.scenario_id for s in problem.scenarios), ("ab-preferred", "ac-preferred"))
        self.assertAlmostEqual(risk.cvar_weight, 0.5)
        placement, metadata = solve_exact(problem, risk)
        self.assertTrue(metadata["proven_optimal"])
        self.assertTrue(evaluate_placement(problem, placement, risk).feasible)

    def test_scenario_selection_is_mandatory(self):
        source = json.loads((ROOT / "config" / "examples" / "experiment.example.json").read_text())
        source.pop("scenario_ids")
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            for name in ("application.example.json", "cluster.example.json", "link_trace.example.json"):
                (temp / name).write_text((ROOT / "config" / "examples" / name).read_text())
            path = temp / "experiment.json"
            path.write_text(json.dumps(source))
            with self.assertRaises(InputValidationError):
                load_experiment(path, ROOT / "config" / "schemas")

    def test_problem_semantics_validate(self):
        valid, reasons = validate_problem(build_demo_problem())
        self.assertTrue(valid, msg="; ".join(reasons))


    def test_invalid_node_assignment_is_reported_not_crashed(self):
        problem = build_demo_problem()
        placement = dict(problem.current_placement)
        placement[next(iter(placement))] = "unknown-node"
        evaluation = evaluate_placement(problem, placement, RiskConfig())
        self.assertFalse(evaluation.feasible)
        self.assertTrue(any("unknown node" in reason for reason in evaluation.reasons))

    def test_duplicate_link_trace_scenarios_are_rejected(self):
        document = json.loads((ROOT / "config" / "examples" / "link_trace.example.json").read_text())
        document["scenarios"].append(dict(document["scenarios"][0]))
        valid, reasons = validate_link_trace_document(document)
        self.assertFalse(valid)
        self.assertTrue(any("duplicate scenario_id" in reason for reason in reasons))

    def test_programmatic_fractional_relocation_budget_is_rejected(self):
        problem = replace(build_demo_problem(), max_relocations=1.5)
        valid, reasons = validate_problem(problem)
        self.assertFalse(valid)
        self.assertIn("max_relocations must be an integer or null", reasons)

    def test_duplicate_flow_ids_are_rejected(self):
        problem = build_demo_problem()
        flows = list(problem.flows)
        flows[1] = replace(flows[1], flow_id=flows[0].flow_id)
        valid, reasons = validate_problem(replace(problem, flows=tuple(flows)))
        self.assertFalse(valid)
        self.assertIn("flow IDs must be unique", reasons)

    def test_available_zero_goodput_is_rejected_before_solver(self):
        scenario = controlled_scenario("zero", 2.0, 3.0, 4.0)
        links = dict(scenario.links)
        key = ("rack-a", "rack-b")
        links[key] = replace(links[key], goodput_bps=0.0, available=True)
        problem = build_demo_problem([replace(scenario, links=links)])
        valid, reasons = validate_problem(problem)
        self.assertFalse(valid)
        self.assertTrue(any("must have positive goodput" in reason for reason in reasons))
        with self.assertRaises(ValueError):
            solve_exact(problem, RiskConfig())

    def test_exact_matches_exhaustive_enumeration(self):
        problem = build_demo_problem([controlled_scenario("ab", 2.0, 30.0, 15.0)])
        risk = RiskConfig(cvar_weight=0.0, relocation_weight=0.0)
        _, metadata = solve_exact(problem, risk)
        best, _ = exhaustive_best(problem, risk)
        self.assertAlmostEqual(metadata["placement_evaluation"]["total_objective"], best, places=7)

    def test_robust_exact_matches_exhaustive_enumeration(self):
        problem = build_demo_problem([
            controlled_scenario("s1", 2.0, 30.0, 15.0, weight=0.7),
            controlled_scenario("s2", 15.0, 2.0, 15.0, weight=0.3),
        ])
        risk = RiskConfig(cvar_quantile=0.8, cvar_weight=0.75, relocation_weight=1.0)
        _, metadata = solve_exact(problem, risk)
        best, _ = exhaustive_best(problem, risk)
        self.assertAlmostEqual(metadata["placement_evaluation"]["total_objective"], best, places=7)

    def test_relocation_weight_changes_solution(self):
        problem = build_demo_problem([controlled_scenario("ac", 15.0, 2.0, 15.0)])
        free, _ = solve_exact(problem, RiskConfig(cvar_weight=0.0, relocation_weight=0.0))
        costly, _ = solve_exact(problem, RiskConfig(cvar_weight=0.0, relocation_weight=100.0))
        self.assertNotEqual(free, costly)
        self.assertEqual(costly, dict(problem.current_placement))

    def test_cvar_weight_can_change_solution(self):
        problem = build_demo_problem([
            controlled_scenario("common", 2.0, 2.0, 2.0, weight=0.8),
            controlled_scenario("tail", 2.0, 10.0, 2.0, weight=0.2),
        ])
        expected, _ = solve_exact(problem, RiskConfig(cvar_weight=0.0, relocation_weight=0.0, slo_slack_weight=0.0))
        risk_averse, _ = solve_exact(problem, RiskConfig(cvar_quantile=0.8, cvar_weight=2.0, relocation_weight=0.0, slo_slack_weight=0.0))
        self.assertNotEqual(expected, risk_averse)

    def test_slo_slack_weight_can_change_solution(self):
        problem = build_demo_problem([controlled_scenario("slo", 2.0, 30.0, 15.0)])
        flows = list(problem.flows)
        flows[0] = replace(flows[0], max_expected_latency_ms=0.2)
        problem = replace(problem, flows=tuple(flows))
        unpenalized, _ = solve_exact(
            problem, RiskConfig(cvar_weight=0.0, relocation_weight=0.0, slo_slack_weight=0.0)
        )
        penalized, _ = solve_exact(
            problem, RiskConfig(cvar_weight=0.0, relocation_weight=0.0, slo_slack_weight=10_000.0)
        )
        self.assertNotEqual(unpenalized, penalized)
        self.assertLess(
            evaluate_placement(problem, penalized, RiskConfig(cvar_weight=0.0, relocation_weight=0.0, slo_slack_weight=10_000.0)).slo_slack,
            evaluate_placement(problem, unpenalized, RiskConfig(cvar_weight=0.0, relocation_weight=0.0, slo_slack_weight=10_000.0)).slo_slack,
        )

    def test_persistent_states_change_and_improve_preferred_placement(self):
        risk = RiskConfig(cvar_weight=0.0, relocation_weight=0.0)
        problem_ab = build_demo_problem([controlled_scenario("ab", 2.0, 30.0, 15.0)])
        problem_ac = build_demo_problem([controlled_scenario("ac", 15.0, 2.0, 15.0)])
        placement_ab, _ = solve_exact(problem_ab, risk)
        placement_ac, _ = solve_exact(problem_ac, risk)
        self.assertNotEqual(placement_ab, placement_ac)
        self.assertLessEqual(
            evaluate_placement(problem_ab, placement_ab, risk).total_objective,
            evaluate_placement(problem_ab, placement_ac, risk).total_objective,
        )
        self.assertLessEqual(
            evaluate_placement(problem_ac, placement_ac, risk).total_objective,
            evaluate_placement(problem_ac, placement_ab, risk).total_objective,
        )

    def test_link_degradation_is_monotone_for_fixed_placement(self):
        risk = RiskConfig(cvar_weight=0.0, relocation_weight=0.0)
        good = build_demo_problem([controlled_scenario("good", 2.0, 2.0, 2.0)])
        degraded = build_demo_problem([controlled_scenario("bad", 20.0, 20.0, 20.0)])
        good_eval = evaluate_placement(good, good.current_placement, risk)
        bad_eval = evaluate_placement(degraded, good.current_placement, risk)
        self.assertTrue(good_eval.feasible and bad_eval.feasible)
        self.assertGreaterEqual(bad_eval.expected_delay_cost, good_eval.expected_delay_cost)

    def test_temporary_change_does_not_trigger_replan(self):
        decision = PersistentRegimeDetector(minimum_persistent_windows=3).evaluate(
            ["baseline", "temporary", "baseline"], "baseline", 10.0, 20.0
        )
        self.assertFalse(decision.should_replan)

    def test_persistent_long_horizon_change_triggers_replan(self):
        decision = PersistentRegimeDetector(minimum_persistent_windows=3).evaluate(
            ["degraded", "degraded", "degraded"], "baseline", 120.0, 20.0
        )
        self.assertTrue(decision.should_replan)

    def test_controller_rejects_negative_costs(self):
        with self.assertRaises(ValueError):
            accept_relocation(100.0, 50.0, -1.0, 0.0)

    def test_conservative_net_benefit_gate(self):
        accepted, benefit, _ = accept_relocation(1000, 700, 100, 50)
        self.assertTrue(accepted)
        self.assertEqual(benefit, 150)
        rejected, _, _ = accept_relocation(1000, 900, 75, 50)
        self.assertFalse(rejected)

    def test_conflict_budget_changes_feasibility_and_exact_repairs_it(self):
        tight = controlled_scenario("tight", 4.0, 4.0, 4.0, goodput_bps=200_000_000.0, budget_seconds=0.12)
        problem = build_demo_problem([tight])
        risk = RiskConfig(cvar_weight=0.0, relocation_weight=0.0)
        current_eval = evaluate_placement(problem, problem.current_placement, risk)
        self.assertFalse(current_eval.feasible)
        placement, metadata = solve_exact(problem, risk)
        self.assertTrue(metadata["placement_evaluation"]["feasible"])
        self.assertTrue(evaluate_placement(problem, placement, risk).feasible)

    def test_heuristic_repairs_network_infeasible_start(self):
        tight = controlled_scenario("tight", 4.0, 4.0, 4.0, goodput_bps=200_000_000.0, budget_seconds=0.12)
        problem = build_demo_problem([tight])
        placement, metadata = robust_local_search(problem, RiskConfig(cvar_weight=0.0, relocation_weight=0.0))
        self.assertTrue(metadata["evaluation"]["feasible"])
        self.assertTrue(evaluate_placement(problem, placement, RiskConfig()).feasible)

    def test_outage_without_fallback_prohibits_failed_rack_pair(self):
        outage = outage_scenario("outage", failed_pairs=(("rack-a", "rack-c"), ("rack-c", "rack-a")), fallback=False)
        problem = build_demo_problem([outage])
        placement, metadata = solve_exact(problem, RiskConfig(cvar_weight=0.0, relocation_weight=0.0))
        self.assertTrue(metadata["placement_evaluation"]["feasible"])
        self.assertNotEqual(placement["orders-0"], "node-c")

    def test_wired_fallback_is_available_but_costly(self):
        fallback = outage_scenario("fallback", failed_pairs=(("rack-a", "rack-c"), ("rack-c", "rack-a")), fallback=True)
        problem = build_demo_problem([fallback])
        evaluation = evaluate_placement(problem, problem.current_placement, RiskConfig(cvar_weight=0.0, relocation_weight=0.0))
        self.assertTrue(evaluation.feasible)
        self.assertGreater(evaluation.expected_delay_cost, 0.0)

    def test_relocation_timestamp_semantics(self):
        document = json.loads((ROOT / "config" / "examples" / "relocation_cost.example.json").read_text())
        valid, reasons = validate_relocation_document(document)
        self.assertTrue(valid, msg="; ".join(reasons))
        document["records"][0]["ready_at"] = "2026-08-06T23:59:59Z"
        valid, reasons = validate_relocation_document(document)
        self.assertFalse(valid)
        self.assertTrue(any("precedes" in reason for reason in reasons))


if __name__ == "__main__":
    unittest.main(verbosity=2)
