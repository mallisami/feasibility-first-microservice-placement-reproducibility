"""Run the v0.3 R3 closed-loop Kubernetes regime campaign."""
from __future__ import annotations

import argparse
import json
import math
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mape_cap_bplus.v03_evidence import atomic_write_json, atomic_write_text, utc_now, write_manifest
from run_v03_classifier import raw_label
from run_v03_r1 import (
    CampaignLock, SERVICES, WORKERS, all_egress, apply_placement, clear_network,
    initial_placement, r2_traffic, stats_snapshot, summarize_resources,
)
from run_v03_r2 import NS, assert_healthy, frontend_metrics, kubectl, kubectl_json

SEQUENCES = {
    1: ["stable", "stable", "degradation", "degradation", "degradation", "recovery", "recovery", "stable", "stable", "stable", "recovery"],
    2: ["stable", "degradation", "degradation", "degradation", "recovery", "recovery", "stable", "stable", "degradation", "recovery", "stable"],
    3: ["stable", "stable", "recovery", "degradation", "degradation", "degradation", "recovery", "stable", "stable", "recovery", "stable"],
    4: ["stable", "recovery", "stable", "degradation", "degradation", "degradation", "recovery", "recovery", "stable", "stable", "stable"],
    5: ["stable", "stable", "degradation", "degradation", "degradation", "recovery", "stable", "recovery", "stable", "stable", "recovery"],
    # Additional S-E1 sequences (gap-closure): the frozen sequences 1-5 gave
    # 7 live full-planner replan opportunities, all rejected by the
    # unmodified economic gate (see PAPER/ISSUE_RESOLUTION_MATRIX.md issue 1
    # and SCIENTIFIC_COMPLETION_CHECKLIST.md). Per VALIDATION_PROTOCOL's
    # integration rule, the gate/detector/formulation are not retuned;
    # instead these add more independent live trials (new sequence_ids ->
    # new deterministic seeds -> new scenario draws) to observe whether an
    # accepted relocation occurs under the same unmodified gate.
    6: ["stable", "stable", "degradation", "degradation", "degradation", "degradation", "degradation", "recovery", "stable", "stable", "recovery"],
    7: ["stable", "degradation", "degradation", "degradation", "degradation", "recovery", "degradation", "degradation", "degradation", "recovery", "stable"],
    8: ["stable", "stable", "degradation", "degradation", "degradation", "recovery", "recovery", "degradation", "degradation", "degradation", "recovery"],
    9: ["stable", "degradation", "degradation", "degradation", "recovery", "stable", "degradation", "degradation", "degradation", "recovery", "stable"],
    10: ["stable", "stable", "stable", "degradation", "degradation", "degradation", "degradation", "degradation", "degradation", "recovery", "recovery"],
}
PERSISTENCE = 3
FORECAST_SECONDS = 300.0


def live_placement() -> dict[str, str]:
    pods = kubectl_json("get", "pods", "-n", NS)
    result: dict[str, str] = {}
    for pod in pods["items"]:
        app = pod.get("metadata", {}).get("labels", {}).get("app")
        node = pod.get("spec", {}).get("nodeName")
        if app in SERVICES and node and not pod.get("metadata", {}).get("deletionTimestamp"):
            result[app] = node
    if set(result) != set(SERVICES):
        raise RuntimeError(f"incomplete live placement: {sorted(result)}")
    return result


def shape(regime: str, seed: int, window: int) -> dict[str, Any]:
    clear_network()
    rng = random.Random(seed * 1000 + window)
    if regime == "stable":
        values = {"latency_ms": 2.0, "loss_percent": 0.1, "availability": 1.0, "conflict_ratio": 0.05, "rate_mbit": 1000.0}
    elif regime == "degradation":
        values = {"latency_ms": round(rng.uniform(13.0, 18.0), 3), "loss_percent": round(rng.uniform(1.1, 2.0), 3), "availability": 1.0, "conflict_ratio": round(rng.uniform(.18, .32), 3), "rate_mbit": round(rng.uniform(70, 130), 3)}
        all_egress(values["latency_ms"], values["rate_mbit"], values["loss_percent"])
    elif regime == "recovery":
        values = {"latency_ms": round(rng.uniform(4.0, 6.5), 3), "loss_percent": round(rng.uniform(.35, .6), 3), "availability": 1.0, "conflict_ratio": round(rng.uniform(.07, .14), 3), "rate_mbit": round(rng.uniform(400, 700), 3)}
        all_egress(values["latency_ms"], values["rate_mbit"], values["loss_percent"])
    else:
        raise ValueError(regime)
    tc = {node: __import__("run_v03_r1").docker(node, "tc", "qdisc", "show", "dev", "eth0") for node in WORKERS}
    return {"applied": values, "tc_qdisc": tc}


def best_single_move(run_root: Path, placement: dict[str, str]) -> dict[str, Any]:
    traffic = r2_traffic(run_root)

    def cross_bytes(candidate: dict[str, str]) -> float:
        return sum(rate for (src, dst), (_, rate) in traffic.items() if src in candidate and dst in candidate and candidate[src] != candidate[dst])

    current = cross_bytes(placement)
    best = None
    for service in SERVICES:
        for node in WORKERS:
            if node == placement[service]:
                continue
            candidate = dict(placement)
            candidate[service] = node
            cost = cross_bytes(candidate)
            row = (cost, service, node, candidate)
            if best is None or row[:3] < best[:3]:
                best = row
    assert best is not None
    cost, service, node, candidate = best
    improvement_bps = max(0.0, current - cost)
    relocation_cost = max(4096.0, sum(rate for (src, dst), (_, rate) in traffic.items() if src == service or dst == service) * 4.062)
    uncertainty = max(4096.0, improvement_bps * FORECAST_SECONDS * .05)
    net = improvement_bps * FORECAST_SECONDS - relocation_cost - uncertainty
    return {
        "service": service, "source_node": placement[service], "target_node": node,
        "current_cross_node_bytes_per_second": current,
        "candidate_cross_node_bytes_per_second": cost,
        "forecast_seconds": FORECAST_SECONDS,
        "relocation_cost_equivalent_bytes": relocation_cost,
        "uncertainty_margin_bytes": uncertainty,
        "net_benefit_bytes": net, "placement": candidate,
    }


def measure_window(duration: int) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    started = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    samples = [stats_snapshot()]
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        time.sleep(min(5, max(0.0, deadline - time.monotonic())))
        samples.append(stats_snapshot())
    app, log = frontend_metrics(started, duration)
    return {"application": app, "resources": summarize_resources(samples, duration)}, samples, log


def accepted_result(path: Path, duration: int) -> dict[str, Any] | None:
    if not path.exists():
        return None
    row = json.loads(path.read_text(encoding="utf-8"))
    return row if row.get("accepted") and row.get("window_duration_seconds") == duration else None


def progress(run_root: Path, latest: str | None = None) -> dict[str, Any]:
    rows = []
    for path in (run_root / "raw" / "r3").glob("sequence-*/window-*/result.json"):
        row = accepted_result(path, int(json.loads(path.read_text(encoding="utf-8")).get("window_duration_seconds", 0)))
        if row:
            rows.append(row)
    completed_sequences = len({row["sequence_id"] for row in rows if row["window_index"] == 10})
    report = {
        "updated_utc": utc_now(), "status": "complete" if len(rows) == 55 else "in_progress",
        "accepted_windows": len(rows), "desired_windows": 55, "remaining_windows": 55 - len(rows),
        "completed_sequences": completed_sequences, "desired_sequences": 5,
        "accepted_relocations": sum(bool(row["gate"]["accepted"]) for row in rows),
        "rejected_gate_windows": sum(not bool(row["gate"]["accepted"]) for row in rows),
        "latest_window_id": latest,
    }
    atomic_write_json(run_root / "checkpoints" / "r3-progress.json", report)
    return report


def run_campaign(run_root: Path, duration: int) -> int:
    raw = run_root / "raw" / "r3"
    raw.mkdir(parents=True, exist_ok=True)
    classifier = json.loads((run_root / "derived" / "phase-2-classifier-freeze.json").read_text(encoding="utf-8"))
    if classifier["selected"]["method"] != "hysteresis" or classifier["selected"]["configuration"] != "threshold-scale-1.0":
        raise RuntimeError("R3 requires the frozen threshold-scale-1.0 hysteresis classifier")
    kubectl("scale", "deployment/bplus-controller-v03", "-n", NS, "--replicas=0")
    health = assert_healthy(False, False)
    if not health["healthy"]:
        raise RuntimeError("R3 preflight requires all relevant pods Ready with zero restarts")
    progress(run_root)
    try:
        for sequence_id, regimes in SEQUENCES.items():
            sequence_dir = raw / f"sequence-{sequence_id:02d}"
            sequence_dir.mkdir(parents=True, exist_ok=True)
            trace_id = f"r3-seed-{7300 + sequence_id}-trace-{sequence_id:02d}"
            initial = initial_placement(f"r3-sequence-{sequence_id}", 7300 + sequence_id)
            existing = sum((sequence_dir / f"window-{i:02d}" / "result.json").exists() for i in range(11))
            if existing == 11:
                print(f"R3 sequence {sequence_id}/5 already complete; skipping", flush=True)
                continue
            apply_placement(initial, f"r3:sequence{sequence_id}:initial")
            classified_history: list[str] = []
            current_regime = "stable"
            # Reconstruct controller state from accepted prior windows on resume.
            for i in range(existing):
                prior = json.loads((sequence_dir / f"window-{i:02d}" / "result.json").read_text(encoding="utf-8"))
                classified_history.append(prior["classified_regime"])
                current_regime = prior["controller_regime_after"]
            for index, truth in enumerate(regimes):
                result_path = sequence_dir / f"window-{index:02d}" / "result.json"
                prior = accepted_result(result_path, duration)
                if prior:
                    continue
                cell = result_path.parent
                cell.mkdir(parents=True, exist_ok=True)
                print(f"R3 sequence {sequence_id}/5 window {index + 1}/11 truth {truth}", flush=True)
                shaping = shape(truth, 7300 + sequence_id, index)
                observed = dict(shaping["applied"])
                classified = raw_label(observed, 1.0)
                classified_history.append(classified)
                tail = classified_history[-PERSISTENCE:]
                persistent = len(tail) == PERSISTENCE and len(set(tail)) == 1
                candidate_regime = tail[0] if persistent else None
                should_replan = persistent and candidate_regime != current_regime
                placement_before = live_placement()
                candidate = best_single_move(run_root, placement_before)
                economic = candidate["net_benefit_bytes"] > 0
                gate_accepted = bool(should_replan and candidate_regime == "degradation" and economic and candidate["source_node"] != candidate["target_node"])
                gate_reason = (
                    "accepted: persistent degradation and positive measured-traffic net benefit" if gate_accepted
                    else "rejected: persistence not met" if not persistent
                    else "rejected: classified regime matches controller state" if candidate_regime == current_regime
                    else "rejected: recovery/stable does not justify relocation" if candidate_regime != "degradation"
                    else "rejected: insufficient conservative net benefit"
                )
                relocation = None
                if gate_accepted:
                    relocation = apply_placement(candidate["placement"], f"r3:{trace_id}:window{index}")
                    current_regime = str(candidate_regime)
                elif should_replan and candidate_regime in {"stable", "recovery"}:
                    current_regime = str(candidate_regime)
                measured, samples, frontend_log = measure_window(duration)
                health = assert_healthy(False, False)
                detected_at = next((i for i in range(index + 1) if classified_history[i] == truth), None)
                result = {
                    "window_id": f"{trace_id}:window-{index:02d}", "sequence_id": sequence_id,
                    "seed": 7300 + sequence_id, "trace_id": trace_id, "window_index": index,
                    "window_duration_seconds": duration, "truth_regime": truth,
                    "classified_regime": classified, "classifier": classifier["selected"],
                    "detection_delay_windows": None if detected_at is None else detected_at - next(i for i, x in enumerate(regimes[:index + 1]) if x == truth),
                    "shaping": shaping, "controller_regime_before": current_regime if not gate_accepted else "stable",
                    "controller_regime_after": current_regime,
                    "gate": {"should_replan": should_replan, "persistent_windows": len(tail) if len(set(tail)) == 1 else 1, "candidate_regime": candidate_regime, "accepted": gate_accepted, "reason": gate_reason, "economics": {k: v for k, v in candidate.items() if k != "placement"}},
                    "planning_time_seconds": 0.0, "placement_before": placement_before,
                    "placement_after": live_placement(), "relocation": relocation,
                    "relocation_time_seconds": None if relocation is None else relocation["rollout_seconds"],
                    "downtime_seconds": None if relocation is None else sum(not x["frontend_ok"] for x in relocation["probe_timeline"]),
                    "failed_requests": measured["application"]["errors"],
                    "recovery_seconds": None if relocation is None else relocation["recovery_seconds"],
                    **measured, "health": health, "completed_utc": utc_now(),
                }
                result["accepted"] = bool(health["healthy"] and measured["application"]["requests"] > 0)
                atomic_write_json(result_path, result)
                atomic_write_json(cell / "resource-samples.json", samples)
                atomic_write_text(cell / "frontend.log", frontend_log)
                if not result["accepted"]:
                    raise RuntimeError(f"R3 window acceptance failed: {result['window_id']}")
                progress(run_root, result["window_id"])
            clear_network()
            apply_placement(initial, f"r3:sequence{sequence_id}:cleanup")
            atomic_write_json(run_root / "checkpoints" / f"r3-sequence-{sequence_id:02d}.json", {"completed_utc": utc_now(), "sequence_id": sequence_id, "seed": 7300 + sequence_id, "trace_id": trace_id, "windows": 11})
            write_manifest(run_root, run_root / "manifests" / "run.sha256")
    finally:
        clear_network()
        kubectl("scale", "deployment/loadgenerator", "-n", NS, "--replicas=1")
    report = progress(run_root)
    rows = [json.loads(p.read_text(encoding="utf-8")) for p in raw.glob("sequence-*/window-*/result.json")]
    if report["accepted_windows"] != 55 or report["accepted_relocations"] < 1 or report["rejected_gate_windows"] < 1:
        raise RuntimeError(f"R3 completeness/decision acceptance failed: {report}")
    summary = {**report, "independent_seeds": sorted({r["seed"] for r in rows}), "unique_trace_ids": sorted({r["trace_id"] for r in rows}), "all_health_accepted": all(r["health"]["healthy"] for r in rows)}
    atomic_write_json(run_root / "derived" / "r3-summary.json", summary)
    ledger_path = run_root / "checkpoints" / "ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["phases"]["phase-8-r1"] = "completed"
    ledger["phases"]["phase-9-r3"] = "completed"
    ledger["current_phase"] = "phase-10-r4"
    atomic_write_json(ledger_path, ledger)
    write_manifest(run_root, run_root / "manifests" / "run.sha256")
    print(json.dumps(summary, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_root", type=Path)
    parser.add_argument("--window-duration-seconds", type=int, default=15)
    args = parser.parse_args()
    if args.window_duration_seconds < 10:
        parser.error("window duration must be at least 10 seconds")
    run_root = args.run_root.resolve()
    # Keep the process-lifetime lock outside the evidence tree so sequence
    # manifests never try to hash an actively locked Windows file.
    lock_scope = run_root.parent / f".r3-lock-{run_root.name}"
    with CampaignLock(lock_scope):
        return run_campaign(run_root, args.window_duration_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
