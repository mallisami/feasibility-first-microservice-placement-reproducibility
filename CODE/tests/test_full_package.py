from __future__ import annotations

from dataclasses import replace
import json
import subprocess
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "code"))

from mape_cap_bplus.campaign import _runtime_signature, _sensitivity_rows
from mape_cap_bplus.checkpoints import CampaignState, stable_json_hash
from mape_cap_bplus.generators import generate_problem, homogenize_network, without_conflicts
from mape_cap_bplus.lns import robust_lns
from mape_cap_bplus.models import ReplicaSpec, RiskConfig
from mape_cap_bplus.objective import evaluate_placement
from mape_cap_bplus.workload import ServiceTraffic, expand_service_traffic


class FullPackageTests(unittest.TestCase):
    def test_generated_problem_is_feasible(self):
        problem = generate_problem(replica_count=8, rack_count=3, nodes_per_rack=2, seed=7)
        evaluation = evaluate_placement(problem, problem.current_placement, RiskConfig())
        self.assertTrue(evaluation.feasible, msg="; ".join(evaluation.reasons))

    def test_lns_returns_feasible_solution(self):
        problem = generate_problem(replica_count=10, rack_count=3, nodes_per_rack=2, seed=3)
        placement, metadata = robust_lns(problem, RiskConfig(cvar_weight=0.5), seed=3, iterations=5, time_limit_seconds=5)
        self.assertTrue(metadata["evaluation"]["feasible"])
        self.assertTrue(evaluate_placement(problem, placement, RiskConfig(cvar_weight=0.5)).feasible)

    def test_homogeneous_and_no_conflict_transforms_validate(self):
        problem = generate_problem(replica_count=6, seed=2, nodes_per_rack=2)
        for transformed in (homogenize_network(problem), without_conflicts(problem)):
            self.assertTrue(evaluate_placement(transformed, transformed.current_placement, RiskConfig()).feasible)

    def test_service_routing_expands_and_conserves_traffic(self):
        replicas = (
            ReplicaSpec("a-0", "a", 1, 128),
            ReplicaSpec("a-1", "a", 1, 128),
            ReplicaSpec("b-0", "b", 1, 128),
            ReplicaSpec("b-1", "b", 1, 128),
        )
        traffic = (ServiceTraffic("a-b", "a", "b", 100.0, 8000.0),)
        flows = expand_service_traffic(replicas, traffic)
        self.assertEqual(len(flows), 4)
        self.assertAlmostEqual(sum(flow.requests_per_window for flow in flows), 100.0)
        self.assertAlmostEqual(sum(flow.bits_per_window for flow in flows), 8000.0)

    def test_service_routing_rejects_unknown_replica(self):
        replicas = (ReplicaSpec("a-0", "a", 1, 128), ReplicaSpec("b-0", "b", 1, 128))
        traffic = (ServiceTraffic("a-b", "a", "b", 1.0, 8.0),)
        with self.assertRaises(ValueError):
            expand_service_traffic(replicas, traffic, {"a": {"unknown": 1.0}})


    def test_sensitivity_fixtures_change_decisions_or_feasibility(self):
        rows = _sensitivity_rows()
        by_block = {}
        for row in rows:
            by_block.setdefault(row["sensitivity"], []).append(row)
        self.assertGreater(len({json.dumps(row.get("placement"), sort_keys=True) for row in by_block["cvar-weight"]}), 1)
        self.assertGreater(len({json.dumps(row.get("placement"), sort_keys=True) for row in by_block["relocation-weight"]}), 1)
        conflict = by_block["conflict-budget"]
        self.assertTrue(any(row.get("status") == "infeasible" for row in conflict))
        self.assertGreater(len({json.dumps(row.get("placement"), sort_keys=True) for row in conflict if row.get("placement")}), 1)

    def test_simulator_converter_rejects_ambiguous_boolean(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source = directory / "bad.csv"
            source.write_text(
                "scenario_id,weight,source_rack,destination_rack,latency_ms,goodput_bps,available,path_id,conflict_group,budget_seconds,regime_duration_seconds,provenance\n"
                "s,1,r1,r2,1,1000000,maybe,p,g,1,60,test\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(ROOT / "code" / "convert_simulator_trace.py"), "--input", str(source), "--output", str(directory / "out.json")],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("available", result.stderr + result.stdout)

    def test_kubernetes_pilot_uses_hostname_antiaffinity_without_zone_dependency(self):
        manifest = (ROOT / "kubernetes" / "manifests" / "pilot-echo.yaml").read_text(encoding="utf-8")
        self.assertIn("requiredDuringSchedulingIgnoredDuringExecution", manifest)
        self.assertIn("kubernetes.io/hostname", manifest)
        self.assertNotIn("topology.kubernetes.io/zone", manifest)
        relocation_manifest = (ROOT / "kubernetes" / "manifests" / "relocation-echo.yaml").read_text(encoding="utf-8")
        self.assertIn("kind: Service", relocation_manifest)
        self.assertIn("name: relocation-echo", relocation_manifest)

    def test_timeseries_replay_rejects_nonzero_initial_offset_and_duplicates(self):
        import importlib.util
        script = ROOT / "kubernetes" / "scripts" / "tc_timeseries_replay.py"
        spec = importlib.util.spec_from_file_location("tc_timeseries_replay_test", script)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            nonzero = directory / "nonzero.csv"
            nonzero.write_text(
                "offset_seconds,destination_cidr,delay_ms,rate_mbit,loss_percent\n"
                "1,10.0.0.2/32,5,100,0\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "must start at offset 0"):
                module.load_rows(nonzero)
            duplicate = directory / "duplicate.csv"
            duplicate.write_text(
                "offset_seconds,destination_cidr,delay_ms,rate_mbit,loss_percent\n"
                "0,10.0.0.2/32,5,100,0\n"
                "0,10.0.0.2/32,6,90,1\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "duplicate schedule"):
                module.load_rows(duplicate)

    def test_network_replay_rejects_nonfinite_parameters(self):
        static_script = ROOT / "kubernetes" / "scripts" / "tc_replay.py"
        result = subprocess.run(
            [sys.executable, str(static_script), "--interface", "eth0", "--destination", "10.0.0.2",
             "--delay-ms", "nan", "--rate-mbit", "100", "--loss-pct", "0"],
            text=True, capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("finite", result.stderr + result.stdout)


    def test_checkpoint_skips_only_when_hashes_match(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = CampaignState(root / "state.json")
            output = root / "output.txt"
            calls = {"count": 0}
            def action():
                calls["count"] += 1
                output.write_text("valid", encoding="utf-8")
                return "done"
            fingerprint = stable_json_hash({"a": 1})
            status, _ = state.run_stage("s", fingerprint, [output], action)
            self.assertEqual(status, "complete")
            status, _ = state.run_stage("s", fingerprint, [output], action)
            self.assertEqual(status, "skipped")
            self.assertEqual(calls["count"], 1)
            output.write_text("modified", encoding="utf-8")
            status, _ = state.run_stage("s", fingerprint, [output], action)
            self.assertEqual(status, "complete")
            self.assertEqual(calls["count"], 2)

    def test_runtime_signature_contains_portable_environment_fields(self):
        signature = _runtime_signature()
        self.assertIn("python", signature)
        self.assertIn("platform", signature)
        self.assertIn("packages", signature)
        self.assertIn("scipy", signature["packages"])

    def test_packaged_random_exact_audit_is_reproducible_on_small_sample(self):
        import importlib.util
        script = ROOT / "code" / "run_randomized_exact_audit.py"
        spec = importlib.util.spec_from_file_location("random_exact_audit_test", script)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        payload = module.run_audit(5, 20260807)
        self.assertEqual(payload["matches"], 5)
        self.assertEqual(payload["mismatches"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
