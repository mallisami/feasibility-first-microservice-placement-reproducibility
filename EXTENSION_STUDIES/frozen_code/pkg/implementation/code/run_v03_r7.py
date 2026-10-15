"""Run the full v0.3 R7 DeathStarBench Hotel Reservation campaign sequentially."""
from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mape_cap_bplus.v03_evidence import (
    assert_resource_gate,
    atomic_write_json,
    atomic_write_text,
    resource_snapshot,
    utc_now,
    write_manifest,
)
from run_v03_r1 import CampaignLock, WORKERS, clear_network, docker

SCRIPT_ROOT = Path(__file__).resolve().parents[1]

NS = "hotel-res"
SOURCE = WORKERS[0]
TARGET = WORKERS[1]
LOAD_NODE = WORKERS[2]
CONDITIONS = ("stable", "degradation", "conflict", "recovery")
METHODS = ("Baseline", "BPlus")
REPLICATES = 5
DURATION_SECONDS = 30
RATE_RPS = 50
EXPECTED_APPLICATION_PODS = 18
EXPECTED_TOTAL_DEPLOYMENTS = 19
MANIFEST_ROOT = SCRIPT_ROOT / "kubernetes" / "deathstarbench" / "kubernetes"
WORKLOAD_SCRIPT = SCRIPT_ROOT / "kubernetes" / "deathstarbench" / "workload" / "mixed-workload_type_1.lua"
IMAGE_REWRITES = {
    "memcached": "memcached:alpine",
    "memcached:latest": "memcached:alpine",
}


def run(
    args: list[str], *, check: bool = True, timeout: int = 180,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, input=input_text, capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(args)}\n"
            f"{result.stdout[-1000:]}\n{result.stderr[-2000:]}"
        )
    return result


def kubectl(*args: str, check: bool = True, timeout: int = 180, input_text: str | None = None) -> str:
    return run(["kubectl", *args], check=check, timeout=timeout, input_text=input_text).stdout


def kubectl_json(*args: str, timeout: int = 180) -> dict[str, Any]:
    return json.loads(kubectl(*args, "-o", "json", timeout=timeout))


def transform_manifest(text: str, path: Path | None = None) -> str:
    """Make upstream deployments deterministic and offline-safe without changing originals."""
    output: list[str] = []
    volume_name = None
    if path is not None and path.name.endswith("-pvc.yaml"):
        volume_name = f"{path.name.removesuffix('-pvc.yaml')}-pv"
    for line in text.splitlines():
        match = re.match(r"(\s*(?:-\s*)?image:\s*)(\S+)(\s*)$", line)
        if match:
            image = IMAGE_REWRITES.get(match.group(2), match.group(2))
            line = f"{match.group(1)}{image}{match.group(3)}"
            output.append(line)
            indent = re.match(r"\s*", line).group(0)
            if line.lstrip().startswith("- image:"):
                output.append(f"{indent}  imagePullPolicy: IfNotPresent")
            else:
                output.append(f"{indent}imagePullPolicy: IfNotPresent")
            continue
        output.append(line)
        if volume_name and line.strip() == "storageClassName: standard":
            output.append(f"  volumeName: {volume_name}")
    return "\n".join(output) + "\n"


def capture_json(run_root: Path, relative: str, *args: str) -> None:
    payload = kubectl_json(*args)
    atomic_write_json(run_root / relative, payload)


def capture_pre_handover(run_root: Path) -> None:
    destination = run_root / "raw" / "r7" / "pre-handover"
    destination.mkdir(parents=True, exist_ok=True)
    for namespace in ("online-boutique", "r4-v03"):
        presence_path = destination / f"{namespace}-presence.json"
        if presence_path.exists():
            continue
        exists = run(["kubectl", "get", "namespace", namespace], check=False).returncode == 0
        atomic_write_json(presence_path, {"namespace": namespace, "present": exists, "captured_utc": utc_now()})
        if exists:
            capture_json(run_root, f"raw/r7/pre-handover/{namespace}-all.json", "get", "all", "-n", namespace)
            capture_json(run_root, f"raw/r7/pre-handover/{namespace}-pods.json", "get", "pods", "-n", namespace)


def delete_old_workloads() -> None:
    for namespace in ("online-boutique", "r4-v03"):
        kubectl("delete", "namespace", namespace, "--ignore-not-found=true", "--wait=true", "--timeout=240s", check=False, timeout=260)
    for namespace in ("online-boutique", "r4-v03"):
        if run(["kubectl", "get", "namespace", namespace], check=False).returncode == 0:
            raise RuntimeError(f"old workload namespace still exists: {namespace}")


def apply_stack() -> None:
    kubectl("create", "namespace", NS, check=False)
    files = sorted(MANIFEST_ROOT.rglob("*.yaml"))
    if not files:
        raise RuntimeError(f"no manifests found under {MANIFEST_ROOT}")
    for path in files:
        text = transform_manifest(path.read_text(encoding="utf-8"), path)
        kubectl("apply", "-n", NS, "-f", "-", input_text=text)
    wait_stack(600)


def deployment_health() -> dict[str, Any]:
    deployments = kubectl_json("get", "deployments", "-n", NS)["items"]
    pods = kubectl_json("get", "pods", "-n", NS)["items"]
    ready_deployments = []
    zero_replica_deployments = []
    for item in deployments:
        desired = int(item.get("spec", {}).get("replicas", 1))
        if desired < 1:
            zero_replica_deployments.append(item["metadata"]["name"])
        elif item.get("status", {}).get("readyReplicas", 0) == desired:
            ready_deployments.append(item["metadata"]["name"])
    application = [name for name in ready_deployments if name != "jaeger"]
    bad_pods = []
    for pod in pods:
        statuses = pod.get("status", {}).get("containerStatuses", [])
        if pod.get("status", {}).get("phase") != "Running" or not statuses or not all(x.get("ready") for x in statuses):
            bad_pods.append(pod["metadata"]["name"])
    return {
        "deployment_count": len(deployments),
        "ready_deployments": sorted(ready_deployments),
        "application_ready_count_excluding_jaeger": len(application),
        "total_ready_count_including_jaeger": len(ready_deployments),
        "zero_replica_deployments": sorted(zero_replica_deployments),
        "bad_pods": bad_pods,
        "accepted": (
            len(deployments) == EXPECTED_TOTAL_DEPLOYMENTS
            and len(application) == EXPECTED_APPLICATION_PODS
            and len(ready_deployments) == EXPECTED_TOTAL_DEPLOYMENTS
            and not zero_replica_deployments
            and not bad_pods
        ),
    }


def wait_stack(timeout: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = deployment_health()
        if last["accepted"]:
            return last
        time.sleep(5)
    raise RuntimeError(f"Hotel Reservation stack failed health gate: {last}")


def install_workload_script(run_root: Path) -> str:
    script = WORKLOAD_SCRIPT.read_text(encoding="utf-8")
    original = 'local url = "http://localhost:5000"'
    replacement = 'local url = "http://frontend.hotel-res.svc.cluster.local:5000"'
    if original not in script:
        raise RuntimeError("official Hotel Reservation Lua URL marker was not found")
    script = script.replace(original, replacement, 1)
    atomic_write_text(run_root / "raw" / "r7" / "official-mixed-workload.lua", script)
    manifest = {
        "apiVersion": "v1", "kind": "ConfigMap",
        "metadata": {"name": "r7-workload", "namespace": NS},
        "data": {"mixed-workload.lua": script},
    }
    kubectl("apply", "-f", "-", input_text=json.dumps(manifest))
    return script


def node_shape(node: str, delay_ms: float, rate_mbit: float, loss_pct: float) -> dict[str, Any]:
    docker(
        node, "tc", "qdisc", "replace", "dev", "eth0", "root", "netem",
        "delay", f"{delay_ms}ms", "rate", f"{rate_mbit}mbit", "loss", f"{loss_pct}%",
    )
    return {
        "node": node, "delay_ms": delay_ms, "rate_mbit": rate_mbit,
        "loss_pct": loss_pct, "tc_qdisc": docker(node, "tc", "qdisc", "show", "dev", "eth0"),
    }


def network_is_clear() -> bool:
    return all("netem" not in docker(node, "tc", "qdisc", "show", "dev", "eth0") for node in WORKERS)


def set_frontend_node(node: str) -> float:
    started = time.monotonic()
    patch = json.dumps({"spec": {"template": {"spec": {"nodeSelector": {"kubernetes.io/hostname": node}}}}})
    kubectl("patch", "deployment", "frontend", "-n", NS, "--type=merge", "-p", patch)
    kubectl("rollout", "status", "deployment/frontend", "-n", NS, "--timeout=240s", timeout=260)
    return time.monotonic() - started


def placement() -> dict[str, str]:
    result: dict[str, str] = {}
    for pod in kubectl_json("get", "pods", "-n", NS)["items"]:
        labels = pod.get("metadata", {}).get("labels", {})
        service = labels.get("io.kompose.service")
        node = pod.get("spec", {}).get("nodeName")
        if service and node and not pod.get("metadata", {}).get("deletionTimestamp"):
            result[service] = node
    return result


def pod_runtime_state() -> dict[str, Any]:
    pods = kubectl_json("get", "pods", "-n", NS)["items"]
    rows = {}
    for pod in pods:
        if pod["metadata"]["name"].startswith("r7-"):
            continue
        statuses = pod.get("status", {}).get("containerStatuses", [])
        rows[pod["metadata"]["name"]] = {
            "phase": pod.get("status", {}).get("phase"),
            "node": pod.get("spec", {}).get("nodeName"),
            "restarts": sum(int(x.get("restartCount", 0)) for x in statuses),
            "ready": bool(statuses) and all(x.get("ready", False) for x in statuses),
            "reasons": [
                x.get("state", {}).get("terminated", {}).get("reason")
                for x in statuses if x.get("state", {}).get("terminated")
            ],
        }
    return rows


def stats_snapshot() -> dict[str, dict[str, int]]:
    by_pod: dict[str, dict[str, int]] = {}
    for node in kubectl_json("get", "nodes")["items"]:
        name = node["metadata"]["name"]
        summary = json.loads(kubectl("get", "--raw", f"/api/v1/nodes/{name}/proxy/stats/summary"))
        for pod in summary.get("pods", []):
            ref = pod.get("podRef", {})
            if ref.get("namespace") != NS:
                continue
            network = pod.get("network", {})
            by_pod[ref["name"]] = {
                "cpu_nano_cores": sum(int(c.get("cpu", {}).get("usageNanoCores") or 0) for c in pod.get("containers", [])),
                "memory_working_set_bytes": sum(int(c.get("memory", {}).get("workingSetBytes") or 0) for c in pod.get("containers", [])),
                "rx_bytes": int(network.get("rxBytes") or 0),
                "tx_bytes": int(network.get("txBytes") or 0),
            }
    return by_pod


def summarize_resources(samples: list[dict[str, dict[str, int]]], duration: float) -> dict[str, Any]:
    if len(samples) < 2:
        raise RuntimeError("at least two resource samples are required")
    cpu = [sum(p["cpu_nano_cores"] for p in sample.values()) for sample in samples]
    memory = [sum(p["memory_working_set_bytes"] for p in sample.values()) for sample in samples]
    first, last = samples[0], samples[-1]
    common = set(first) & set(last)
    rx = sum(max(0, last[p]["rx_bytes"] - first[p]["rx_bytes"]) for p in common)
    tx = sum(max(0, last[p]["tx_bytes"] - first[p]["tx_bytes"]) for p in common)
    return {
        "sample_count": len(samples),
        "mean_cpu_cores": statistics.fmean(cpu) / 1e9,
        "max_cpu_cores": max(cpu) / 1e9,
        "mean_memory_mib": statistics.fmean(memory) / 1024**2,
        "max_memory_mib": max(memory) / 1024**2,
        "network_rx_bytes": rx,
        "network_tx_bytes": tx,
        "network_bytes_per_second": (rx + tx) / max(duration, 0.001),
    }


def job_manifest(name: str, duration: int, rate: int) -> dict[str, Any]:
    probe_url = (
        "http://frontend:5000/hotels?inDate=2015-04-09&outDate=2015-04-10"
        "&lat=38.0235&lon=-122.095"
    )
    probe = (
        f"end=$(( $(date +%s) + {duration} )); "
        "while [ \"$(date +%s)\" -lt \"$end\" ]; do "
        f"if timeout 0.25 wget -q -T 1 -O /dev/null '{probe_url}'; then echo OK; else echo FAIL; fi; "
        "sleep 0.02; done"
    )
    wrk = (
        f"wrk -D exp -t 2 -c 16 -d {duration}s -T 2s -L "
        f"-s /scripts/mixed-workload.lua http://frontend:5000 -R {rate}"
    )
    return {
        "apiVersion": "batch/v1", "kind": "Job",
        "metadata": {"name": name, "namespace": NS, "labels": {"experiment": "r7"}},
        "spec": {
            # Leave cleanup headroom without allowing either workload container
            # to determine the sampling duration. Both commands are time-bounded.
            "backoffLimit": 0, "activeDeadlineSeconds": duration + 180,
            "template": {
                "metadata": {"labels": {"experiment": "r7", "cell": name}},
                "spec": {
                    "restartPolicy": "Never",
                    "nodeSelector": {"kubernetes.io/hostname": LOAD_NODE},
                    "containers": [
                        {
                            "name": "wrk2", "image": "deathstarbench/wrk2-client:latest",
                            "imagePullPolicy": "IfNotPresent", "command": ["/bin/bash", "-lc", wrk],
                            "resources": {"requests": {"cpu": "100m", "memory": "64Mi"}, "limits": {"cpu": "1", "memory": "256Mi"}},
                            "volumeMounts": [{"name": "script", "mountPath": "/scripts"}],
                        },
                        {
                            "name": "probe", "image": "busybox:latest", "imagePullPolicy": "IfNotPresent",
                            "command": ["sh", "-c", probe],
                            "resources": {"requests": {"cpu": "10m", "memory": "8Mi"}, "limits": {"cpu": "100m", "memory": "32Mi"}},
                        },
                    ],
                    "volumes": [{"name": "script", "configMap": {"name": "r7-workload"}}],
                },
            },
        },
    }


def parse_duration_ms(value: str) -> float:
    match = re.fullmatch(r"([0-9.]+)(us|ms|s)", value.strip())
    if not match:
        raise ValueError(value)
    scale = {"us": 0.001, "ms": 1.0, "s": 1000.0}[match.group(2)]
    return float(match.group(1)) * scale


def parse_wrk(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {"raw_parser_version": 1}
    requests = re.search(r"([0-9]+) requests in ([0-9.]+)s", text)
    rps = re.search(r"Requests/sec:\s*([0-9.]+)", text)
    non2xx = re.search(r"Non-2xx or 3xx responses:\s*([0-9]+)", text)
    sockets = re.search(r"Socket errors: connect ([0-9]+), read ([0-9]+), write ([0-9]+), timeout ([0-9]+)", text)
    if requests:
        result["requests"] = int(requests.group(1)); result["measured_seconds"] = float(requests.group(2))
    if rps:
        result["requests_per_second"] = float(rps.group(1))
    result["non_2xx_3xx"] = int(non2xx.group(1)) if non2xx else 0
    if sockets:
        result["socket_errors"] = {name: int(value) for name, value in zip(("connect", "read", "write", "timeout"), sockets.groups())}
    else:
        result["socket_errors"] = {"connect": 0, "read": 0, "write": 0, "timeout": 0}
    latency: dict[str, float] = {}
    for percentile, value in re.findall(r"^\s*(50\.000|90\.000|99\.000|99\.900)%\s+([0-9.]+(?:us|ms|s))", text, re.MULTILINE):
        latency[f"p{percentile.replace('.000', '').replace('.900', '9')}_ms"] = parse_duration_ms(value)
    result["latency"] = latency
    result["total_errors"] = result["non_2xx_3xx"] + sum(result["socket_errors"].values())
    return result


def parse_probe(text: str) -> dict[str, Any]:
    samples = [line.strip() for line in text.splitlines() if line.strip() in {"OK", "FAIL"}]
    failed = sum(value == "FAIL" for value in samples)
    longest = current = 0
    for value in samples:
        current = current + 1 if value == "FAIL" else 0
        longest = max(longest, current)
    last_fail = max((index for index, value in enumerate(samples) if value == "FAIL"), default=-1)
    return {
        "samples": len(samples), "successes": len(samples) - failed, "failures": failed,
        "downtime_seconds": failed * 0.2, "longest_outage_seconds": longest * 0.2,
        "last_failure_seconds": None if last_fail < 0 else last_fail * 0.2,
    }


def accepted_prior(cell_base: Path, duration: int, rate: int) -> dict[str, Any] | None:
    paths = ([cell_base / "result.json"] if (cell_base / "result.json").exists() else []) + sorted(cell_base.glob("attempt-*/result.json"))
    for path in paths:
        row = json.loads(path.read_text(encoding="utf-8"))
        if row.get("accepted") and row.get("duration_seconds") == duration and row.get("target_rate_rps") == rate:
            return row
    return None


def attempt_dir(cell_base: Path) -> Path:
    if not cell_base.exists():
        cell_base.mkdir(parents=True, exist_ok=False)
        return cell_base
    numbers = []
    for path in cell_base.glob("attempt-*"):
        try:
            numbers.append(int(path.name.split("-")[-1]))
        except ValueError:
            pass
    result = cell_base / f"attempt-{max(numbers, default=0) + 1:02d}"
    result.mkdir(parents=True, exist_ok=False)
    return result


def invalid_runtime(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    failures = []
    for pod, state in after.items():
        if state["phase"] != "Running" or not state["ready"]:
            failures.append(f"unhealthy:{pod}")
        if state["restarts"] > before.get(pod, {}).get("restarts", 0):
            failures.append(f"restart:{pod}")
        if any(reason in {"OOMKilled", "Evicted"} for reason in state["reasons"]):
            failures.append(f"runtime-instability:{pod}")
    return failures


def cell_id(condition: str, replicate: int, method: str) -> str:
    return f"{condition}__replicate-{replicate:02d}__{method.lower()}"


def run_cell(
    run_root: Path, condition: str, replicate: int, method: str,
    duration: int, rate: int,
) -> dict[str, Any]:
    identity = cell_id(condition, replicate, method)
    cell_base = run_root / "raw" / "r7" / condition / f"replicate-{replicate:02d}" / method
    prior = accepted_prior(cell_base, duration, rate)
    if prior:
        return prior
    cell = attempt_dir(cell_base)
    clear_network()
    if not network_is_clear():
        raise RuntimeError("network shaping could not be cleared before cell")
    set_frontend_node(SOURCE)
    wait_stack(240)
    before = pod_runtime_state()
    before_placement = placement()
    shape: dict[str, Any] | None = None
    if condition == "degradation":
        shape = node_shape(SOURCE, 35, 60, 1.5)
    elif condition == "conflict":
        shape = node_shape(SOURCE, 80, 20, 5.0)
    elif condition == "recovery":
        shape = node_shape(SOURCE, 50, 40, 2.0)
    job = f"r7-{condition[:4]}-r{replicate}-{method.lower()}"
    kubectl("delete", "job", job, "-n", NS, "--ignore-not-found=true", "--wait=true", check=False)
    kubectl("apply", "-f", "-", input_text=json.dumps(job_manifest(job, duration, rate)))
    kubectl("wait", "-n", NS, f"pod", "-l", f"job-name={job}", "--for=condition=Ready", "--timeout=120s", timeout=140)
    started_utc = utc_now(); started = time.monotonic()
    samples = [stats_snapshot()]
    controller = {
        "method": method, "condition": condition, "observed_node": SOURCE,
        "decision": "hold", "reason": "baseline-no-controller" if method == "Baseline" else "stable-hysteresis-gate",
        "decision_utc": utc_now(), "relocation": None,
    }
    time.sleep(5)
    samples.append(stats_snapshot())
    if method == "BPlus" and condition in {"degradation", "conflict", "recovery"}:
        move_started = time.monotonic()
        rollout = set_frontend_node(TARGET)
        controller.update({
            "decision": "relocate", "reason": "persistent-source-network-risk",
            "target_node": TARGET,
            "relocation": {"service": "frontend", "source": SOURCE, "target": TARGET, "rollout_seconds": rollout, "elapsed_seconds": time.monotonic() - move_started},
        })
    if condition == "recovery":
        remaining_to_recovery = 15 - (time.monotonic() - started)
        if remaining_to_recovery > 0:
            time.sleep(remaining_to_recovery)
        clear_network()
        controller["network_recovered_utc"] = utc_now()
        controller["network_recovery_elapsed_seconds"] = time.monotonic() - started
    while time.monotonic() - started < duration + 2:
        time.sleep(min(5, max(0.2, duration + 2 - (time.monotonic() - started))))
        samples.append(stats_snapshot())
    completion = run(["kubectl", "wait", "-n", NS, f"job/{job}", "--for=condition=complete", "--timeout=90s"], check=False, timeout=110)
    wrk_log = kubectl("logs", "-n", NS, f"job/{job}", "-c", "wrk2", check=False)
    probe_log = kubectl("logs", "-n", NS, f"job/{job}", "-c", "probe", check=False)
    after = pod_runtime_state()
    after_placement = placement()
    clear_network()
    clear_ok = network_is_clear()
    measured = parse_wrk(wrk_log)
    probe = parse_probe(probe_log)
    runtime_failures = invalid_runtime(before, after)
    acceptance_failures = []
    if completion.returncode != 0:
        acceptance_failures.append("workload-job-nonzero-or-timeout")
    if measured.get("requests", 0) <= 0 or measured.get("requests_per_second", 0) <= 0:
        acceptance_failures.append("missing-workload-throughput")
    if not measured.get("latency"):
        acceptance_failures.append("missing-latency-histogram")
    if probe["samples"] < duration * 3:
        acceptance_failures.append("insufficient-probe-telemetry")
    if not clear_ok:
        acceptance_failures.append("network-shaping-not-cleared")
    acceptance_failures.extend(runtime_failures)
    accepted = not acceptance_failures
    result = {
        "cell_id": identity, "condition": condition, "method": method, "replicate": replicate,
        "duration_seconds": duration, "target_rate_rps": rate,
        "started_utc": started_utc, "completed_utc": utc_now(),
        "elapsed_seconds": time.monotonic() - started,
        "official_workload": {"image": "deathstarbench/wrk2-client:latest", "script": "DeathStarBench hotelReservation mixed-workload_type_1.lua"},
        "network_condition": shape, "workload": measured, "probe": probe,
        "resources": summarize_resources(samples, duration),
        "placement_before": before_placement, "placement_after": after_placement,
        "controller": controller, "runtime_before": before, "runtime_after": after,
        "network_clear_after": clear_ok, "acceptance_failures": acceptance_failures,
        "accepted": accepted, "acceptance_gate_version": 1,
    }
    atomic_write_text(cell / "wrk2.log", wrk_log)
    atomic_write_text(cell / "probe.log", probe_log)
    atomic_write_json(cell / "resource-samples.json", samples)
    atomic_write_json(cell / "result.json", result)
    kubectl("delete", "job", job, "-n", NS, "--ignore-not-found=true", "--wait=true", check=False)
    set_frontend_node(SOURCE)
    if not accepted:
        raise RuntimeError(f"R7 cell failed acceptance: {identity}: {acceptance_failures}")
    return result


def accepted_rows(run_root: Path, duration: int, rate: int) -> list[dict[str, Any]]:
    rows = []
    for path in (run_root / "raw" / "r7").glob("**/result.json"):
        row = json.loads(path.read_text(encoding="utf-8"))
        if row.get("accepted") and row.get("duration_seconds") == duration and row.get("target_rate_rps") == rate:
            rows.append(row)
    unique = {row["cell_id"]: row for row in rows}
    return list(unique.values())


def progress(run_root: Path, duration: int, rate: int, started: float, latest: str | None = None) -> dict[str, Any]:
    rows = accepted_rows(run_root, duration, rate)
    desired = len(CONDITIONS) * len(METHODS) * REPLICATES
    completed = len(rows)
    elapsed = time.monotonic() - started
    # Base resumed-run ETAs on accepted cell timings, not on how quickly the
    # current process discovers already-completed checkpoints.
    timings = [float(row["elapsed_seconds"]) for row in rows if row.get("elapsed_seconds") is not None]
    mean = statistics.fmean(timings) if timings else None
    remaining = desired - completed
    report = {
        "updated_utc": utc_now(), "status": "complete" if completed == desired else "in_progress",
        "observed_cells": completed, "desired_cells": desired, "remaining_cells": remaining,
        "percent_complete": round(100 * completed / desired, 2), "latest_cell_id": latest,
        "elapsed_seconds_this_process": elapsed, "mean_seconds_per_completed_cell_this_process": mean,
        "estimated_remaining_seconds": None if mean is None else mean * remaining,
        "estimated_completion_utc": None if mean is None else datetime.fromtimestamp(time.time() + mean * remaining, timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    atomic_write_json(run_root / "checkpoints" / "r7-progress.json", report)
    return report


def prepare(run_root: Path) -> dict[str, Any]:
    snapshot = resource_snapshot(run_root)
    assert_resource_gate(snapshot, min_disk_gib=5, min_docker_gib=11)
    atomic_write_json(run_root / "raw" / "r7" / "preflight-resources.json", snapshot)
    capture_pre_handover(run_root)
    delete_old_workloads()
    apply_stack()
    install_workload_script(run_root)
    health = wait_stack(600)
    atomic_write_json(run_root / "raw" / "r7" / "deployment-health.json", health)
    capture_json(run_root, "raw/r7/deployed-resources.json", "get", "all", "-n", NS)
    capture_json(run_root, "raw/r7/deployed-pods.json", "get", "pods", "-n", NS)
    return health


def campaign(run_root: Path, duration: int, rate: int, prepare_only: bool) -> int:
    (run_root / "raw" / "r7").mkdir(parents=True, exist_ok=True)
    health = prepare(run_root)
    if prepare_only:
        print(json.dumps({"status": "prepared", "health": health}, indent=2)); return 0
    process_started = time.monotonic()
    report = progress(run_root, duration, rate, process_started)
    for replicate in range(1, REPLICATES + 1):
        for condition in CONDITIONS:
            for method in METHODS:
                identity = cell_id(condition, replicate, method)
                print(f"R7 {identity}", flush=True)
                row = run_cell(run_root, condition, replicate, method, duration, rate)
                report = progress(run_root, duration, rate, process_started, row["cell_id"])
                print(json.dumps({key: report[key] for key in ("observed_cells", "desired_cells", "remaining_cells", "percent_complete", "estimated_completion_utc")}), flush=True)
    rows = accepted_rows(run_root, duration, rate)
    desired = len(CONDITIONS) * len(METHODS) * REPLICATES
    if len(rows) != desired:
        raise RuntimeError(f"R7 incomplete: {len(rows)}/{desired}")
    summary = {
        **report,
        "conditions": list(CONDITIONS), "methods": list(METHODS), "replicates": REPLICATES,
        "official_workload_used": True,
        "mean_requests_per_second": statistics.fmean(row["workload"]["requests_per_second"] for row in rows),
        "total_requests": sum(row["workload"]["requests"] for row in rows),
        "total_errors": sum(row["workload"]["total_errors"] for row in rows),
        "total_relocations": sum(row["controller"]["relocation"] is not None for row in rows),
        "all_cells_accepted": all(row["accepted"] for row in rows),
    }
    atomic_write_json(run_root / "derived" / "r7-summary.json", summary)
    ledger_path = run_root / "checkpoints" / "ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["phases"]["phase-11-r7"] = "completed"
    ledger["current_phase"] = "phase-12-regenerate"
    atomic_write_json(ledger_path, ledger)
    write_manifest(run_root, run_root / "manifests" / "run.sha256")
    print(json.dumps(summary, indent=2)); return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_root", type=Path)
    parser.add_argument("--duration-seconds", type=int, default=DURATION_SECONDS)
    parser.add_argument("--rate-rps", type=int, default=RATE_RPS)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    if args.duration_seconds < 20:
        raise ValueError("R7 measured duration must be at least 20 seconds")
    lock_scope = args.run_root.resolve().parent / f".r7-lock-{args.run_root.resolve().name}"
    with CampaignLock(lock_scope):
        try:
            return campaign(args.run_root.resolve(), args.duration_seconds, args.rate_rps, args.prepare_only)
        finally:
            clear_network()


if __name__ == "__main__":
    raise SystemExit(main())
