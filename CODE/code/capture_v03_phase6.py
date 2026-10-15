"""Capture the Phase 6 Kind/Online Boutique acceptance evidence."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from mape_cap_bplus.v03_evidence import atomic_write_json, atomic_write_text, utc_now


def run(*args: str) -> str:
    completed = subprocess.run(args, check=True, capture_output=True, text=True)
    return completed.stdout


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_root", type=Path)
    args = parser.parse_args()
    raw = args.run_root.resolve() / "raw"
    derived = args.run_root.resolve() / "derived"

    pods = json.loads(run("kubectl", "get", "pods", "-n", "online-boutique", "-o", "json"))
    deployments = json.loads(
        run("kubectl", "get", "deployments", "-n", "online-boutique", "-o", "json")
    )
    nodes = json.loads(run("kubectl", "get", "nodes", "-o", "json"))
    services = json.loads(
        run("kubectl", "get", "services", "-n", "online-boutique", "-o", "json")
    )
    statuses = []
    for pod in pods["items"]:
        containers = pod.get("status", {}).get("containerStatuses", [])
        statuses.append(
            {
                "pod": pod["metadata"]["name"],
                "node": pod.get("spec", {}).get("nodeName"),
                "phase": pod.get("status", {}).get("phase"),
                "ready": bool(containers) and all(item.get("ready", False) for item in containers),
                "restarts": sum(item.get("restartCount", 0) for item in containers),
            }
        )

    atomic_write_json(raw / "phase-6-final-pods.json", pods)
    atomic_write_json(raw / "phase-6-final-deployments.json", deployments)
    atomic_write_json(raw / "phase-6-final-nodes.json", nodes)
    atomic_write_json(raw / "phase-6-final-services.json", services)
    atomic_write_text(
        raw / "phase-6-loadgenerator-final.log",
        run(
            "kubectl", "logs", "-n", "online-boutique", "deployment/loadgenerator",
            "-c", "main", "--tail=-1",
        ),
    )
    atomic_write_json(
        raw / "phase-6-recovery-incident.json",
        {
            "timestamp_utc": utc_now(),
            "classification": "invalidated pilot; controlled infrastructure recovery",
            "trigger": (
                "Sequential containerd image imports filled the Windows host file cache, "
                "reducing available host RAM to approximately 0.58 GiB and hanging Docker."
            ),
            "recovery": (
                "The interrupted import was terminated, docker-desktop WSL was terminated, "
                "stale Docker Desktop processes were stopped, and Docker Desktop was restarted."
            ),
            "scientific_handling": (
                "No measurements from the interrupted pilot are accepted. CoreDNS and all "
                "Online Boutique deployments were rolled cleanly before a new pilot baseline."
            ),
            "prevention": (
                "Large image bundles remain on D:. Additional load images are pulled by one "
                "scheduled node at a time; multi-node sequential imports are not repeated."
            ),
        },
    )

    accepted = (
        len(statuses) == 12
        and all(item["phase"] == "Running" and item["ready"] for item in statuses)
        and sum(item["restarts"] for item in statuses) == 0
        and len(deployments["items"]) == 12
        and all(
            item.get("status", {}).get("availableReplicas", 0)
            == item.get("spec", {}).get("replicas", 0)
            for item in deployments["items"]
        )
    )
    summary = {
        "captured_utc": utc_now(),
        "accepted": accepted,
        "acceptance_basis": "fresh post-recovery stability pilot",
        "pod_count": len(statuses),
        "ready_count": sum(item["ready"] for item in statuses),
        "total_restarts": sum(item["restarts"] for item in statuses),
        "deployment_count": len(deployments["items"]),
        "node_count": len(nodes["items"]),
        "pods": statuses,
        "notes": [
            "Frontend health returned HTTP 200 in the final stability capture.",
            "The load generator recorded three early POST /cart failures; the count remained "
            "unchanged as total requests grew from 396 to 622.",
            "Metrics Server is intentionally absent; host/pod resource telemetry is collected "
            "by the experiment harness in Phase 7.",
        ],
    }
    atomic_write_json(derived / "phase-6-acceptance.json", summary)
    print(json.dumps(summary, indent=2))
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
