#!/usr/bin/env python3
"""Three-host k3s replication of the frozen N5 S1 application experiment.

Purpose: isolate the single-host limitation. The 20 original S1 graph identities,
placements, tau=1.25 calibration, executed wireless state, traffic generator,
shared-medium emulator, measurement window and endpoints are replayed on three
separate Kubernetes hosts. Planner decisions are NOT recomputed using the small
follow-up machines' capacities.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import random
import re
import shutil
import subprocess
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / "frozen"
EXP = FROZEN / "EXPERIMENTS" / "k8s_affinity_wireless_confirmatory"
sys.path.insert(0, str(EXP / "src"))
sys.path.insert(0, str(FROZEN / "implementation" / "code"))

import live_confirmatory as lc  # noqa: E402

CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
SOURCE = json.loads((FROZEN / "N5_source" / "original_n5_enrolled.json").read_text(encoding="utf-8"))
SOURCE_S1 = {int(x["seed"]): x for x in SOURCE["enrolled"]["S1"]}
SOURCE_CLUSTER = SOURCE["cluster"]
OUT = ROOT / "results"
OPLOG = ROOT / "operator_logs"

# Redirect only runtime cluster/image paths; frozen scientific code remains unchanged.
try:
    current_context = subprocess.run(
        ["kubectl", "config", "current-context"], capture_output=True, text=True, timeout=20, check=True
    ).stdout.strip()
except Exception:
    current_context = "default"
lc.CONTEXT = os.environ.get("KUBE_CONTEXT", current_context or "default")
lc.NS = CFG["namespace"]
lc.IMAGE = CFG["benchmark_image"]
lc.CANONICAL_TRACE_FILE = FROZEN / "RESULTS" / "calibration" / "external" / "ns3_simulation_backed_traces.csv"
lc.CFG = {
    **lc.CFG,
    "namespace": CFG["namespace"],
    "benchmark_image": CFG["benchmark_image"],
    "settle_seconds": CFG["settle_seconds"],
}

METHODS = tuple(CFG["methods"])
RISK = lc.RISK
TIMEOUT_MS = 1000.0 * float(lc.CFG["benchmark_http_timeout_seconds"])


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def dump(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, default=lc._json_default), encoding="utf-8")
    os.replace(tmp, path)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def node_ready(node: Mapping[str, Any]) -> bool:
    return any(c.get("type") == "Ready" and c.get("status") == "True" for c in node.get("status", {}).get("conditions", []))


def internal_ip(node: Mapping[str, Any]) -> str:
    for a in node.get("status", {}).get("addresses", []):
        if a.get("type") == "InternalIP":
            return str(a.get("address", ""))
    return ""


def cluster_info() -> dict[str, Any]:
    obj = lc.kubectl_json("get", "nodes")
    items = obj.get("items", [])
    if len(items) != 3:
        raise RuntimeError(f"expected exactly 3 Kubernetes nodes, found {len(items)}: {[x['metadata']['name'] for x in items]}")
    rack_to_node: dict[str, str] = {}
    node_rows = []
    server_node = None
    for n in items:
        name = n["metadata"]["name"]
        labels = n["metadata"].get("labels", {})
        rack = labels.get("mape-cap-ws/rack") or labels.get("topology.kubernetes.io/zone")
        if rack in ("rack-a", "rack-b", "rack-c"):
            if rack in rack_to_node:
                raise RuntimeError(f"duplicate rack label {rack}")
            rack_to_node[rack] = name
        if labels.get("mape-cap-ws/role") == "server":
            server_node = name
        alloc = n.get("status", {}).get("allocatable", {})
        cpu = lc.parse_cpu(alloc.get("cpu", "0"))
        mem = lc.parse_mem_mb(alloc.get("memory", "0"))
        conds = {c.get("type"): c.get("status") for c in n.get("status", {}).get("conditions", [])}
        pressure = {k: conds.get(k, "Unknown") for k in ("MemoryPressure", "DiskPressure", "PIDPressure")}
        row = {
            "name": name,
            "rack": rack,
            "server": labels.get("mape-cap-ws/role") == "server",
            "internal_ip": internal_ip(n),
            "ready": node_ready(n),
            "pressure": pressure,
            "cpu": cpu,
            "memory_mb": mem,
            "kubelet_version": n.get("status", {}).get("nodeInfo", {}).get("kubeletVersion", ""),
            "provider_id": n.get("spec", {}).get("providerID", ""),
            "architecture": n.get("status", {}).get("nodeInfo", {}).get("architecture", ""),
            "operating_system": n.get("status", {}).get("nodeInfo", {}).get("operatingSystem", ""),
        }
        node_rows.append(row)
        if not row["ready"]:
            raise RuntimeError(f"node not Ready: {name}")
        bad_pressure = [k for k, v in pressure.items() if v == "True"]
        if bad_pressure:
            raise RuntimeError(f"node {name} reports pressure condition(s): {bad_pressure}")
        is_server = labels.get("mape-cap-ws/role") == "server"
        min_cpu = float(CFG["minimum_server_allocatable_cpu"] if is_server else CFG["minimum_agent_allocatable_cpu"])
        min_mem = float(CFG["minimum_server_allocatable_memory_mb"] if is_server else CFG["minimum_agent_allocatable_memory_mb"])
        if cpu < min_cpu or mem < min_mem:
            raise RuntimeError(
                f"node {name} below frozen execution minimum for {'server' if is_server else 'agent'}: "
                f"cpu={cpu:.3f}, memory={mem:.1f} MiB; need >= {min_cpu} CPU and >= {min_mem} MiB"
            )
        if row["kubelet_version"] != CFG["expected_kubelet_version"]:
            raise RuntimeError(
                f"node {name} kubelet {row['kubelet_version']} != frozen {CFG['expected_kubelet_version']}"
            )
        if row["architecture"] != CFG["expected_node_architecture"] or row["operating_system"] != CFG["expected_node_os"]:
            raise RuntimeError(
                f"node {name} platform {row['operating_system']}/{row['architecture']} != frozen "
                f"{CFG['expected_node_os']}/{CFG['expected_node_architecture']}"
            )
    if set(rack_to_node) != {"rack-a", "rack-b", "rack-c"}:
        raise RuntimeError(f"rack labels must be exactly rack-a/rack-b/rack-c; got {rack_to_node}")
    if server_node is None:
        server_node = rack_to_node["rack-a"]
    if server_node != rack_to_node["rack-a"]:
        raise RuntimeError("server/control-plane must be the rack-a node for this frozen follow-up")
    ips = [r["internal_ip"] for r in node_rows]
    if any(not x for x in ips) or len(set(ips)) != 3:
        raise RuntimeError(f"three distinct InternalIP addresses required, got {ips}")
    return {
        "server_node": server_node,
        "control_plane": server_node,
        "rack_to_node": rack_to_node,
        "rack_to_worker": rack_to_node,  # compatibility with frozen harness
        "nodes": sorted(node_rows, key=lambda x: x["rack"] or ""),
        "kube_context": lc.CONTEXT,
    }


def old_node_to_rack() -> dict[str, str]:
    return {node: rack for rack, node in SOURCE_CLUSTER["rack_to_worker"].items()}


def build_problem(seed: int, info: Mapping[str, Any]):
    """Reconstruct the original N5 planning problem using original node capacities.

    Only node IDs are mapped from the old Kind workers to current Kubernetes/VM hosts.
    """
    src = SOURCE_S1[seed]
    tau = float(src["tau"])
    g = lc.generate_problem(replica_count=6, rack_count=3, nodes_per_rack=1, scenario_count=3,
                            seed=seed, decision_window_seconds=60.0)
    alias = {"rack-0": "rack-a", "rack-1": "rack-b", "rack-2": "rack-c"}
    generated_nodes = sorted(g.nodes, key=lambda n: n.rack_id)
    node_map = {n.node_id: info["rack_to_node"][alias[n.rack_id]] for n in generated_nodes}
    # Preserve the original N5 planner capacities; current tiny VMs are execution hosts only.
    old_by_rack = SOURCE_CLUSTER["rack_to_worker"]
    nodes = []
    for n in generated_nodes:
        rack = alias[n.rack_id]
        old = old_by_rack[rack]
        cap = SOURCE_CLUSTER["allocatable"][old]
        nodes.append(lc.NodeSpec(node_map[n.node_id], rack, cap["cpu"] * 0.95, cap["memory_mb"] * 0.95))
    nodes = tuple(nodes)
    allowed = tuple(n.node_id for n in nodes)
    reps = tuple(replace(r, allowed_nodes=allowed) for r in g.replicas)
    cur = {rid: node_map[nid] for rid, nid in g.current_placement.items()}
    reloc = {
        r.replica_id: lc.RelocationCost(r.replica_id, 4062.0, 4.062, 690.0, provenance="frozen Kind relocation pilot")
        for r in reps
    }
    base = replace(
        g, nodes=nodes, replicas=reps, current_placement=cur,
        scenarios=lc.load_frozen_scenarios(), relocation_costs=reloc,
        metadata={**g.metadata, "multihost_replay_seed": seed, "source_protocol": "N5-S1"},
    )
    u0 = lc.max_conflict_util(base, base.current_placement)
    if not math.isfinite(u0) or u0 <= 0:
        raise RuntimeError(f"invalid original Current utilization for seed {seed}: {u0}")
    scale = u0 / tau
    scenarios = tuple(
        replace(sc, links={k: replace(link, goodput_bps=link.goodput_bps * scale) for k, link in sc.links.items()})
        for sc in base.scenarios
    )
    plan_problem = replace(base, scenarios=scenarios, metadata={**base.metadata, "tau": tau, "goodput_scale": scale})

    old_to_rack = old_node_to_rack()
    plans = {}
    for method in METHODS:
        old_plan = src["plans"][method]
        plans[method] = {rid: info["rack_to_node"][old_to_rack[old_node]] for rid, old_node in old_plan.items()}

    # Verify the replay still represents the exact original S1 planning contrast.
    if abs(lc.max_conflict_util(plan_problem, plan_problem.current_placement) - tau) > 1e-8:
        raise RuntimeError(f"seed {seed}: Current tau reconstruction mismatch")
    if lc.evaluate_placement(plan_problem, plans["Affinity-Bytes"], RISK).feasible:
        raise RuntimeError(f"seed {seed}: Affinity-Bytes unexpectedly feasible")
    for m in ("Affinity-Bytes+Admission", "MAPE-CAP-WS"):
        if not lc.evaluate_placement(plan_problem, plans[m], RISK).feasible:
            raise RuntimeError(f"seed {seed}: {m} unexpectedly infeasible")
    computed_state = max(
        (lc.scenario_conflict_util(plan_problem, plans["Affinity-Bytes"], s.scenario_id), -i, s.scenario_id)
        for i, s in enumerate(plan_problem.scenarios)
    )[2]
    if computed_state != src["executed_state"]:
        raise RuntimeError(f"seed {seed}: executed-state mismatch {computed_state} != {src['executed_state']}")

    # Execution-only requests are deliberately lightweight so 1-vCPU agents can host multiple services.
    exec_reps = tuple(
        replace(r, cpu_request=float(CFG["execution_cpu_request"]), memory_request_mb=float(CFG["execution_memory_request_mb"]))
        for r in plan_problem.replicas
    )
    exec_problem = replace(
        plan_problem, replicas=exec_reps,
        metadata={**plan_problem.metadata, "execution_resource_mode": "fixed-lightweight-reservations"},
    )
    return plan_problem, exec_problem, plans, src["executed_state"]


def node_metrics() -> dict[str, Any]:
    """Best-effort metrics-server snapshot; never used as a performance acceptance gate."""
    text = lc.kubectl("top", "nodes", "--no-headers", check=False, timeout=30)
    rows = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 5:
            rows.append({"node": parts[0], "cpu": parts[1], "cpu_pct": parts[2], "memory": parts[3], "memory_pct": parts[4]})
    return {"available": bool(rows), "rows": rows, "raw": text.strip()}


def pod_nodes(problem) -> dict[str, str]:
    pods = lc.kubectl_json("get", "pods", "-n", lc.NS)
    out = {}
    for p in pods.get("items", []):
        app = p.get("metadata", {}).get("labels", {}).get("app")
        if app in problem.replica_by_id and not p.get("metadata", {}).get("deletionTimestamp"):
            if p.get("status", {}).get("phase") == "Running" and p.get("spec", {}).get("nodeName"):
                out[app] = p["spec"]["nodeName"]
    return out


def endpoints(run: Mapping[str, Any]) -> dict[str, Any]:
    lat, attempted, success, errors = [], 0, 0, 0
    dur = float(run["stop_epoch"]) - float(run["start_epoch"])
    if dur <= 0:
        raise RuntimeError(f"invalid measured duration: {dur}")
    scheduled = sum(
        int(math.ceil(max(0.0, dur * float(c["rate_rps"]) - 1e-12)))
        for cfgs in run["flow_configs"].values() for c in cfgs
    )
    for metrics in run["pod_metrics"].values():
        for row in metrics.get("flows", {}).values():
            attempted += int(row.get("attempted", 0))
            success += int(row.get("success", 0))
            errors += int(row.get("errors", 0))
            lat.extend(float(x) for x in row.get("latencies_ms", []))
    if scheduled <= 0:
        raise RuntimeError("scheduled offered request count is zero")
    if success > attempted:
        raise RuntimeError(f"successful requests ({success}) exceed attempted requests ({attempted})")
    if success > scheduled:
        raise RuntimeError(f"successful requests ({success}) exceed scheduled requests ({scheduled})")
    missing = max(0, scheduled - attempted)
    sched_lat = lat + [TIMEOUT_MS] * missing
    med = run.get("wireless_medium_metrics", {}).get("metrics", {})
    qw = med.get("queue_wait_ms", []) or []
    return {
        "scheduled": scheduled,
        "attempted": attempted,
        "success": success,
        "errors": errors,
        "scheduled_completion": success / scheduled if scheduled else float("nan"),
        "sched_p50_ms": lc.nearest_rank(sched_lat, 0.50),
        "sched_p95_ms": lc.nearest_rank(sched_lat, 0.95),
        "sched_p99_ms": lc.nearest_rank(sched_lat, 0.99),
        "attempted_p95_ms": lc.nearest_rank(lat, 0.95),
        "medium_requests": int(med.get("requests", 0)),
        "medium_mean_queue_wait_ms": (sum(qw) / len(qw)) if qw else 0.0,
    }


def preflight() -> dict[str, Any]:
    missing = [x for x in ("kubectl",) if shutil.which(x) is None]
    if missing:
        raise RuntimeError(f"missing executable(s): {missing}")
    free_gib = shutil.disk_usage(ROOT).free / 1024**3
    if free_gib < 2.0:
        raise RuntimeError(f"need at least 2 GiB free disk; found {free_gib:.2f}")
    info = cluster_info()
    # Verify all frozen source cases reconstruct before touching workloads.
    checks = []
    for seed in CFG["science_seeds"]:
        p, _, plans, state = build_problem(int(seed), info)
        checks.append({
            "seed": seed, "executed_state": state,
            "affinity_exec_util": lc.scenario_conflict_util(p, plans["Affinity-Bytes"], state),
            "admission_exec_util": lc.scenario_conflict_util(p, plans["Affinity-Bytes+Admission"], state),
            "mape_exec_util": lc.scenario_conflict_util(p, plans["MAPE-CAP-WS"], state),
        })
    out = {
        "utc": utc_now(), "python": platform.python_version(), "platform": platform.platform(),
        "cluster": info, "case_count": len(checks), "cases": checks,
        "execution_resource_requests": {"cpu": CFG["execution_cpu_request"], "memory_mb": CFG["execution_memory_request_mb"]},
    }
    dump(OPLOG / "PREFLIGHT.json", out)
    return out


def image_probe(info: Mapping[str, Any]) -> None:
    # imagePullPolicy Never proves the frozen benchmark image is present on each Kubernetes/VM node.
    docs = []
    for rack, node in info["rack_to_node"].items():
        docs.append({
            "apiVersion": "v1", "kind": "Pod", "metadata": {"name": f"image-probe-{rack}", "namespace": lc.NS},
            "spec": {"restartPolicy": "Never", "nodeName": node, "containers": [{
                "name": "probe", "image": lc.IMAGE, "imagePullPolicy": "Never",
                "command": ["python", "-c", "print('IMAGE_OK')"]
            }]}
        })
    manifest = "\n---\n".join(json.dumps(x) for x in docs) + "\n"
    lc.kubectl("apply", "-f", "-", input_text=manifest, timeout=120)
    try:
        for rack in ("rack-a", "rack-b", "rack-c"):
            deadline = time.time() + 90
            phase = ""
            while time.time() < deadline:
                pod = lc.kubectl_json("get", "pod", f"image-probe-{rack}", "-n", lc.NS)
                phase = pod.get("status", {}).get("phase", "")
                if phase in ("Running", "Succeeded"):
                    break
                if phase == "Failed":
                    break
                time.sleep(2)
            if phase not in ("Running", "Succeeded"):
                detail = lc.kubectl("describe", "pod", f"image-probe-{rack}", "-n", lc.NS, check=False)
                raise RuntimeError(f"image probe {rack} did not start from local image; phase={phase}\n{detail[-2500:]}")
    finally:
        for rack in ("rack-a", "rack-b", "rack-c"):
            lc.kubectl("delete", "pod", f"image-probe-{rack}", "-n", lc.NS, "--ignore-not-found=true", check=False)



def host_fingerprint_probe(info: Mapping[str, Any]) -> dict[str, str]:
    """Verify that rack-a/rack-b/rack-c are backed by distinct Linux host OS instances.

    A short-lived pod is pinned to each Kubernetes node and mounts only the host's
    /etc/machine-id file read-only. Only SHA-256 digests are retained; raw machine IDs
    are never written to the result package.
    """
    docs = []
    for rack, node in info["rack_to_node"].items():
        docs.append({
            "apiVersion": "v1", "kind": "Pod",
            "metadata": {"name": f"host-fingerprint-{rack}", "namespace": lc.NS},
            "spec": {
                "restartPolicy": "Never", "nodeName": node,
                "containers": [{
                    "name": "fingerprint", "image": lc.IMAGE, "imagePullPolicy": "Never",
                    "command": ["python", "-c",
                        "import hashlib; p='/host-etc/machine-id'; "
                        "print(hashlib.sha256(open(p,'rb').read().strip()).hexdigest())"],
                    "volumeMounts": [{"name": "host-etc", "mountPath": "/host-etc", "readOnly": True}],
                }],
                "volumes": [{"name": "host-etc", "hostPath": {"path": "/etc", "type": "Directory"}}],
            },
        })
    manifest = "\n---\n".join(json.dumps(x) for x in docs) + "\n"
    lc.kubectl("apply", "-f", "-", input_text=manifest, timeout=120)
    fingerprints: dict[str, str] = {}
    try:
        for rack in ("rack-a", "rack-b", "rack-c"):
            deadline = time.time() + 90
            phase = ""
            while time.time() < deadline:
                pod = lc.kubectl_json("get", "pod", f"host-fingerprint-{rack}", "-n", lc.NS)
                phase = pod.get("status", {}).get("phase", "")
                if phase in ("Succeeded", "Failed"):
                    break
                time.sleep(2)
            if phase != "Succeeded":
                detail = lc.kubectl("describe", "pod", f"host-fingerprint-{rack}", "-n", lc.NS, check=False)
                raise RuntimeError(f"host fingerprint probe {rack} failed; phase={phase}\n{detail[-2500:]}")
            value = lc.kubectl("logs", f"host-fingerprint-{rack}", "-n", lc.NS, timeout=30).strip().splitlines()[-1].strip()
            if not re.fullmatch(r"[0-9a-f]{64}", value):
                raise RuntimeError(f"invalid host fingerprint for {rack}: {value!r}")
            fingerprints[rack] = value
        if len(set(fingerprints.values())) != 3:
            raise RuntimeError(f"three distinct host machine-id hashes required; got {fingerprints}")
        return fingerprints
    finally:
        for rack in ("rack-a", "rack-b", "rack-c"):
            lc.kubectl("delete", "pod", f"host-fingerprint-{rack}", "-n", lc.NS, "--ignore-not-found=true", check=False)

def cmd_setup() -> None:
    pf = preflight()
    lc.ensure_namespace()
    info = pf["cluster"]
    image_probe(info)
    fingerprints = host_fingerprint_probe(info)
    medium = lc.ensure_wireless_medium(info)
    excluded_parts = {"results", "operator_logs", "operator_private", ".venv", "__pycache__", ".git"}
    files = sorted(
        p for p in ROOT.rglob("*")
        if p.is_file() and not any(part in excluded_parts for part in p.relative_to(ROOT).parts)
        and p.relative_to(ROOT).as_posix() != "cluster/cluster.env"
    )
    manifest = {str(p.relative_to(ROOT)): sha256(p) for p in files}
    dump(OPLOG / "SETUP_PASSED.json", {
        "utc": utc_now(), "cluster": info, "host_machine_id_sha256": fingerprints,
        "medium": medium, "files_sha256": manifest
    })
    print("SETUP PASSED: three distinct Kubernetes/VM hosts verified")


def run_cell(seed: int, method: str, *, pilot: bool = False) -> dict[str, Any]:
    info = cluster_info()
    p_plan, p_exec, plans, state = build_problem(seed, info)
    root = OUT / ("pilot" if pilot else "science") / f"seed-{seed}" / method
    accepted = sorted(root.glob("attempt-*/result.json"))
    if accepted:
        return json.loads(accepted[0].read_text(encoding="utf-8"))
    n = len(list(root.glob("attempt-*"))) + 1
    ar = root / f"attempt-{n:02d}"
    ar.mkdir(parents=True, exist_ok=False)
    run_id = f"mh:{'pilot' if pilot else 'science'}:seed{seed}:{method}:attempt{n}"
    placement = plans[method]
    try:
        before_nodes = cluster_info()
        metrics_before = node_metrics()
        relocation = lc.apply_placement(p_exec, placement, run_id)
        actual = pod_nodes(p_exec)
        if actual != placement:
            raise RuntimeError(f"Kubernetes/VM pod placement mismatch: expected={placement}, actual={actual}")
        used_hosts = sorted(set(actual.values()))
        time.sleep(float(CFG["settle_seconds"]))
        scenario = lc.scenario_by_id(p_exec, state)
        seconds = int(CFG["pilot_measurement_seconds"] if pilot else CFG["measurement_seconds"])
        traffic = lc.configure_and_run_for_scenario(p_exec, placement, run_id, seconds, scenario)
        ep = endpoints(traffic)
        health = lc.deployment_health(p_exec)
        expected_cross = any(placement[f.source_replica] != placement[f.destination_replica] for f in p_exec.flows)
        if ep["attempted"] <= 0:
            raise RuntimeError("zero attempted requests")
        if expected_cross and ep["medium_requests"] <= 0:
            raise RuntimeError("shared medium saw zero requests despite cross-host flows")
        if not health["healthy"]:
            raise RuntimeError(f"unhealthy deployments after traffic: {health}")
        result = {
            "run_id": run_id, "utc": utc_now(), "pilot": pilot, "seed": seed, "method": method,
            "source_protocol": "N5-S1", "tau": 1.25, "executed_state": state,
            "placement": placement, "actual_pod_nodes": actual, "kubernetes_hosts_used": used_hosts,
            "kubernetes_host_count": len(used_hosts), "cluster_before": before_nodes, "cluster_after": cluster_info(),
            "node_metrics_before": metrics_before, "node_metrics_after": node_metrics(),
            "planned_exec_util": lc.scenario_conflict_util(p_plan, placement, state),
            "planned_feasible": bool(lc.evaluate_placement(p_plan, placement, RISK).feasible),
            "moves": lc.move_count(p_plan, placement), "cross_rack_bits": lc.cross_rack_bits(p_plan, placement),
            "execution_resource_mode": "fixed-lightweight-reservations",
            "execution_cpu_request": CFG["execution_cpu_request"],
            "execution_memory_request_mb": CFG["execution_memory_request_mb"],
            "endpoints": ep, "relocation": relocation, "traffic": traffic,
            "accepted_infrastructure": True,
        }
        dump(ar / "result.json", result)
        return result
    except Exception as exc:
        dump(ar / "failure.json", {"run_id": run_id, "utc": utc_now(), "error": f"{type(exc).__name__}: {exc}"})
        raise
    finally:
        try:
            _, _, pods = lc.pod_service_ips(p_exec)
            for rid in sorted(pods):
                lc.control_pod(pods[rid], "stop", {})
        except Exception:
            pass


def run_with_retries(seed: int, method: str, *, pilot: bool) -> dict[str, Any]:
    last = None
    for i in range(int(CFG["max_cell_attempts"])):
        try:
            return run_cell(seed, method, pilot=pilot)
        except Exception as exc:
            last = exc
            print(f"seed {seed} {method}: attempt {i+1} failed: {exc}", flush=True)
            time.sleep(5)
    raise RuntimeError(f"seed {seed} {method} failed after {CFG['max_cell_attempts']} attempts: {last}")


def cmd_run(pilot: bool) -> None:
    if not (OPLOG / "SETUP_PASSED.json").exists():
        raise RuntimeError("run setup first; operator_logs/SETUP_PASSED.json is missing")
    seeds = list(CFG["pilot_seeds"] if pilot else CFG["science_seeds"])
    for seed in seeds:
        methods = list(METHODS)
        random.Random(int(CFG["method_order_seed"]) + int(seed)).shuffle(methods)
        for method in methods:
            r = run_with_retries(int(seed), method, pilot=pilot)
            e = r["endpoints"]
            print(
                f"{'PILOT' if pilot else 'SCIENCE'} seed={seed} {method:26s} "
                f"p95={e['sched_p95_ms']:.1f}ms completion={e['scheduled_completion']:.4f} "
                f"execU={r['planned_exec_util']:.3f} hosts={r['kubernetes_host_count']}", flush=True
            )
    marker = OPLOG / ("PILOT_PASSED.json" if pilot else "SCIENCE_COMPLETE.json")
    dump(marker, {"utc": utc_now(), "seeds": seeds, "methods": METHODS})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["preflight", "setup", "pilot", "science"])
    args = ap.parse_args()
    if args.command == "preflight":
        print(json.dumps(preflight(), indent=2))
    elif args.command == "setup":
        cmd_setup()
    elif args.command == "pilot":
        cmd_run(True)
    else:
        if not (OPLOG / "PILOT_PASSED.json").exists():
            raise RuntimeError("pilot must pass before science")
        cmd_run(False)


if __name__ == "__main__":
    main()
