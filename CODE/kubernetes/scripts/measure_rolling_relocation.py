#!/usr/bin/env python3
"""Measure one create-ready-remove rolling relocation through kubectl.

The script patches a single-replica Deployment with maxSurge=1 and
maxUnavailable=0 to a declared target node. It records controller-observed
lifecycle timestamps. Request failures must come from a concurrent load probe
and are therefore required explicitly rather than silently defaulting to zero.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import subprocess
import time
import uuid


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def kubectl_json(arguments: list[str]) -> dict:
    result = subprocess.run(["kubectl", *arguments, "-o", "json"], check=True, text=True, capture_output=True)
    return json.loads(result.stdout)


def kubectl(arguments: list[str]) -> None:
    subprocess.run(["kubectl", *arguments], check=True)


def ready(pod: dict) -> bool:
    return any(
        condition.get("type") == "Ready" and condition.get("status") == "True"
        for condition in pod.get("status", {}).get("conditions", [])
    )


def list_pods(namespace: str, label: str) -> list[dict]:
    return kubectl_json(["get", "pods", "-n", namespace, "-l", label]).get("items", [])


def parse_bool(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in {"true", "1", "yes"}:
        return True
    if lowered in {"false", "0", "no"}:
        return False
    raise argparse.ArgumentTypeError("expected true/false, yes/no, or 1/0")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--namespace", default="mape-cap-bplus-pilot")
    parser.add_argument("--deployment", default="relocation-echo")
    parser.add_argument("--label", default="app=relocation-echo")
    parser.add_argument("--target-node", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--failed-requests", type=int, required=True, help="measured by a concurrent request probe")
    parser.add_argument("--image-cached", type=parse_bool)
    parser.add_argument("--image-size-bytes", type=int)
    parser.add_argument("--state-transfer-bytes", type=int, default=0)
    parser.add_argument("--no-rollback", action="store_true", help="leave the patched Deployment in place after failure")
    args = parser.parse_args()

    if not math.isfinite(args.timeout_seconds) or args.timeout_seconds <= 0:
        parser.error("timeout-seconds must be positive and finite")
    if args.failed_requests < 0:
        parser.error("failed-requests must be non-negative")
    if args.image_size_bytes is not None and args.image_size_bytes < 0:
        parser.error("image-size-bytes must be non-negative")
    if args.state_transfer_bytes < 0:
        parser.error("state-transfer-bytes must be non-negative")

    target_node = kubectl_json(["get", "node", args.target_node])
    node_ready = any(
        condition.get("type") == "Ready" and condition.get("status") == "True"
        for condition in target_node.get("status", {}).get("conditions", [])
    )
    if not node_ready:
        raise SystemExit(f"target node is not Ready: {args.target_node}")

    initial = list_pods(args.namespace, args.label)
    ready_initial = [pod for pod in initial if ready(pod)]
    if len(ready_initial) != 1:
        raise SystemExit(f"expected exactly one ready initial pod, found {len(ready_initial)}")
    old = ready_initial[0]
    old_name = old["metadata"]["name"]
    source_node = old.get("spec", {}).get("nodeName", "")
    if not source_node:
        raise SystemExit("initial pod has no assigned source node")
    if source_node == args.target_node:
        raise SystemExit("target node must differ from current source node")

    event_id = str(uuid.uuid4())
    started_at = utc_now()
    patch = {
        "spec": {
            "template": {
                "metadata": {"annotations": {"mape-cap-bplus/relocation-id": event_id}},
                "spec": {"nodeSelector": {"kubernetes.io/hostname": args.target_node}},
            }
        }
    }
    kubectl(["patch", "deployment", args.deployment, "-n", args.namespace, "--type=merge", "-p", json.dumps(patch)])

    deadline = time.monotonic() + args.timeout_seconds
    new_pod = None
    ready_at = None
    old_removed_at = None
    try:
        while time.monotonic() < deadline:
            pods = list_pods(args.namespace, args.label)
            for pod in pods:
                if (
                    pod["metadata"]["name"] != old_name
                    and pod.get("spec", {}).get("nodeName") == args.target_node
                    and ready(pod)
                ):
                    new_pod = pod
                    ready_at = ready_at or utc_now()
            if new_pod is not None and all(pod["metadata"]["name"] != old_name for pod in pods):
                old_removed_at = utc_now()
                break
            time.sleep(1.0)
        if new_pod is None or ready_at is None or old_removed_at is None:
            raise RuntimeError("relocation did not complete within timeout")
    except Exception:
        if not args.no_rollback:
            subprocess.run(
                ["kubectl", "rollout", "undo", "deployment", args.deployment, "-n", args.namespace],
                check=False,
            )
        raise

    started_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    ready_dt = datetime.fromisoformat(ready_at.replace("Z", "+00:00"))
    removed_dt = datetime.fromisoformat(old_removed_at.replace("Z", "+00:00"))
    measurement = {
        "event_id": event_id,
        "replica_id": args.deployment,
        "source_node": source_node,
        "target_node": args.target_node,
        "method": "create-ready-remove",
        "started_at": started_at,
        "ready_at": ready_at,
        "old_removed_at": old_removed_at,
        "ready_seconds": (ready_dt - started_dt).total_seconds(),
        "rollout_seconds": (removed_dt - started_dt).total_seconds(),
        "failed_requests": args.failed_requests,
        "state_transfer_bytes": args.state_transfer_bytes,
        "provenance": "controller-observed-kubernetes-rolling-update",
        "old_pod": old_name,
        "new_pod": new_pod["metadata"]["name"],
    }
    if args.image_cached is not None:
        measurement["image_cached"] = args.image_cached
    if args.image_size_bytes is not None:
        measurement["image_size_bytes"] = args.image_size_bytes

    record = {"schema_version": "1.0", "records": [measurement]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Wrote relocation measurement: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
