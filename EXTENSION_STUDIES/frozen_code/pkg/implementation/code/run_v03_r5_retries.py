#!/usr/bin/env python3
"""Run append-only corrective R5 cells while preserving the original failures."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))

from mape_cap_bplus.v03_evidence import atomic_write_csv, atomic_write_json, utc_now, write_manifest
from run_v03_r5_ns3 import run_cell

RETRIES = [
    {"id": "retry-traffic-allocation-short", "coverage": "beam-scheduling", "program": "evaluate_trafficstream_allocation",
     "args": "--simulationTime=10 --duration=1600", "reason": "original 4-second run hit upstream PHY-state assertion"},
    {"id": "retry-traffic-allocation-long", "coverage": "beam-scheduling", "program": "evaluate_trafficstream_allocation",
     "args": "--simulationTime=10 --duration=6400", "reason": "original 4-second run hit upstream PHY-state assertion"},
    {"id": "retry-service-period-1600us", "coverage": "beam-scheduling,alignment-overhead", "program": "evaluate_simple_service_period",
     "args": "--simulationTime=2 --spDuration=1600", "reason": "create upstream-required Traces directory"},
    {"id": "retry-service-period-3200us", "coverage": "beam-scheduling,alignment-overhead", "program": "evaluate_simple_service_period",
     "args": "--simulationTime=2 --spDuration=3200", "reason": "create upstream-required Traces directory"},
    {"id": "retry-service-period-6400us", "coverage": "beam-scheduling,alignment-overhead", "program": "evaluate_simple_service_period",
     "args": "--simulationTime=2 --spDuration=6400", "reason": "create upstream-required Traces directory"},
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_root", type=Path)
    parser.add_argument("--seeds", type=int, default=3)
    args = parser.parse_args()
    run_root = args.run_root.resolve()
    root = run_root / "raw" / "phase-5-r5-retries"
    output = run_root / "raw" / "phase-5-r5-retry-index.csv"
    if root.exists() or output.exists():
        raise FileExistsError("R5 retry evidence already exists")
    root.mkdir()
    rows = []
    for cell in RETRIES:
        for seed in range(1, args.seeds + 1):
            result = run_cell(cell, seed, root / f"{cell['id']}-seed{seed}")
            rows.append({"run_id": f"{cell['id']}:seed{seed}", "scenario": cell["id"], "seed": seed,
                         "program": cell["program"], "coverage": cell["coverage"], "retry_reason": cell["reason"],
                         **{k: json.dumps(v, sort_keys=True) if isinstance(v, (list, dict)) else v for k, v in result.items()}})
            atomic_write_json(run_root / "checkpoints" / "phase-5-r5-retries.json",
                              {"updated_utc": utc_now(), "rows": rows})
            print(f"[{len(rows)}/{len(RETRIES) * args.seeds}] {rows[-1]['run_id']} {result['status']}", flush=True)
    atomic_write_csv(output, rows)
    write_manifest(run_root, run_root / "manifests" / "run.sha256")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
