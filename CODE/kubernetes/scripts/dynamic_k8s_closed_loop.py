#!/usr/bin/env python3
"""Closed-loop dynamic adaptation experiment on Kind cluster with tc/netem.

Applies live network regime changes via tc/netem and actively triggers pod relocations
using the Kubernetes API when the B+ controller accepts a relocation.
"""
from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
import uuid

ROOT = Path(__file__).resolve().parents[2]
REPO = ROOT.parent

import sys
sys.path.insert(0, str(ROOT / "code"))

from mape_cap_bplus.controller import PersistentRegimeDetector, accept_relocation

NODE_IPS = {}
REGIME_SEQUENCE = (
    ["stable"] * 3 +
    ["degraded"] * 3 +
    ["recovery"] * 3
)

REGIME_PARAMS = {
    "stable": {"delay_ms": 0.0, "rate_mbit": 1000.0, "loss_pct": 0.0},
    "degraded": {"delay_ms": 25.0, "rate_mbit": 100.0, "loss_pct": 1.0},
    "recovery": {"delay_ms": 2.0, "rate_mbit": 500.0, "loss_pct": 0.0},
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def kubectl_json(args: list[str]) -> dict:
    result = subprocess.run(
        ["kubectl", *args, "-o", "json"],
        check=True, text=True, capture_output=True, timeout=30,
    )
    return json.loads(result.stdout)


def kubectl(args: list[str]) -> None:
    subprocess.run(["kubectl", *args], check=True)


def get_node_ips() -> dict[str, str]:
    nodes = kubectl_json(["get", "nodes"])
    ips = {}
    for node in nodes.get("items", []):
        name = node["metadata"]["name"]
        for addr in node.get("status", {}).get("addresses", []):
            if addr["type"] == "InternalIP":
                ips[name] = addr["address"]
    return ips


def docker_exec(node: str, cmd: list[str], timeout: int = 15) -> tuple[int, str]:
    result = subprocess.run(
        ["docker", "exec", node, *cmd],
        capture_output=True, text=True, timeout=timeout,
    )
    return result.returncode, result.stdout.strip()


def apply_tc_netem(source_node: str, dest_ip: str, delay_ms: float, rate_mbit: float, loss_pct: float) -> bool:
    commands = [
        ["tc", "qdisc", "replace", "dev", "eth0", "root", "handle", "1:", "prio", "bands", "3"],
        ["tc", "qdisc", "replace", "dev", "eth0", "parent", "1:3", "handle", "30:",
         "netem", "delay", f"{delay_ms}ms", "rate", f"{rate_mbit}mbit", "loss", f"{loss_pct}%"],
        ["tc", "filter", "replace", "dev", "eth0", "protocol", "ip", "parent", "1:0",
         "prio", "3", "u32", "match", "ip", "dst", f"{dest_ip}/32", "flowid", "1:3"],
    ]
    for cmd in commands:
        rc, _ = docker_exec(source_node, cmd)
        if rc != 0:
            return False
    return True


def clear_tc(node: str) -> bool:
    rc, _ = docker_exec(node, ["tc", "qdisc", "del", "dev", "eth0", "root"])
    return rc == 0


def measure_latency(source_node: str, dest_ip: str, count: int = 3) -> float:
    """Measure TCP connect latency via /dev/tcp to kubelet port 10250."""
    samples = []
    for _ in range(count):
        cmd = [
            "bash", "-c",
            f"start=$(date +%s%N) && exec 3<>/dev/tcp/{dest_ip}/10250 && "
            f"end=$(date +%s%N) && echo $((end-start)) && exec 3>&-"
        ]
        rc, output = docker_exec(source_node, cmd, timeout=10)
        if rc == 0 and output.strip().isdigit():
            samples.append(int(output.strip()) / 1_000_000.0)
    return sum(samples) / len(samples) if samples else -1.0


def ready(pod: dict) -> bool:
    return any(
        condition.get("type") == "Ready" and condition.get("status") == "True"
        for condition in pod.get("status", {}).get("conditions", [])
    )


def list_pods(namespace: str, label: str) -> list[dict]:
    return kubectl_json(["get", "pods", "-n", namespace, "-l", label]).get("items", [])


def get_current_pod_node(namespace: str, label: str) -> tuple[str, str]:
    pods = list_pods(namespace, label)
    ready_pods = [pod for pod in pods if ready(pod)]
    if not ready_pods:
        return "", ""
    pod = ready_pods[0]
    return pod["metadata"]["name"], pod.get("spec", {}).get("nodeName", "")


def execute_relocation(namespace: str, deployment: str, label: str, target_node: str, timeout: float = 60.0) -> float:
    old_name, source_node = get_current_pod_node(namespace, label)
    if not source_node:
        print("  Error: No source pod found for relocation")
        return -1.0
    if source_node == target_node:
        print(f"  Pod is already on target node: {target_node}")
        return 0.0

    print(f"  [Action] Relocating {deployment} from {source_node} to {target_node}...")
    event_id = str(uuid.uuid4())
    started_at = time.monotonic()
    patch = {
        "spec": {
            "template": {
                "metadata": {"annotations": {"mape-cap-bplus/relocation-id": event_id}},
                "spec": {"nodeSelector": {"kubernetes.io/hostname": target_node}},
            }
        }
    }
    kubectl(["patch", "deployment", deployment, "-n", namespace, "--type=merge", "-p", json.dumps(patch)])

    deadline = time.monotonic() + timeout
    new_pod_ready = False
    ready_at = 0.0
    while time.monotonic() < deadline:
        pods = list_pods(namespace, label)
        for pod in pods:
            if (
                pod["metadata"]["name"] != old_name
                and pod.get("spec", {}).get("nodeName") == target_node
                and ready(pod)
            ):
                new_pod_ready = True
                ready_at = time.monotonic()
                break
        if new_pod_ready:
            break
        time.sleep(0.5)

    if not new_pod_ready:
        print("  Error: Relocation timed out!")
        return -1.0
    
    elapsed = ready_at - started_at
    print(f"  [Success] Relocation complete in {elapsed:.2f}s")
    return elapsed


def main() -> int:
    global NODE_IPS
    NODE_IPS = get_node_ips()
    print(f"Node IPs: {NODE_IPS}")

    workers = sorted([n for n in NODE_IPS if "worker" in n])
    if len(workers) < 2:
        raise SystemExit("need at least 2 worker nodes")

    source_node = workers[0]
    target_node = workers[1]
    source_ip = NODE_IPS[source_node]
    target_ip = NODE_IPS[target_node]
    print(f"Shaping: {source_node} ({source_ip}) -> {target_node} ({target_ip})")

    # Setup namespace and deployment
    print("Initializing closed-loop deployment...")
    kubectl(["apply", "-f", "kubernetes/manifests/pilot-namespace.yaml"])
    
    # We patch it to start on source_node
    patch_initial = {
        "spec": {
            "template": {
                "spec": {"nodeSelector": {"kubernetes.io/hostname": source_node}}
            }
        }
    }
    kubectl(["apply", "-f", "kubernetes/manifests/relocation-echo.yaml"])
    kubectl(["patch", "deployment", "relocation-echo", "-n", "mape-cap-bplus-pilot", "--type=merge", "-p", json.dumps(patch_initial)])
    
    # Wait for initial pod to be ready on source node
    print(f"Waiting for relocation-echo to start on {source_node}...")
    time.sleep(5)
    
    detector = PersistentRegimeDetector(minimum_persistent_windows=3)
    current_regime = "stable"
    observed: list[str] = []
    records: list[dict] = []

    simulated_current_cost = 2000.0
    simulated_degraded_cost = 12000.0
    measured_relocation_seconds = 4.062
    relocation_cost_units = 4062.0
    uncertainty_margin = 10.0

    for window_idx, regime in enumerate(REGIME_SEQUENCE):
        params = REGIME_PARAMS[regime]
        window_start = utc_now()

        # Apply shaping
        apply_tc_netem(source_node, target_ip, params["delay_ms"], params["rate_mbit"], params["loss_pct"])
        time.sleep(1.0)
        latency = measure_latency(source_node, target_ip)

        observed.append(regime)
        decision = detector.evaluate(
            observed,
            current_regime,
            300.0,
            measured_relocation_seconds,
        )

        accepted = False
        net_benefit = 0.0
        reason = decision.reason
        relocation_time = -1.0

        if decision.should_replan:
            if regime == "degraded":
                candidate_cost = simulated_degraded_cost * 0.3
                current_cost = simulated_degraded_cost
            elif regime == "recovery":
                candidate_cost = simulated_current_cost * 0.8
                current_cost = simulated_current_cost * 1.2
            else:
                candidate_cost = simulated_current_cost
                current_cost = simulated_current_cost

            accepted, net_benefit, acceptance_reason = accept_relocation(
                current_cost, candidate_cost, relocation_cost_units, uncertainty_margin,
            )
            reason = f"{decision.reason}; {acceptance_reason}"

            if accepted:
                # Determine target node for this relocation
                _, cur_node = get_current_pod_node("mape-cap-bplus-pilot", "app=relocation-echo")
                reloc_target = target_node if cur_node == source_node else source_node
                
                # Execute relocation (Closed Loop!)
                relocation_time = execute_relocation(
                    namespace="mape-cap-bplus-pilot",
                    deployment="relocation-echo",
                    label="app=relocation-echo",
                    target_node=reloc_target
                )
                current_regime = regime

        record = {
            "window_index": window_idx,
            "regime": regime,
            "tc_delay_ms": params["delay_ms"],
            "tc_rate_mbit": params["rate_mbit"],
            "tc_loss_pct": params["loss_pct"],
            "measured_latency_ms": latency,
            "should_replan": decision.should_replan,
            "accepted": accepted,
            "net_benefit": net_benefit,
            "reason": reason,
            "relocation_time_seconds": relocation_time,
            "timestamp": window_start,
            "evidence_type": "kubernetes-measured-closed-loop",
        }
        records.append(record)
        status = f"RELOCATE (took {relocation_time:.2f}s)" if accepted else ("REPLAN-REJECTED" if decision.should_replan else "NO-OP")
        print(f"  Window {window_idx}: {regime} | latency={latency:.1f}ms | {status} | {reason}")

    # Cleanup
    for node in workers:
        clear_tc(node)
    print("Cleared all tc rules")
    
    # Delete namespace
    print("Cleaning up pilot namespace...")
    kubectl(["delete", "ns", "mape-cap-bplus-pilot"])

    output = {
        "experiment": "closed-loop-dynamic-adaptation-k8s",
        "evidence_type": "kubernetes-measured-closed-loop",
        "timestamp": utc_now(),
        "source_node": source_node,
        "target_node": target_node,
        "regime_sequence": REGIME_SEQUENCE,
        "records": records,
        "summary": {
            "total_windows": len(records),
            "relocations": sum(1 for r in records if r["accepted"]),
            "replans_triggered": sum(1 for r in records if r["should_replan"]),
            "average_relocation_time": sum(r["relocation_time_seconds"] for r in records if r["accepted"]) / sum(1 for r in records if r["accepted"]),
        },
    }

    output_path = REPO / "RESULTS" / "calibration" / "reproduced" / "closed_loop_k8s_experiment.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(output, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"\nClosed-loop experiment complete: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
