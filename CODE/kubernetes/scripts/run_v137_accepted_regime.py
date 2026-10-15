#!/usr/bin/env python3
"""Execute the frozen accepted full-planner placement on Kubernetes v1.37."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "implementation" / "code"))
os.environ.setdefault(
    "MCB_R1_WORKERS",
    "mcb-k137-worker,mcb-k137-worker2,mcb-k137-worker3",
)

from mape_cap_bplus.v03_evidence import atomic_write_json, atomic_write_text, utc_now
from run_v03_r1 import apply_placement, measure, wait_healthy

INITIAL = {
    "adservice": "mcb-k137-worker3",
    "cartservice": "mcb-k137-worker",
    "checkoutservice": "mcb-k137-worker",
    "currencyservice": "mcb-k137-worker",
    "emailservice": "mcb-k137-worker2",
    "frontend": "mcb-k137-worker",
    "paymentservice": "mcb-k137-worker3",
    "productcatalogservice": "mcb-k137-worker",
    "recommendationservice": "mcb-k137-worker",
    "redis-cart": "mcb-k137-worker3",
    "shippingservice": "mcb-k137-worker3",
}

CANDIDATE = {
    service: ("mcb-k137-worker3" if service == "redis-cart" else "mcb-k137-worker")
    for service in INITIAL
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--duration-seconds", type=int, default=420)
    args = parser.parse_args()
    if args.duration_seconds < 60:
        parser.error("duration must be at least 60 seconds")

    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    started = utc_now()

    initial_rollout = apply_placement(INITIAL, "v137-followup:item2:initial")
    time.sleep(15)
    baseline, baseline_samples, baseline_log = measure(
        "confirmatory-persistent-severe", 42, args.duration_seconds
    )

    action_started = time.monotonic()
    candidate_rollout = apply_placement(CANDIDATE, "v137-followup:item2:accepted-candidate")
    action_seconds = time.monotonic() - action_started
    time.sleep(15)
    post, post_samples, post_log = measure(
        "confirmatory-persistent-severe", 42, args.duration_seconds
    )
    post_health = wait_healthy(timeout_seconds=180)

    base_app = baseline["application"]
    post_app = post["application"]
    safety_keep = bool(
        post_health["healthy"]
        and post_app["error_rate"] <= 0.05
        and post_app["p95_ms"] <= 1.25 * base_app["p95_ms"]
    )
    safety_reason = (
        "health/error/P95 guard passed" if safety_keep else "health/error/P95 guard failed"
    )

    restore_started = time.monotonic()
    restore_rollout = apply_placement(INITIAL, "v137-followup:item2:restore")
    restore_seconds = time.monotonic() - restore_started
    final_health = wait_healthy(timeout_seconds=180)

    result = {
        "schema_version": "1.0",
        "arm": "item2-accepted-full-planner-live-relocation",
        "started_utc": started,
        "completed_utc": utc_now(),
        "cluster": "kind-mcb-k137",
        "kubernetes": "v1.37.0",
        "shared_host_limitation": True,
        "frozen_regime": {
            "latency_ms": 40.0,
            "rate_mbit": 20.0,
            "loss_pct": 2.0,
            "load_multiplier": 2.0,
            "planning_horizon_seconds": 300.0,
            "planner": "Exact",
            "calibration_net_benefit": 93099.25,
            "moved_services": [
                "adservice", "emailservice", "paymentservice", "shippingservice"
            ],
        },
        "duration_seconds_per_phase": args.duration_seconds,
        "initial_placement": INITIAL,
        "candidate_placement": CANDIDATE,
        "initial_rollout": initial_rollout,
        "candidate_rollout": candidate_rollout,
        "candidate_action_seconds": action_seconds,
        "baseline": baseline,
        "post_action": post,
        "post_action_health": post_health,
        "safety_would_keep": safety_keep,
        "safety_reason": safety_reason,
        "restored_after_capture": True,
        "restore_rollout": restore_rollout,
        "restore_seconds": restore_seconds,
        "final_health": final_health,
        "accepted": bool(
            final_health["healthy"]
            and base_app["successes"] >= 1000
            and post_app["successes"] >= 1000
        ),
    }
    atomic_write_json(out / "result.json", result)
    atomic_write_json(out / "baseline-resource-samples.json", baseline_samples)
    atomic_write_json(out / "post-resource-samples.json", post_samples)
    atomic_write_text(out / "baseline-frontend.log", baseline_log)
    atomic_write_text(out / "post-frontend.log", post_log)
    print(json.dumps({
        "accepted": result["accepted"],
        "baseline_successes": base_app["successes"],
        "post_successes": post_app["successes"],
        "baseline_p95_ms": base_app["p95_ms"],
        "post_p95_ms": post_app["p95_ms"],
        "safety_would_keep": safety_keep,
        "output": str(out / "result.json"),
    }, indent=2), flush=True)
    return 0 if result["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
