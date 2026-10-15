#!/usr/bin/env python3
"""Packet-level ns-3/WiGig confirmation of value beyond byte affinity.

Protocol v1.1. This post-Kubernetes, separately frozen confirmation reuses the
same 30 held-out six-replica communication graphs and Current/Affinity-Bytes/
BPlus-Exact placements. Six directed rack-pair aggregates map to six fixed STAs
in the pinned Q-D DenseScenario and contend at one DMG AP.

Evidence boundary: packet-level 802.11ad/WiGig simulation under a fixed dense
shared-medium mapping. This is not physical hardware and not a complete three-
rack RF geometry.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
from scipy.stats import wilcoxon

EXP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EXP_ROOT.parents[1]
K8S_EXP = REPO_ROOT / "EXPERIMENTS" / "k8s_affinity_wireless_confirmatory"
sys.path.insert(0, str(K8S_EXP / "src"))
sys.path.insert(0, str(REPO_ROOT / "implementation" / "code"))

import live_confirmatory as live  # canonical held-out graph/planner construction

CFG = json.loads((EXP_ROOT / "config" / "experiment.json").read_text(encoding="utf-8"))
RESULTS = EXP_ROOT / "results"
CURRENT_RUN_FILE = RESULTS / "CURRENT_RUN.txt"
PAIR_TO_STA = dict(CFG["rack_pair_to_sta"])
WIRELESS_TRACE = REPO_ROOT / "RESULTS" / "calibration" / "external" / "ns3_simulation_backed_traces.csv"
K8S_CONFIG = K8S_EXP / "config" / "experiment.json"
LIVE_SOURCE = K8S_EXP / "src" / "live_confirmatory.py"
PLANNER_TREE = REPO_ROOT / "implementation" / "code" / "mape_cap_bplus"
BASE_DOCKERFILE = REPO_ROOT / "implementation" / "kubernetes" / "simulator" / "Dockerfile.ns3-wigig"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def atomic_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str), encoding="utf-8")
    os.replace(tmp, path)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_tree(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if not p.is_file() or "__pycache__" in p.parts or p.suffix in {".pyc", ".pyo"}:
            continue
        rel = p.relative_to(root).as_posix().encode("utf-8")
        h.update(len(rel).to_bytes(8, "big")); h.update(rel)
        digest = bytes.fromhex(sha256_file(p))
        h.update(digest)
    return h.hexdigest()


def json_digest(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def run_cmd(args: list[str], *, timeout: int = 180, check: bool = True) -> subprocess.CompletedProcess[str]:
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if check and p.returncode:
        raise RuntimeError(
            f"command failed ({p.returncode}): {' '.join(args)}\nstdout:\n{p.stdout[-3000:]}\nstderr:\n{p.stderr[-3000:]}"
        )
    return p


def reference_info() -> dict[str, Any]:
    cap = CFG["reference_node_capacity"]
    workers = ("worker-a", "worker-b", "worker-c")
    return {
        "rack_to_worker": {"rack-a": "worker-a", "rack-b": "worker-b", "rack-c": "worker-c"},
        "allocatable": {w: {"cpu": float(cap["cpu"]), "memory_mb": float(cap["memory_mb"])} for w in workers},
    }


def raw_pair_rates_mbps(problem, placement: Mapping[str, str]) -> list[float]:
    rates = [0.0] * int(CFG["num_stas"])
    nodes = problem.node_by_id
    for flow in problem.flows:
        sr = nodes[placement[flow.source_replica]].rack_id
        dr = nodes[placement[flow.destination_replica]].rack_id
        if sr == dr:
            continue
        key = f"{sr}>{dr}"
        if key not in PAIR_TO_STA:
            raise RuntimeError(f"unmapped rack pair {key}")
        idx = int(PAIR_TO_STA[key])
        rates[idx] += float(flow.bits_per_window) / float(problem.decision_window_seconds) / 1e6
    if any(r < -1e-12 for r in rates):
        raise RuntimeError("negative raw rack-pair rate generated")
    return rates


def scale_rates(raw_rates: list[float], multiplier: float) -> list[float]:
    rates = [float(r) * float(multiplier) for r in raw_rates]
    mx = max(rates, default=0.0)
    if mx > float(CFG["max_rate_mbps_per_stream"]) + 1e-9:
        raise RuntimeError(
            f"per-stream offered rate {mx:.6f} Mbps exceeds frozen guard {CFG['max_rate_mbps_per_stream']}"
        )
    return rates


def make_cell_plan(seed: int, target: float) -> dict[str, Any]:
    problem, calibration = live.build_problem(seed, reference_info(), target)
    plans = live.plan_methods(problem)

    raw_current = raw_pair_rates_mbps(problem, plans["Current"]["placement"])
    current_raw_total = float(sum(raw_current))
    if current_raw_total <= 0:
        raise RuntimeError(f"Current placement has zero cross-rack traffic for seed {seed}, target {target}")

    reference_aggregate = float(CFG["reference_dense_aggregate_mbps"])
    expected_reference = float(CFG["reference_dense_num_stas"]) * float(CFG["reference_dense_sta_rate_mbps"])
    if not math.isclose(reference_aggregate, expected_reference, rel_tol=0.0, abs_tol=1e-12):
        raise RuntimeError("dense offered-load reference is internally inconsistent")
    desired_current_total = reference_aggregate * float(target)
    load_multiplier = desired_current_total / current_raw_total

    out: dict[str, Any] = {
        "seed": int(seed),
        "target": float(target),
        "load_anchor": {
            "reference_sta_rate_mbps": float(CFG["reference_dense_sta_rate_mbps"]),
            "reference_num_stas": int(CFG["reference_dense_num_stas"]),
            "reference_aggregate_mbps": reference_aggregate,
            "desired_current_total_mbps": desired_current_total,
            "current_raw_cross_rack_mbps": current_raw_total,
            "common_graph_load_multiplier": load_multiplier,
        },
        "calibration": calibration,
        "methods": {},
    }
    for method in CFG["methods"]:
        pmeta = plans[method]
        placement = dict(pmeta["placement"])
        raw_rates = raw_pair_rates_mbps(problem, placement)
        rates = scale_rates(raw_rates, load_multiplier)
        out["methods"][method] = {
            "placement": placement,
            "planner_abstained": bool(pmeta.get("planner_abstained", False)),
            "planned_feasible": bool(pmeta.get("planned_feasible", False)),
            "worst_conflict_utilization": float(pmeta["worst_conflict_utilization"]),
            "cross_rack_bits": float(pmeta["cross_rack_bits"]),
            "raw_pair_rates_mbps": raw_rates,
            "rates_mbps": rates,
            "total_offered_mbps": float(sum(rates)),
        }

    current_total = float(out["methods"]["Current"]["total_offered_mbps"])
    if not math.isclose(current_total, desired_current_total, rel_tol=1e-10, abs_tol=1e-8):
        raise RuntimeError(
            f"Current packet-load anchor mismatch: got {current_total:.12g}, expected {desired_current_total:.12g}"
        )
    return out


def self_test() -> dict[str, Any]:
    held = list(CFG["held_out_seeds"])
    if CFG["protocol_id"] != "wireless-beyond-affinity-ns3-v1.1":
        raise RuntimeError("packet protocol ID changed")
    if held != list(range(44001, 44031)):
        raise RuntimeError("held-out seed block changed")
    if CFG["methods"] != ["Current", "Affinity-Bytes", "BPlus-Exact"]:
        raise RuntimeError("method set/order changed")
    if CFG["load_targets"] != [0.5, 1.25]:
        raise RuntimeError("load targets changed")
    if CFG["ns3_rng_runs"] != [201, 202, 203]:
        raise RuntimeError("nested ns-3 RNG runs changed")
    if sorted(PAIR_TO_STA.values()) != list(range(6)) or len(PAIR_TO_STA) != 6:
        raise RuntimeError("rack-pair to STA mapping is not a one-to-one six-stream mapping")
    if CFG["wigig_commit"] != "f3404236d05eb1da1cab80eec06c56ea8ab43f7d":
        raise RuntimeError("pinned WiGig commit changed")

    max_rate = 0.0
    min_active = float("inf")
    max_total = 0.0
    bplus_abstentions = 0
    for target in CFG["load_targets"]:
        for seed in held:
            plan = make_cell_plan(int(seed), float(target))
            expected_current = float(CFG["reference_dense_aggregate_mbps"]) * float(target)
            if not math.isclose(plan["methods"]["Current"]["total_offered_mbps"], expected_current, rel_tol=1e-10, abs_tol=1e-8):
                raise RuntimeError("Current load anchor not preserved")
            for method in CFG["methods"]:
                rates = plan["methods"][method]["rates_mbps"]
                active = [r for r in rates if r > 0]
                if active:
                    max_rate = max(max_rate, max(active))
                    min_active = min(min_active, min(active))
                max_total = max(max_total, sum(rates))
                if method == "BPlus-Exact" and plan["methods"][method]["planner_abstained"]:
                    bplus_abstentions += 1
    if max_rate > float(CFG["max_rate_mbps_per_stream"]) + 1e-9:
        raise RuntimeError("rate guard violated")
    return {
        "passed": True,
        "protocol_id": CFG["protocol_id"],
        "held_out_seeds": [min(held), max(held)],
        "load_targets": CFG["load_targets"],
        "nested_ns3_runs": CFG["ns3_rng_runs"],
        "reference_dense_aggregate_mbps": float(CFG["reference_dense_aggregate_mbps"]),
        "min_active_stream_mbps": min_active,
        "max_stream_mbps": max_rate,
        "max_total_offered_mbps": max_total,
        "bplus_abstention_rows_across_targets": bplus_abstentions,
        "evidence_boundary": "packet-level WiGig QD dense shared-medium cross-check; no physical hardware",
    }


def offline_audit() -> dict[str, Any]:
    rows = []
    for target in CFG["load_targets"]:
        for seed in CFG["held_out_seeds"]:
            plan = make_cell_plan(int(seed), float(target))
            for method in CFG["methods"]:
                m = plan["methods"][method]
                active = [r for r in m["rates_mbps"] if r > 0]
                rows.append({
                    "seed": int(seed), "target": float(target), "method": method,
                    "planner_abstained": bool(m["planner_abstained"]),
                    "planned_feasible": bool(m["planned_feasible"]),
                    "active_streams": len(active),
                    "total_offered_mbps": float(sum(m["rates_mbps"])),
                    "max_stream_mbps": float(max(active) if active else 0.0),
                    "common_graph_load_multiplier": float(plan["load_anchor"]["common_graph_load_multiplier"]),
                    "desired_current_total_mbps": float(plan["load_anchor"]["desired_current_total_mbps"]),
                })
    expected_cells = len(rows) * len(CFG["ns3_rng_runs"])
    return {
        "protocol_id": CFG["protocol_id"],
        "planned_graph_method_target_rows": len(rows),
        "planned_packet_level_cells": expected_cells,
        "max_stream_mbps": max(r["max_stream_mbps"] for r in rows),
        "max_total_offered_mbps": max(r["total_offered_mbps"] for r in rows),
        "bplus_abstention_rows": sum(r["method"] == "BPlus-Exact" and r["planner_abstained"] for r in rows),
        "rows": rows,
    }


def check_results_disk() -> dict[str, Any]:
    RESULTS.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(RESULTS)
    free_gib = usage.free / (1024 ** 3)
    required = float(CFG["min_results_free_gib"])
    if free_gib + 1e-12 < required:
        raise RuntimeError(f"results filesystem has only {free_gib:.2f} GiB free; frozen minimum is {required:.2f} GiB")
    return {"results_path": str(RESULTS.resolve()), "free_gib": free_gib, "required_free_gib": required}


def docker_image_id(image: str) -> str:
    p = run_cmd(["docker", "image", "inspect", image, "--format", "{{.Id}}"], timeout=60, check=False)
    if p.returncode != 0 or not p.stdout.strip():
        raise RuntimeError(f"Docker image is unavailable: {image}")
    return p.stdout.strip()


def docker_git_commit(image: str) -> str:
    p = run_cmd(["docker", "run", "--rm", image, "git", "rev-parse", "HEAD"], timeout=60, check=False)
    if p.returncode != 0:
        raise RuntimeError(f"cannot verify WiGig Git commit inside image {image}: {p.stderr[-1500:]}")
    return p.stdout.strip().splitlines()[-1].strip()


def cleanup_container(name: str) -> None:
    if shutil.which("docker"):
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, text=True, timeout=60)


def ns3_container_command(evidence_dir: Path, rates: list[float], rng: int, name: str) -> tuple[list[str], str]:
    rates_csv = ",".join(f"{x:.6f}" for x in rates)
    spec = (
        f"evaluate_bplus_affinity_dense --simulationTime={CFG['simulation_seconds']} "
        f"--packetSize={CFG['packet_size_bytes']} --socketType={CFG['socket_type']} "
        f"--numSTAs={CFG['num_stas']} --ratesMbpsCsv={rates_csv} --csv=true "
        f"--reportDataSnr=true --directory=/evidence/ --qdChannelFolder={CFG['qd_channel_folder']} --RngRun={rng}"
    )
    command = [
        "docker", "run", "--rm", "--name", name,
        "-v", f"{evidence_dir.resolve()}:/evidence", str(CFG["experiment_image"]),
        "/bin/bash", "-lc", f"set -o pipefail; mkdir -p Traces; ./waf --run-no-build {json.dumps(spec)}",
    ]
    return command, spec


def validate_summary(path: Path, expected_rates: list[float], *, require_positive_rx: bool = False) -> dict[str, Any]:
    if not path.exists():
        raise RuntimeError("packet_summary.csv missing")
    df = pd.read_csv(path)
    required = {"sta_index", "configured_mbps", "active_seconds", "rx_bytes", "achieved_mbps", "delivered_fraction"}
    if not required.issubset(df.columns):
        raise RuntimeError(f"packet summary missing columns: {sorted(required - set(df.columns))}")
    if df["sta_index"].duplicated().any():
        raise RuntimeError("packet summary contains duplicate STA rows")
    active_expected = {i: float(r) for i, r in enumerate(expected_rates) if r > 0}
    if set(df["sta_index"].astype(int)) != set(active_expected):
        raise RuntimeError("active STA set does not match frozen rack-pair rate vector")

    offered_bits = 0.0
    rx_bits = 0.0
    achieved_sum = 0.0
    per_stream_delivered = []
    for _, row in df.iterrows():
        i = int(row["sta_index"])
        configured = float(row["configured_mbps"])
        active = float(row["active_seconds"])
        rx_bytes = float(row["rx_bytes"])
        achieved = float(row["achieved_mbps"])
        delivered = float(row["delivered_fraction"])
        vals = [configured, active, rx_bytes, achieved, delivered]
        if not all(math.isfinite(v) for v in vals):
            raise RuntimeError(f"non-finite packet summary value for STA {i}")
        if not math.isclose(configured, active_expected[i], rel_tol=1e-6, abs_tol=1e-6):
            raise RuntimeError(f"configured rate mismatch for STA {i}")
        if active <= 0 or active > float(CFG["simulation_seconds"]) + 1e-6 or rx_bytes < 0:
            raise RuntimeError(f"invalid active time/RX bytes for STA {i}")
        if require_positive_rx and rx_bytes <= 0:
            raise RuntimeError(f"smoke STA {i} received zero payload bytes")
        expected_achieved = rx_bytes * 8.0 / active / 1e6
        if not math.isclose(achieved, expected_achieved, rel_tol=2e-6, abs_tol=2e-6):
            raise RuntimeError(f"achieved Mbps is inconsistent with rx_bytes/active_seconds for STA {i}")
        stream_offered_bits = configured * 1e6 * active
        stream_rx_bits = rx_bytes * 8.0
        expected_delivered = min(1.0, stream_rx_bits / stream_offered_bits) if stream_offered_bits > 0 else 1.0
        if not math.isclose(delivered, expected_delivered, rel_tol=2e-6, abs_tol=2e-6):
            raise RuntimeError(f"stream delivered fraction is inconsistent for STA {i}")
        offered_bits += stream_offered_bits
        rx_bits += stream_rx_bits
        achieved_sum += achieved
        per_stream_delivered.append(delivered)

    aggregate_fraction = min(1.0, rx_bits / offered_bits) if offered_bits > 0 else 1.0
    return {
        "aggregate_offered_mbps": float(sum(active_expected.values())),
        "aggregate_offered_bits_active_intervals": offered_bits,
        "aggregate_rx_bits": rx_bits,
        "aggregate_achieved_mbps": achieved_sum,
        "aggregate_delivered_fraction": aggregate_fraction,
        "active_streams": len(active_expected),
        "mean_stream_delivered_fraction": float(np.mean(per_stream_delivered)) if per_stream_delivered else 1.0,
    }


def ensure_images() -> dict[str, Any]:
    disk = check_results_disk()
    if shutil.which("docker") is None:
        raise RuntimeError("docker executable is required")
    if run_cmd(["docker", "version"], timeout=60, check=False).returncode != 0:
        raise RuntimeError("Docker engine is not reachable")

    base = str(CFG["base_image"])
    if run_cmd(["docker", "image", "inspect", base], timeout=60, check=False).returncode != 0:
        canonical = REPO_ROOT / "implementation" / "kubernetes" / "simulator"
        run_cmd([
            "docker", "build", "--pull=false", "-t", base,
            "-f", str(canonical / "Dockerfile.ns3-wigig"), str(canonical),
        ], timeout=7200)
    base_id = docker_image_id(base)
    base_commit = docker_git_commit(base)
    if base_commit != str(CFG["wigig_commit"]):
        raise RuntimeError(f"base image WiGig commit {base_commit} != frozen {CFG['wigig_commit']}")

    image = str(CFG["experiment_image"])
    run_cmd(["docker", "build", "--pull=false", "-t", image, str(EXP_ROOT / "simulator")], timeout=3600)
    experiment_id = docker_image_id(image)
    experiment_commit = docker_git_commit(image)
    if experiment_commit != str(CFG["wigig_commit"]):
        raise RuntimeError(f"experiment image WiGig commit {experiment_commit} != frozen {CFG['wigig_commit']}")

    help_run = run_cmd([
        "docker", "run", "--rm", image, "./waf", "--run-no-build", "evaluate_bplus_affinity_dense --PrintHelp"
    ], timeout=180, check=False)
    if help_run.returncode != 0 or "ratesMbpsCsv" not in (help_run.stdout + help_run.stderr):
        raise RuntimeError(f"experiment image help gate failed\n{help_run.stdout[-2000:]}\n{help_run.stderr[-2000:]}")

    smoke_root = EXP_ROOT / "operator_logs" / f"packet-smoke-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    smoke_root.mkdir(parents=True, exist_ok=False)
    smoke_rates = [float(CFG["smoke_rate_mbps_per_stream"])] * int(CFG["num_stas"])
    smoke_name = f"mape-ns3-smoke-{os.getpid()}"
    cleanup_container(smoke_name)
    command, spec = ns3_container_command(smoke_root, smoke_rates, int(CFG["smoke_rng_run"]), smoke_name)
    started = time.perf_counter()
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=int(CFG["cell_timeout_seconds"]))
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        cleanup_container(smoke_name)
        proc = None
        timed_out = True
        stdout = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout.decode(errors="replace") if exc.stdout else "")
        stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr.decode(errors="replace") if exc.stderr else "")
        atomic_json(smoke_root / "process.json", {
            "command": command, "spec": spec, "timed_out": True, "returncode": None,
            "runtime_seconds": time.perf_counter() - started, "stdout": stdout, "stderr": stderr,
            "completed_utc": utc_now(),
        })
        raise RuntimeError("real packet smoke run timed out")
    finally:
        cleanup_container(smoke_name)
    atomic_json(smoke_root / "process.json", {
        "command": command, "spec": spec, "timed_out": timed_out, "returncode": proc.returncode,
        "runtime_seconds": time.perf_counter() - started, "stdout": proc.stdout, "stderr": proc.stderr,
        "completed_utc": utc_now(),
    })
    if proc.returncode != 0:
        raise RuntimeError(f"real packet smoke run failed: {proc.stderr[-1800:]}")
    smoke_summary = validate_summary(smoke_root / "packet_summary.csv", smoke_rates, require_positive_rx=True)
    atomic_json(smoke_root / "SMOKE_PASS.json", {"passed": True, "summary": smoke_summary, "rng_run": CFG["smoke_rng_run"]})

    result = {
        "passed": True,
        "disk": disk,
        "base_image": base, "base_id": base_id, "base_commit": base_commit,
        "experiment_image": image, "experiment_id": experiment_id, "experiment_commit": experiment_commit,
        "packet_smoke_directory": str(smoke_root.relative_to(EXP_ROOT)),
        "packet_smoke_summary": smoke_summary,
    }
    atomic_json(EXP_ROOT / "operator_logs" / "LAST_PREPARE.json", result)
    return result


def runtime_identity() -> dict[str, Any]:
    check_results_disk()
    if shutil.which("docker") is None or run_cmd(["docker", "version"], timeout=60, check=False).returncode != 0:
        raise RuntimeError("Docker engine is not reachable; run prepare/preflight first")
    base = str(CFG["base_image"]); image = str(CFG["experiment_image"])
    base_id = docker_image_id(base); experiment_id = docker_image_id(image)
    base_commit = docker_git_commit(base); experiment_commit = docker_git_commit(image)
    if base_commit != CFG["wigig_commit"] or experiment_commit != CFG["wigig_commit"]:
        raise RuntimeError("WiGig Git commit identity changed since freeze")
    return {
        "protocol_id": CFG["protocol_id"],
        "config_sha256": sha256_file(EXP_ROOT / "config" / "experiment.json"),
        "protocol_sha256": sha256_file(EXP_ROOT / "protocol" / "PACKET_LEVEL_PROTOCOL_FROZEN.md"),
        "simulator_source_sha256": sha256_file(EXP_ROOT / "simulator" / "evaluate_bplus_affinity_dense.cc"),
        "live_confirmatory_source_sha256": sha256_file(LIVE_SOURCE),
        "k8s_planner_config_sha256": sha256_file(K8S_CONFIG),
        "wireless_trace_sha256": sha256_file(WIRELESS_TRACE),
        "canonical_planner_tree_sha256": sha256_tree(PLANNER_TREE),
        "base_dockerfile_sha256": sha256_file(BASE_DOCKERFILE),
        "wigig_commit": CFG["wigig_commit"],
        "base_image": base, "base_image_id": base_id,
        "experiment_image": image, "experiment_image_id": experiment_id,
    }


def current_or_new_run() -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    if CURRENT_RUN_FILE.exists():
        rel = CURRENT_RUN_FILE.read_text(encoding="utf-8").strip()
        if not rel:
            raise RuntimeError("results/CURRENT_RUN.txt is empty")
        p = EXP_ROOT / rel
        if not p.exists():
            raise RuntimeError(f"CURRENT_RUN points to a missing run directory: {rel}; do not silently create a replacement")
        return p
    stamp = datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%SZ")
    p = RESULTS / stamp
    p.mkdir(parents=True, exist_ok=False)
    CURRENT_RUN_FILE.write_text(str(p.relative_to(EXP_ROOT)).replace("\\", "/") + "\n", encoding="utf-8")
    return p


def initialize_or_verify_provenance(run_root: Path) -> dict[str, Any]:
    identity = runtime_identity()
    path = run_root / "provenance.json"
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        frozen = old.get("frozen_identity")
        if frozen != identity:
            diffs = {k: {"saved": (frozen or {}).get(k), "current": identity.get(k)} for k in sorted(set(identity) | set(frozen or {})) if (frozen or {}).get(k) != identity.get(k)}
            raise RuntimeError(f"resume identity mismatch; refusing to mix evidence: {json.dumps(diffs, indent=2)}")
        return old
    existing = [p for p in run_root.iterdir() if p.name != "provenance.json"]
    if existing:
        raise RuntimeError("run directory contains evidence but no provenance.json; refusing unsafe resume")
    prov = {
        "protocol_id": CFG["protocol_id"], "started_utc": utc_now(),
        "frozen_identity": identity,
        "evidence_boundary": "packet-level WiGig QD dense shared-medium cross-check; not physical hardware",
    }
    atomic_json(path, prov)
    return prov


def cell_id(seed: int, target: float, method: str, rng: int) -> str:
    safe = method.lower().replace("+", "plus").replace("-", "_")
    return f"seed{seed}-t{target:.2f}-{safe}-rng{rng}"


def verify_or_write_plan(path: Path, plan: dict[str, Any]) -> None:
    if path.exists():
        saved = json.loads(path.read_text(encoding="utf-8"))
        if json_digest(saved) != json_digest(plan):
            raise RuntimeError(f"saved plan no longer matches frozen recomputation: {path}")
    else:
        atomic_json(path, plan)


def validate_accepted_record(accepted_path: Path, plan: dict[str, Any], method: str, rng: int) -> dict[str, Any]:
    rec = json.loads(accepted_path.read_text(encoding="utf-8"))
    expected_meta = plan["methods"][method]
    expected = {
        "seed": int(plan["seed"]), "target": float(plan["target"]), "method": method, "rng_run": int(rng),
        "planner_abstained": bool(expected_meta["planner_abstained"]),
        "planned_feasible": bool(expected_meta["planned_feasible"]),
    }
    for k, v in expected.items():
        if rec.get(k) != v:
            raise RuntimeError(f"accepted record metadata mismatch for {accepted_path}: {k}")
    rates = [float(x) for x in expected_meta["rates_mbps"]]
    saved_rates = [float(x) for x in rec.get("rates_mbps", [])]
    if len(saved_rates) != len(rates) or any(not math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-8) for a, b in zip(saved_rates, rates)):
        raise RuntimeError(f"accepted record rate vector mismatch for {accepted_path}")
    attempt = int(rec.get("attempt", 0))
    if attempt < 1 or attempt > int(CFG["max_cell_attempts"]):
        raise RuntimeError(f"accepted record has invalid attempt number: {accepted_path}")
    summary_path = accepted_path.parent / f"attempt-{attempt}" / "packet_summary.csv"
    summary = validate_summary(summary_path, rates)
    for k in ("aggregate_delivered_fraction", "aggregate_offered_bits_active_intervals", "aggregate_rx_bits"):
        if not math.isclose(float(rec.get(k, float("nan"))), float(summary[k]), rel_tol=2e-8, abs_tol=2e-8):
            raise RuntimeError(f"accepted record summary mismatch for {accepted_path}: {k}")
    return rec


def run_one(run_root: Path, plan: dict[str, Any], method: str, rng: int) -> dict[str, Any]:
    seed = int(plan["seed"]); target = float(plan["target"])
    meta = plan["methods"][method]
    cid = cell_id(seed, target, method, rng)
    final = run_root / "cells" / cid
    accepted = final / "accepted.json"
    if accepted.exists():
        return validate_accepted_record(accepted, plan, method, rng)
    final.mkdir(parents=True, exist_ok=True)
    rates = [float(x) for x in meta["rates_mbps"]]
    max_attempts = int(CFG["max_cell_attempts"])
    last_error = ""

    # Existing attempt directories are preserved and count toward the frozen limit.
    for attempt in range(1, max_attempts + 1):
        adir = final / f"attempt-{attempt}"
        if adir.exists():
            if not (adir / "failure.json").exists() and not (adir / "interrupted.json").exists():
                atomic_json(adir / "interrupted.json", {
                    "error": "attempt directory existed without accepted/failure marker on resume; counted as interrupted",
                    "detected_utc": utc_now(),
                })
            last_error = f"preserved prior attempt-{attempt} is not accepted"
            continue

        adir.mkdir(parents=True, exist_ok=False)
        container_name = f"mape-ns3-{seed}-{str(target).replace('.','p')}-{method.lower().replace('-','_')}-{rng}-a{attempt}"
        cleanup_container(container_name)
        command, spec = ns3_container_command(adir, rates, int(rng), container_name)
        started = time.perf_counter()
        proc = None
        try:
            proc = subprocess.run(command, capture_output=True, text=True, timeout=int(CFG["cell_timeout_seconds"]))
            proc_meta = {
                "command": command, "spec": spec, "returncode": proc.returncode, "timed_out": False,
                "runtime_seconds": time.perf_counter() - started, "stdout": proc.stdout, "stderr": proc.stderr,
                "completed_utc": utc_now(),
            }
            atomic_json(adir / "process.json", proc_meta)
            if proc.returncode != 0:
                raise RuntimeError(f"ns-3 returned {proc.returncode}: {proc.stderr[-1200:]}")
            summary = validate_summary(adir / "packet_summary.csv", rates)
            record = {
                "cell_id": cid, "seed": seed, "target": target, "method": method, "rng_run": int(rng),
                "planner_abstained": bool(meta["planner_abstained"]),
                "planned_feasible": bool(meta["planned_feasible"]),
                "analytical_worst_conflict_utilization": float(meta["worst_conflict_utilization"]),
                "analytical_cross_rack_bits": float(meta["cross_rack_bits"]),
                "common_graph_load_multiplier": float(plan["load_anchor"]["common_graph_load_multiplier"]),
                "load_anchor_reference_aggregate_mbps": float(plan["load_anchor"]["reference_aggregate_mbps"]),
                "rates_mbps": rates,
                **summary,
                "attempt": attempt,
                "status": "accepted",
            }
            atomic_json(accepted, record)
            return validate_accepted_record(accepted, plan, method, rng)
        except subprocess.TimeoutExpired as exc:
            cleanup_container(container_name)
            stdout = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout.decode(errors="replace") if exc.stdout else "")
            stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr.decode(errors="replace") if exc.stderr else "")
            last_error = f"ns-3 wall-clock timeout after {CFG['cell_timeout_seconds']} s"
            atomic_json(adir / "process.json", {
                "command": command, "spec": spec, "returncode": None, "timed_out": True,
                "runtime_seconds": time.perf_counter() - started, "stdout": stdout, "stderr": stderr,
                "completed_utc": utc_now(),
            })
            atomic_json(adir / "failure.json", {"error": last_error, "timestamp_utc": utc_now(), "failure_class": "timeout"})
        except KeyboardInterrupt:
            cleanup_container(container_name)
            atomic_json(adir / "interrupted.json", {
                "error": "operator/process interruption during ns-3 attempt; attempt is consumed",
                "timestamp_utc": utc_now(), "runtime_seconds": time.perf_counter() - started,
            })
            raise
        except Exception as exc:
            cleanup_container(container_name)
            last_error = str(exc)
            atomic_json(adir / "failure.json", {"error": last_error, "timestamp_utc": utc_now(), "failure_class": "execution_or_output"})
        finally:
            cleanup_container(container_name)

    raise RuntimeError(f"cell {cid} has no accepted result after {max_attempts} preserved attempts: {last_error}")


def write_manifest(run_root: Path) -> None:
    lines = []
    for p in sorted(run_root.rglob("*")):
        if p.is_file() and p.name != "SHA256SUMS.txt":
            lines.append(f"{sha256_file(p)}  {p.relative_to(run_root).as_posix()}")
    (run_root / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def execute() -> Path:
    run_root = current_or_new_run()
    initialize_or_verify_provenance(run_root)
    rows = []
    total = len(CFG["load_targets"]) * len(CFG["held_out_seeds"]) * len(CFG["methods"]) * len(CFG["ns3_rng_runs"])
    for target in CFG["load_targets"]:
        for seed in CFG["held_out_seeds"]:
            plan = make_cell_plan(int(seed), float(target))
            pfile = run_root / "plans" / f"seed{seed}-t{float(target):.2f}.json"
            verify_or_write_plan(pfile, plan)
            methods = list(CFG["methods"])
            rnd = random.Random(int(CFG["method_order_seed"]) + int(seed) * 100 + int(round(float(target) * 100)))
            rnd.shuffle(methods)
            for method in methods:
                for rng in CFG["ns3_rng_runs"]:
                    rec = run_one(run_root, plan, method, int(rng))
                    rows.append(rec)
                    print(f"[{len(rows)}/{total}] {rec['cell_id']} {rec['aggregate_delivered_fraction']:.4f}", flush=True)
    pd.DataFrame(rows).to_csv(run_root / "cell_results.csv", index=False)
    analyze(run_root)  # analyze refreshes SHA256SUMS.txt
    return run_root


def bootstrap_ci(d: np.ndarray, n: int, seed: int) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    vals = []
    remain = n
    while remain:
        m = min(5000, remain)
        idx = rng.integers(0, len(d), size=(m, len(d)))
        vals.append(d[idx].mean(axis=1)); remain -= m
    b = np.concatenate(vals)
    return float(np.quantile(b, .025)), float(np.quantile(b, .975))


def analyze(run_root: Path) -> dict[str, Any]:
    # Provenance identity is rechecked before any report is regenerated.
    initialize_or_verify_provenance(run_root)
    accepted_paths = sorted((run_root / "cells").glob("*/accepted.json"))
    expected = len(CFG["load_targets"]) * len(CFG["held_out_seeds"]) * len(CFG["methods"]) * len(CFG["ns3_rng_runs"])
    if len(accepted_paths) != expected:
        raise RuntimeError(f"analysis requires {expected} accepted cells; found {len(accepted_paths)}")

    accepted = []
    for target in CFG["load_targets"]:
        for seed in CFG["held_out_seeds"]:
            plan = make_cell_plan(int(seed), float(target))
            verify_or_write_plan(run_root / "plans" / f"seed{seed}-t{float(target):.2f}.json", plan)
            for method in CFG["methods"]:
                for rng in CFG["ns3_rng_runs"]:
                    ap = run_root / "cells" / cell_id(int(seed), float(target), method, int(rng)) / "accepted.json"
                    if not ap.exists():
                        raise RuntimeError(f"missing accepted cell during analysis: {ap}")
                    accepted.append(validate_accepted_record(ap, plan, method, int(rng)))

    df = pd.DataFrame(accepted)
    df.to_csv(run_root / "analysis_cells.csv", index=False)
    graph = df.groupby(["seed", "target", "method"], as_index=False).agg(
        delivered_fraction=("aggregate_delivered_fraction", "mean"),
        achieved_mbps=("aggregate_achieved_mbps", "mean"),
        configured_mbps=("aggregate_offered_mbps", "mean"),
        active_streams=("active_streams", "mean"),
        planner_abstained=("planner_abstained", "max"),
    )
    graph.to_csv(run_root / "graph_level_results.csv", index=False)
    summary = graph.groupby(["target", "method"], as_index=False).agg(
        n_graphs=("seed", "nunique"), mean_delivered_fraction=("delivered_fraction", "mean"),
        median_delivered_fraction=("delivered_fraction", "median"), mean_achieved_mbps=("achieved_mbps", "mean"),
        mean_configured_mbps=("configured_mbps", "mean"), mean_active_streams=("active_streams", "mean"),
    )
    summary.to_csv(run_root / "summary.csv", index=False)

    primary_target = float(CFG["primary_load_target"])
    p = graph[np.isclose(graph["target"], primary_target)].pivot(index="seed", columns="method", values="delivered_fraction")
    p = p.dropna(subset=["BPlus-Exact", "Affinity-Bytes"])
    d = p["BPlus-Exact"].to_numpy(float) - p["Affinity-Bytes"].to_numpy(float)
    if len(d) != len(CFG["held_out_seeds"]):
        raise RuntimeError("primary paired graph count mismatch")
    if np.allclose(d, 0):
        p_w = 1.0
    else:
        p_w = float(wilcoxon(d, alternative="greater", zero_method="wilcox", method="auto").pvalue)
    lo, hi = bootstrap_ci(d, int(CFG["bootstrap_resamples"]), int(CFG["bootstrap_seed"]))

    low_target = float(CFG["specificity_load_target"])
    low = graph[np.isclose(graph["target"], low_target)].pivot(index="seed", columns="method", values="delivered_fraction").dropna(subset=["BPlus-Exact", "Affinity-Bytes"])
    low_d = low["BPlus-Exact"].to_numpy(float) - low["Affinity-Bytes"].to_numpy(float)

    primary = {
        "n_paired_graphs": len(d),
        "target": primary_target,
        "mean_difference_bplus_minus_affinity": float(np.mean(d)),
        "median_difference_bplus_minus_affinity": float(np.median(d)),
        "bootstrap95_low": lo, "bootstrap95_high": hi,
        "one_sided_wilcoxon_p": p_w,
        "primary_hypothesis_supported": bool(p_w < 0.05 and lo > 0),
        "low_load_mean_difference": float(np.mean(low_d)),
        "nested_rng_runs_per_graph_method": len(CFG["ns3_rng_runs"]),
    }
    result = {
        "analyzed_utc": utc_now(), "protocol_id": CFG["protocol_id"], "primary": primary,
        "evidence_boundary": "packet-level 802.11ad/WiGig QD dense contention cross-check with fixed rack-pair-to-STA mapping; not physical hardware and not a full three-rack RF geometry",
    }
    atomic_json(run_root / "PRIMARY_RESULT.json", result)
    lines = [
        "# ns-3/WiGig Affinity-vs-Wireless Packet-Level Confirmation", "",
        f"Run: `{run_root.name}`", "", f"Protocol: `{CFG['protocol_id']}`", "",
        "## Evidence boundary",
        "Packet-level IEEE 802.11ad/WiGig Q-D DenseScenario cross-check. Six directed rack-pair aggregates are mapped to six fixed STAs contending at one DMG AP. This is not physical hardware and is not claimed to reproduce a full three-rack RF geometry.", "",
        "## Primary hypothesis",
        "At the frozen 1.25 offered-load target, B+ Exact has a higher graph-level delivered offered-traffic fraction than Affinity-Bytes.", "",
        f"Paired graphs: **{len(d)}**",
        f"Mean B+ - Affinity difference: **{np.mean(d):.6g}**",
        f"Bootstrap 95% CI: **[{lo:.6g}, {hi:.6g}]**",
        f"One-sided Wilcoxon p: **{p_w:.6g}**",
        f"Primary hypothesis supported: **{primary['primary_hypothesis_supported']}**", "",
        "## Summary", "", summary.to_markdown(index=False), "",
        "## Interpretation boundary",
        "A favorable result supports packet-level contention robustness beyond byte affinity under this fixed dense WiGig mapping. It does not establish physical RF interference reduction, a hardware result, or universal superiority.",
    ]
    (run_root / "FINAL_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_manifest(run_root)
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=["self-test", "offline-audit", "prepare", "run", "analyze"])
    ap.add_argument("--run-root", type=Path)
    args = ap.parse_args()
    if args.command == "self-test":
        print(json.dumps(self_test(), indent=2)); return 0
    if args.command == "offline-audit":
        print(json.dumps(offline_audit(), indent=2)); return 0
    if args.command == "prepare":
        print(json.dumps(ensure_images(), indent=2)); return 0
    if args.command == "run":
        root = execute(); print(f"COMPLETE: {root}"); return 0
    if args.command == "analyze":
        root = args.run_root or current_or_new_run(); print(json.dumps(analyze(root), indent=2)); return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
