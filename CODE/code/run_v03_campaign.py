#!/usr/bin/env python3
"""Initialize and inspect an append-only B+ v0.3 campaign run."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))

from mape_cap_bplus.v03_evidence import (
    assert_resource_gate,
    atomic_write_json,
    create_run_root,
    resource_snapshot,
    utc_now,
    write_manifest,
)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    sub = result.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="create a never-before-used run root")
    init.add_argument("--run-id")
    init.add_argument("--allow-unverified-docker", action="store_true")
    status = sub.add_parser("status", help="show a run ledger")
    status.add_argument("run_root", type=Path)
    manifest = sub.add_parser("manifest", help="refresh the run-local SHA-256 manifest")
    manifest.add_argument("run_root", type=Path)
    return result


def initialize(run_id: str | None, allow_unverified_docker: bool) -> int:
    config = json.loads((ROOT / "config" / "campaign" / "v03_sequential_campaign.json").read_text(encoding="utf-8"))
    run_root = create_run_root(ROOT / config["raw_root"], run_id)
    snapshot = resource_snapshot(run_root)
    limits = config["minimum_resources"]
    assert_resource_gate(
        snapshot,
        min_disk_gib=limits["disk_free_gib"],
        min_host_available_gib=limits["light_phase_host_available_gib"],
        min_docker_gib=0.0 if allow_unverified_docker else limits["docker_memory_gib"],
    )
    atomic_write_json(run_root / "raw" / "phase-0-resource-snapshot.json", snapshot)
    ledger = {
        "campaign_version": config["campaign_version"],
        "created_utc": utc_now(),
        "run_id": run_root.name,
        "status": "in_progress",
        "current_phase": "phase-0-audit",
        "phases": {phase: "pending" for phase in config["execution_order"]},
        "notes": ["No experiment is complete until its acceptance gate passes."],
    }
    ledger["phases"]["phase-0-audit"] = "in_progress"
    atomic_write_json(run_root / "checkpoints" / "ledger.json", ledger)
    write_manifest(run_root, run_root / "manifests" / "run.sha256")
    print(run_root)
    return 0


def main() -> int:
    args = parser().parse_args()
    if args.command == "init":
        return initialize(args.run_id, args.allow_unverified_docker)
    if args.command == "status":
        print((args.run_root / "checkpoints" / "ledger.json").read_text(encoding="utf-8"))
        return 0
    if args.command == "manifest":
        write_manifest(args.run_root, args.run_root / "manifests" / "run.sha256")
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
