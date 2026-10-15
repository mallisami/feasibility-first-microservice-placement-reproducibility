"""Append-only accepted rerun of the corrected four-link R5 Q-D cells."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from mape_cap_bplus.v03_evidence import atomic_write_csv, atomic_write_json, sha256, utc_now, write_manifest
from run_v03_r5_ns3 import run_cell

IMAGE = "ns3-wigig:v0.3-r5-repair-06"
QD_FOLDER = "DenseScenario"
QD_NODE_IDS = "1,3,5,7,2,4,6,8"


def link_throughputs(stdout: str) -> dict[str, float]:
    pattern = re.compile(r"Communication Link \((\d+)\) Statistics:.*?Throughput:\s*([0-9.]+) Mbps", re.S)
    return {f"link{match.group(1)}": float(match.group(2)) for match in pattern.finditer(stdout)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_root", type=Path)
    args = parser.parse_args()
    run_root = args.run_root.resolve()
    root = run_root / "raw" / "phase-5-r5-repair-06-spatial4"
    output = run_root / "raw" / "phase-5-r5-repair-06-spatial4-index.csv"
    checkpoint = run_root / "checkpoints" / "phase-5-r5-repair-06-spatial4.json"
    if output.exists():
        raise FileExistsError("R5 repair-06 spatial-four index already exists")
    resuming = root.exists()
    if resuming and not checkpoint.exists():
        raise FileExistsError("repair evidence exists without a resumable checkpoint")
    root.mkdir(exist_ok=resuming)
    inspected = subprocess.run(["docker", "image", "inspect", IMAGE, "--format", "{{json .}}"], capture_output=True, text=True)
    if inspected.returncode:
        raise RuntimeError(inspected.stderr)
    if not resuming:
        atomic_write_json(root / "image-inspect.json", json.loads(inspected.stdout))
    source = Path("kubernetes/simulator/wigig-module/scratch/evaluate_qd_channel_spatial_sharing.cc")
    qd_root = Path("kubernetes/simulator/wigig-module/WigigFiles/QdChannel/DenseScenario/QdFiles")
    qd_files = sorted(qd_root.glob("Tx*Rx*.txt"))
    provenance = {
        "image": IMAGE,
        "source": source.as_posix(),
        "source_sha256": sha256(source),
        "qd_scenario": QD_FOLDER,
        "qd_node_mapping": {
            "ap_qd_ids": [1, 3, 5, 7],
            "sta_qd_ids": [2, 4, 6, 8],
            "pairs": [[1, 2], [3, 4], [5, 6], [7, 8]],
            "selection_rule": "four adjacent, non-overlapping perimeter-node pairs from the official 11-node DenseScenario",
        },
        "qd_file_count": len(qd_files),
        "qd_file_hashes": [{"path": path.name, "sha256": sha256(path)} for path in qd_files],
        "repair": "Explicitly map eight ns-3 nodes to eight real Q-D node IDs so all desired and cross-link interference channels are available.",
        "unchanged": ["program", "parallel link count", "offered load", "PHY mode", "simulation time", "seeds"],
        "generated_utc": utc_now(),
    }
    if not resuming:
        atomic_write_json(root / "repair-provenance.json", provenance)
    cell = {
        "id": "spatial-sharing-4-links",
        "coverage": "simultaneous-transmissions,interference,conflict-groups,spatial-reuse",
        "program": "evaluate_qd_channel_spatial_sharing",
        "args": f"--simulationTime=1.5 --parallelLinks=4 --csv=false --directory=/evidence/ --qdChannelFolder={QD_FOLDER} --qdNodeIds={QD_NODE_IDS}",
    }
    rows = json.loads(checkpoint.read_text(encoding="utf-8")).get("rows", []) if resuming else []
    accepted_seeds = {int(row["seed"]) for row in rows if row.get("accepted") is True}
    for seed in range(1, 4):
        if seed in accepted_seeds:
            print(f"[resume] preserving accepted seed {seed}", flush=True)
            continue
        directory = root / f"spatial-sharing-4-links-seed{seed}"
        result = run_cell(cell, seed, directory, IMAGE)
        process = json.loads((directory / "process.json").read_text(encoding="utf-8"))
        throughput = link_throughputs(process["stdout"])
        accepted = result["status"] == "complete" and set(throughput) == {"link1", "link2", "link3", "link4"} and min(throughput.values()) > 0
        row = {
            "run_id": f"repair-06-spatial-sharing-4-links:seed{seed}",
            "replaces_run_id": f"spatial-sharing-4-links:seed{seed}",
            "scenario": "spatial-sharing-4-links",
            "seed": seed,
            "image": IMAGE,
            "qd_scenario": QD_FOLDER,
            "qd_node_ids": QD_NODE_IDS,
            "accepted": accepted,
            **throughput,
            "acceptance_failures": json.dumps([] if accepted else ["four-positive-link-throughputs-gate-failed"]),
            **{key: json.dumps(value, sort_keys=True) if isinstance(value, (list, dict)) else value for key, value in result.items()},
        }
        rows.append(row)
        atomic_write_json(checkpoint, {"updated_utc": utc_now(), "rows": rows})
        print(f"[{len(rows)}/3] {row['run_id']} accepted={accepted} throughputs={throughput}", flush=True)
        if not accepted:
            atomic_write_csv(output, rows)
            raise RuntimeError(f"R5 repair gate failed: {row['run_id']}")
    atomic_write_csv(output, rows)
    atomic_write_json(checkpoint, {"completed_utc": utc_now(), "row_count": 3, "accepted": 3})
    write_manifest(run_root, run_root / "manifests" / "run.sha256")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
