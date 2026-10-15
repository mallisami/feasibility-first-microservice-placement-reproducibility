#!/usr/bin/env python3
"""Run ONLY the strict S-E6 three-scheduler validation campaign.

This wrapper never launches S-E1/S-E2/S-E3/S-E4/S-E5/S-E7/S-E8/S-GRACE/S-MILP.
It creates a fresh append-only results root, runs S-E6, performs symmetric
feasibility/application post-processing, and writes an integrity manifest.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import atomic_json, create_run_root, resource_snapshot, utc_now, write_manifest
from se6_external_support import HELM_VERSION, SCHEDULER_PLUGINS_VERSION, SCHEDULER_IMAGE


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, encoding="utf-8", errors="replace")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-id", default=None, help="Optional fresh run id. Must not already exist.")
    p.add_argument("--dry-run", action="store_true", help="Print the frozen S-E6 plan without modifying the cluster.")
    p.add_argument("--keep-external-scheduler", action="store_true", help="Leave the secondary scheduler installed after S-E6.")
    args = p.parse_args()

    if args.dry_run:
        plan = {
            "experiment": "S-E6",
            "only_experiment_executed": True,
            "conditions": 9,
            "paired_replicates": 5,
            "methods": ["Native", "External-NetworkOverhead/Diktyo", "BPlus-Exact"],
            "total_cells": 135,
            "external_scheduler": {
                "implementation": "Kubernetes SIG scheduler-plugins NetworkOverhead (Diktyo API lineage)",
                "version": SCHEDULER_PLUGINS_VERSION,
                "image": SCHEDULER_IMAGE,
            },
            "helm": {
                "pinned_version": HELM_VERSION,
                "behavior": "use exact pinned system Helm if present; otherwise download locally and SHA-256 verify",
            },
            "results_policy": "fresh append-only RESULTS/strengthening/se6-external-<UTC>/; previous results untouched",
            "fallback": "DISABLED: if external scheduler cannot be verified, S-E6 stops before scientific measurements",
            "postprocessing": [
                "symmetric feasibility evaluation for all three methods",
                "paired replicate-level application differences",
                "summary CSV/JSON",
                "SHA-256 run manifest",
            ],
        }
        print(json.dumps(plan, indent=2))
        return 0

    run_id = args.run_id or datetime.now(timezone.utc).strftime("se6-external-%Y%m%dT%H%M%SZ")
    root = create_run_root(run_id)
    atomic_json(root / "S-E6-only-plan.json", {
        "created_utc": utc_now(),
        "experiment": "S-E6",
        "scope": "S-E6 only; no other strengthening or primary experiment is executed",
        "expected_cells": 135,
        "methods": ["Native", "External-NetworkOverhead", "BPlus-Exact"],
        "external_scheduler_version": SCHEDULER_PLUGINS_VERSION,
        "external_scheduler_image": SCHEDULER_IMAGE,
        "helm_version": HELM_VERSION,
        "fallback_allowed": False,
        "append_only": True,
    })
    atomic_json(root / "logs" / "S-E6-wrapper-pre-resource.json", resource_snapshot())

    runner = HERE / "run_se6_external_scheduler.py"
    post = HERE / "se6_symmetric_feasibility.py"
    cmd = [sys.executable, str(runner), str(root)]
    if args.keep_external_scheduler:
        cmd.append("--keep-external-scheduler")

    rc = _run(cmd).returncode
    if rc != 0:
        atomic_json(root / "S-E6-only-status.json", {
            "status": "FAILED_OR_BLOCKED",
            "runner_exit_code": rc,
            "completed_utc": utc_now(),
            "other_experiments_executed": False,
            "previous_results_modified": False,
        })
        write_manifest(root)
        print(f"S-E6 stopped with exit code {rc}. Partial/block evidence is preserved at: {root}", file=sys.stderr)
        return rc

    post_rc = _run([sys.executable, str(post), str(root)]).returncode
    status = "COMPLETED" if post_rc == 0 else "COMPLETED_POSTPROCESS_FAILED"
    atomic_json(root / "S-E6-only-status.json", {
        "status": status,
        "runner_exit_code": rc,
        "postprocess_exit_code": post_rc,
        "completed_utc": utc_now(),
        "other_experiments_executed": False,
        "previous_results_modified": False,
    })
    write_manifest(root)
    print(f"S-E6 result root: {root}")
    return post_rc


if __name__ == "__main__":
    raise SystemExit(main())
