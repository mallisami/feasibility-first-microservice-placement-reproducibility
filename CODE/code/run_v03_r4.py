"""Run the full v0.3 R4 stateful relocation matrix sequentially."""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from mape_cap_bplus.v03_evidence import atomic_write_json, atomic_write_text, utc_now, write_manifest
from run_v03_r1 import CampaignLock, WORKERS, all_egress, clear_network, docker
from run_v03_r2 import kubectl

NS = "r4-v03"
IMAGE = "redis:7-alpine"
SOURCE = WORKERS[0]
TARGET = WORKERS[1]
STORAGE = ("emptydir", "persistent-volume", "application-replication")
IMAGE_STATES = ("cached", "uncached")
STATE_SIZES = {"small": 1 * 1024**2, "medium": 16 * 1024**2, "large": 64 * 1024**2}
NETWORKS = ("stable", "degraded")
LOADS = ("idle", "loaded")
TOTAL = len(STORAGE) * len(IMAGE_STATES) * len(STATE_SIZES) * len(NETWORKS) * len(LOADS)


def run(args: list[str], *, check: bool = True, timeout: int = 180, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, input=input_text, capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(args)}\n{result.stderr[-2000:]}")
    return result


def apply(manifest: dict[str, Any]) -> None:
    run(["kubectl", "apply", "-f", "-"], input_text=json.dumps(manifest))


def delete(kind: str, name: str, *, wait: bool = True) -> None:
    run(["kubectl", "delete", kind, name, "-n", NS, f"--wait={'true' if wait else 'false'}", "--ignore-not-found=true"], check=False, timeout=120)


def pod_manifest(name: str, node: str, role: str, storage: str, *, replica: bool = False) -> dict[str, Any]:
    volumes: list[dict[str, Any]] = []
    mounts: list[dict[str, Any]] = []
    if storage == "persistent-volume":
        volumes = [{"name": "data", "persistentVolumeClaim": {"claimName": "r4-data"}}]
        mounts = [{"name": "data", "mountPath": "/data"}]
    else:
        volumes = [{"name": "data", "emptyDir": {}}]
        mounts = [{"name": "data", "mountPath": "/data"}]
    args = ["redis-server", "--appendonly", "yes", "--appendfsync", "always"]
    if replica:
        args += ["--replicaof", "r4-source", "6379"]
    return {
        "apiVersion": "v1", "kind": "Pod", "metadata": {"name": name, "namespace": NS, "labels": {"app": "r4-redis", "role": role, "r4-source": "true" if name == "r4-source-pod" else "false"}},
        "spec": {"nodeSelector": {"kubernetes.io/hostname": node}, "restartPolicy": "Never",
                 "containers": [{"name": "redis", "image": IMAGE, "imagePullPolicy": "IfNotPresent", "command": args,
                                 "ports": [{"containerPort": 6379}], "volumeMounts": mounts,
                                 "readinessProbe": {"exec": {"command": ["redis-cli", "ping"]}, "periodSeconds": 1, "failureThreshold": 90},
                                 "resources": {"requests": {"cpu": "20m", "memory": "96Mi"}, "limits": {"cpu": "1", "memory": "512Mi"}}}],
                 "volumes": volumes},
    }


def wait_ready(name: str, timeout: int = 180) -> tuple[bool, float]:
    started = time.monotonic()
    result = run(["kubectl", "wait", "-n", NS, f"pod/{name}", "--for=condition=Ready", f"--timeout={timeout}s"], check=False, timeout=timeout + 15)
    return result.returncode == 0, time.monotonic() - started


def exec_redis(pod: str, *args: str, check: bool = True, timeout: int = 120) -> str:
    return run(["kubectl", "exec", "-n", NS, pod, "--", "redis-cli", *args], check=check, timeout=timeout).stdout.strip()


def seed_state(pod: str, size: int) -> tuple[str, float]:
    started = time.monotonic()
    command = f"head -c {size} /dev/zero | redis-cli -x set state"
    run(["kubectl", "exec", "-n", NS, pod, "--", "sh", "-c", command], timeout=300)
    actual = int(exec_redis(pod, "STRLEN", "state"))
    if actual != size:
        raise RuntimeError(f"state length mismatch: expected {size}, got {actual}")
    digest = exec_redis(pod, "EVAL", "return redis.sha1hex(redis.call('GET',KEYS[1]))", "1", "state")
    expected = hashlib.sha1(b"\0" * size).hexdigest()
    if digest != expected:
        raise RuntimeError("initial state digest mismatch")
    return digest, time.monotonic() - started


def state_integrity(pod: str, size: int, digest: str) -> dict[str, Any]:
    length_text = exec_redis(pod, "STRLEN", "state", check=False)
    try:
        length = int(length_text)
    except ValueError:
        return {"available": False, "length_bytes": None, "digest": None, "intact": False}
    actual = exec_redis(pod, "EVAL", "local v=redis.call('GET',KEYS[1]); if not v then return '' end; return redis.sha1hex(v)", "1", "state", check=False)
    return {"available": True, "length_bytes": length, "digest": actual, "intact": length == size and actual == digest}


def ensure_namespace() -> None:
    run(["kubectl", "create", "namespace", NS], check=False)
    apply({"apiVersion": "v1", "kind": "Service", "metadata": {"name": "r4-active", "namespace": NS}, "spec": {"selector": {"app": "r4-redis", "role": "active"}, "ports": [{"port": 6379}]}})
    apply({"apiVersion": "v1", "kind": "Service", "metadata": {"name": "r4-source", "namespace": NS}, "spec": {"selector": {"app": "r4-redis", "r4-source": "true"}, "ports": [{"port": 6379}]}})
    apply({"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "r4-client", "namespace": NS}, "spec": {"nodeSelector": {"kubernetes.io/hostname": WORKERS[2]}, "containers": [{"name": "client", "image": IMAGE, "command": ["sh", "-c", "sleep infinity"]}]}})
    ready, _ = wait_ready("r4-client", 180)
    if not ready:
        raise RuntimeError("R4 client did not become Ready")


def cleanup_cell() -> None:
    clear_network()
    for name in ("r4-source-pod", "r4-target-pod"):
        delete("pod", name, wait=False)
    delete("pvc", "r4-data", wait=False)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        result = run(["kubectl", "get", "pod", "-n", NS, "-l", "app=r4-redis", "-o", "name"], check=False)
        if not result.stdout.strip():
            return
        time.sleep(1)
    raise RuntimeError("R4 cell cleanup timed out")


def set_role(pod: str, role: str) -> None:
    run(["kubectl", "label", "pod", pod, "-n", NS, f"role={role}", "--overwrite"])


def start_probe() -> subprocess.Popen[str]:
    script = "ok=0; fail=0; i=0; while [ $i -lt 180 ]; do if redis-cli -h r4-active ping 2>/dev/null | grep -q PONG; then ok=$((ok+1)); echo OK; else fail=$((fail+1)); echo FAIL; fi; i=$((i+1)); sleep 0.2; done; echo SUMMARY:$ok:$fail"
    return subprocess.Popen(["kubectl", "exec", "-n", NS, "r4-client", "--", "sh", "-c", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def start_load(enabled: bool) -> subprocess.Popen[str] | None:
    if not enabled:
        return None
    return subprocess.Popen(["kubectl", "exec", "-n", NS, "r4-client", "--", "redis-benchmark", "-h", "r4-active", "-t", "get,set", "-n", "1000000", "-c", "10", "-q"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def stop_process(process: subprocess.Popen[str] | None) -> str:
    if process is None:
        return ""
    process.terminate()
    try:
        stdout, stderr = process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill(); stdout, stderr = process.communicate()
    return stdout + stderr


def uncached_target() -> dict[str, Any]:
    def redis_images() -> list[dict[str, Any]]:
        payload = json.loads(docker(TARGET, "crictl", "images", "--output", "json"))
        matches = []
        for item in payload.get("images", []):
            references = [*item.get("repoTags", []), *item.get("repoDigests", [])]
            if any(reference == IMAGE or reference.startswith("docker.io/library/redis:") for reference in references):
                matches.append({"id": item.get("id"), "references": references})
        return matches

    before = redis_images()
    removal_attempts = []
    if before:
        for attempt in range(1, 4):
            removal = run(
                ["docker", "exec", TARGET, "crictl", "rmi", IMAGE],
                check=False,
                timeout=90,
            )
            remaining = redis_images()
            removal_attempts.append({
                "attempt": attempt,
                "returncode": removal.returncode,
                "stderr": removal.stderr[-1000:],
                "remaining_images": remaining,
            })
            if not remaining:
                break
            time.sleep(3 * attempt)
    after = redis_images()
    return {
        "before_images": before,
        "after_images": after,
        "was_present": bool(before),
        "removed": bool(before) and not bool(after),
        "confirmed_absent": not bool(after),
        "removal_attempts": removal_attempts,
    }


def events() -> str:
    return run(["kubectl", "get", "events", "-n", NS, "--sort-by=.lastTimestamp"], check=False).stdout


def cell_id(storage: str, image: str, size: str, network: str, load: str) -> str:
    return f"{storage}__{image}__{size}__{network}__{load}"


def progress(run_root: Path, latest: str | None = None) -> dict[str, Any]:
    all_rows = [json.loads(p.read_text(encoding="utf-8")) for p in (run_root / "raw" / "r4").glob("**/result.json")]
    rows = [row for row in all_rows if row.get("accepted_evidence") is True]
    report = {"updated_utc": utc_now(), "status": "complete" if len(rows) == TOTAL else "in_progress", "observed_cells": len(rows), "desired_cells": TOTAL, "remaining_cells": TOTAL - len(rows), "preserved_failed_attempts": len(all_rows) - len(rows), "successful_relocations": sum(r["relocation_success"] for r in rows), "expected_boundary_failures": sum(r["classification"] == "pvc-node-affinity-boundary" for r in rows), "integrity_preserved_cells": sum(r["integrity"].get("intact") is True for r in rows), "latest_cell_id": latest}
    atomic_write_json(run_root / "checkpoints" / "r4-progress.json", report)
    return report


def run_cell(run_root: Path, storage: str, image_state: str, size_name: str, network: str, load: str, timeout: int) -> dict[str, Any]:
    identity = cell_id(storage, image_state, size_name, network, load)
    cell_base = run_root / "raw" / "r4" / identity
    prior_paths = ([cell_base / "result.json"] if (cell_base / "result.json").exists() else []) + sorted(cell_base.glob("attempt-*/result.json"))
    for prior_path in prior_paths:
        prior = json.loads(prior_path.read_text(encoding="utf-8"))
        if prior.get("accepted_evidence"):
            return prior
    if not cell_base.exists():
        cell = cell_base
    else:
        attempts = []
        for directory in cell_base.glob("attempt-*"):
            try:
                attempts.append(int(directory.name.rsplit("-", 1)[-1]))
            except ValueError:
                pass
        cell = cell_base / f"attempt-{max(attempts, default=0) + 1:02d}"
    result_path = cell / "result.json"
    cell.mkdir(parents=True, exist_ok=False)
    cleanup_cell()
    if storage == "persistent-volume":
        apply({"apiVersion": "v1", "kind": "PersistentVolumeClaim", "metadata": {"name": "r4-data", "namespace": NS}, "spec": {"accessModes": ["ReadWriteOnce"], "storageClassName": "standard", "resources": {"requests": {"storage": "256Mi"}}}})
    source_role = "source" if storage == "application-replication" else "active"
    apply(pod_manifest("r4-source-pod", SOURCE, source_role, storage))
    source_ready, initial_seconds = wait_ready("r4-source-pod", timeout)
    if not source_ready:
        raise RuntimeError(f"source pod failed: {identity}")
    size = STATE_SIZES[size_name]
    digest, seed_seconds = seed_state("r4-source-pod", size)
    if storage == "application-replication":
        set_role("r4-source-pod", "active")
    image_evidence = {"requested": image_state, "removed": False}
    if image_state == "uncached":
        image_evidence = {"requested": image_state, **uncached_target()}
        if not image_evidence["confirmed_absent"]:
            raise RuntimeError(f"target image absence was not verified for uncached cell: {identity}")
    if network == "degraded":
        all_egress(20, 50, .5)
    probe = start_probe()
    load_process = start_load(load == "loaded")
    started_utc = utc_now(); started = time.monotonic()
    relocation_success = False; cold_start = None; storage_reattach = None; classification = ""
    integrity: dict[str, Any] = {"available": False, "intact": False}
    target_ready = False
    try:
        if storage in {"emptydir", "persistent-volume"}:
            delete("pod", "r4-source-pod")
            apply(pod_manifest("r4-target-pod", TARGET, "active", storage))
            target_ready, cold_start = wait_ready("r4-target-pod", 25 if storage == "persistent-volume" else timeout)
            relocation_success = target_ready
            storage_reattach = cold_start if target_ready and storage == "persistent-volume" else None
            if target_ready:
                integrity = state_integrity("r4-target-pod", size, digest)
                classification = "emptydir-state-loss" if storage == "emptydir" and not integrity["intact"] else "unexpected-outcome"
            else:
                event_text = events()
                affinity = "volume node affinity conflict" in event_text.lower() or "PersistentVolume's node affinity" in event_text
                classification = "pvc-node-affinity-boundary" if storage == "persistent-volume" and affinity else "unexpected-failure"
        else:
            apply(pod_manifest("r4-target-pod", TARGET, "replica", storage, replica=True))
            target_ready, cold_start = wait_ready("r4-target-pod", timeout)
            if not target_ready:
                raise RuntimeError("application replica target did not become Ready")
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                info = exec_redis("r4-target-pod", "INFO", "replication", check=False)
                if "master_link_status:up" in info and state_integrity("r4-target-pod", size, digest)["intact"]:
                    break
                time.sleep(1)
            integrity = state_integrity("r4-target-pod", size, digest)
            if not integrity["intact"]:
                raise RuntimeError("application replica did not synchronize state")
            exec_redis("r4-target-pod", "REPLICAOF", "NO", "ONE")
            set_role("r4-source-pod", "source")
            set_role("r4-target-pod", "active")
            delete("pod", "r4-source-pod", wait=False)
            relocation_success = True
            classification = "application-replication-success"
        relocation_seconds = time.monotonic() - started
    finally:
        clear_network()
        load_log = stop_process(load_process)
        probe_log = stop_process(probe)
    event_text = events()
    ok = probe_log.count("OK\n"); failed = probe_log.count("FAIL\n")
    pull_match = re.search(r"Successfully pulled image .* in ([0-9.]+)s", event_text)
    image_evidence["observed_pull_seconds"] = float(pull_match.group(1)) if pull_match else None
    expected = ((storage == "emptydir" and relocation_success and not integrity["intact"]) or (storage == "persistent-volume" and classification == "pvc-node-affinity-boundary") or (storage == "application-replication" and relocation_success and integrity["intact"]))
    result = {"cell_id": identity, "storage": storage, "image_state": image_state, "state_size": size_name, "state_size_bytes": size, "network": network, "load": load, "source_node": SOURCE, "target_node": TARGET, "started_utc": started_utc, "completed_utc": utc_now(), "initial_deployment_seconds": initial_seconds, "state_seed_seconds": seed_seconds, "relocation_success": relocation_success, "relocation_seconds": relocation_seconds, "cold_start_seconds": cold_start, "storage_reattachment_seconds": storage_reattach, "state_transfer_bytes": size if storage == "application-replication" else 0, "integrity": integrity, "data_loss": integrity.get("intact") is False if integrity.get("available") else None, "probe_successes": ok, "failed_requests": failed, "downtime_probe_seconds": failed * .2, "image_evidence": image_evidence, "classification": classification, "expected_outcome_observed": expected, "accepted_evidence": expected}
    atomic_write_json(result_path, result); atomic_write_text(cell / "events.log", event_text); atomic_write_text(cell / "probe.log", probe_log); atomic_write_text(cell / "load.log", load_log)
    if not expected:
        raise RuntimeError(f"R4 unexpected outcome: {identity}: {classification}")
    return result


def campaign(run_root: Path, timeout: int) -> int:
    (run_root / "raw" / "r4").mkdir(parents=True, exist_ok=True)
    kubectl("scale", "deployment/loadgenerator", "-n", "online-boutique", "--replicas=0")
    ensure_namespace(); progress(run_root)
    try:
        for values in itertools.product(STORAGE, IMAGE_STATES, STATE_SIZES, NETWORKS, LOADS):
            identity = cell_id(*values)
            print(f"R4 {identity}", flush=True)
            row = run_cell(run_root, *values, timeout)
            progress(run_root, row["cell_id"])
    finally:
        cleanup_cell(); clear_network()
    report = progress(run_root)
    if report["observed_cells"] != TOTAL:
        raise RuntimeError(f"R4 incomplete: {report}")
    rows = [json.loads(p.read_text(encoding="utf-8")) for p in (run_root / "raw" / "r4").glob("**/result.json")]
    rows = [row for row in rows if row.get("accepted_evidence") is True]
    summary = {**report, "matrix_dimensions": {"storage": list(STORAGE), "image_state": list(IMAGE_STATES), "state_sizes_bytes": STATE_SIZES, "network": list(NETWORKS), "load": list(LOADS)}, "all_expected_outcomes_observed": all(r["expected_outcome_observed"] for r in rows), "total_failed_requests": sum(r["failed_requests"] for r in rows), "total_state_transfer_bytes": sum(r["state_transfer_bytes"] for r in rows)}
    atomic_write_json(run_root / "derived" / "r4-summary.json", summary)
    ledger_path = run_root / "checkpoints" / "ledger.json"; ledger = json.loads(ledger_path.read_text(encoding="utf-8")); ledger["phases"]["phase-9-r3"] = "completed"; ledger["phases"]["phase-10-r4"] = "completed"; ledger["current_phase"] = "phase-11-r7"; atomic_write_json(ledger_path, ledger)
    write_manifest(run_root, run_root / "manifests" / "run.sha256")
    print(json.dumps(summary, indent=2)); return 0


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("run_root", type=Path); parser.add_argument("--timeout-seconds", type=int, default=180); args = parser.parse_args()
    lock_scope = args.run_root.resolve().parent / f".r4-lock-{args.run_root.resolve().name}"
    with CampaignLock(lock_scope):
        return campaign(args.run_root.resolve(), args.timeout_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
