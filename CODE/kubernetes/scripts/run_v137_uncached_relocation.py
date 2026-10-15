#!/usr/bin/env python3
"""Run the frozen Kubernetes v1.37 uncached-relocation calibration arm."""
from __future__ import annotations

import argparse
import json
import random
import statistics
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
NS = "mape-cap-bplus-pilot"
DEPLOYMENT = "relocation-echo"
LABEL = "app=relocation-echo"
IMAGE = "hashicorp/http-echo:1.0.0"
WORKERS = ["mcb-k137-worker", "mcb-k137-worker2", "mcb-k137-worker3"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run(args: list[str], *, check: bool = True, timeout: float = 240) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(args)}\n{result.stderr[-3000:]}"
        )
    return result


def kubectl(*args: str, check: bool = True, timeout: float = 240) -> subprocess.CompletedProcess[str]:
    return run(["kubectl", *args], check=check, timeout=timeout)


def kubectl_json(*args: str) -> dict:
    return json.loads(kubectl(*args, "-o", "json").stdout)


def node_cmd(node: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["docker", "exec", node, *args], check=check, timeout=90)


def ready(pod: dict) -> bool:
    return any(
        c.get("type") == "Ready" and c.get("status") == "True"
        for c in pod.get("status", {}).get("conditions", [])
    )


def pods() -> list[dict]:
    return kubectl_json("get", "pods", "-n", NS, "-l", LABEL).get("items", [])


def one_ready_pod() -> dict:
    matches = [pod for pod in pods() if ready(pod) and not pod["metadata"].get("deletionTimestamp")]
    if len(matches) != 1:
        raise RuntimeError(f"expected one ready relocation pod, found {len(matches)}")
    return matches[0]


def image_present(node: str, identity: str) -> bool:
    result = node_cmd(node, "crictl", "inspecti", identity, check=False)
    return result.returncode == 0


def ensure_image_absent(node: str, image_id: str) -> dict:
    before_by_id = image_present(node, image_id)
    before_by_ref = image_present(node, IMAGE)
    removals = []
    for identity in (image_id, IMAGE):
        result = node_cmd(node, "crictl", "rmi", identity, check=False)
        removals.append(
            {"identity": identity, "returncode": result.returncode, "output": (result.stdout + result.stderr)[-2000:]}
        )
    after_by_id = image_present(node, image_id)
    after_by_ref = image_present(node, IMAGE)
    if after_by_id or after_by_ref:
        raise RuntimeError(f"image still present on {node} immediately before measurement")
    return {
        "checked_utc": utc_now(),
        "before_by_id": before_by_id,
        "before_by_ref": before_by_ref,
        "removals": removals,
        "verified_absent": True,
        "after_by_id": after_by_id,
        "after_by_ref": after_by_ref,
    }


def start_probe(seconds: int = 30) -> subprocess.Popen[str]:
    code = (
        "import json,time,urllib.request;"
        "end=time.monotonic()+%d;ok=bad=0;errors=[];"
        "\nwhile time.monotonic()<end:\n"
        " try:\n"
        "  r=urllib.request.urlopen('http://relocation-echo.mape-cap-bplus-pilot.svc.cluster.local',timeout=2);"
        "  ok+=int(r.status==200);bad+=int(r.status!=200);r.read()\n"
        " except Exception as e: bad+=1;errors.append(type(e).__name__)\n"
        " time.sleep(.1)\n"
        "print(json.dumps({'successful_requests':ok,'failed_requests':bad,'errors':errors[-20:]}))"
    ) % seconds
    return subprocess.Popen(
        [
            "kubectl", "exec", "-n", "online-boutique", "deployment/loadgenerator",
            "-c", "main", "--", "python", "-c", code,
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def pod_events(name: str) -> list[dict]:
    items = kubectl_json(
        "get", "events", "-n", NS, "--field-selector", f"involvedObject.name={name}"
    ).get("items", [])
    return [
        {
            "reason": item.get("reason"),
            "message": item.get("message"),
            "first_timestamp": item.get("firstTimestamp") or item.get("eventTime"),
            "last_timestamp": item.get("lastTimestamp") or item.get("eventTime"),
            "count": item.get("count"),
        }
        for item in items
        if item.get("reason") in {"Pulling", "Pulled", "Failed", "FailedToRetrieveImagePullSecret"}
    ]


def image_details(node: str, image_id: str) -> dict:
    payload = json.loads(node_cmd(node, "crictl", "inspecti", image_id).stdout)
    status = payload.get("status", {})
    return {
        "reference": IMAGE,
        "image_id": status.get("id") or image_id,
        "repo_tags": status.get("repoTags", []),
        "repo_digests": status.get("repoDigests", []),
        "size_bytes": status.get("size"),
    }


def median_ci(values: list[float], seed: int = 137, draws: int = 10000) -> dict:
    rng = random.Random(seed + len(values))
    medians = sorted(
        statistics.median(rng.choices(values, k=len(values))) for _ in range(draws)
    )
    median = statistics.median(values)
    low = medians[int(0.025 * draws)]
    high = medians[min(draws - 1, int(0.975 * draws))]
    half_width = (high - low) / 2.0
    return {
        "median_seconds": median,
        "bootstrap_95_low_seconds": low,
        "bootstrap_95_high_seconds": high,
        "bootstrap_95_half_width_seconds": half_width,
        "relative_half_width": half_width / median if median > 0 else None,
        "draws": draws,
    }


def relocate(target: str, timeout_seconds: float) -> dict:
    old = one_ready_pod()
    old_name = old["metadata"]["name"]
    source = old["spec"]["nodeName"]
    if source == target:
        raise RuntimeError("target equals source")
    image_id = old["status"]["containerStatuses"][0]["imageID"]
    absence = ensure_image_absent(target, image_id)
    probe = start_probe()
    time.sleep(1.0)
    event_id = str(uuid.uuid4())
    action_utc = utc_now()
    action_started = time.monotonic()
    patch = {
        "spec": {
            "template": {
                "metadata": {"annotations": {"mape-cap-bplus/relocation-id": event_id}},
                "spec": {
                    "nodeSelector": {"kubernetes.io/hostname": target},
                    "containers": [{"name": "echo", "image": IMAGE, "imagePullPolicy": "Always"}],
                },
            }
        }
    }
    kubectl("patch", "deployment", DEPLOYMENT, "-n", NS, "--type=merge", "-p", json.dumps(patch))
    deadline = time.monotonic() + timeout_seconds
    new_pod = None
    old_removed = False
    while time.monotonic() < deadline:
        current = pods()
        for pod in current:
            if pod["metadata"]["name"] != old_name and pod.get("spec", {}).get("nodeName") == target:
                if ready(pod):
                    new_pod = pod
        old_removed = all(pod["metadata"]["name"] != old_name for pod in current)
        if new_pod is not None and old_removed:
            break
        time.sleep(0.25)
    rollout_seconds = time.monotonic() - action_started
    if new_pod is None or not old_removed:
        probe.terminate()
        stdout, stderr = probe.communicate(timeout=10)
        raise RuntimeError(
            f"relocation timeout source={source} target={target}; probe={stdout[-1000:]} {stderr[-1000:]}"
        )
    stdout, stderr = probe.communicate(timeout=45)
    if probe.returncode:
        raise RuntimeError(f"request probe failed ({probe.returncode}): {stderr[-2000:]}")
    probe_result = json.loads(stdout.strip().splitlines()[-1])
    ready_condition = next(
        c for c in new_pod["status"]["conditions"]
        if c.get("type") == "Ready" and c.get("status") == "True"
    )
    created = datetime.fromisoformat(new_pod["metadata"]["creationTimestamp"].replace("Z", "+00:00"))
    ready_at = datetime.fromisoformat(ready_condition["lastTransitionTime"].replace("Z", "+00:00"))
    new_image_id = new_pod["status"]["containerStatuses"][0]["imageID"]
    return {
        "schema_version": "1.0",
        "event_id": event_id,
        "action_started_utc": action_utc,
        "completed_utc": utc_now(),
        "source_node": source,
        "target_node": target,
        "old_pod": old_name,
        "new_pod": new_pod["metadata"]["name"],
        "image_absence_precheck": absence,
        "image": image_details(target, new_image_id),
        "pull_events": pod_events(new_pod["metadata"]["name"]),
        "create_to_ready_seconds": (ready_at - created).total_seconds(),
        "create_ready_remove_rollout_seconds": rollout_seconds,
        "request_probe": probe_result,
        "final_pod_ready": ready(new_pod),
        "accepted": bool(ready(new_pod) and absence["verified_absent"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-observations", type=int, default=20)
    parser.add_argument("--min-observations", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    args = parser.parse_args()
    if not 5 <= args.min_observations <= args.max_observations <= 20:
        parser.error("require 5 <= min-observations <= max-observations <= 20")

    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    kubectl("apply", "-f", str(ROOT / "implementation/kubernetes/manifests/pilot-namespace.yaml"))
    kubectl("apply", "-f", str(ROOT / "implementation/kubernetes/manifests/relocation-echo.yaml"))
    initial_patch = json.dumps({"spec": {"template": {"spec": {"nodeSelector": {"kubernetes.io/hostname": WORKERS[0]}}}}})
    kubectl("patch", "deployment", DEPLOYMENT, "-n", NS, "--type=merge", "-p", initial_patch)
    kubectl("rollout", "status", "deployment/relocation-echo", "-n", NS, "--timeout=5m")

    records: list[dict] = []
    failures: list[dict] = []
    stopping_reason = "maximum successful observations reached"
    for index in range(1, args.max_observations + 1):
        source = one_ready_pod()["spec"]["nodeName"]
        candidates = [worker for worker in WORKERS if worker != source]
        target = candidates[(index - 1) % len(candidates)]
        try:
            record = relocate(target, args.timeout_seconds)
            record["observation"] = index
            records.append(record)
            (out / f"observation-{index:02d}.json").write_text(
                json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
            )
        except Exception as exc:
            failure = {"observation": index, "recorded_utc": utc_now(), "source_node": source, "target_node": target, "error": repr(exc)}
            failures.append(failure)
            (out / f"failure-{index:02d}.json").write_text(
                json.dumps(failure, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            continue

        values = [float(row["create_ready_remove_rollout_seconds"]) for row in records]
        ci = median_ci(values)
        summary = {
            "schema_version": "1.0",
            "arm": "item3-uncached-relocation-calibration",
            "updated_utc": utc_now(),
            "successful_observations": len(records),
            "failed_observations": len(failures),
            "calibration": ci,
            "failures": failures,
        }
        (out / "summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
        )
        if len(records) >= args.min_observations and ci["relative_half_width"] is not None and ci["relative_half_width"] <= 0.20:
            stopping_reason = "bootstrap 95% median half-width reached at most 20%"
            break

    final = one_ready_pod()
    summary.update(
        {
            "completed_utc": utc_now(),
            "stopping_reason": stopping_reason,
            "final_health": {"pod": final["metadata"]["name"], "node": final["spec"]["nodeName"], "ready": ready(final)},
            "accepted": bool(records and ready(final)),
        }
    )
    (out / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True), flush=True)
    return 0 if summary["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
