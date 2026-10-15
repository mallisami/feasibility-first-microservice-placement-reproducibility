#!/usr/bin/env python3
"""Deploy and measure the frozen native TAS/CompositePodGroup comparator."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "implementation" / "code"))
os.environ.setdefault("MCB_R1_WORKERS", "mcb-k137-worker,mcb-k137-worker2,mcb-k137-worker3")

from mape_cap_bplus.v03_evidence import atomic_write_json, atomic_write_text, utc_now
from run_v03_r1 import measure, wait_healthy


NS = "online-boutique"
WORKERS = ["mcb-k137-worker", "mcb-k137-worker2", "mcb-k137-worker3"]
REQUEST_PATH = {"frontend", "checkoutservice", "paymentservice", "shippingservice"}
SUPPORTING = {
    "adservice", "cartservice", "currencyservice", "emailservice",
    "productcatalogservice", "recommendationservice", "redis-cart",
}


def run(args: list[str], *, check: bool = True, timeout: float = 1200) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(args)}\n{result.stderr[-4000:]}")
    return result


def kubectl(*args: str, check: bool = True, timeout: float = 1200) -> subprocess.CompletedProcess[str]:
    return run(["kubectl", *args], check=check, timeout=timeout)


def kubectl_json(*args: str) -> dict:
    return json.loads(kubectl(*args, "-o", "json").stdout)


def render_grouped_manifest(output: Path) -> dict[str, str]:
    source = ROOT / "implementation/kubernetes/manifests/online-boutique-core.yaml"
    documents = list(yaml.safe_load_all(source.read_text(encoding="utf-8")))
    assignments: dict[str, str] = {}
    for document in documents:
        if not document or document.get("kind") != "Deployment":
            continue
        name = document["metadata"]["name"]
        if name in REQUEST_PATH:
            group = "online-boutique-request-path"
        elif name in SUPPORTING:
            group = "online-boutique-supporting-services"
        else:
            raise RuntimeError(f"unclassified core deployment: {name}")
        document["spec"]["template"]["spec"]["schedulingGroup"] = {"podGroupName": group}
        assignments[name] = group
    expected = REQUEST_PATH | SUPPORTING
    if set(assignments) != expected:
        raise RuntimeError(f"group assignment mismatch: {sorted(set(assignments) ^ expected)}")
    output.write_text(yaml.safe_dump_all(documents, sort_keys=False), encoding="utf-8")
    return assignments


def placement_evidence(assignments: dict[str, str]) -> dict:
    nodes = {item["metadata"]["name"]: item["metadata"].get("labels", {}) for item in kubectl_json("get", "nodes")["items"]}
    pods = kubectl_json("get", "pods", "-n", NS)["items"]
    rows = []
    for pod in pods:
        app = pod["metadata"].get("labels", {}).get("app")
        if app not in assignments:
            continue
        node = pod.get("spec", {}).get("nodeName")
        labels = nodes.get(node, {})
        rows.append(
            {
                "app": app,
                "pod": pod["metadata"]["name"],
                "pod_group": pod.get("spec", {}).get("schedulingGroup", {}).get("podGroupName"),
                "node": node,
                "zone": labels.get("topology.mape-cap/zone"),
                "rack": labels.get("topology.mape-cap/rack"),
                "phase": pod.get("status", {}).get("phase"),
            }
        )
    by_group = {}
    for group in sorted(set(assignments.values())):
        members = [row for row in rows if row["pod_group"] == group]
        by_group[group] = {
            "members": members,
            "racks": sorted({row["rack"] for row in members if row["rack"]}),
            "zones": sorted({row["zone"] for row in members if row["zone"]}),
            "expected_count": sum(value == group for value in assignments.values()),
        }
    valid = bool(
        len(rows) == len(assignments)
        and all(len(group["racks"]) == 1 and len(group["zones"]) == 1 and len(group["members"]) == group["expected_count"] for group in by_group.values())
        and len({row["zone"] for row in rows}) == 1
    )
    return {"valid": valid, "workers": {worker: nodes.get(worker, {}) for worker in WORKERS}, "groups": by_group}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--duration-seconds", type=int, default=420)
    args = parser.parse_args()
    if args.duration_seconds < 60:
        parser.error("duration must be at least 60 seconds")
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    rendered = out / "online-boutique-core-tas-rendered.yaml"
    assignments = render_grouped_manifest(rendered)

    for index, worker in enumerate(WORKERS):
        kubectl(
            "label", "node", worker,
            "topology.mape-cap/zone=zone-a",
            f"topology.mape-cap/rack=rack-{chr(ord('a') + index)}",
            "--overwrite",
        )
    # Remove any objects from a partial prior attempt before applying the
    # immutable schedulingGroup field from the rendered template.
    kubectl("delete", "namespace", NS, "--ignore-not-found=true", "--wait=true")
    kubectl("create", "namespace", NS)
    kubectl("apply", "-f", str(ROOT / "implementation/kubernetes/manifests/online-boutique-tas-v137.yaml"))
    kubectl("apply", "-f", str(rendered))
    kubectl("apply", "-f", str(ROOT / "implementation/kubernetes/manifests/online-boutique-loadgen.yaml"))
    kubectl("wait", "--for=condition=Available", "deployment", "--all", "-n", NS, "--timeout=20m")

    api_objects = {
        "workload": kubectl_json("get", "workload", "online-boutique-tas", "-n", NS),
        "composite_pod_group": kubectl_json("get", "compositepodgroup", "online-boutique-root", "-n", NS),
        "pod_groups": kubectl_json("get", "podgroups", "-n", NS),
    }
    placement = placement_evidence(assignments)
    measured, samples, frontend_log = measure("confirmatory-persistent-severe", 42, args.duration_seconds)
    health = wait_healthy(timeout_seconds=180)
    application = measured["application"]
    result = {
        "schema_version": "1.0",
        "arm": "item5-native-tas-composite-pod-group",
        "completed_utc": utc_now(),
        "kubernetes": "v1.37.0",
        "feature_gates": ["GenericWorkload", "TopologyAwareWorkloadScheduling", "CompositePodGroup"],
        "api_versions": ["scheduling.k8s.io/v1beta1", "scheduling.k8s.io/v1alpha3"],
        "group_assignments": assignments,
        "api_objects": api_objects,
        "placement": placement,
        "condition": {"latency_ms": 40, "rate_mbit": 20, "loss_pct": 2.0, "load_multiplier": 2.0},
        "duration_seconds": args.duration_seconds,
        "measurement": measured,
        "health": health,
        "accepted": bool(placement["valid"] and health["healthy"] and application["successes"] >= 1000),
        "shared_host_limitation": True,
    }
    atomic_write_json(out / "result.json", result)
    atomic_write_json(out / "resource-samples.json", samples)
    atomic_write_text(out / "frontend.log", frontend_log)
    print(json.dumps({"accepted": result["accepted"], "placement_valid": placement["valid"], "successes": application["successes"], "output": str(out / 'result.json')}, indent=2), flush=True)
    return 0 if result["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
