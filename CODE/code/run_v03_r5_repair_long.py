"""Append-only accepted rerun of the corrected 6,400-us R5 allocation cells."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from mape_cap_bplus.v03_evidence import atomic_write_csv, atomic_write_json, sha256, utc_now, write_manifest
from run_v03_r5_ns3 import run_cell
from run_v03_r5_repair import throughput_summary

IMAGE = "ns3-wigig:v0.3-r5-repair-05"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_root", type=Path)
    args = parser.parse_args(); run_root = args.run_root.resolve()
    root = run_root / "raw" / "phase-5-r5-repair-05-long"
    output = run_root / "raw" / "phase-5-r5-repair-05-long-index.csv"
    checkpoint = run_root / "checkpoints" / "phase-5-r5-repair-05-long.json"
    if root.exists() or output.exists():
        raise FileExistsError("R5 repair-05 long evidence already exists")
    root.mkdir()
    inspected = subprocess.run(["docker", "image", "inspect", IMAGE, "--format", "{{json .}}"], capture_output=True, text=True)
    if inspected.returncode: raise RuntimeError(inspected.stderr)
    atomic_write_json(root / "image-inspect.json", json.loads(inspected.stdout))
    source = Path("kubernetes/simulator/wigig-module/scratch/evaluate_trafficstream_allocation.cc")
    atomic_write_json(root / "repair-provenance.json", {
        "image": IMAGE, "source": source.as_posix(), "source_sha256": sha256(source),
        "repair": "Preserve 6400-us SP duration and use the feasible half-BI repetition period; distinct allocation IDs; second same-host application starts 1 ms later.",
        "unchanged": ["topology", "offered load", "PHY mode", "simulation time", "service-period duration", "seeds"],
        "generated_utc": utc_now(),
    })
    cell = {"id": "traffic-allocation-long", "coverage": "beam-scheduling", "program": "evaluate_trafficstream_allocation",
            "args": "--simulationTime=10 --duration=6400"}
    rows = []
    for seed in range(1, 4):
        directory = root / f"traffic-allocation-long-seed{seed}"
        result = run_cell(cell, seed, directory, IMAGE)
        process = json.loads((directory / "process.json").read_text(encoding="utf-8"))
        throughput = throughput_summary(process["stdout"])
        accepted = result["status"] == "complete" and set(throughput) == {"SP1", "SP2"} and min(throughput.values()) > 0
        row = {"run_id": f"repair-05-traffic-allocation-long:seed{seed}",
               "replaces_run_id": f"traffic-allocation-long:seed{seed}", "scenario": "traffic-allocation-long",
               "seed": seed, "image": IMAGE, "accepted": accepted,
               "sp1_throughput_mbps": throughput.get("SP1"), "sp2_throughput_mbps": throughput.get("SP2"),
               "acceptance_failures": json.dumps([] if accepted else ["nonzero-two-stream-throughput-gate-failed"]),
               **{key: json.dumps(value, sort_keys=True) if isinstance(value, (list, dict)) else value for key, value in result.items()}}
        rows.append(row); atomic_write_json(checkpoint, {"updated_utc": utc_now(), "rows": rows})
        print(f"[{len(rows)}/3] {row['run_id']} accepted={accepted}", flush=True)
        if not accepted:
            atomic_write_csv(output, rows); raise RuntimeError(f"R5 repair gate failed: {row['run_id']}")
    atomic_write_csv(output, rows)
    atomic_write_json(checkpoint, {"completed_utc": utc_now(), "row_count": 3, "accepted": 3})
    write_manifest(run_root, run_root / "manifests" / "run.sha256")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
