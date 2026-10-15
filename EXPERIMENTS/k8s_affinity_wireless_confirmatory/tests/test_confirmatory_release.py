from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

import pytest

EXP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EXP_ROOT.parents[1]
sys.path.insert(0, str(EXP_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "implementation" / "code"))

import live_confirmatory as lc
from mape_cap_bplus.generators import generate_problem


@pytest.fixture
def reference_info():
    return {
        "control_plane": "control-plane",
        "workers": ["worker-a", "worker-b", "worker-c"],
        "rack_to_worker": {"rack-a": "worker-a", "rack-b": "worker-b", "rack-c": "worker-c"},
        "allocatable": {w: {"cpu": 4.0, "memory_mb": 3500.0} for w in ("worker-a", "worker-b", "worker-c")},
    }


def test_config_is_frozen_v11():
    assert lc.CFG["protocol_id"] == "wireless-beyond-affinity-k8s-v1.1"
    assert lc.CFG["network_emulation_mode"] == "shared-medium-proxy"
    assert lc.CFG["held_out_seeds"] == list(range(44001, 44031))
    assert lc.CFG["specificity_seeds"] == list(range(44001, 44006))
    assert lc.CFG["methods"] == ["Current", "Affinity-Bytes", "BPlus-Exact"]
    assert lc.CFG["primary_target_current_utilization"] == 1.25
    assert lc.CFG["specificity_target_current_utilization"] == 0.5


def test_resource_parsers_and_percentile():
    assert lc.parse_cpu("2500m") == 2.5
    assert lc.parse_cpu("1000000000n") == 1.0
    assert lc.parse_mem_mb("2Gi") == 2048
    assert lc.parse_mem_mb("512Mi") == 512
    assert lc.nearest_rank([1, 2, 3, 4], 0.95) == 4
    assert lc.nearest_rank([], 0.95) is None


def test_calibration_hits_primary_target_and_guard(reference_info):
    problem, cal = lc.build_problem(44001, reference_info, 1.25)
    got = lc.scenario_conflict_util(problem, problem.current_placement, lc.CFG["emulated_scenario"])
    assert math.isclose(got, 1.25, rel_tol=0, abs_tol=1e-8)
    assert lc.max_conflict_util(problem, problem.current_placement) >= got
    assert lc.CFG["emulator_min_mbit"] <= cal["min_rate_mbit"]
    assert cal["max_rate_mbit"] <= lc.CFG["emulator_max_mbit"]


def test_planning_audit_expected_discordance(reference_info):
    # Fixed regression guard for the pre-execution held-out block.
    aff = bplus = abstain = bplus_only = affinity_only = 0
    for seed in lc.CFG["held_out_seeds"]:
        problem, _ = lc.build_problem(seed, reference_info, 1.25)
        plans = lc.plan_methods(problem)
        af = bool(plans["Affinity-Bytes"]["planned_feasible"])
        bf = bool(plans["BPlus-Exact"]["planned_feasible"])
        aff += af
        bplus += bf
        abstain += bool(plans["BPlus-Exact"]["planner_abstained"])
        bplus_only += bf and not af
        affinity_only += af and not bf
    assert (aff, bplus, abstain, bplus_only, affinity_only) == (16, 28, 2, 12, 0)


def test_flow_configs_route_only_cross_worker_flows_through_medium(reference_info):
    problem, _ = lc.build_problem(44001, reference_info, 1.25)
    placement = dict(problem.current_placement)
    cfgs = lc.flow_configs(problem, placement)
    saw_cross = saw_local = False
    for source, rows in cfgs.items():
        for row in rows:
            flow = next(f for f in problem.flows if f.flow_id == row["flow_id"])
            cross = placement[flow.source_replica] != placement[flow.destination_replica]
            if cross:
                saw_cross = True
                assert row["via_shared_medium"] is True
                assert row["destination"].startswith("http://wireless-medium:8080/transmit?")
                assert "goodput_bps=" in row["destination"]
                assert "latency_ms=" in row["destination"]
            else:
                saw_local = True
                assert row["via_shared_medium"] is False
                assert row["destination"] == f"http://{flow.destination_replica}:8080/data"
    assert saw_cross and saw_local


def test_manifest_uses_recreate_and_exact_node_selector(reference_info):
    problem, _ = lc.build_problem(44001, reference_info, 1.25)
    manifest = lc.benchmark_manifest(problem, problem.current_placement, "test-token")
    docs = [json.loads(x) for x in manifest.strip().split("\n---\n")]
    deployments = [d for d in docs if d["kind"] == "Deployment"]
    assert len(deployments) == 6
    for dep in deployments:
        name = dep["metadata"]["name"]
        assert dep["spec"]["strategy"] == {"type": "Recreate"}
        assert dep["spec"]["template"]["spec"]["nodeSelector"]["kubernetes.io/hostname"] == problem.current_placement[name]


def test_medium_manifest_isolated_to_control_plane(reference_info):
    manifest = lc.wireless_medium_manifest(reference_info)
    docs = [json.loads(x) for x in manifest.strip().split("\n---\n")]
    dep = next(d for d in docs if d["kind"] == "Deployment")
    spec = dep["spec"]["template"]["spec"]
    assert spec["nodeSelector"]["kubernetes.io/hostname"] == "control-plane"
    assert any(t["key"] == "node-role.kubernetes.io/control-plane" for t in spec["tolerations"])
    assert dep["spec"]["strategy"] == {"type": "Recreate"}


def test_scheduled_denominator_prevents_backpressure_reward(reference_info):
    problem, _ = lc.build_problem(44001, reference_info, 1.25)
    placement = dict(problem.current_placement)
    configs = lc.flow_configs(problem, placement)
    duration = 10.0
    # Only one attempted/successful request is reported even though the frozen
    # schedule contains many more requests. The primary fraction must be < 1.
    first = problem.flows[0]
    pod_metrics = {
        r.replica_id: {"flows": {}} for r in problem.replicas
    }
    pod_metrics[first.source_replica]["flows"][first.flow_id] = {
        "attempted": 1,
        "success": 1,
        "errors": 0,
        "bytes_attempted": 100,
        "bytes_success": 100,
        "latencies_ms": [5.0],
    }
    run = {
        "start_epoch": 100.0,
        "stop_epoch": 100.0 + duration,
        "flow_configs": configs,
        "pod_metrics": pod_metrics,
    }
    out = lc.aggregate_metrics(problem, placement, run)
    assert out["attempt_success_fraction"] == 1.0
    assert out["scheduled_completion_fraction"] < 1.0
    assert out["expected_scheduled_requests"] > 1


def _load_medium_module():
    path = EXP_ROOT / "benchmark" / "wireless_medium.py"
    spec = importlib.util.spec_from_file_location("wireless_medium_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_shared_medium_service_time_formula(monkeypatch):
    wm = _load_medium_module()
    wm._metrics = wm._fresh_metrics()
    wm.configure({"run_id": "unit", "duty_fraction": 0.25})
    sleeps = []
    monkeypatch.setattr(wm.time, "sleep", lambda x: sleeps.append(float(x)))

    class FakeResponse:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, n=-1): return b"{}"

    monkeypatch.setattr(wm.urllib.request, "urlopen", lambda *a, **k: FakeResponse())
    code, body = wm.transmit(dst="replica-1", goodput_bps=100_000.0, latency_ms=10.0, payload=b"x" * 1250)
    # 1250 bytes = 10,000 bits; airtime = 0.1 s; duty 0.25 => 0.4 s serialization.
    assert code == 200 and body["ok"] is True
    assert math.isclose(body["modeled_airtime_ms"], 100.0, rel_tol=1e-9)
    assert math.isclose(body["serialized_service_ms"], 400.0, rel_tol=1e-9)
    assert any(math.isclose(x, 0.4, rel_tol=1e-9) for x in sleeps)
    assert any(math.isclose(x, 0.01, rel_tol=1e-9) for x in sleeps)
    snap = wm.snapshot()
    assert snap["metrics"]["requests"] == 1
    assert snap["metrics"]["success"] == 1
    assert math.isclose(snap["metrics"]["modeled_airtime_seconds"], 0.1, rel_tol=1e-9)
    assert math.isclose(snap["metrics"]["serialized_service_seconds"], 0.4, rel_tol=1e-9)


def test_local_self_test_passes():
    out = lc.local_self_test()
    assert out["passed"] is True
    assert out["shared_medium_duty_fraction"] == 0.25
