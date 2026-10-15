"""Run the full sequential R1 Online Boutique placement campaign."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
try:
    import msvcrt  # type: ignore
except ImportError:  # POSIX/Linux
    msvcrt = None
    import fcntl
import random
import re
import statistics
import subprocess
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mape_cap_bplus.exact import ExactSolveError, solve_exact
from mape_cap_bplus.generators import homogenize_network, single_scenario
from mape_cap_bplus.lns import robust_lns
from mape_cap_bplus.models import FlowSpec, LinkState, NodeSpec, ProblemInstance, RelocationCost, ReplicaSpec, RiskConfig, Scenario
from mape_cap_bplus.objective import evaluate_placement
from mape_cap_bplus.v03_evidence import atomic_write_json, atomic_write_text, utc_now
from run_v03_r2 import NS, assert_healthy, frontend_metrics, kubectl, kubectl_json, stats_snapshot, summarize_resources

SERVICES = [
    "adservice", "cartservice", "checkoutservice", "currencyservice", "emailservice",
    "frontend", "paymentservice", "productcatalogservice", "recommendationservice",
    "redis-cart", "shippingservice",
]
def _detect_workers() -> list[str]:
    raw = os.environ.get("MCB_R1_WORKERS", "").strip()
    if raw:
        workers = [value.strip() for value in raw.split(",") if value.strip()]
        if len(workers) == 3:
            return workers
    # Auto-detect from active cluster if available
    try:
        nodes_out = kubectl("get", "nodes", "-o", "jsonpath={.items[*].metadata.name}")
        nodes = nodes_out.split()
        detected = sorted([n for n in nodes if not any(cp in n for cp in ("control-plane", "master"))])
        if len(detected) == 3:
            return detected
    except Exception:
        pass
    return ["mape-cap-bplus-worker", "mape-cap-bplus-worker2", "mape-cap-bplus-worker3"]


WORKERS = _detect_workers()
if len(WORKERS) != 3:
    raise RuntimeError("MCB_R1_WORKERS must contain exactly three worker names")
RACKS = {worker: f"rack-{letter}" for worker, letter in zip(WORKERS, "abc")}
ROLLOUT_TIMEOUT_SECONDS = 420
CONDITIONS = [
    "stable", "persistent-degradation", "partial-blockage", "conflict-dense",
    "outage-with-fallback", "recovery", "bursty", "hotspot", "structural-workload-change",
    "confirmatory-healthy", "confirmatory-temporary-moderate", "confirmatory-persistent-severe",
]
METHODS = ["Current", "TrafficOnly-MAPE-CAP", "DeterministicNetworkAware", "BPlus-LNS", "BPlus-Exact"]
REQUESTS = {
    "adservice": (0.20, 180), "cartservice": (0.15, 128), "checkoutservice": (0.10, 96),
    "currencyservice": (0.10, 96), "emailservice": (0.10, 96), "frontend": (0.20, 192),
    "paymentservice": (0.10, 96), "productcatalogservice": (0.15, 128),
    "recommendationservice": (0.15, 128), "redis-cart": (0.10, 128),
    "shippingservice": (0.10, 96),
}


def invalidated_result_paths(run_root: Path) -> set[str]:
    registry = run_root / "checkpoints" / "r1-invalidated-attempts.json"
    if not registry.exists():
        return set()
    payload = json.loads(registry.read_text(encoding="utf-8"))
    return set(payload.get("invalidated_result_paths", []))


def accepted_cell_result(
    run_root: Path,
    condition: str,
    replicate: int,
    method: str,
    duration: int,
    min_completed_requests: int = 1,
) -> dict[str, Any] | None:
    cell_base = run_root / "raw" / "r1" / condition / f"replicate-{replicate:02d}" / method
    invalidated = invalidated_result_paths(run_root)
    prior_paths = (
        ([cell_base / "result.json"] if (cell_base / "result.json").exists() else [])
        + sorted(cell_base.glob("attempt-*/result.json"))
    )
    for prior_path in prior_paths:
        if prior_path.relative_to(run_root).as_posix() in invalidated:
            continue
        prior = json.loads(prior_path.read_text(encoding="utf-8"))
        if (
            prior.get("accepted")
            and prior.get("acceptance_gate_version") == 2
            and prior.get("duration_seconds") == duration
            and int(prior.get("application", {}).get("successes", 0)) >= min_completed_requests
        ):
            return prior
    return None


class CampaignLock:
    """Process-lifetime cross-platform lock enforcing one sequential R1 worker."""

    def __init__(self, run_root: Path) -> None:
        self.path = run_root / "checkpoints" / "r1-worker.lock"
        self.handle = None

    def __enter__(self) -> "CampaignLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        self.handle.seek(0, 2)
        if self.handle.tell() == 0:
            self.handle.write(b"\0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            if msvcrt is not None:
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.handle.close()
            self.handle = None
            raise RuntimeError("another R1 campaign worker already owns the sequential lock") from exc
        atomic_write_json(
            self.path.with_suffix(".status.json"),
            {"status": "running", "acquired_utc": utc_now()},
        )
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.handle is not None:
            self.handle.seek(0)
            if msvcrt is not None:
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            self.handle.close()
        atomic_write_json(
            self.path.with_suffix(".status.json"),
            {"status": "stopped", "released_utc": utc_now(), "clean_exit": exc is None},
        )


def run(args: list[str], *, check: bool = True, timeout: int = 180) -> str:
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(args)}\n{result.stderr[-2000:]}")
    return result.stdout


def docker(node: str, *args: str, check: bool = True) -> str:
    return run(["docker", "exec", node, *args], check=check, timeout=30)


def clear_network() -> None:
    for worker in WORKERS:
        docker(worker, "tc", "qdisc", "del", "dev", "eth0", "root", check=False)


def assert_runtime_access() -> None:
    """Fail before campaign work if Kubernetes or Docker shaping is unavailable."""
    kubectl("get", "namespace", NS)
    for worker in WORKERS:
        output = docker(worker, "tc", "qdisc", "show", "dev", "eth0")
        if not isinstance(output, str):
            raise RuntimeError(f"invalid tc preflight response from {worker}")


def all_egress(delay_ms: float, rate_mbit: float, loss_pct: float) -> None:
    for worker in WORKERS:
        docker(
            worker, "tc", "qdisc", "replace", "dev", "eth0", "root", "netem",
            "delay", f"{delay_ms}ms", "rate", f"{rate_mbit}mbit", "loss", f"{loss_pct}%",
        )


def filtered(source: str, destination: str, delay_ms: float, rate_mbit: float, loss_pct: float) -> None:
    node = kubectl_json("get", "node", destination)
    destination_ip = next(a["address"] for a in node["status"]["addresses"] if a["type"] == "InternalIP")
    docker(source, "tc", "qdisc", "replace", "dev", "eth0", "root", "handle", "1:", "prio", "bands", "3")
    docker(
        source, "tc", "qdisc", "replace", "dev", "eth0", "parent", "1:3", "handle", "30:",
        "netem", "delay", f"{delay_ms}ms", "rate", f"{rate_mbit}mbit", "loss", f"{loss_pct}%",
    )
    docker(
        source, "tc", "filter", "replace", "dev", "eth0", "protocol", "ip", "parent", "1:0",
        "prio", "3", "u32", "match", "ip", "dst", f"{destination_ip}/32", "flowid", "1:3",
    )


def configure_condition(condition: str, replicate: int) -> dict[str, Any]:
    clear_network()
    source = WORKERS[replicate % len(WORKERS)]
    destination = WORKERS[(replicate + 1) % len(WORKERS)]
    event = {"condition": condition, "source_node": source, "destination_node": destination, "applied_utc": utc_now()}
    if condition == "confirmatory-persistent-severe":
        all_egress(40, 20, 2.0)
        event["initial"] = {"delay_ms": 40, "rate_mbit": 20, "loss_pct": 2.0, "scope": "all-worker-egress"}
    elif condition == "confirmatory-temporary-moderate":
        all_egress(20, 100, 0.5)
        event["initial"] = {"delay_ms": 20, "rate_mbit": 100, "loss_pct": 0.5, "scope": "all-worker-egress", "phase": "degraded"}
        event["scheduled"] = {"at_fraction": 0.5, "phase": "clear-to-stable"}
    elif condition == "persistent-degradation":
        all_egress(25, 100, 1.0)
        event["initial"] = {"delay_ms": 25, "rate_mbit": 100, "loss_pct": 1.0, "scope": "all-worker-egress"}
    elif condition == "partial-blockage":
        filtered(source, destination, 80, 20, 5.0)
        event["initial"] = {"delay_ms": 80, "rate_mbit": 20, "loss_pct": 5.0, "scope": "one-directed-worker-path"}
    elif condition == "conflict-dense":
        all_egress(15, 30, 0.5)
        event["initial"] = {"delay_ms": 15, "rate_mbit": 30, "loss_pct": 0.5, "scope": "all-worker-egress"}
    elif condition == "outage-with-fallback":
        filtered(source, destination, 0, 1000, 100.0)
        event["initial"] = {"loss_pct": 100.0, "scope": "one-directed-worker-path", "phase": "outage"}
        event["scheduled"] = {"after_seconds": 5, "delay_ms": 8, "rate_mbit": 50, "loss_pct": 0.0, "phase": "fallback"}
    elif condition == "recovery":
        all_egress(35, 50, 2.0)
        event["initial"] = {"delay_ms": 35, "rate_mbit": 50, "loss_pct": 2.0, "scope": "all-worker-egress", "phase": "degraded"}
        event["scheduled"] = {"at_fraction": 0.5, "phase": "clear-to-stable"}
    else:
        event["initial"] = {"delay_ms": 0, "rate_mbit": 1000, "loss_pct": 0.0, "scope": "stable"}
    return event


def stable_index(text: str) -> int:
    return int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)


def initial_placement(condition: str, replicate: int) -> dict[str, str]:
    return {
        service: WORKERS[(stable_index(service) + replicate + stable_index(condition)) % len(WORKERS)]
        for service in SERVICES
    }


def r2_traffic(run_root: Path) -> dict[tuple[str, str], tuple[float, float]]:
    results = []
    for path in sorted((run_root / "raw" / "r2").glob("replicate-*-telemetry_on_controller_off/result.json")):
        results.append(json.loads(path.read_text(encoding="utf-8")))
    total_seconds = sum(float(row["duration_seconds"]) for row in results)
    requests: dict[tuple[str, str], float] = {}
    transport_bytes: dict[tuple[str, str], float] = {}
    for row in results:
        for trace in row["native_trace_windows"]:
            pair = (trace["source"], trace["destination"])
            requests[pair] = requests.get(pair, 0.0) + float(trace["requests"])
        for flow in row["transport_flow_windows"]:
            pair = (flow["source"], flow["destination"])
            transport_bytes[pair] = transport_bytes.get(pair, 0.0) + float(flow["request_bytes"] + flow["response_bytes"])
    pairs = set(requests) | set(transport_bytes)
    return {
        pair: (requests.get(pair, 0.0) / total_seconds, transport_bytes.get(pair, 0.0) / total_seconds)
        for pair in pairs if pair[0] in SERVICES and pair[1] in SERVICES
    }


def scenario(scenario_id: str, delay_ms: float, goodput_bps: float, available: bool = True, conflict: bool = False) -> Scenario:
    links = {}
    for source in RACKS.values():
        for destination in RACKS.values():
            if source == destination:
                continue
            links[(source, destination)] = LinkState(
                source, destination, delay_ms, goodput_bps, available,
                path_id=f"{scenario_id}:{source}->{destination}",
                conflict_group="dense-shared" if conflict else None,
                provenance="R1 live tc/netem condition",
            )
    return Scenario(
        scenario_id, 1.0, links,
        conflict_budgets_seconds={"dense-shared": 20.0} if conflict else {},
        regime_duration_seconds=60.0,
        metadata={"evidence_boundary": "planner model paired to live tc/netem"},
    )


def directed_scenario(
    scenario_id: str, replicate: int, delay_ms: float, goodput_bps: float, available: bool = True,
) -> Scenario:
    base = scenario(scenario_id, 2, 1_000_000_000)
    source = RACKS[WORKERS[replicate % len(WORKERS)]]
    destination = RACKS[WORKERS[(replicate + 1) % len(WORKERS)]]
    links = dict(base.links)
    links[(source, destination)] = LinkState(
        source, destination, delay_ms, goodput_bps, available,
        path_id=f"{scenario_id}:{source}->{destination}",
        provenance="R1 directed live tc/netem path",
    )
    return Scenario(
        scenario_id, 1.0, links, regime_duration_seconds=60.0,
        metadata={"source_rack": source, "destination_rack": destination},
    )


def scenarios_for(condition: str, replicate: int) -> tuple[Scenario, ...]:
    stable = scenario("stable", 2, 1_000_000_000)
    if condition in {"stable", "confirmatory-healthy", "bursty", "hotspot", "structural-workload-change"}:
        return (stable,)
    params = {
        "persistent-degradation": scenario("degradation", 27, 100_000_000),
        "partial-blockage": directed_scenario("blockage", replicate, 82, 20_000_000),
        "conflict-dense": scenario("conflict", 17, 30_000_000, conflict=True),
        "outage-with-fallback": directed_scenario("fallback", replicate, 10, 50_000_000),
        "recovery": scenario("degraded", 37, 50_000_000),
        "confirmatory-temporary-moderate": scenario("temporary-moderate", 20, 100_000_000),
        "confirmatory-persistent-severe": scenario("persistent-severe", 40, 20_000_000),
    }
    adverse = params[condition]
    return (
        Scenario(**{**adverse.__dict__, "weight": 0.7}),
        Scenario(**{**stable.__dict__, "weight": 0.3}),
    )


def build_problem(run_root: Path, condition: str, replicate: int, current: dict[str, str]) -> ProblemInstance:
    traffic = r2_traffic(run_root)
    nodes = tuple(NodeSpec(worker, RACKS[worker], 4.0, 6144.0) for worker in WORKERS)
    replicas = tuple(ReplicaSpec(service, service, REQUESTS[service][0], REQUESTS[service][1]) for service in SERVICES)
    flows = []
    for (source, destination), (request_rate, byte_rate) in sorted(traffic.items()):
        multiplier = 10.0 if condition.startswith("confirmatory-") else 1.0
        if condition == "bursty":
            multiplier = 3.0
        elif condition == "hotspot" and source == "frontend" and destination in {"productcatalogservice", "currencyservice"}:
            multiplier = 5.0
        elif condition == "structural-workload-change":
            multiplier = 4.0 if source == "checkoutservice" or destination == "checkoutservice" else 0.35
        flows.append(FlowSpec(
            f"{source}->{destination}", source, destination,
            max(0.01, request_rate * 60 * multiplier),
            max(8.0, byte_rate * 60 * 8 * multiplier), 1.0, 500.0,
        ))
    relocation = {
        service: RelocationCost(
            service, 4062.0 * (4 if service == "redis-cart" else 1),
            4.062 * (4 if service == "redis-cart" else 1), 690.0,
            provenance="Kind measured create-ready-remove calibration",
        ) for service in SERVICES
    }
    return ProblemInstance(
        f"r1-{condition}-rep{replicate}", 300.0 if condition.startswith("confirmatory-") else 60.0, nodes, replicas, tuple(flows),
        scenarios_for(condition, replicate), current, relocation, max_relocations=4,
        metadata={"condition": condition, "replicate": replicate, "traffic_source": "R2 native telemetry"},
    )


def plan(method: str, problem: ProblemInstance, replicate: int) -> tuple[dict[str, str], dict[str, Any], float]:
    risk = RiskConfig(0.8, 1.5, 1.0, 1000.0)
    started = time.perf_counter()
    metadata: dict[str, Any] = {}
    if method == "Current":
        placement = dict(problem.current_placement)
    elif method == "TrafficOnly-MAPE-CAP":
        placement, metadata = solve_exact(homogenize_network(problem), replace(risk, cvar_weight=0.0), time_limit_seconds=30.0)
    elif method == "DeterministicNetworkAware":
        placement, metadata = solve_exact(single_scenario(problem, 0), replace(risk, cvar_weight=0.0), time_limit_seconds=30.0)
    elif method == "BPlus-LNS":
        placement, metadata = robust_lns(problem, risk, seed=1000 + replicate, iterations=40, destroy_size=4, time_limit_seconds=5.0, local_iterations=8)
    elif method == "BPlus-Exact":
        placement, metadata = solve_exact(problem, risk, time_limit_seconds=45.0)
    else:
        raise ValueError(method)
    runtime = time.perf_counter() - started
    evaluation = evaluate_placement(problem, placement, risk)
    metadata = {key: value for key, value in metadata.items() if key not in {"iteration_log", "candidate_log"}}
    return placement, {
        "objective": evaluation.total_objective, "expected_delay_cost": evaluation.expected_delay_cost,
        "cvar_delay_cost": evaluation.cvar_delay_cost, "relocation_cost": evaluation.relocation_cost,
        "slo_slack": evaluation.slo_slack, "feasible": evaluation.feasible,
        "solver": metadata,
    }, runtime


def frontend_probe() -> bool:
    code = "import urllib.request; urllib.request.urlopen('http://frontend:80/_healthz',timeout=5).read()"
    try:
        kubectl_cmd = ["kubectl", "--context", os.environ["KUBE_CONTEXT"]] if os.environ.get("KUBE_CONTEXT") else ["kubectl"]
        result = subprocess.run(
            [*kubectl_cmd, "exec", "-n", NS, "deployment/loadgenerator", "-c", "main", "--", "python", "-c", code],
            capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired:
        # A slow/contended exec channel is a failed probe sample, not a crash:
        # apply_placement already tracks failed probes in probe_timeline.
        return False
    return result.returncode == 0


def validate_placement_target(
    target: dict[str, str], nodes_document: dict[str, Any], deployments_document: dict[str, Any]
) -> dict[str, Any]:
    """Reject an invalid plan before the first Kubernetes mutation."""
    missing_services = sorted(set(SERVICES) - set(target))
    unexpected_services = sorted(set(target) - set(SERVICES))
    deployment_names = {
        item.get("metadata", {}).get("name") for item in deployments_document.get("items", [])
    }
    missing_deployments = sorted(set(SERVICES) - deployment_names)

    eligible_nodes: set[str] = set()
    rejected_nodes: dict[str, str] = {}
    for item in nodes_document.get("items", []):
        metadata = item.get("metadata", {})
        spec = item.get("spec", {})
        name = metadata.get("name")
        ready = any(
            condition.get("type") == "Ready" and condition.get("status") == "True"
            for condition in item.get("status", {}).get("conditions", [])
        )
        if not name:
            continue
        if spec.get("unschedulable"):
            rejected_nodes[name] = "unschedulable"
        elif not ready:
            rejected_nodes[name] = "not Ready"
        else:
            eligible_nodes.add(name)

    invalid_targets = {
        service: node for service, node in target.items() if node not in eligible_nodes
    }
    problems = []
    if missing_services:
        problems.append(f"missing services: {missing_services}")
    if unexpected_services:
        problems.append(f"unexpected services: {unexpected_services}")
    if missing_deployments:
        problems.append(f"deployments not found: {missing_deployments}")
    if invalid_targets:
        details = {
            service: f"{node} ({rejected_nodes.get(node, 'node not found')})"
            for service, node in invalid_targets.items()
        }
        problems.append(f"invalid target nodes: {details}")
    if problems:
        raise ValueError("placement pre-execution validation failed: " + "; ".join(problems))
    return {"eligible_nodes": sorted(eligible_nodes), "validated_services": sorted(SERVICES)}


def capture_placement_snapshot(
    pods_document: dict[str, Any] | None = None,
    nodes_document: dict[str, Any] | None = None,
    deployments_document: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Capture rich snapshot of cluster placement and health state before mutation."""
    if pods_document is None:
        try:
            pods_document = kubectl_json("get", "pods", "-n", NS)
        except Exception as exc:
            pods_document = {"error": str(exc), "items": []}
    if nodes_document is None:
        try:
            nodes_document = kubectl_json("get", "nodes")
        except Exception as exc:
            nodes_document = {"error": str(exc), "items": []}
    if deployments_document is None:
        try:
            deployments_document = kubectl_json("get", "deployments", "-n", NS)
        except Exception as exc:
            deployments_document = {"error": str(exc), "items": []}

    assignments: dict[str, str] = {}
    pod_details: dict[str, list[dict[str, Any]]] = {}
    for pod in pods_document.get("items", []):
        app = pod.get("metadata", {}).get("labels", {}).get("app")
        if not app:
            continue
        node = pod.get("spec", {}).get("nodeName")
        if node:
            assignments[app] = node
        statuses = pod.get("status", {}).get("containerStatuses", [])
        pod_info = {
            "name": pod.get("metadata", {}).get("name"),
            "node": node,
            "phase": pod.get("status", {}).get("phase"),
            "ready": bool(statuses) and all(c.get("ready", False) for c in statuses),
            "resource_version": pod.get("metadata", {}).get("resourceVersion"),
        }
        pod_details.setdefault(app, []).append(pod_info)

    deployment_details: dict[str, dict[str, Any]] = {}
    for item in deployments_document.get("items", []):
        name = item.get("metadata", {}).get("name")
        if not name:
            continue
        spec = item.get("spec", {})
        status = item.get("status", {})
        template_spec = spec.get("template", {}).get("spec", {})
        deployment_details[name] = {
            "generation": item.get("metadata", {}).get("generation"),
            "observed_generation": status.get("observedGeneration"),
            "resource_version": item.get("metadata", {}).get("resourceVersion"),
            "replicas": spec.get("replicas"),
            "ready_replicas": status.get("readyReplicas", 0),
            "available_replicas": status.get("availableReplicas", 0),
            "node_selector": template_spec.get("nodeSelector", {}),
        }

    eligible_nodes = []
    for item in nodes_document.get("items", []):
        name = item.get("metadata", {}).get("name")
        ready = any(
            c.get("type") == "Ready" and c.get("status") == "True"
            for c in item.get("status", {}).get("conditions", [])
        )
        if name:
            eligible_nodes.append({
                "name": name,
                "ready": ready,
                "unschedulable": bool(item.get("spec", {}).get("unschedulable")),
            })

    return {
        "timestamp_utc": utc_now(),
        "assignments": assignments,
        "deployments": deployment_details,
        "pods": pod_details,
        "nodes": eligible_nodes,
    }


def _patch_service_node(service: str, node: str, run_id: str) -> None:
    patch = {
        "spec": {"template": {"metadata": {"annotations": {"mape-cap-bplus/r1-run": run_id}},
        "spec": {"nodeSelector": {"kubernetes.io/hostname": node}}}}
    }
    kubectl("patch", "deployment", service, "-n", NS, "--type=merge", "-p", json.dumps(patch))


def apply_placement(target: dict[str, str], run_id: str, *, fault_hook: Any = None) -> dict[str, Any]:
    current_pods = kubectl_json("get", "pods", "-n", NS)
    current = {
        pod.get("metadata", {}).get("labels", {}).get("app"): pod.get("spec", {}).get("nodeName")
        for pod in current_pods["items"]
    }
    nodes = kubectl_json("get", "nodes")
    deployments = kubectl_json("get", "deployments", "-n", NS)
    snapshot_before = capture_placement_snapshot(current_pods, nodes, deployments)
    validation = validate_placement_target(target, nodes, deployments)
    changed = [service for service in SERVICES if current.get(service) != target[service]]
    started = time.monotonic()
    patched: list[str] = []
    samples: list[dict[str, Any]] = []
    blocking_services = list(changed)
    try:
        for service in changed:
            _patch_service_node(service, target[service], run_id)
            patched.append(service)
            if fault_hook is not None:
                fault_hook(stage="post_patch", service=service, patched=list(patched), target=target)
        deadline = time.monotonic() + ROLLOUT_TIMEOUT_SECONDS
        while changed and time.monotonic() < deadline:
            deployments = kubectl_json("get", "deployments", "-n", NS)
            pods = kubectl_json("get", "pods", "-n", NS)
            status = {item["metadata"]["name"]: item for item in deployments["items"]}
            complete = True
            blocking_services = []
            for name in changed:
                deployment = status[name]
                desired = deployment.get("spec", {}).get("replicas", 0)
                deployment_ready = (
                    deployment.get("status", {}).get("observedGeneration", 0) >= deployment["metadata"].get("generation", 0)
                    and deployment.get("status", {}).get("availableReplicas", 0) == desired
                    and deployment.get("status", {}).get("updatedReplicas", 0) == desired
                    and deployment.get("status", {}).get("unavailableReplicas", 0) == 0
                )
                target_pods = []
                for pod in pods["items"]:
                    if pod.get("metadata", {}).get("labels", {}).get("app") != name:
                        continue
                    if pod.get("metadata", {}).get("deletionTimestamp"):
                        continue
                    statuses = pod.get("status", {}).get("containerStatuses", [])
                    if (
                        pod.get("spec", {}).get("nodeName") == target[name]
                        and pod.get("status", {}).get("phase") == "Running"
                        and statuses and all(container.get("ready", False) for container in statuses)
                    ):
                        target_pods.append(pod)
                service_complete = deployment_ready and len(target_pods) == desired
                complete = complete and service_complete
                if not service_complete:
                    blocking_services.append(name)
            samples.append({"elapsed_seconds": time.monotonic() - started, "frontend_ok": frontend_probe(), "rollouts_complete": complete})
            if complete:
                break
            time.sleep(1)
        if changed and (not samples or not samples[-1]["rollouts_complete"]):
            raise RuntimeError(
                f"placement rollout timeout after {ROLLOUT_TIMEOUT_SECONDS}s; "
                f"blocking services: {blocking_services}"
            )
    except Exception as exc:
        rollback_errors = []
        for service in reversed(patched):
            previous_node = current.get(service)
            if not previous_node:
                rollback_errors.append(f"{service}: previous node unknown")
                continue
            try:
                _patch_service_node(service, previous_node, run_id + ":rollback")
            except Exception as rollback_exc:  # pragma: no cover - requires live Kubernetes failure
                rollback_errors.append(f"{service}: {rollback_exc}")
        # Best-effort wait for rolled-back pods to stabilize
        try:
            h = assert_healthy(include_telemetry=False, include_controller=False)
            if not h.get("healthy"):
                deadline = time.monotonic() + 15.0
                while time.monotonic() < deadline:
                    time.sleep(1)
                    if assert_healthy(include_telemetry=False, include_controller=False).get("healthy"):
                        break
        except Exception:
            pass
        suffix = f"; rollback errors: {rollback_errors}" if rollback_errors else "; rollback submitted"
        raise RuntimeError(f"placement transaction failed before commit: {exc}{suffix}") from exc

    elapsed = time.monotonic() - started
    failed = sum(not sample["frontend_ok"] for sample in samples)
    recovery = 0.0 if samples and all(sample["frontend_ok"] for sample in samples) else None
    failed_indexes = [index for index, sample in enumerate(samples) if not sample["frontend_ok"]]
    if failed_indexes:
        for sample in samples[failed_indexes[-1] + 1:]:
            if sample["frontend_ok"]:
                recovery = sample["elapsed_seconds"]
                break
    return {"changed_services": changed, "relocations": len(changed), "rollout_seconds": elapsed,
            "failed_health_probes": failed, "recovery_seconds": recovery, "probe_timeline": samples,
            "pre_execution_validation": validation, "transactional_rollback": "armed",
            "snapshot_before": snapshot_before}


def extra_workload(condition: str, duration: int) -> subprocess.Popen[str] | None:
    if condition not in {"hotspot", "structural-workload-change"}:
        return None
    if condition == "hotspot":
        body = (
            "import time,urllib.request\nend=time.time()+%d\n"
            "while time.time()<end:\n"
            "  try: urllib.request.urlopen('http://frontend:80/product/OLJCESPC7Z',timeout=3).read()\n"
            "  except Exception: pass\n"
            "  time.sleep(.15)\n" % duration
        )
    else:
        body = (
            "import time,urllib.request\nstart=time.time(); end=start+%d\n"
            "while time.time()<end:\n"
            "  path='/product/OLJCESPC7Z' if time.time()-start<%f else '/cart'\n"
            "  try: urllib.request.urlopen('http://frontend:80'+path,timeout=3).read()\n"
            "  except Exception: pass\n"
            "  time.sleep(.2)\n" % (duration, duration / 2)
        )
    kubectl_cmd = ["kubectl", "--context", os.environ["KUBE_CONTEXT"]] if os.environ.get("KUBE_CONTEXT") else ["kubectl"]
    return subprocess.Popen(
        [*kubectl_cmd, "exec", "-n", NS, "deployment/loadgenerator", "-c", "main", "--", "python", "-c", body],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def slo_from_log(text: str, threshold_ms: float = 500.0) -> tuple[int, int]:
    violations = 0
    timeouts = 0
    for line in text.splitlines():
        body = line.split(" ", 1)[-1]
        try:
            event = json.loads(body)
        except json.JSONDecodeError:
            continue
        if event.get("message") == "request complete" and float(event.get("http.resp.took_ms", 0)) > threshold_ms:
            violations += 1
        error = str(event.get("error", "")).lower()
        timeouts += int("timeout" in error or "deadline exceeded" in error)
    return violations, timeouts


def wait_healthy(timeout_seconds: float = 45.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    latest = assert_healthy(True, False)
    while not latest["healthy"] and time.monotonic() < deadline:
        time.sleep(2)
        latest = assert_healthy(True, False)
    return latest


def measure(condition: str, replicate: int, duration: int) -> tuple[dict[str, Any], list[dict], str]:
    condition_event = configure_condition(condition, replicate)
    if condition.startswith("confirmatory-"):
        kubectl("scale", "deployment/loadgenerator", "-n", NS, "--replicas=2")
    if condition == "bursty":
        kubectl("scale", "deployment/loadgenerator", "-n", NS, "--replicas=1")
    process = extra_workload(condition, duration)
    started = datetime.now(timezone.utc)
    started_utc = started.isoformat().replace("+00:00", "Z")
    samples = []
    events = []
    deadline = time.monotonic() + duration
    fallback_applied = False
    burst_up = burst_down = False
    try:
        while time.monotonic() < deadline:
            elapsed = duration - max(0, deadline - time.monotonic())
            if condition == "outage-with-fallback" and elapsed >= 5 and not fallback_applied:
                filtered(condition_event["source_node"], condition_event["destination_node"], 8, 50, 0)
                events.append({"elapsed_seconds": elapsed, "event": "fallback-path-active"})
                fallback_applied = True
            if condition in {"recovery", "confirmatory-temporary-moderate"} and elapsed >= duration / 2 and not fallback_applied:
                clear_network()
                events.append({"elapsed_seconds": elapsed, "event": "network-recovered"})
                fallback_applied = True
            if condition == "bursty" and elapsed >= duration / 3 and not burst_up:
                kubectl("scale", "deployment/loadgenerator", "-n", NS, "--replicas=4")
                events.append({"elapsed_seconds": elapsed, "event": "load-burst-up", "replicas": 4})
                burst_up = True
            if condition == "bursty" and elapsed >= 2 * duration / 3 and not burst_down:
                kubectl("scale", "deployment/loadgenerator", "-n", NS, "--replicas=1")
                events.append({"elapsed_seconds": elapsed, "event": "load-burst-down", "replicas": 1})
                burst_down = True
            last_stats_error = None
            for _ in range(3):
                try:
                    samples.append(stats_snapshot())
                    last_stats_error = None
                    break
                except RuntimeError as exc:
                    last_stats_error = exc
                    time.sleep(2)
            if last_stats_error is not None:
                raise last_stats_error
            time.sleep(min(5, max(0, deadline - time.monotonic())))
    finally:
        clear_network()
        if condition == "bursty":
            kubectl("scale", "deployment/loadgenerator", "-n", NS, "--replicas=1")
        if process is not None:
            try:
                process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                process.terminate()
    samples.append(stats_snapshot())
    app, log = frontend_metrics(started_utc, duration)
    slo_violations, timeouts = slo_from_log(log)
    app["slo_threshold_ms"] = 500.0
    app["slo_violations"] = slo_violations
    app["timeouts"] = timeouts
    app["successes"] = app["requests"] - app["errors"]
    app["condition_events"] = [condition_event, *events]
    return {"application": app, "resources": summarize_resources(samples, duration)}, samples, log


def run_cell(
    run_root: Path,
    condition: str,
    replicate: int,
    method: str,
    problem: ProblemInstance,
    duration: int,
    min_completed_requests: int,
) -> dict[str, Any]:
    cell_base = run_root / "raw" / "r1" / condition / f"replicate-{replicate:02d}" / method
    prior = accepted_cell_result(
        run_root, condition, replicate, method, duration, min_completed_requests
    )
    if prior is not None:
        return prior
    existing_attempts = []
    for directory in cell_base.glob("attempt-*"):
        try:
            existing_attempts.append(int(directory.name.rsplit("-", 1)[-1]))
        except ValueError:
            pass
    attempt = max(existing_attempts, default=0) + 1
    cell = cell_base / f"attempt-{attempt:02d}"
    result_path = cell / "result.json"
    cell.mkdir(parents=True, exist_ok=False)
    run_id = f"r1:{condition}:rep{replicate}:{method}"
    placement, planner, planner_seconds = plan(method, problem, replicate)
    relocation = apply_placement(placement, run_id)
    time.sleep(10)
    measured, samples, frontend_log = measure(condition, replicate, duration)
    health = wait_healthy()
    result = {
        "run_id": run_id, "condition": condition, "replicate": replicate, "method": method,
        "acceptance_gate_version": 2,
        "duration_seconds": duration, "completed_utc": utc_now(),
        "initial_placement": problem.current_placement, "placement": placement,
        "planner": planner, "planner_runtime_seconds": planner_seconds,
        "relocation": relocation, **measured, "health": health,
    }
    result["accepted"] = bool(
        health["healthy"]
        and measured["application"]["successes"] >= min_completed_requests
        and planner["feasible"] and math.isfinite(float(planner["objective"]))
    )
    result["minimum_completed_requests"] = min_completed_requests
    atomic_write_json(result_path, result)
    atomic_write_json(cell / "resource-samples.json", samples)
    atomic_write_text(cell / "frontend.log", frontend_log)
    if not result["accepted"]:
        raise RuntimeError(f"R1 acceptance failed: {run_id}")
    return result


def progress(
    run_root: Path,
    desired_total: int,
    duration: int,
    min_completed_requests: int,
    latest: str | None = None,
) -> dict[str, Any]:
    accepted = 0
    rejected = 0
    invalidated_count = 0
    invalidated = invalidated_result_paths(run_root)
    for path in (run_root / "raw" / "r1").glob("**/result.json"):
        if path.relative_to(run_root).as_posix() in invalidated:
            invalidated_count += 1
            continue
        row = json.loads(path.read_text(encoding="utf-8"))
        if (
            row.get("accepted") and row.get("acceptance_gate_version") == 2
            and row.get("duration_seconds") == duration
            and int(row.get("application", {}).get("successes", 0)) >= min_completed_requests
        ):
            accepted += 1
        else:
            rejected += 1
    report = {
        "updated_utc": utc_now(), "desired_total_cells": desired_total,
        "accepted_full_cells": accepted, "preserved_nonaccepted_or_smoke_attempts": rejected,
        "preserved_concurrency_invalidated_attempts": invalidated_count,
        "remaining_cells": max(0, desired_total - accepted), "latest_run_id": latest,
        "status": "complete" if accepted >= desired_total else "in_progress",
    }
    atomic_write_json(run_root / "checkpoints" / "r1-progress.json", report)
    return report


def execute_campaign(args: argparse.Namespace, conditions: list[str], methods: list[str], run_root: Path) -> int:
    (run_root / "raw" / "r1").mkdir(parents=True, exist_ok=True)
    assert_runtime_access()
    # The controller is present in the telemetry deployment, but the v1.37
    # request-rich follow-up intentionally deploys only the core application.
    # Scaling an absent optional controller must not prevent the frozen Current
    # versus BPlus-Exact campaign from starting.
    kubectl_cmd = ["kubectl", "--context", os.environ["KUBE_CONTEXT"]] if os.environ.get("KUBE_CONTEXT") else ["kubectl"]
    subprocess.run(
        [*kubectl_cmd, "scale", "deployment/bplus-controller-v03", "-n", NS, "--replicas=0"],
        check=False, capture_output=True, text=True,
    )
    clear_network()
    completed = []
    desired_total = len(conditions) * len(methods) * args.replicates
    progress(run_root, desired_total, args.duration_seconds, args.min_completed_requests)
    try:
        for condition_index, condition in enumerate(conditions):
            for replicate in range(1, args.replicates + 1):
                if all(
                    accepted_cell_result(
                        run_root,
                        condition,
                        replicate,
                        method,
                        args.duration_seconds,
                        args.min_completed_requests,
                    ) is not None
                    for method in methods
                ):
                    print(
                        f"R1 {condition} replicate {replicate}/{args.replicates} already complete; skipping",
                        flush=True,
                    )
                    continue
                initial = initial_placement(condition, replicate)
                initial_error = None
                for initial_attempt in range(1, args.max_cell_attempts + 1):
                    try:
                        apply_placement(
                            initial,
                            f"r1:{condition}:rep{replicate}:initial-{initial_attempt}",
                        )
                        initial_error = None
                        break
                    except Exception as exc:
                        initial_error = exc
                        print(
                            f"  initial placement attempt {initial_attempt} failed: {exc}",
                            flush=True,
                        )
                        clear_network()
                        wait_healthy(timeout_seconds=120)
                        time.sleep(10)
                if initial_error is not None:
                    raise RuntimeError(
                        f"R1 initial placement exhausted {args.max_cell_attempts} attempts: "
                        f"{condition}/rep{replicate}: {initial_error}"
                    ) from initial_error
                problem = build_problem(run_root, condition, replicate, initial)
                order = methods[(replicate + condition_index) % len(methods):] + methods[:(replicate + condition_index) % len(methods)]
                for method in order:
                    print(f"R1 {condition} replicate {replicate}/{args.replicates} method {method}", flush=True)
                    last_error = None
                    for cell_attempt in range(1, args.max_cell_attempts + 1):
                        try:
                            row = run_cell(
                                run_root,
                                condition,
                                replicate,
                                method,
                                problem,
                                args.duration_seconds,
                                args.min_completed_requests,
                            )
                            completed.append(row)
                            progress(
                                run_root,
                                desired_total,
                                args.duration_seconds,
                                args.min_completed_requests,
                                row["run_id"],
                            )
                            last_error = None
                            break
                        except Exception as exc:
                            last_error = exc
                            print(f"  cell attempt {cell_attempt} failed: {exc}", flush=True)
                            clear_network()
                            wait_healthy()
                            apply_placement(initial, f"r1:{condition}:rep{replicate}:retry-{method}-{cell_attempt}")
                            time.sleep(5)
                    if last_error is not None:
                        raise RuntimeError(
                            f"R1 cell exhausted {args.max_cell_attempts} attempts: "
                            f"{condition}/rep{replicate}/{method}: {last_error}"
                        ) from last_error
                    apply_placement(initial, f"r1:{condition}:rep{replicate}:restore-{method}")
                    time.sleep(3)
    finally:
        clear_network()
        kubectl("scale", "deployment/loadgenerator", "-n", NS, "--replicas=1")
    summary = {
        "completed_utc": utc_now(), "cells": len(completed),
        "accepted_cells": sum(bool(row["accepted"]) for row in completed),
        "conditions": conditions, "methods": methods, "replicates": args.replicates,
    }
    atomic_write_json(run_root / "derived" / "r1-summary.json", summary)
    print(json.dumps(summary, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_root", type=Path)
    parser.add_argument("--replicates", type=int, default=30)
    parser.add_argument("--duration-seconds", type=int, default=20)
    parser.add_argument("--min-completed-requests", type=int, default=1)
    parser.add_argument("--conditions", default=",".join(CONDITIONS))
    parser.add_argument("--methods", default=",".join(METHODS))
    parser.add_argument("--max-cell-attempts", type=int, default=3)
    args = parser.parse_args()
    conditions = args.conditions.split(",")
    methods = args.methods.split(",")
    if not set(conditions) <= set(CONDITIONS) or not set(methods) <= set(METHODS):
        parser.error("unknown condition or method")
    if args.replicates < 1 or args.duration_seconds < 15 or args.min_completed_requests < 1:
        parser.error("replicates >= 1, duration >= 15, and min completed requests >= 1 required")
    run_root = args.run_root.resolve()
    with CampaignLock(run_root):
        return execute_campaign(args, conditions, methods, run_root)


if __name__ == "__main__":
    raise SystemExit(main())
