#!/usr/bin/env python3
"""Capture a raw infrastructure snapshot without mutating the cluster."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))

from mape_cap_bplus.v03_evidence import atomic_write_json, utc_now, write_manifest


def capture(command: list[str]) -> dict:
    completed = subprocess.run(command, capture_output=True, text=True, timeout=30)
    return {"command": command, "returncode": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_root", type=Path)
    args = parser.parse_args()
    run_root = args.run_root.resolve()
    output = run_root / "raw" / "phase-0-infrastructure-snapshot.json"
    if output.exists():
        raise FileExistsError("infrastructure snapshot already exists")
    commands = [
        ["docker", "info", "--format", "{{json .}}"],
        ["docker", "ps", "-a", "--no-trunc", "--format", "{{json .}}"],
        ["kubectl", "get", "nodes", "--show-labels", "-o", "wide"],
        ["kubectl", "get", "pods", "-A", "-o", "wide"],
        ["kubectl", "get", "services", "-A", "-o", "wide"],
        ["kubectl", "get", "events", "-A", "--sort-by=.lastTimestamp"],
    ]
    records = [capture(command) for command in commands]
    atomic_write_json(output, {"captured_utc": utc_now(), "records": records})
    write_manifest(run_root, run_root / "manifests" / "run.sha256")
    if any(record["returncode"] != 0 for record in records):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
