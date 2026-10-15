#!/usr/bin/env python3
"""S-E7: computational overhead of B+ control-plane components in isolation.

Five modes measured independently:
  O1  telemetry OFF, controller OFF        (bare baseline)
  O2  telemetry ON,  controller OFF        (telemetry-only)
  O3  telemetry ON,  gate/controller ON,   optimization disabled
  O4  telemetry ON,  full B+ gate + Exact  optimizer
  O5  telemetry ON,  full B+ gate + LNS    optimizer

Design: 5 modes x 5 replicates = 25 runs.
Derived overhead comparisons are computed in post-processing, not here.
"""
from __future__ import annotations

import argparse, csv, json, sys, time, threading
from dataclasses import replace
from pathlib import Path

HERE = Path(__file__).resolve().parent; IMPL = HERE.parent; REPO = IMPL.parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(IMPL / "code"))

from common import (
    atomic_json, assert_live_preflight, campaign_lock,
    clear_live_network, utc_now, write_manifest, resource_snapshot,
)
from run_v03_r1 import (
    SERVICES, CONDITIONS, apply_placement, build_problem,
    initial_placement, measure, wait_healthy,
)
from run_v03_r2 import (
    NS, kubectl, kubectl_json, set_tracing, set_controller,
    assert_healthy, frontend_metrics, stats_snapshot, summarize_resources,
)
from run_v03_r3 import live_placement
from mape_cap_bplus.models import RiskConfig
from mape_cap_bplus.exact import solve_exact
from mape_cap_bplus.lns import robust_lns
from mape_cap_bplus.objective import evaluate_placement

MODES = ("O1", "O2", "O3", "O4", "O5")
RISK = RiskConfig(cvar_quantile=0.8, cvar_weight=1.5, relocation_weight=1.0, slo_slack_weight=1000.0)


# ---- helpers ----------------------------------------------------------------

def _controller_pod_metrics() -> dict:
    """Scrape CPU/memory/threads from the bplus-controller pod via kubectl top."""
    try:
        pods = kubectl_json("get", "pods", "-n", NS, "-l", "app=bplus-controller-v03")["items"]
        if not pods:
            return {"available": False}
        pod = pods[0]
        name = pod["metadata"]["name"]
        containers = []
        try:
            top_text = kubectl("top", "pod", name, "-n", NS, "--containers")
            for line in top_text.strip().splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 3:
                    containers.append({"container": parts[1], "cpu": parts[2], "memory": parts[3] if len(parts) > 3 else ""})
        except Exception:
            pass
        return {
            "available": True,
            "pod": name,
            "containers": containers,
            "phase": pod.get("status", {}).get("phase"),
        }
    except Exception as exc:
        return {"available": False, "error": str(exc)}


def _telemetry_pod_metrics() -> dict:
    """Scrape metrics from the OpenTelemetry collector pod."""
    try:
        pods = kubectl_json("get", "pods", "-n", NS, "-l", "app=opentelemetrycollector")["items"]
        if not pods:
            return {"available": False}
        pod = pods[0]
        name = pod["metadata"]["name"]
        containers = []
        try:
            top_text = kubectl("top", "pod", name, "-n", NS, "--containers")
            for line in top_text.strip().splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 3:
                    containers.append({"container": parts[1], "cpu": parts[2], "memory": parts[3] if len(parts) > 3 else ""})
        except Exception:
            pass
        return {
            "available": True,
            "pod": name,
            "containers": containers,
            "phase": pod.get("status", {}).get("phase"),
        }
    except Exception as exc:
        return {"available": False, "error": str(exc)}


def _k8s_api_stats() -> dict:
    """Count recent API-server audit metrics (best-effort)."""
    try:
        metrics_raw = kubectl("get", "--raw", "/metrics")
        api_calls = 0; patch_calls = 0
        for line in metrics_raw.splitlines():
            if line.startswith("apiserver_request_total"):
                api_calls += 1
            if "PATCH" in line:
                patch_calls += 1
        return {"api_call_lines": api_calls, "patch_lines": patch_calls}
    except Exception as exc:
        return {"error": str(exc)}


def _resource_samples(duration: float, interval: float = 5.0) -> list[dict]:
    """Collect periodic resource snapshots in a background thread."""
    samples = []
    stop = threading.Event()

    def _collect():
        while not stop.is_set():
            try:
                samples.append({"t": time.monotonic(), "stats": stats_snapshot()})
            except Exception:
                pass
            stop.wait(interval)

    t = threading.Thread(target=_collect, daemon=True)
    t.start()
    stop.wait(duration)
    stop.set()
    t.join(timeout=10)
    return samples


# ---- mode configuration -----------------------------------------------------

def configure_mode(mode: str) -> None:
    """Enable/disable telemetry and controller for the given mode."""
    if mode == "O1":
        set_tracing(False); set_controller(False)
    elif mode == "O2":
        set_tracing(True); set_controller(False)
    elif mode in ("O3", "O4", "O5"):
        set_tracing(True); set_controller(True)
    time.sleep(8)  # allow pods to stabilise


def run_solver(mode: str, problem, current: dict[str, str], seed: int,
               time_limit: float) -> dict:
    """Run the solver component appropriate for the mode.  Returns solver dict."""
    if mode in ("O1", "O2"):
        return {"solver": "none", "skipped": True}

    operating_risk = replace(RISK, relocation_weight=0.0)
    current_eval = evaluate_placement(problem, current, operating_risk)

    if mode == "O3":
        # Gate/controller active but optimisation deliberately disabled.
        return {
            "solver": "none-gate-only",
            "skipped": True,
            "gate_evaluated": True,
            "current_objective": current_eval.total_objective,
            "current_feasible": current_eval.feasible,
        }

    t0 = time.perf_counter()
    if mode == "O4":
        placement, meta = solve_exact(
            problem, operating_risk,
            time_limit_seconds=max(time_limit, 1.0),
            require_optimal=False,
        )
    elif mode == "O5":
        placement, meta = robust_lns(
            problem, operating_risk,
            seed=seed, iterations=80,
            destroy_size=min(4, len(problem.replicas)),
            time_limit_seconds=time_limit,
            local_iterations=10,
        )
    else:
        raise ValueError(mode)
    wall_time = time.perf_counter() - t0

    candidate_eval = evaluate_placement(problem, placement, operating_risk)
    moved = [r for r, n in placement.items() if current.get(r) != n]

    # Apply placement only if feasible
    if candidate_eval.feasible and moved:
        apply_placement(placement, f"S-E7:{mode}:solver-apply")

    return {
        "solver": "exact" if mode == "O4" else "lns",
        "wall_seconds": wall_time,
        "status": meta.get("status"),
        "variables": meta.get("variables"),
        "constraints": meta.get("constraints"),
        "candidate_objective": candidate_eval.total_objective,
        "candidate_feasible": candidate_eval.feasible,
        "current_objective": current_eval.total_objective,
        "moved_replicas": moved,
        "metadata": {k: v for k, v in meta.items()
                      if k not in {"iteration_log", "candidate_log"}},
    }


# ---- single cell -------------------------------------------------------------

def run_cell(mode: str, replicate: int, condition: str,
             evidence: Path, duration: int, seed_base: int) -> dict:
    """Execute one mode x replicate cell and return the result dict."""
    seed = seed_base + replicate
    initial = initial_placement(f"S-E7-{mode}", seed)
    apply_placement(initial, f"S-E7:{mode}:rep{replicate}:initial")

    configure_mode(mode)

    include_telemetry = mode != "O1"
    include_controller = mode in ("O3", "O4", "O5")
    health_pre = assert_healthy(include_telemetry, include_controller)

    problem = build_problem(evidence, condition, replicate, initial)
    current = dict(problem.current_placement)

    # Pre-measurement snapshots
    pre_controller = _controller_pod_metrics() if include_controller else {}
    pre_telemetry = _telemetry_pod_metrics() if include_telemetry else {}
    pre_k8s = _k8s_api_stats()
    pre_resources = resource_snapshot()

    # Solver invocation (timed inside run_solver)
    solver_result = run_solver(mode, problem, current, seed, time_limit=60.0)

    # Warm-up
    time.sleep(5)

    # Measurement interval with resource sampling
    mark_time = utc_now()
    t_start = time.monotonic()
    samples = _resource_samples(duration)
    t_elapsed = time.monotonic() - t_start

    # Post-measurement snapshots
    post_controller = _controller_pod_metrics() if include_controller else {}
    post_telemetry = _telemetry_pod_metrics() if include_telemetry else {}
    post_k8s = _k8s_api_stats()
    post_resources = resource_snapshot()

    # Application metrics
    app_metrics, frontend_log = frontend_metrics(mark_time, t_elapsed)
    health_post = wait_healthy()

    # Summarise resource samples
    stat_dicts = [s["stats"] for s in samples if "stats" in s]
    resources_summary = (summarize_resources(stat_dicts, t_elapsed)
                         if len(stat_dicts) >= 2 else {"insufficient_samples": True})

    row = {
        "experiment": "S-E7",
        "mode": mode,
        "replicate": replicate,
        "condition": condition,
        "seed": seed,
        "duration_seconds": duration,
        "elapsed_seconds": t_elapsed,
        "placement": current,
        "solver": solver_result,
        "controller_pre": pre_controller,
        "controller_post": post_controller,
        "telemetry_pre": pre_telemetry,
        "telemetry_post": post_telemetry,
        "k8s_pre": pre_k8s,
        "k8s_post": post_k8s,
        "resources_pre": pre_resources,
        "resources_post": post_resources,
        "resources_summary": resources_summary,
        "application": app_metrics,
        "health_pre": health_pre,
        "health_post": health_post,
        "completed_utc": utc_now(),
    }
    row["accepted_evidence"] = bool(
        health_post.get("healthy")
        and app_metrics.get("requests", 0) > 0
    )
    return row, samples, frontend_log


# ---- main --------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("run_root", type=Path)
    p.add_argument("--evidence-run-root", type=Path,
                    default=REPO / "RESULTS" / "primary" / "v03-20260811T151500Z")
    p.add_argument("--replicates", type=int, default=5)
    p.add_argument("--duration-seconds", type=int, default=60)
    p.add_argument("--condition", default="stable")
    args = p.parse_args()

    root = args.run_root.resolve()
    evidence = args.evidence_run_root.resolve()
    out = root / "raw" / "S-E7-isolated-overhead"
    out.mkdir(parents=True, exist_ok=True)
    atomic_json(out / "preflight.json", assert_live_preflight())

    total_cells = len(MODES) * args.replicates
    rows: list[dict] = []

    with campaign_lock("strengthening-live"):
        for mode in MODES:
            seed_base = 70000 + MODES.index(mode) * 1000
            for rep in range(1, args.replicates + 1):
                print(f"[S-E7] {mode} replicate {rep}/{args.replicates}")
                try:
                    row, samples, log = run_cell(
                        mode, rep, args.condition, evidence,
                        args.duration_seconds, seed_base,
                    )
                except Exception as exc:
                    print(f"[S-E7] FAILED {mode} rep {rep}: {exc}")
                    raise

                cell = out / mode / f"replicate-{rep:02d}"
                cell.mkdir(parents=True, exist_ok=True)
                atomic_json(cell / "result.json", row)
                atomic_json(cell / "resource-samples.json", samples)
                (cell / "frontend.log").write_text(log, encoding="utf-8")

                if not row["accepted_evidence"]:
                    raise RuntimeError(
                        f"S-E7 evidence acceptance failed: {mode} rep {rep}"
                    )
                rows.append(row)
                atomic_json(out / "progress.json", {
                    "updated_utc": utc_now(),
                    "completed": len(rows),
                    "target": total_cells,
                })

                # Restore baseline state between cells
                clear_live_network()
                set_tracing(False); set_controller(False)
                time.sleep(5)
                if not wait_healthy()["healthy"]:
                    raise RuntimeError("cluster unhealthy between cells")

    # ---- summary CSV ---------------------------------------------------------
    csv_path = root / "derived" / "S-E7-isolated-overhead.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "mode", "replicate", "condition", "duration_seconds",
        "elapsed_seconds", "accepted_evidence",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows([{k: r.get(k) for k in fields} for r in rows])

    summary = {
        "experiment": "S-E7",
        "completed_utc": utc_now(),
        "modes": list(MODES),
        "condition": args.condition,
        "replicates": args.replicates,
        "duration_seconds": args.duration_seconds,
        "cells": len(rows),
        "all_evidence_accepted": all(r["accepted_evidence"] for r in rows),
        "output_csv": str(csv_path.relative_to(root)),
    }
    atomic_json(root / "derived" / "S-E7-summary.json", summary)
    write_manifest(root)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
