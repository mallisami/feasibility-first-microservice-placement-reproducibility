"""Append-only R5 repair for the two traffic-allocation scenarios."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from mape_cap_bplus.v03_evidence import atomic_write_csv, atomic_write_json, sha256, utc_now, write_manifest
from run_v03_r5_ns3 import run_cell

IMAGE = "ns3-wigig:v0.3-r5-repair-02"
CELLS = (
    {"id": "traffic-allocation-short", "coverage": "beam-scheduling", "program": "evaluate_trafficstream_allocation",
     "args": "--simulationTime=10 --duration=1600"},
    {"id": "traffic-allocation-long", "coverage": "beam-scheduling", "program": "evaluate_trafficstream_allocation",
     "args": "--simulationTime=10 --duration=6400"},
)


def throughput_summary(stdout: str) -> dict[str, float]:
    section = stdout.split("Total throughput [Mbps] during each service period allocation:")[-1]
    found = {name: float(value) for name, value in re.findall(r"^(SP[12])\s*=\s*([0-9.]+)\s*$", section, re.MULTILINE)}
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_root", type=Path)
    args = parser.parse_args(); run_root = args.run_root.resolve()
    root = run_root / "raw" / "phase-5-r5-repair-02"
    output = run_root / "raw" / "phase-5-r5-repair-02-index.csv"
    checkpoint = run_root / "checkpoints" / "phase-5-r5-repair-02.json"
    if root.exists() or output.exists():
        raise FileExistsError("R5 repair-02 evidence already exists")
    root.mkdir()
    inspect = subprocess.run(["docker", "image", "inspect", IMAGE, "--format", "{{json .}}"], capture_output=True, text=True)
    if inspect.returncode:
        raise RuntimeError(inspect.stderr)
    atomic_write_json(root / "image-inspect.json", json.loads(inspect.stdout))
    source = Path("kubernetes/simulator/wigig-module/scratch/evaluate_trafficstream_allocation.cc")
    atomic_write_json(root / "repair-provenance.json", {
        "image": IMAGE, "source_sha256": sha256(source), "source": source.as_posix(),
        "repair": "distinct allocation IDs and 1 ms stagger for the second same-host application start",
        "unchanged": ["topology", "offered load", "PHY mode", "simulation time", "service-period duration", "seeds"],
        "diagnostic": "original double transmit occurred in WifiPhyState::TX at 3000093 us",
        "generated_utc": utc_now(),
    })
    rows = []
    for cell in CELLS:
        for seed in range(1, 4):
            directory = root / f"{cell['id']}-seed{seed}"
            result = run_cell(cell, seed, directory, IMAGE)
            process = json.loads((directory / "process.json").read_text(encoding="utf-8"))
            throughput = throughput_summary(process["stdout"])
            accepted = result["status"] == "complete" and set(throughput) == {"SP1", "SP2"} and min(throughput.values()) > 0
            failures = [] if accepted else ["nonzero-two-stream-throughput-gate-failed"]
            row = {
                "run_id": f"repair-02-{cell['id']}:seed{seed}", "replaces_run_id": f"{cell['id']}:seed{seed}",
                "scenario": cell["id"], "seed": seed, "program": cell["program"], "coverage": cell["coverage"],
                "image": IMAGE, "accepted": accepted, "acceptance_failures": json.dumps(failures),
                "sp1_throughput_mbps": throughput.get("SP1"), "sp2_throughput_mbps": throughput.get("SP2"),
                **{key: json.dumps(value, sort_keys=True) if isinstance(value, (list, dict)) else value for key, value in result.items()},
            }
            rows.append(row)
            atomic_write_json(checkpoint, {"updated_utc": utc_now(), "rows": rows})
            print(f"[{len(rows)}/6] {row['run_id']} accepted={accepted}", flush=True)
            if not accepted:
                atomic_write_csv(output, rows); raise RuntimeError(f"R5 repair gate failed: {row['run_id']}")
    atomic_write_csv(output, rows)
    atomic_write_json(checkpoint, {"completed_utc": utc_now(), "row_count": len(rows), "accepted": sum(bool(row["accepted"]) for row in rows)})
    write_manifest(run_root, run_root / "manifests" / "run.sha256")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
