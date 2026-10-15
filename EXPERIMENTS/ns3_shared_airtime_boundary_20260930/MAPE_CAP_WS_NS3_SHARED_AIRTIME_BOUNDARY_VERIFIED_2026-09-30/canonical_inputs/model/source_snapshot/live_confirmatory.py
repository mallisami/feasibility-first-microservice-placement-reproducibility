#!/usr/bin/env python3
"""Live Kubernetes confirmation of wireless-aware placement beyond byte affinity.

This experiment deploys held-out synthetic microservice communication graphs on a
3-worker Kind cluster. Each microservice is a real Kubernetes Deployment running
`benchmark/benchmark_service.py`. Cross-rack requests traverse a deterministic
in-cluster shared-medium emulator implementing the frozen directed-goodput and
conflict-budget semantics. The B+ planner is robust over three frozen
simulation-backed wireless states.

Evidence boundary: Kubernetes execution with a deterministic in-cluster shared-medium
emulator derived from the frozen wireless airtime model. This is not physical 60-GHz/RF
interference measurement.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import math
import os
import platform
import random
import shutil
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd
from scipy.stats import binomtest, wilcoxon

EXP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EXP_ROOT.parents[1]
sys.path.insert(0, str(EXP_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "implementation" / "code"))

from affinity_exact import cross_rack_bits, move_count, solve_affinity_bytes
from mape_cap_bplus.exact import ExactSolveError, solve_exact
from mape_cap_bplus.generators import generate_problem
from mape_cap_bplus.heuristic import resource_greedy_placement
from mape_cap_bplus.lns import robust_lns
from mape_cap_bplus.models import LinkState, NodeSpec, ProblemInstance, RelocationCost, RiskConfig, Scenario
from mape_cap_bplus.objective import evaluate_placement

CFG = json.loads((EXP_ROOT / "config" / "experiment.json").read_text(encoding="utf-8"))
RISK = RiskConfig(**CFG["risk"])
CLUSTER = CFG["cluster_name"]
CONTEXT = f"kind-{CLUSTER}"
NS = CFG["namespace"]
IMAGE = CFG["benchmark_image"]
RESULTS = EXP_ROOT / "results"
CURRENT_RUN_FILE = RESULTS / "CURRENT_RUN.txt"
CANONICAL_TRACE_FILE = REPO_ROOT / "RESULTS" / "calibration" / "external" / "ns3_simulation_backed_traces.csv"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=_json_default), encoding="utf-8")
    os.replace(tmp, path)


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    return str(value)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run_cmd(
    args: list[str], *, check: bool = True, timeout: int = 180, input_text: str | None = None
) -> str:
    proc = subprocess.run(args, input=input_text, capture_output=True, text=True, timeout=timeout)
    if check and proc.returncode:
        raise RuntimeError(
            f"command failed ({proc.returncode}): {' '.join(args)}\n"
            f"stdout:\n{proc.stdout[-3000:]}\nstderr:\n{proc.stderr[-3000:]}"
        )
    return proc.stdout


def kubectl(*args: str, timeout: int = 180, check: bool = True, input_text: str | None = None) -> str:
    return run_cmd(["kubectl", "--context", CONTEXT, *args], check=check, timeout=timeout, input_text=input_text)


def kubectl_json(*args: str) -> dict[str, Any]:
    return json.loads(kubectl(*args, "-o", "json"))


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def parse_cpu(value: str) -> float:
    value = str(value).strip()
    if value.endswith("m"):
        return float(value[:-1]) / 1000.0
    if value.endswith("n"):
        return float(value[:-1]) / 1e9
    return float(value)


def parse_mem_mb(value: str) -> float:
    value = str(value).strip()
    multipliers = {
        "Ki": 1 / 1024,
        "Mi": 1.0,
        "Gi": 1024.0,
        "Ti": 1024.0 * 1024,
        "K": 1 / 1000,
        "M": 1.0 / 1.048576,
        "G": 1000.0 / 1.048576,
    }
    for suffix, factor in multipliers.items():
        if value.endswith(suffix):
            return float(value[: -len(suffix)]) * factor
    return float(value) / (1024 * 1024)


def nearest_rank(values: Iterable[float], q: float) -> float | None:
    seq = sorted(float(v) for v in values if math.isfinite(float(v)))
    if not seq:
        return None
    idx = max(0, min(len(seq) - 1, math.ceil(q * len(seq)) - 1))
    return seq[idx]


def preflight() -> dict[str, Any]:
    missing = [c for c in ("docker", "kubectl", "kind") if not command_exists(c)]
    if missing:
        raise RuntimeError(f"missing required executable(s): {missing}")
    docker_server = run_cmd(["docker", "version", "--format", "{{.Server.Version}}"], timeout=60).strip()
    kind_version = run_cmd(["kind", "version"], timeout=60).strip()
    kubectl_client = json.loads(run_cmd(["kubectl", "version", "--client", "-o", "json"], timeout=60))
    free_gib = shutil.disk_usage(EXP_ROOT).free / 1024**3
    if free_gib < 4:
        raise RuntimeError(f"at least 4 GiB free disk is required; found {free_gib:.2f} GiB")
    return {
        "timestamp_utc": utc_now(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "docker_server": docker_server,
        "kind": kind_version,
        "kubectl_client": kubectl_client,
        "free_disk_gib": free_gib,
    }


def kind_clusters() -> set[str]:
    text = run_cmd(["kind", "get", "clusters"], check=False, timeout=60)
    return {line.strip() for line in text.splitlines() if line.strip()}


def cluster_info() -> dict[str, Any]:
    nodes = kubectl_json("get", "nodes")
    names = [n["metadata"]["name"] for n in nodes["items"]]
    workers = sorted(n for n in names if "control-plane" not in n)
    controls = sorted(n for n in names if "control-plane" in n)
    if len(workers) != 3 or len(controls) != 1:
        raise RuntimeError(f"expected 1 control-plane + 3 workers, got: {names}")
    racks = ["rack-a", "rack-b", "rack-c"]
    rack_to_worker = dict(zip(racks, workers))
    by_name = {n["metadata"]["name"]: n for n in nodes["items"]}
    expected_k8s = str(CFG["kubectl_version"])
    kubelet_versions = {name: str(node.get("status", {}).get("nodeInfo", {}).get("kubeletVersion", "")) for name, node in by_name.items()}
    wrong = {name: version for name, version in kubelet_versions.items() if version != expected_k8s}
    if wrong:
        raise RuntimeError(
            f"existing Kind cluster does not match frozen Kubernetes {expected_k8s}: {wrong}. "
            f"Delete only the dedicated cluster with 'kind delete cluster --name {CLUSTER}' and rerun; "
            "do not mix results from different Kubernetes versions."
        )
    alloc = {}
    for rack, worker in rack_to_worker.items():
        a = by_name[worker]["status"]["allocatable"]
        cpu = parse_cpu(a["cpu"])
        mem = parse_mem_mb(a["memory"])
        if cpu < 3.1 or mem < 2300:
            raise RuntimeError(
                f"worker {worker} is too small for the frozen held-out blocks: "
                f"allocatable cpu={cpu:.2f}, memory={mem:.0f} MiB; need >=3.1 CPU and >=2300 MiB"
            )
        alloc[worker] = {"cpu": cpu, "memory_mb": mem}
    return {"control_plane": controls[0], "workers": workers, "rack_to_worker": rack_to_worker, "allocatable": alloc, "kubelet_versions": kubelet_versions}


def ensure_cluster() -> dict[str, Any]:
    created = False
    if CLUSTER not in kind_clusters():
        cmd = [
            "kind", "create", "cluster", "--name", CLUSTER,
            "--config", str(EXP_ROOT / "config" / "kind-cluster-config.yaml"),
            "--wait", "240s",
        ]
        if str(CFG.get("kind_node_image", "")).strip():
            cmd += ["--image", CFG["kind_node_image"]]
        run_cmd(cmd, timeout=900)
        created = True
    info = cluster_info()
    for rack, worker in info["rack_to_worker"].items():
        kubectl("label", "node", worker, f"topology.kubernetes.io/zone={rack}", "--overwrite")
    return {**info, "created": created}


def ensure_benchmark_image() -> dict[str, Any]:
    base = CFG["benchmark_base_image"]
    image = CFG["benchmark_image"]
    if subprocess.run(["docker", "image", "inspect", base], capture_output=True, text=True, timeout=60).returncode != 0:
        run_cmd(["docker", "pull", base], timeout=1200)
    run_cmd(
        [
            "docker", "build", "--pull=false",
            "--build-arg", f"BASE_IMAGE={base}",
            "-t", image, str(EXP_ROOT / "benchmark"),
        ],
        timeout=1200,
    )
    run_cmd(["kind", "load", "docker-image", "--name", CLUSTER, image], timeout=600)
    return {"base_image": base, "benchmark_image": image, "image_id": run_cmd(["docker", "image", "inspect", image, "--format", "{{.Id}}"], timeout=60).strip()}


def ensure_namespace() -> None:
    exists = subprocess.run(
        ["kubectl", "--context", CONTEXT, "get", "namespace", NS],
        capture_output=True, text=True, timeout=30,
    ).returncode == 0
    if not exists:
        kubectl("create", "namespace", NS)


def wireless_medium_manifest(info: Mapping[str, Any]) -> str:
    name = str(CFG["wireless_medium_service"])
    control = str(info["control_plane"])
    docs = [
        {
            "apiVersion": "v1", "kind": "Service",
            "metadata": {"name": name, "namespace": NS},
            "spec": {"selector": {"app": name}, "ports": [{"name": "http", "port": 8080, "targetPort": 8080}]},
        },
        {
            "apiVersion": "apps/v1", "kind": "Deployment",
            "metadata": {"name": name, "namespace": NS},
            "spec": {
                "replicas": 1, "strategy": {"type": "Recreate"},
                "selector": {"matchLabels": {"app": name}},
                "template": {
                    "metadata": {"labels": {"app": name, "mape-cap-confirm": "wireless-medium"}},
                    "spec": {
                        "nodeSelector": {"kubernetes.io/hostname": control},
                        "tolerations": [{"key": "node-role.kubernetes.io/control-plane", "operator": "Exists", "effect": "NoSchedule"}],
                        "containers": [{
                            "name": "medium", "image": IMAGE, "imagePullPolicy": "Never",
                            "command": ["python", "/app/wireless_medium.py"],
                            "env": [{"name": "FORWARD_TIMEOUT_SECONDS", "value": str(CFG["wireless_medium_timeout_seconds"])}],
                            "ports": [{"containerPort": 8080}],
                            "resources": {"requests": {"cpu": "100m", "memory": "128Mi"}, "limits": {"memory": "256Mi"}},
                            "readinessProbe": {"httpGet": {"path": "/healthz", "port": 8080}, "initialDelaySeconds": 1, "periodSeconds": 2, "timeoutSeconds": 1},
                        }],
                    },
                },
            },
        },
    ]
    return "\n---\n".join(json.dumps(d) for d in docs) + "\n"


def ensure_wireless_medium(info: Mapping[str, Any]) -> dict[str, Any]:
    kubectl("apply", "-f", "-", input_text=wireless_medium_manifest(info), timeout=180)
    kubectl("rollout", "status", "deployment", str(CFG["wireless_medium_deployment"]), "-n", NS, "--timeout=180s", timeout=210)
    pods = kubectl_json("get", "pods", "-n", NS, "-l", f"app={CFG['wireless_medium_service']}")
    items = [x for x in pods.get("items", []) if not x.get("metadata", {}).get("deletionTimestamp")]
    if len(items) != 1 or items[0].get("status", {}).get("phase") != "Running":
        raise RuntimeError(f"wireless-medium pod is not healthy: {items}")
    pod = items[0]["metadata"]["name"]
    health = json.loads(kubectl("exec", "-n", NS, pod, "--", "python", "/app/medium_control.py", "health", timeout=30))
    if not health.get("ok"):
        raise RuntimeError(f"wireless-medium health check failed: {health}")
    return {"pod": pod, "node": items[0].get("spec", {}).get("nodeName"), "health": health}


def wireless_medium_pod() -> str:
    pods = kubectl_json("get", "pods", "-n", NS, "-l", f"app={CFG['wireless_medium_service']}")
    items = [x for x in pods.get("items", []) if not x.get("metadata", {}).get("deletionTimestamp") and x.get("status", {}).get("phase") == "Running"]
    if len(items) != 1:
        raise RuntimeError(f"expected one running wireless-medium pod, found {len(items)}")
    return items[0]["metadata"]["name"]


def medium_control(command: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    pod = wireless_medium_pod()
    text = kubectl(
        "exec", "-i", "-n", NS, pod, "--", "python", "/app/medium_control.py", command,
        input_text=(json.dumps(payload) if payload is not None else None), timeout=30,
    )
    return json.loads(text)


def load_frozen_scenarios(*, goodput_scale: float = 1.0) -> tuple[Scenario, ...]:
    wanted = set(CFG["planner_scenarios"])
    groups: dict[str, list[dict[str, str]]] = {}
    with CANONICAL_TRACE_FILE.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row["scenario_id"] in wanted:
                groups.setdefault(row["scenario_id"], []).append(row)
    if set(groups) != wanted:
        raise RuntimeError(f"missing frozen scenario rows: {sorted(wanted-set(groups))}")
    scenarios: list[Scenario] = []
    for sid in CFG["planner_scenarios"]:
        rows = groups[sid]
        links: dict[tuple[str, str], LinkState] = {}
        budgets: dict[str, float] = {}
        for row in rows:
            group = row["conflict_group"].strip() or None
            links[(row["source_rack"], row["destination_rack"])] = LinkState(
                row["source_rack"], row["destination_rack"], float(row["latency_ms"]),
                float(row["goodput_bps"]) * goodput_scale, row["available"].lower() == "true",
                row["path_id"], group, row["provenance"],
            )
            if group and row["budget_seconds"].strip():
                budgets[group] = float(row["budget_seconds"])
        scenarios.append(Scenario(
            sid, float(rows[0]["weight"]), links, budgets,
            regime_duration_seconds=float(rows[0]["regime_duration_seconds"]),
            metadata={"source": "frozen simulation-backed trace library", "goodput_scale": goodput_scale},
        ))
    total = sum(s.weight for s in scenarios)
    return tuple(replace(s, weight=s.weight / total) for s in scenarios)


def max_conflict_util(problem: ProblemInstance, placement: Mapping[str, str]) -> float:
    ev = evaluate_placement(problem, placement, RISK)
    worst = 0.0
    for scenario in problem.scenarios:
        amap = ev.scenario_airtime_by_group.get(scenario.scenario_id, {})
        for group, budget in scenario.conflict_budgets_seconds.items():
            if budget > 0:
                worst = max(worst, float(amap.get(group, 0.0)) / float(budget))
    return worst


def scenario_conflict_util(problem: ProblemInstance, placement: Mapping[str, str], scenario_id: str) -> float:
    ev = evaluate_placement(problem, placement, RISK)
    scenario = next(s for s in problem.scenarios if s.scenario_id == scenario_id)
    amap = ev.scenario_airtime_by_group.get(scenario_id, {})
    vals = [float(amap.get(group, 0.0)) / float(budget) for group, budget in scenario.conflict_budgets_seconds.items() if budget > 0]
    return max(vals, default=0.0)


def build_problem(seed: int, info: Mapping[str, Any], target: float) -> tuple[ProblemInstance, dict[str, Any]]:
    generated = generate_problem(
        replica_count=int(CFG["replica_count"]), rack_count=3, nodes_per_rack=1,
        scenario_count=3, seed=seed, decision_window_seconds=60.0,
    )
    rack_alias = {"rack-0": "rack-a", "rack-1": "rack-b", "rack-2": "rack-c"}
    gen_nodes = sorted(generated.nodes, key=lambda n: n.rack_id)
    node_map = {node.node_id: info["rack_to_worker"][rack_alias[node.rack_id]] for node in gen_nodes}
    nodes = []
    for node in gen_nodes:
        worker = node_map[node.node_id]
        alloc = info["allocatable"][worker]
        nodes.append(NodeSpec(worker, rack_alias[node.rack_id], alloc["cpu"] * 0.95, alloc["memory_mb"] * 0.95))
    allowed = tuple(n.node_id for n in nodes)
    replicas = tuple(replace(r, allowed_nodes=allowed) for r in generated.replicas)
    current = {rid: node_map[nid] for rid, nid in generated.current_placement.items()}
    relocation = {
        r.replica_id: RelocationCost(
            r.replica_id, float(CFG["relocation"]["cost_units"]), float(CFG["relocation"]["expected_seconds"]),
            float(CFG["relocation"]["uncertainty_units"]), provenance="frozen Kind relocation pilot",
        ) for r in replicas
    }
    base = replace(
        generated, nodes=tuple(nodes), replicas=replicas, current_placement=current,
        scenarios=load_frozen_scenarios(), relocation_costs=relocation,
        metadata={**generated.metadata, "live_confirmation_seed": seed, "wireless_source": "frozen simulation-backed traces"},
    )
    # Live calibration is tied to the scenario actually executed by the shared-medium emulator.
    # The B+ planner still evaluates all frozen robust scenarios after the same common scaling.
    base_util = scenario_conflict_util(base, base.current_placement, str(CFG["emulated_scenario"]))
    if not math.isfinite(base_util) or base_util <= 0:
        raise RuntimeError(f"seed {seed}: zero/invalid Current utilization in emulated scenario")
    scale = base_util / float(target)
    scenarios = []
    for scenario in base.scenarios:
        links = {k: replace(link, goodput_bps=link.goodput_bps * scale) for k, link in scenario.links.items()}
        scenarios.append(replace(scenario, links=links, metadata={**scenario.metadata, "target_goodput_scale": scale}))
    problem = replace(base, scenarios=tuple(scenarios), metadata={**base.metadata, "target_current_utilization": target, "goodput_scale": scale})
    check = scenario_conflict_util(problem, problem.current_placement, str(CFG["emulated_scenario"]))
    if not math.isclose(check, float(target), rel_tol=1e-8, abs_tol=1e-8):
        raise RuntimeError(f"seed {seed}: live-scenario target calibration mismatch: {check} vs {target}")
    dense = next(s for s in problem.scenarios if s.scenario_id == CFG["emulated_scenario"])
    rates = [link.goodput_bps / 1e6 for link in dense.links.values()]
    if min(rates) < float(CFG["emulator_min_mbit"]) or max(rates) > float(CFG["emulator_max_mbit"]):
        raise RuntimeError(
            f"seed {seed}: calibrated rate outside frozen emulator guard: min={min(rates):.4f}, max={max(rates):.4f} Mbit/s"
        )
    return problem, {
        "base_current_emulated_scenario_utilization": base_util,
        "calibrated_current_emulated_scenario_utilization": check,
        "calibrated_current_worst_robust_utilization": max_conflict_util(problem, problem.current_placement),
        "goodput_scale": scale, "min_rate_mbit": min(rates), "max_rate_mbit": max(rates),
    }


def plan_methods(problem: ProblemInstance) -> dict[str, dict[str, Any]]:
    plans: dict[str, dict[str, Any]] = {}
    current = dict(problem.current_placement)
    affinity, affinity_meta = solve_affinity_bytes(problem)
    try:
        bplus, bmeta = solve_exact(problem, RISK, time_limit_seconds=60.0, require_optimal=True)
        bstatus = {"planner_status": "optimal", "planner_abstained": False}
    except ExactSolveError as exc:
        text = str(exc).lower()
        if "infeasible" not in text:
            raise
        # Amendment 2026-09-20 (IMPLEMENTATION_CORRECTION_2026-09-20-ABSTENTION-FALLBACK.md):
        # proven infeasibility => fall back to a risk-aware heuristic rather than the stale
        # Current placement. Current carries no wireless-model awareness at all and was
        # empirically the worst-performing placement in the confirmatory dataset, so it
        # penalized abstention far more than the safety property requires.
        #
        # Two tiers, because both robust_lns() and robust_local_search() internally require a
        # placement that is *fully* feasible under the same CVaR-robust/airtime constraint the
        # exact solver just proved unsatisfiable -- for a genuinely infeasible graph instance,
        # neither can produce anything (find_feasible_start() raises ValueError). That case is
        # structurally different from "the exact solver just couldn't prove optimality": no
        # method can certify a risk-compliant placement for that instance at all, including
        # Affinity-Bytes -- it simply never checks, and deploys its heuristic placement anyway.
        # Tier 1 (robust_lns) covers the former; tier 2 (resource_greedy_placement, the same
        # compute/affinity-valid but network-unaware layer Affinity-Bytes effectively operates
        # at) covers the latter, so B+ deploys *something* sensible instead of retreating to
        # Current. planner_abstained stays True in both tiers so every downstream consumer of
        # that flag (both this harness and the ns-3 harness that reuses this function) keeps
        # full visibility into which seeds triggered the exact solver's abstention, and which
        # tier was used, unchanged from before in spirit.
        seed_for_lns = int(problem.metadata.get("live_confirmation_seed", 1000))
        try:
            bplus, lns_meta = robust_lns(problem, RISK, current, seed=seed_for_lns, time_limit_seconds=30.0)
            bmeta = {
                "solver": "bounded-large-neighbourhood-search",
                "status": "proven_infeasible_fallback_to_lns",
                "message": str(exc),
                "lns_meta": {k: v for k, v in lns_meta.items() if k != "iteration_log"},
            }
            bstatus = {"planner_status": "proven_infeasible_fallback_to_lns", "planner_abstained": True}
        except ValueError as lns_exc:
            bplus = resource_greedy_placement(problem)
            bmeta = {
                "solver": "resource-greedy-placement",
                "status": "proven_infeasible_no_risk_compliant_placement_exists",
                "message": str(exc),
                "lns_failure": str(lns_exc),
            }
            bstatus = {
                "planner_status": "proven_infeasible_no_risk_compliant_placement_exists",
                "planner_abstained": True,
            }
    for method, placement, meta, status in (
        ("Current", current, {"solver": "identity"}, {"planner_status": "identity", "planner_abstained": False}),
        ("Affinity-Bytes", affinity, affinity_meta, {"planner_status": "optimal", "planner_abstained": False}),
        ("BPlus-Exact", bplus, bmeta, bstatus),
    ):
        ev = evaluate_placement(problem, placement, RISK)
        plans[method] = {
            "placement": placement,
            "planner": meta,
            **status,
            "evaluation": asdict(ev),
            "planned_feasible": bool(ev.feasible) and not bool(status.get("planner_abstained")),
            "worst_conflict_utilization": max_conflict_util(problem, placement),
            "cross_rack_bits": cross_rack_bits(problem, placement),
            "moves": move_count(problem, placement),
        }
    return plans


def benchmark_manifest(problem: ProblemInstance, placement: Mapping[str, str], run_token: str) -> str:
    docs: list[dict[str, Any]] = []
    docs.append({"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": NS}})
    for replica in sorted(problem.replicas, key=lambda r: r.replica_id):
        name = replica.replica_id
        labels = {"app": name, "mape-cap-confirm": "benchmark"}
        docs.append({
            "apiVersion": "v1", "kind": "Service",
            "metadata": {"name": name, "namespace": NS},
            "spec": {"selector": {"app": name}, "ports": [{"name": "http", "port": 8080, "targetPort": 8080}]},
        })
        docs.append({
            "apiVersion": "apps/v1", "kind": "Deployment",
            "metadata": {"name": name, "namespace": NS},
            "spec": {
                "replicas": 1,
                "strategy": {"type": "Recreate"},
                "selector": {"matchLabels": {"app": name}},
                "template": {
                    "metadata": {"labels": labels, "annotations": {"mape-cap-confirm/run-token": run_token}},
                    "spec": {
                        "nodeSelector": {"kubernetes.io/hostname": placement[name]},
                        "containers": [{
                            "name": "bench", "image": IMAGE, "imagePullPolicy": "Never",
                            "env": [
                                {"name": "SERVICE_ID", "value": name},
                                {"name": "HTTP_TIMEOUT_SECONDS", "value": str(CFG["benchmark_http_timeout_seconds"])},
                            ],
                            "ports": [{"containerPort": 8080}],
                            "resources": {
                                "requests": {"cpu": f"{int(round(replica.cpu_request*1000))}m", "memory": f"{int(round(replica.memory_request_mb))}Mi"},
                                "limits": {"memory": f"{max(256, int(round(replica.memory_request_mb*1.25)))}Mi"},
                            },
                            "readinessProbe": {"httpGet": {"path": "/healthz", "port": 8080}, "initialDelaySeconds": 1, "periodSeconds": 2, "timeoutSeconds": 1},
                        }],
                    },
                },
            },
        })
    # yaml dependency is intentionally avoided in the runner; kubectl accepts JSON documents separated by ---.
    return "\n---\n".join(json.dumps(d) for d in docs) + "\n"


def apply_placement(problem: ProblemInstance, placement: Mapping[str, str], run_token: str) -> dict[str, Any]:
    started = time.monotonic()
    kubectl("apply", "-f", "-", input_text=benchmark_manifest(problem, placement, run_token), timeout=300)
    # kubectl rollout status has never accepted an "--all" flag for a bare `deployment` resource type;
    # wait on each deployment in the placement individually against the same shared overall deadline.
    deadline = started + int(CFG["max_rollout_seconds"])
    for replica in problem.replicas:
        remaining = max(1, int(round(deadline - time.monotonic())))
        kubectl("rollout", "status", f"deployment/{replica.replica_id}", "-n", NS, f"--timeout={remaining}s", timeout=remaining + 30)
    health = deployment_health(problem)
    if not health["healthy"]:
        raise RuntimeError(f"deployment health failed after placement: {health}")
    return {"rollout_seconds": time.monotonic() - started, "health": health}


def deployment_health(problem: ProblemInstance) -> dict[str, Any]:
    deps = kubectl_json("get", "deployments", "-n", NS)
    by = {d["metadata"]["name"]: d for d in deps.get("items", [])}
    rows = []
    healthy = True
    for replica in problem.replicas:
        d = by.get(replica.replica_id)
        if d is None:
            rows.append({"name": replica.replica_id, "ready": False, "reason": "missing"})
            healthy = False
            continue
        desired = int(d["spec"].get("replicas", 1) or 1)
        available = int(d.get("status", {}).get("availableReplicas", 0) or 0)
        ready = desired == available
        rows.append({"name": replica.replica_id, "desired": desired, "available": available, "ready": ready})
        healthy = healthy and ready
    return {"healthy": healthy, "deployments": rows}


def pod_service_ips(problem: ProblemInstance) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    pods = kubectl_json("get", "pods", "-n", NS)
    services = kubectl_json("get", "services", "-n", NS)
    pod_ip: dict[str, str] = {}
    pod_name: dict[str, str] = {}
    pod_node: dict[str, str] = {}
    for p in pods.get("items", []):
        app = p.get("metadata", {}).get("labels", {}).get("app")
        if app not in problem.replica_by_id or p.get("metadata", {}).get("deletionTimestamp"):
            continue
        ip = p.get("status", {}).get("podIP")
        node = p.get("spec", {}).get("nodeName")
        phase = p.get("status", {}).get("phase")
        if ip and node and phase == "Running":
            pod_ip[app] = ip
            pod_name[app] = p["metadata"]["name"]
            pod_node[app] = node
    svc_ip = {}
    for s in services.get("items", []):
        name = s.get("metadata", {}).get("name")
        ip = s.get("spec", {}).get("clusterIP")
        if name in problem.replica_by_id and ip and ip != "None":
            svc_ip[name] = ip
    missing = [r.replica_id for r in problem.replicas if r.replica_id not in pod_ip or r.replica_id not in svc_ip]
    if missing:
        raise RuntimeError(f"pod/service IP discovery incomplete: {missing}")
    return pod_ip, svc_ip, pod_name


def emulated_dense(problem: ProblemInstance) -> Scenario:
    return next(s for s in problem.scenarios if s.scenario_id == CFG["emulated_scenario"])


def current_live_placement(problem: ProblemInstance) -> dict[str, str]:
    pods = kubectl_json("get", "pods", "-n", NS)
    result = {}
    for p in pods.get("items", []):
        app = p.get("metadata", {}).get("labels", {}).get("app")
        if app in problem.replica_by_id and not p.get("metadata", {}).get("deletionTimestamp"):
            node = p.get("spec", {}).get("nodeName")
            if node and p.get("status", {}).get("phase") == "Running":
                result[app] = node
    if set(result) != set(problem.replica_by_id):
        raise RuntimeError(f"live placement incomplete: got {sorted(result)}, expected {sorted(problem.replica_by_id)}")
    return result


def flow_configs(problem: ProblemInstance, placement: Mapping[str, str]) -> dict[str, list[dict[str, Any]]]:
    result = {r.replica_id: [] for r in problem.replicas}
    nodes = problem.node_by_id
    dense = emulated_dense(problem)
    medium_name = str(CFG["wireless_medium_service"])
    for flow in problem.flows:
        requests = float(flow.requests_per_window)
        if requests <= 0:
            continue
        rate = requests / float(problem.decision_window_seconds)
        payload = max(1, int(round((float(flow.bits_per_window) / 8.0) / requests)))
        src_node = placement[flow.source_replica]
        dst_node = placement[flow.destination_replica]
        if src_node == dst_node:
            destination = f"http://{flow.destination_replica}:8080/data"
            via_medium = False
            link_meta = None
        else:
            src_rack = nodes[src_node].rack_id
            dst_rack = nodes[dst_node].rack_id
            link = dense.links[(src_rack, dst_rack)]
            destination = (
                f"http://{medium_name}:8080/transmit?dst={flow.destination_replica}"
                f"&goodput_bps={link.goodput_bps:.12g}&latency_ms={link.latency_ms:.12g}"
            )
            via_medium = True
            link_meta = {"source_rack": src_rack, "destination_rack": dst_rack, "goodput_bps": link.goodput_bps, "latency_ms": link.latency_ms}
        result[flow.source_replica].append({
            "flow_id": flow.flow_id,
            "destination": destination,
            "destination_replica": flow.destination_replica,
            "rate_rps": rate,
            "payload_bytes": payload,
            "via_shared_medium": via_medium,
            "link": link_meta,
        })
    return result


def control_pod(pod: str, command: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    text = kubectl(
        "exec", "-i", "-n", NS, pod, "--", "python", "/app/bench_control.py", command,
        input_text=(json.dumps(payload) if payload is not None else None),
        timeout=30,
    )
    return json.loads(text)


def configure_and_run(problem: ProblemInstance, placement: Mapping[str, str], run_id: str, seconds: int) -> dict[str, Any]:
    _, _, pod_names = pod_service_ips(problem)
    configs = flow_configs(problem, placement)
    dense = emulated_dense(problem)
    budget = float(dense.conflict_budgets_seconds.get("cg-shared", 0.0))
    duty_fraction = budget / float(problem.decision_window_seconds) if budget > 0 else 1.0
    medium_cfg = medium_control("configure", {"run_id": run_id, "duty_fraction": duty_fraction})
    start_epoch = time.time() + float(CFG["synchronized_start_delay_seconds"])
    stop_epoch = start_epoch + float(seconds)

    def configure_one(replica_id: str) -> tuple[str, dict[str, Any]]:
        payload = {
            "run_id": run_id,
            "start_epoch": start_epoch,
            "stop_epoch": stop_epoch,
            "flows": configs[replica_id],
        }
        return replica_id, control_pod(pod_names[replica_id], "configure", payload)

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(pod_names)) as pool:
        configured = dict(pool.map(configure_one, sorted(pod_names)))
    if time.time() >= start_epoch - 0.5:
        raise RuntimeError("synchronized start delay was consumed by control calls; no traffic result accepted")
    time.sleep(max(0.0, stop_epoch - time.time()) + float(CFG["benchmark_http_timeout_seconds"]) + 0.75)

    def metrics_one(replica_id: str) -> tuple[str, dict[str, Any]]:
        return replica_id, control_pod(pod_names[replica_id], "metrics")

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(pod_names)) as pool:
        metrics = dict(pool.map(metrics_one, sorted(pod_names)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(pod_names)) as pool:
        list(pool.map(lambda rid: control_pod(pod_names[rid], "stop", {}), sorted(pod_names)))
    medium_metrics = medium_control("metrics")
    return {
        "start_epoch": start_epoch, "stop_epoch": stop_epoch, "configured": configured,
        "pod_metrics": metrics, "flow_configs": configs,
        "wireless_medium_config": medium_cfg, "wireless_medium_metrics": medium_metrics,
    }


# --- Multi-scenario weighted composite extension (2026-09-20) -------------
# Everything below is purely additive: it does not modify emulated_dense(),
# flow_configs(), configure_and_run(), or aggregate_metrics() above, which
# remain exactly as frozen for the original single-scenario (conflict-dense
# only) confirmatory protocol and are what the existing 30-seed campaign
# uses. This extension answers a different, explicitly disclosed question:
# does the placement advantage the exact solver finds (real, per the 9-0
# discordant feasibility statistic) survive when live performance is
# measured across the *actual weighted distribution* of frozen wireless
# scenarios the CVaR-robust objective optimizes against, rather than only
# the single conflict-dense condition the original protocol emulates.
# Requires the generalized (per-conflict-group) wireless_medium.py.


def scenario_by_id(problem: ProblemInstance, scenario_id: str) -> Scenario:
    return next(s for s in problem.scenarios if s.scenario_id == scenario_id)


def flow_configs_for_scenario(
    problem: ProblemInstance, placement: Mapping[str, str], scenario: Scenario
) -> dict[str, list[dict[str, Any]]]:
    result = {r.replica_id: [] for r in problem.replicas}
    nodes = problem.node_by_id
    medium_name = str(CFG["wireless_medium_service"])
    for flow in problem.flows:
        requests = float(flow.requests_per_window)
        if requests <= 0:
            continue
        rate = requests / float(problem.decision_window_seconds)
        payload = max(1, int(round((float(flow.bits_per_window) / 8.0) / requests)))
        src_node = placement[flow.source_replica]
        dst_node = placement[flow.destination_replica]
        if src_node == dst_node:
            destination = f"http://{flow.destination_replica}:8080/data"
            via_medium = False
            link_meta = None
        else:
            src_rack = nodes[src_node].rack_id
            dst_rack = nodes[dst_node].rack_id
            link = scenario.links[(src_rack, dst_rack)]
            group = link.conflict_group or "default"
            destination = (
                f"http://{medium_name}:8080/transmit?dst={flow.destination_replica}"
                f"&goodput_bps={link.goodput_bps:.12g}&latency_ms={link.latency_ms:.12g}"
                f"&group={group}"
            )
            via_medium = True
            link_meta = {
                "source_rack": src_rack, "destination_rack": dst_rack,
                "goodput_bps": link.goodput_bps, "latency_ms": link.latency_ms, "conflict_group": group,
            }
        result[flow.source_replica].append({
            "flow_id": flow.flow_id,
            "destination": destination,
            "destination_replica": flow.destination_replica,
            "rate_rps": rate,
            "payload_bytes": payload,
            "via_shared_medium": via_medium,
            "link": link_meta,
        })
    return result


def configure_and_run_for_scenario(
    problem: ProblemInstance, placement: Mapping[str, str], run_id: str, seconds: int, scenario: Scenario,
) -> dict[str, Any]:
    _, _, pod_names = pod_service_ips(problem)
    configs = flow_configs_for_scenario(problem, placement, scenario)
    duty_fractions = {
        group: (budget / float(problem.decision_window_seconds))
        for group, budget in scenario.conflict_budgets_seconds.items()
        if budget > 0
    }
    if not duty_fractions:
        duty_fractions = {"default": 1.0}
    medium_cfg = medium_control("configure", {"run_id": run_id, "duty_fractions": duty_fractions})
    start_epoch = time.time() + float(CFG["synchronized_start_delay_seconds"])
    stop_epoch = start_epoch + float(seconds)

    def configure_one(replica_id: str) -> tuple[str, dict[str, Any]]:
        payload = {
            "run_id": run_id,
            "start_epoch": start_epoch,
            "stop_epoch": stop_epoch,
            "flows": configs[replica_id],
        }
        return replica_id, control_pod(pod_names[replica_id], "configure", payload)

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(pod_names)) as pool:
        configured = dict(pool.map(configure_one, sorted(pod_names)))
    if time.time() >= start_epoch - 0.5:
        raise RuntimeError("synchronized start delay was consumed by control calls; no traffic result accepted")
    time.sleep(max(0.0, stop_epoch - time.time()) + float(CFG["benchmark_http_timeout_seconds"]) + 0.75)

    def metrics_one(replica_id: str) -> tuple[str, dict[str, Any]]:
        return replica_id, control_pod(pod_names[replica_id], "metrics")

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(pod_names)) as pool:
        metrics = dict(pool.map(metrics_one, sorted(pod_names)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(pod_names)) as pool:
        list(pool.map(lambda rid: control_pod(pod_names[rid], "stop", {}), sorted(pod_names)))
    medium_metrics = medium_control("metrics")
    return {
        "start_epoch": start_epoch, "stop_epoch": stop_epoch, "configured": configured,
        "pod_metrics": metrics, "flow_configs": configs,
        "wireless_medium_config": medium_cfg, "wireless_medium_metrics": medium_metrics,
    }


def aggregate_metrics_for_scenario(
    problem: ProblemInstance, placement: Mapping[str, str], run: Mapping[str, Any], scenario: Scenario,
) -> dict[str, Any]:
    node_to_rack = {n.node_id: n.rack_id for n in problem.nodes}
    attempted = success = errors = 0
    duration = float(run["stop_epoch"]) - float(run["start_epoch"])
    if duration <= 0:
        raise RuntimeError(f"invalid measured duration: {duration}")
    expected_scheduled = 0
    for configs in run.get("flow_configs", {}).values():
        for cfg in configs:
            rate = float(cfg["rate_rps"])
            expected_scheduled += int(math.ceil(max(0.0, duration * rate - 1e-12)))
    flow_by_id = {f.flow_id: f for f in problem.flows}
    for source, metrics in run["pod_metrics"].items():
        for flow_id, row in metrics.get("flows", {}).items():
            a = int(row.get("attempted", 0)); s = int(row.get("success", 0)); e = int(row.get("errors", 0))
            attempted += a; success += s; errors += e
    if expected_scheduled <= 0:
        raise RuntimeError("scheduled offered request count is zero")
    if success > expected_scheduled:
        raise RuntimeError(
            f"successful requests ({success}) exceed frozen scheduled offered count ({expected_scheduled})"
        )
    return {
        "scenario_id": scenario.scenario_id,
        "expected_scheduled_requests": expected_scheduled,
        "attempted_requests": attempted,
        "successful_requests": success,
        "errors": errors,
        "scheduled_completion_fraction": success / expected_scheduled,
    }


def run_weighted_multi_scenario_cell(
    problem: ProblemInstance, placement: Mapping[str, str], run_id_base: str, seconds_per_scenario: int,
) -> dict[str, Any]:
    """Run one graph/placement cell under every frozen scenario and combine the
    resulting scheduled_completion_fraction with the same normalized weights
    load_frozen_scenarios() assigns for the CVaR-robust objective, so the
    composite endpoint reflects the actual distribution of conditions B+ is
    optimized against, not only the single scenario the original protocol
    emulates."""
    per_scenario: dict[str, Any] = {}
    weighted_sum = 0.0
    weight_total = 0.0
    for scenario in problem.scenarios:
        run_id = f"{run_id_base}:{scenario.scenario_id}"
        traffic = configure_and_run_for_scenario(problem, placement, run_id, seconds_per_scenario, scenario)
        metrics = aggregate_metrics_for_scenario(problem, placement, traffic, scenario)
        per_scenario[scenario.scenario_id] = {
            "weight": scenario.weight,
            "metrics": metrics,
            "wireless_medium_metrics": traffic.get("wireless_medium_metrics", {}),
        }
        weighted_sum += scenario.weight * metrics["scheduled_completion_fraction"]
        weight_total += scenario.weight
    if weight_total <= 0:
        raise RuntimeError("scenario weights summed to zero")
    composite = weighted_sum / weight_total
    return {
        "run_id_base": run_id_base,
        "composite_scheduled_completion_fraction": composite,
        "per_scenario": per_scenario,
    }


def aggregate_metrics(problem: ProblemInstance, placement: Mapping[str, str], run: Mapping[str, Any]) -> dict[str, Any]:
    """Aggregate application and wireless-emulator endpoints.

    The confirmatory completion endpoint uses the *scheduled offered request count*
    as its denominator rather than only requests that managed to enter urllib.
    This prevents sender back-pressure/timeouts from making a congested method look
    artificially successful merely because fewer requests were attempted.
    """
    node_to_rack = {n.node_id: n.rack_id for n in problem.nodes}
    dense = emulated_dense(problem)
    attempted = success = errors = 0
    attempted_bytes = success_bytes = 0
    cross_attempted_bytes = cross_success_bytes = 0
    offered_airtime = successful_airtime = 0.0
    latencies: list[float] = []
    per_flow = []
    flow_by_id = {f.flow_id: f for f in problem.flows}
    duration = float(run["stop_epoch"]) - float(run["start_epoch"])
    if duration <= 0:
        raise RuntimeError(f"invalid measured duration: {duration}")
    expected_scheduled = 0
    for configs in run.get("flow_configs", {}).values():
        for cfg in configs:
            rate = float(cfg["rate_rps"])
            # Ticks are scheduled at start + k/rate while tick < stop.
            expected_scheduled += int(math.ceil(max(0.0, duration * rate - 1e-12)))

    for source, metrics in run["pod_metrics"].items():
        for flow_id, row in metrics.get("flows", {}).items():
            flow = flow_by_id[flow_id]
            a = int(row.get("attempted", 0)); s = int(row.get("success", 0)); e = int(row.get("errors", 0))
            ba = int(row.get("bytes_attempted", 0)); bs = int(row.get("bytes_success", 0))
            attempted += a; success += s; errors += e; attempted_bytes += ba; success_bytes += bs
            latencies.extend(float(x) for x in row.get("latencies_ms", []))
            src_node = placement[flow.source_replica]; dst_node = placement[flow.destination_replica]
            cross = src_node != dst_node
            flow_air_attempt = flow_air_success = 0.0
            if cross:
                src_rack = node_to_rack[src_node]; dst_rack = node_to_rack[dst_node]
                link = dense.links[(src_rack, dst_rack)]
                flow_air_attempt = ba * 8.0 / link.goodput_bps
                flow_air_success = bs * 8.0 / link.goodput_bps
                cross_attempted_bytes += ba; cross_success_bytes += bs
                offered_airtime += flow_air_attempt; successful_airtime += flow_air_success
            per_flow.append({
                "flow_id": flow_id, "source": flow.source_replica, "destination": flow.destination_replica,
                "attempted": a, "success": s, "errors": e, "bytes_attempted": ba, "bytes_success": bs,
                "cross_rack": cross, "offered_airtime_seconds": flow_air_attempt,
                "successful_airtime_seconds": flow_air_success,
                "p95_ms": nearest_rank(row.get("latencies_ms", []), 0.95),
            })
    if expected_scheduled <= 0:
        raise RuntimeError("scheduled offered request count is zero")
    if success > expected_scheduled:
        raise RuntimeError(
            f"successful requests ({success}) exceed frozen scheduled offered count ({expected_scheduled})"
        )
    budget = float(dense.conflict_budgets_seconds.get("cg-shared", 15.0))
    projected_offered = offered_airtime * (60.0 / duration)
    projected_success = successful_airtime * (60.0 / duration)
    return {
        "expected_scheduled_requests": expected_scheduled,
        "attempted_requests": attempted,
        "successful_requests": success,
        "errors": errors,
        "scheduled_completion_fraction": success / expected_scheduled,
        "attempt_fraction": attempted / expected_scheduled,
        "attempt_success_fraction": (success / attempted if attempted else 0.0),
        # Compatibility alias; the confirmatory report treats this as scheduled completion.
        "flow_success_fraction": success / expected_scheduled,
        "attempted_bytes": attempted_bytes,
        "successful_bytes": success_bytes,
        "cross_rack_attempted_bytes": cross_attempted_bytes,
        "cross_rack_successful_bytes": cross_success_bytes,
        "offered_airtime_seconds": offered_airtime,
        "successful_airtime_seconds": successful_airtime,
        "projected_60s_offered_airtime_seconds": projected_offered,
        "projected_60s_successful_airtime_seconds": projected_success,
        "projected_offered_conflict_utilization": (projected_offered / budget if budget else math.nan),
        "projected_successful_conflict_utilization": (projected_success / budget if budget else math.nan),
        "p50_ms": nearest_rank(latencies, 0.50),
        "p95_ms": nearest_rank(latencies, 0.95),
        "p99_ms": nearest_rank(latencies, 0.99),
        "mean_ms": (statistics.fmean(latencies) if latencies else None),
        "per_flow": per_flow,
    }


def new_or_existing_run() -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    if CURRENT_RUN_FILE.exists():
        rel = CURRENT_RUN_FILE.read_text(encoding="utf-8").strip()
        path = EXP_ROOT / rel
        if path.exists():
            return path
    run_id = "run-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_root = RESULTS / run_id
    run_root.mkdir(parents=True, exist_ok=False)
    CURRENT_RUN_FILE.write_text(str(run_root.relative_to(EXP_ROOT)), encoding="utf-8")
    return run_root


def freeze_run(run_root: Path, pf: Mapping[str, Any], info: Mapping[str, Any], image: Mapping[str, Any]) -> None:
    frozen = run_root / "frozen"
    frozen.mkdir(parents=True, exist_ok=True)
    files = [
        EXP_ROOT / "config" / "experiment.json",
        EXP_ROOT / "config" / "kind-cluster-config.yaml",
        CANONICAL_TRACE_FILE,
        EXP_ROOT / "requirements-runner.txt",
        EXP_ROOT / "protocol" / "LIVE_CONFIRMATORY_PROTOCOL_FROZEN.md",
        EXP_ROOT / "src" / "live_confirmatory.py",
        EXP_ROOT / "src" / "affinity_exact.py",
        EXP_ROOT / "benchmark" / "benchmark_service.py",
        EXP_ROOT / "benchmark" / "bench_control.py",
        EXP_ROOT / "benchmark" / "wireless_medium.py",
        EXP_ROOT / "benchmark" / "medium_control.py",
        EXP_ROOT / "benchmark" / "Dockerfile",
    ]
    files.extend(sorted((REPO_ROOT / "implementation" / "code" / "mape_cap_bplus").glob("*.py")))
    atomic_json(frozen / "preexecution_manifest.json", {
        "frozen_utc": utc_now(),
        "files_sha256": {str(p.relative_to(REPO_ROOT)): sha256_file(p) for p in files},
        "preflight": pf, "cluster": info, "image": image,
    })

def planning_bundle(run_root: Path, seed: int, target: float, info: Mapping[str, Any]) -> tuple[ProblemInstance, dict[str, Any], dict[str, Any]]:
    path = run_root / "plans" / f"target-{target:.2f}" / f"seed-{seed}.json"
    problem, calibration = build_problem(seed, info, target)
    plans = plan_methods(problem)
    payload = {"seed": seed, "target": target, "calibration": calibration, "plans": plans}
    if path.exists():
        prior = json.loads(path.read_text(encoding="utf-8"))
        current = json.loads(json.dumps(payload, default=_json_default))
        if prior != current:
            raise RuntimeError(f"recomputed frozen planning bundle changed: {path}")
    else:
        atomic_json(path, payload)
    return problem, plans, calibration


def method_order(seed: int, target: float) -> list[str]:
    methods = list(CFG["methods"])
    random.Random(int(CFG["method_order_seed"]) + seed * 17 + int(round(target * 100))).shuffle(methods)
    return methods


def existing_accepted(cell_root: Path) -> dict[str, Any] | None:
    for path in sorted(cell_root.glob("attempt-*/result.json")):
        row = json.loads(path.read_text(encoding="utf-8"))
        if row.get("accepted_infrastructure"):
            return row
    return None


def run_cell(
    run_root: Path, seed: int, target: float, method: str, problem: ProblemInstance,
    plan: Mapping[str, Any], info: Mapping[str, Any], *, smoke: bool = False,
) -> dict[str, Any]:
    group = "smoke" if smoke else "confirmatory"
    cell_root = run_root / group / f"target-{target:.2f}" / f"seed-{seed}" / method
    prior = existing_accepted(cell_root)
    if prior is not None:
        return prior
    attempts = []
    for d in cell_root.glob("attempt-*"):
        try: attempts.append(int(d.name.split("-")[-1]))
        except ValueError: pass
    attempt = max(attempts, default=0) + 1
    attempt_root = cell_root / f"attempt-{attempt:02d}"
    attempt_root.mkdir(parents=True, exist_ok=False)
    run_id = f"{group}:seed{seed}:target{target:.2f}:{method}:attempt{attempt}"
    partial: dict[str, Any] = {}
    try:
        relocation = apply_placement(problem, plan["placement"], run_id)
        time.sleep(float(CFG["settle_seconds"]))
        seconds = 10 if smoke else int(CFG["measurement_seconds"])
        traffic = configure_and_run(problem, plan["placement"], run_id, seconds)
        metrics = aggregate_metrics(problem, plan["placement"], traffic)
        health = deployment_health(problem)
        expected_cross = any(
            plan["placement"][f.source_replica] != plan["placement"][f.destination_replica]
            for f in problem.flows
        )
        medium_metrics = traffic.get("wireless_medium_metrics", {}).get("metrics", {})
        if metrics["attempted_requests"] <= 0:
            raise RuntimeError("benchmark generated zero attempts; infrastructure result rejected")
        if expected_cross and int(medium_metrics.get("requests", 0)) <= 0:
            raise RuntimeError("wireless-medium observed zero requests despite expected cross-rack traffic")
        if not health["healthy"]:
            raise RuntimeError(f"deployment health failed after traffic: {health}")
        partial = {
            "run_id": run_id, "seed": seed, "target_current_utilization": target,
            "method": method, "kind": group, "completed_utc": utc_now(),
            "plan": plan, "relocation": relocation,
            "traffic": traffic, "metrics": metrics,
            "wireless_medium": traffic.get("wireless_medium_metrics", {}),
            "health": health,
            "accepted_infrastructure": True,
            "performance_threshold_used_for_acceptance": False,
            "evidence_type": "kubernetes-shared-medium-emulator-live-confirmatory",
        }
        atomic_json(attempt_root / "result.json", partial)
        return partial
    except Exception as exc:
        atomic_json(attempt_root / "failure.json", {
            "run_id": run_id, "failed_utc": utc_now(), "error": f"{type(exc).__name__}: {exc}",
            "partial": partial, "accepted_infrastructure": False,
        })
        raise
    finally:
        # Stop traffic best-effort and always remove network shaping.
        try:
            _, _, pods = pod_service_ips(problem)
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(pods)) as pool:
                list(pool.map(lambda rid: control_pod(pods[rid], "stop", {}), sorted(pods)))
        except Exception:
            pass



def run_with_retries(*args, **kwargs) -> dict[str, Any]:
    last = None
    for n in range(1, int(CFG["max_cell_attempts"]) + 1):
        try:
            return run_cell(*args, **kwargs)
        except Exception as exc:
            last = exc
            print(f"    infrastructure attempt {n} failed: {exc}", flush=True)
            time.sleep(5)
    raise RuntimeError(f"cell exhausted infrastructure retries: {last}") from last


def smoke_gate(run_root: Path, info: Mapping[str, Any]) -> None:
    marker = run_root / "smoke" / "SMOKE_PASSED.json"
    if marker.exists():
        return
    seed = int(CFG["specificity_seeds"][0])
    target = float(CFG["specificity_target_current_utilization"])
    problem, plans, calibration = planning_bundle(run_root, seed, target, info)
    row = run_with_retries(run_root, seed, target, "Current", problem, plans["Current"], info, smoke=True)
    if row["metrics"]["flow_success_fraction"] <= 0:
        raise RuntimeError("smoke traffic produced no successful requests")
    atomic_json(marker, {"passed_utc": utc_now(), "run_id": row["run_id"], "calibration": calibration})


def execute() -> Path:
    pf = preflight()
    info = ensure_cluster()
    image = ensure_benchmark_image()
    ensure_namespace()
    medium = ensure_wireless_medium(info)
    run_root = new_or_existing_run()
    if not (run_root / "frozen" / "preexecution_manifest.json").exists():
        freeze_run(run_root, pf, info, {**image, "wireless_medium": medium})
    smoke_gate(run_root, info)
    schedule = [(float(CFG["primary_target_current_utilization"]), int(seed)) for seed in CFG["held_out_seeds"]]
    schedule += [(float(CFG["specificity_target_current_utilization"]), int(seed)) for seed in CFG["specificity_seeds"]]
    for target, seed in schedule:
        problem, plans, calibration = planning_bundle(run_root, seed, target, info)
        print(
            f"Seed {seed}, target {target:.2f}, rates {calibration['min_rate_mbit']:.2f}–{calibration['max_rate_mbit']:.2f} Mbit/s",
            flush=True,
        )
        for method in method_order(seed, target):
            print(f"  {method}", flush=True)
            run_with_retries(run_root, seed, target, method, problem, plans[method], info, smoke=False)
    analyze(run_root)
    return run_root


def load_cells(run_root: Path) -> pd.DataFrame:
    rows = []
    for path in sorted((run_root / "confirmatory").glob("target-*/seed-*/*/attempt-*/result.json")):
        d = json.loads(path.read_text(encoding="utf-8"))
        if not d.get("accepted_infrastructure"):
            continue
        m = d["metrics"]
        p = d["plan"]
        rows.append({
            "seed": int(d["seed"]), "target": float(d["target_current_utilization"]), "method": d["method"],
            "completion_fraction": float(m["scheduled_completion_fraction"]),
            "attempt_success_fraction": float(m["attempt_success_fraction"]),
            "attempt_fraction": float(m["attempt_fraction"]),
            "expected_scheduled": int(m["expected_scheduled_requests"]),
            "attempted": int(m["attempted_requests"]), "successful": int(m["successful_requests"]),
            "errors": int(m["errors"]), "p50_ms": m["p50_ms"], "p95_ms": m["p95_ms"], "p99_ms": m["p99_ms"],
            "offered_cross_rack_bytes": int(m["cross_rack_attempted_bytes"]),
            "successful_cross_rack_bytes": int(m["cross_rack_successful_bytes"]),
            "offered_conflict_utilization": float(m["projected_offered_conflict_utilization"]),
            "successful_conflict_utilization": float(m["projected_successful_conflict_utilization"]),
            "medium_requests": int(d.get("wireless_medium", {}).get("metrics", {}).get("requests", 0)),
            "medium_errors": int(d.get("wireless_medium", {}).get("metrics", {}).get("errors", 0)),
            "medium_modeled_airtime_seconds": float(d.get("wireless_medium", {}).get("metrics", {}).get("modeled_airtime_seconds", 0.0)),
            "medium_serialized_service_seconds": float(d.get("wireless_medium", {}).get("metrics", {}).get("serialized_service_seconds", 0.0)),
            "planned_feasible": bool(p["planned_feasible"]), "planner_abstained": bool(p["planner_abstained"]),
            "planned_worst_util": float(p["worst_conflict_utilization"]), "planned_cross_rack_bits": float(p["cross_rack_bits"]),
            "moves": int(p["moves"]), "rollout_seconds": float(d["relocation"]["rollout_seconds"]),
            "result_path": str(path.relative_to(run_root)),
        })
    return pd.DataFrame(rows)


def paired_bootstrap(diff: np.ndarray, n: int, seed: int) -> tuple[float, float, float]:
    x = np.asarray(diff, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return math.nan, math.nan, math.nan
    rng = np.random.default_rng(seed)
    chunks = []
    remain = n
    while remain:
        m = min(5000, remain)
        idx = rng.integers(0, len(x), size=(m, len(x)))
        chunks.append(x[idx].mean(axis=1))
        remain -= m
    boot = np.concatenate(chunks)
    return float(x.mean()), float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975))


def safe_wilcoxon(diff: np.ndarray, alternative: str) -> float:
    x = np.asarray(diff, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) == 0 or np.allclose(x, 0):
        return 1.0
    return float(wilcoxon(x, zero_method="wilcox", alternative=alternative, method="auto").pvalue)


def analyze(run_root: Path) -> dict[str, Any]:
    df = load_cells(run_root)
    if df.empty:
        raise RuntimeError("no accepted confirmatory cells")
    df.to_csv(run_root / "analysis_cells.csv", index=False)
    primary_target = float(CFG["primary_target_current_utilization"])
    p = df[np.isclose(df.target, primary_target)]
    required_seeds = set(int(s) for s in CFG["held_out_seeds"])
    for method in ("BPlus-Exact", "Affinity-Bytes", "Current"):
        got = set(int(x) for x in p[p.method == method].seed)
        missing = sorted(required_seeds - got)
        if missing:
            raise RuntimeError(f"analysis incomplete for {method}; missing primary seeds {missing}")
    pivot = p.pivot(index="seed", columns="method", values="completion_fraction")
    paired = pivot.dropna(subset=["BPlus-Exact", "Affinity-Bytes"])
    diff = paired["BPlus-Exact"].to_numpy(float) - paired["Affinity-Bytes"].to_numpy(float)
    mean_diff, ci_lo, ci_hi = paired_bootstrap(diff, int(CFG["bootstrap_resamples"]), int(CFG["bootstrap_seed"]))
    p_w = safe_wilcoxon(diff, "greater")

    fp = p.pivot(index="seed", columns="method", values="planned_feasible").dropna(subset=["BPlus-Exact", "Affinity-Bytes"])
    fb = fp["BPlus-Exact"].astype(bool); fa = fp["Affinity-Bytes"].astype(bool)
    bo = int((fb & ~fa).sum()); ao = int((~fb & fa).sum()); discord = bo + ao
    p_disc = float(binomtest(bo, discord, 0.5, alternative="greater").pvalue) if discord else 1.0

    summary = df.groupby(["target", "method"], dropna=False).agg(
        n=("seed", "size"), mean_completion_fraction=("completion_fraction", "mean"), mean_attempt_fraction=("attempt_fraction", "mean"),
        median_p95_ms=("p95_ms", "median"), mean_offered_util=("offered_conflict_utilization", "mean"),
        mean_successful_util=("successful_conflict_utilization", "mean"),
        mean_cross_rack_bytes=("offered_cross_rack_bytes", "mean"),
        mean_medium_requests=("medium_requests", "mean"), mean_medium_errors=("medium_errors", "mean"),
        mean_medium_modeled_airtime_s=("medium_modeled_airtime_seconds", "mean"),
        planned_feasible_rate=("planned_feasible", "mean"), abstention_rate=("planner_abstained", "mean"),
        mean_moves=("moves", "mean"),
    ).reset_index()
    summary.to_csv(run_root / "summary.csv", index=False)

    primary = {
        "endpoint": "scheduled_completion_fraction",
        "n_paired_held_out_graphs": int(len(paired)),
        "mean_bplus_minus_affinity": mean_diff,
        "bootstrap95_low": ci_lo, "bootstrap95_high": ci_hi,
        "one_sided_wilcoxon_p_bplus_greater": p_w,
        "primary_hypothesis_supported": bool(math.isfinite(mean_diff) and mean_diff > 0 and p_w < 0.05),
        "planned_feasibility_bplus_only": bo, "planned_feasibility_affinity_only": ao,
        "planned_feasibility_one_sided_exact_p": p_disc,
    }
    result = {
        "analyzed_utc": utc_now(), "primary": primary,
        "evidence_boundary": "live Kind + deterministic in-cluster shared-medium emulator; not physical RF",
    }
    atomic_json(run_root / "PRIMARY_RESULT.json", result)
    lines = [
        "# Live Kubernetes Confirmatory Experiment Report", "",
        f"Run: `{run_root.name}`", "",
        "## Evidence boundary", "Live Kubernetes on a dedicated three-worker Kind cluster with a deterministic in-cluster shared-medium emulator implementing the frozen directed-goodput and conflict-budget semantics. This is not physical 60-GHz/RF measurement.", "",
        "## Primary hypothesis", "B+ Exact achieves a higher scheduled-request completion fraction than Affinity-Bytes at the Current-calibrated 1.25 contention target.", "",
        f"Paired held-out graphs: **{primary['n_paired_held_out_graphs']}**", f"Mean B+ − Affinity completion-fraction difference: **{mean_diff:.6g}**",
        f"Bootstrap 95% CI: **[{ci_lo:.6g}, {ci_hi:.6g}]**", f"One-sided Wilcoxon p: **{p_w:.6g}**",
        f"Primary hypothesis supported: **{primary['primary_hypothesis_supported']}**", "",
        "## Planned-feasibility mechanism", f"B+-only feasible graphs: **{bo}**", f"Affinity-only feasible graphs: **{ao}**", f"One-sided exact discordance p: **{p_disc:.6g}**", "",
        "## Summary", "", summary.to_markdown(index=False), "",
        "## Interpretation boundary", "A favorable result supports value beyond byte affinity under the emulated wireless-capacity/conflict model. It does not establish physical RF interference reduction or universal superiority.",
    ]
    (run_root / "FINAL_REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    write_manifest(run_root)
    return result


def write_manifest(run_root: Path) -> None:
    lines = []
    for path in sorted(run_root.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS.txt":
            lines.append(f"{sha256_file(path)}  {path.relative_to(run_root).as_posix()}")
    (run_root / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def local_self_test() -> dict[str, Any]:
    scenarios = load_frozen_scenarios()
    dense = next(s for s in scenarios if s.scenario_id == "conflict-dense")
    if set(dense.conflict_budgets_seconds) != {"cg-shared"}:
        raise RuntimeError("conflict-dense shared budget missing")
    held = list(CFG["held_out_seeds"])
    if held != list(range(44001, 44031)) or len(set(held)) != 30:
        raise RuntimeError("held-out seed block changed")
    prior = set(range(11001, 11051)) | set(range(22001, 22051)) | set(range(33001, 33051))
    if prior.intersection(held):
        raise RuntimeError("held-out seeds overlap prior computational confirmation")
    # Validate generated flow payloads are executable and current placement has at most 3 CPU / 2 GiB per generated node.
    max_cpu = max_mem = 0.0
    for seed in held:
        p = generate_problem(replica_count=6, rack_count=3, nodes_per_rack=1, scenario_count=3, seed=seed)
        by_node = {n.node_id: [0.0, 0.0] for n in p.nodes}
        for r in p.replicas:
            node = p.current_placement[r.replica_id]
            by_node[node][0] += r.cpu_request; by_node[node][1] += r.memory_request_mb
        max_cpu = max(max_cpu, *(x[0] for x in by_node.values()))
        max_mem = max(max_mem, *(x[1] for x in by_node.values()))
        for f in p.flows:
            if f.requests_per_window <= 0 or f.bits_per_window <= 0:
                raise RuntimeError(f"invalid flow in seed {seed}")
            payload = (f.bits_per_window / 8.0) / f.requests_per_window
            if payload > 100_000:
                raise RuntimeError(f"unexpected payload >100kB in seed {seed}: {payload}")
    if CFG.get("network_emulation_mode") != "shared-medium-proxy":
        raise RuntimeError("confirmatory network emulation mode is not shared-medium-proxy")
    duty = float(dense.conflict_budgets_seconds["cg-shared"]) / 60.0
    if not math.isclose(duty, 0.25, rel_tol=0, abs_tol=1e-12):
        raise RuntimeError(f"unexpected shared-medium duty fraction: {duty}")
    return {"passed": True, "held_out_seeds": [min(held), max(held)], "max_current_cpu_per_node": max_cpu, "max_current_memory_mb_per_node": max_mem, "shared_medium_duty_fraction": duty, "timestamp_utc": utc_now()}


def offline_planning_audit() -> dict[str, Any]:
    """Static audit using conservative reference node capacities; produces no live outcome."""
    info = {
        "rack_to_worker": {"rack-a": "worker-a", "rack-b": "worker-b", "rack-c": "worker-c"},
        "allocatable": {w: {"cpu": 4.0, "memory_mb": 3500.0} for w in ("worker-a", "worker-b", "worker-c")},
    }
    rows = []
    for seed in CFG["held_out_seeds"]:
        problem, calibration = build_problem(int(seed), info, float(CFG["primary_target_current_utilization"]))
        plans = plan_methods(problem)
        rows.append({
            "seed": int(seed), **calibration,
            "affinity_feasible": plans["Affinity-Bytes"]["planned_feasible"],
            "affinity_util": plans["Affinity-Bytes"]["worst_conflict_utilization"],
            "bplus_feasible": plans["BPlus-Exact"]["planned_feasible"],
            "bplus_abstained": plans["BPlus-Exact"]["planner_abstained"],
            "bplus_util": plans["BPlus-Exact"]["worst_conflict_utilization"],
        })
    return {"reference_node_capacity": {"cpu": 4.0, "memory_mb": 3500.0}, "rows": rows}


def clean_network() -> None:
    # v1.1 keeps all emulation state inside the wireless-medium service.
    return


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["self-test", "offline-audit", "preflight", "prepare", "run", "analyze", "clean-network"])
    parser.add_argument("--run-root", type=Path)
    args = parser.parse_args()
    if args.command == "self-test":
        print(json.dumps(local_self_test(), indent=2)); return 0
    if args.command == "offline-audit":
        print(json.dumps(offline_planning_audit(), indent=2, default=_json_default)); return 0
    if args.command == "preflight":
        print(json.dumps(preflight(), indent=2)); return 0
    if args.command == "prepare":
        pf = preflight(); info = ensure_cluster(); image = ensure_benchmark_image(); ensure_namespace(); medium = ensure_wireless_medium(info)
        print(json.dumps({"preflight": pf, "cluster": info, "image": image, "wireless_medium": medium}, indent=2)); return 0
    if args.command == "run":
        run_root = execute(); print(f"\nCOMPLETE: {run_root}"); return 0
    if args.command == "analyze":
        run_root = args.run_root or new_or_existing_run(); print(json.dumps(analyze(run_root), indent=2)); return 0
    if args.command == "clean-network":
        clean_network(); print("no external network-emulation state to clear"); return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
