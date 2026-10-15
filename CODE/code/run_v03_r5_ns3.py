#!/usr/bin/env python3
"""Run the full sequential multi-seed v0.3 ns-3/WiGig evidence matrix."""
from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))

from mape_cap_bplus.v03_evidence import atomic_write_csv, atomic_write_json, sha256, utc_now, write_manifest

IMAGE = "ns3-wigig:v0.3-full"


def cells() -> list[dict]:
    result = []
    for distance in (1, 2, 4, 8):
        result.append({"id": f"los-distance-{distance}m", "coverage": "distance,los",
                       "program": "test_beamformedlink_maintenance",
                       "args": f"--simulationTime=1.2 --distance={distance} --enableBlockage=false"})
    result.extend([
        {"id": "partial-blockage-recovery", "coverage": "partial-blockage,recovery,time-varying",
         "program": "test_beamformedlink_maintenance",
         "args": "--simulationTime=1.2 --distance=2 --blockageDb=-20 --blockageTime=0.5 --enableBlockage=true"},
        {"id": "full-blockage-recovery", "coverage": "full-blockage,recovery,time-varying",
         "program": "test_beamformedlink_maintenance",
         "args": "--simulationTime=1.2 --distance=2 --blockageDb=-100 --blockageTime=0.5 --enableBlockage=true"},
        {"id": "beam-training-cbap", "coverage": "beam-training,alignment-overhead",
         "program": "evaluate_beamforming_cbap", "args": "--simulationTime=3 --applicationType=onoff --socketType=ns3::UdpSocketFactory"},
        {"id": "beam-refinement-8x4", "coverage": "beam-training,alignment-overhead",
         "program": "evaluate_beam_refinement_protocol", "args": "--simulationTime=2 --sectors=8 --awvs=4"},
        {"id": "beam-refinement-16x8", "coverage": "beam-training,alignment-overhead",
         "program": "evaluate_beam_refinement_protocol", "args": "--simulationTime=2 --sectors=16 --awvs=8"},
        {"id": "multi-service-period", "coverage": "beam-scheduling,simultaneous-transmissions",
         "program": "evaluate_multi_service_period", "args": "--simulationTime=4"},
        {"id": "traffic-allocation-short", "coverage": "beam-scheduling",
         "program": "evaluate_trafficstream_allocation", "args": "--simulationTime=4 --duration=1600"},
        {"id": "traffic-allocation-long", "coverage": "beam-scheduling",
         "program": "evaluate_trafficstream_allocation", "args": "--simulationTime=4 --duration=6400"},
    ])
    for duration in (1600, 3200, 6400):
        result.append({"id": f"service-period-{duration}us", "coverage": "beam-scheduling,alignment-overhead",
                       "program": "evaluate_simple_service_period", "args": f"--simulationTime=2 --spDuration={duration}"})
    for links in (1, 2, 4):
        result.append({"id": f"spatial-sharing-{links}-links", "coverage": "simultaneous-transmissions,interference,conflict-groups,spatial-reuse",
                       "program": "evaluate_qd_channel_spatial_sharing",
                       "args": f"--simulationTime=1.5 --parallelLinks={links} --csv=false --directory=/evidence/ --qdChannelFolder=SpatialSharingMobility"})
    result.extend([
        {"id": "spatial-sharing-mobile", "coverage": "spatial-reuse,time-varying,interference",
         "program": "evaluate_qd_channel_spatial_sharing",
         "args": "--simulationTime=1.5 --parallelLinks=2 --csv=false --enableMobility=true --directory=/evidence/ --qdChannelFolder=SpatialSharingMobility"},
        {"id": "dense-interference-4", "coverage": "interference,conflict-groups",
         "program": "evaluate_qd_dense_scenario_single_ap",
         "args": "--simulationTime=1.5 --numSTAs=4 --csv=false --directory=/evidence/ --qdChannelFolder=DenseScenario"},
        {"id": "dense-interference-10", "coverage": "interference,conflict-groups",
         "program": "evaluate_qd_dense_scenario_single_ap",
         "args": "--simulationTime=1.5 --numSTAs=10 --csv=false --directory=/evidence/ --qdChannelFolder=DenseScenario"},
    ])
    return result


def run_cell(cell: dict, seed: int, directory: Path, image: str = IMAGE) -> dict:
    directory.mkdir(parents=True, exist_ok=False)
    spec = f"{cell['program']} {cell['args']} --RngRun={seed}"
    inner = f"set -o pipefail; mkdir -p Traces; ./waf --run-no-build {shlex.quote(spec)}; rc=$?; for f in ./*.csv; do [ -f \"$f\" ] && cp \"$f\" /evidence/; done; exit $rc"
    command = ["docker", "run", "--rm", "--name", f"bplus-v03-r5-{cell['id']}-s{seed}",
               "-v", f"{directory}:/evidence", image, "/bin/bash", "-lc", inner]
    started = time.perf_counter()
    completed = subprocess.run(command, capture_output=True, text=True, timeout=180)
    stdout, stderr = completed.stdout, completed.stderr
    atomic_write_json(directory / "process.json", {
        "command": command, "returncode": completed.returncode, "runtime_seconds": time.perf_counter() - started,
        "stdout": stdout, "stderr": stderr, "completed_utc": utc_now(),
    })
    samples = []
    for line in stdout.splitlines():
        match = re.match(r"^\s*(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s*$", line)
        if match:
            samples.append({"time_seconds": float(match.group(1)), "goodput_mbps": float(match.group(2))})
    generated = [{"path": p.name, "sha256": sha256(p), "bytes": p.stat().st_size}
                 for p in sorted(directory.iterdir()) if p.is_file() and p.name != "process.json"]
    return {"status": "complete" if completed.returncode == 0 else "failure", "returncode": completed.returncode,
            "runtime_seconds": time.perf_counter() - started, "timeseries_samples": len(samples),
            "goodput_timeseries": samples, "generated_files": generated,
            "error": stderr[-1000:] if completed.returncode else ""}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_root", type=Path)
    parser.add_argument("--seeds", type=int, default=3)
    args = parser.parse_args()
    run_root = args.run_root.resolve()
    raw_root = run_root / "raw" / "phase-5-r5-ns3"
    output = run_root / "raw" / "phase-5-r5-index.csv"
    checkpoint = run_root / "checkpoints" / "phase-5-r5.json"
    if output.exists():
        raise FileExistsError("final R5 index exists")
    raw_root.mkdir(exist_ok=False)
    image = subprocess.run(["docker", "image", "inspect", IMAGE, "--format", "{{json .}}"], capture_output=True, text=True)
    if image.returncode != 0:
        raise RuntimeError(image.stderr)
    atomic_write_json(raw_root / "image-inspect.json", json.loads(image.stdout))
    state = {"completed": [], "rows": []}
    rows = []
    matrix = cells()
    for cell in matrix:
        for seed in range(1, args.seeds + 1):
            run_id = f"{cell['id']}:seed{seed}"
            result = run_cell(cell, seed, raw_root / f"{cell['id']}-seed{seed}")
            row = {"run_id": run_id, "scenario": cell["id"], "seed": seed, "program": cell["program"],
                   "coverage": cell["coverage"], **{k: json.dumps(v, sort_keys=True) if isinstance(v, (list, dict)) else v for k, v in result.items()}}
            rows.append(row)
            state["completed"].append(run_id)
            state["rows"] = rows
            state["updated_utc"] = utc_now()
            atomic_write_json(checkpoint, state)
            print(f"[{len(rows)}/{len(matrix) * args.seeds}] {run_id} {result['status']}", flush=True)
    atomic_write_csv(output, rows)
    atomic_write_json(checkpoint, {"completed_utc": utc_now(), "completed": state["completed"], "row_count": len(rows)})
    ledger_path = run_root / "checkpoints" / "ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["phases"]["phase-5-r5-ns3"] = "completed" if all(row["status"] == "complete" for row in rows) else "completed_with_failures"
    ledger["current_phase"] = "phase-6-kind"
    atomic_write_json(ledger_path, ledger)
    write_manifest(run_root, run_root / "manifests" / "run.sha256")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
