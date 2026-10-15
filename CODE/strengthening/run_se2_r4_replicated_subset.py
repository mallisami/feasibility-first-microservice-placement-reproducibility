#!/usr/bin/env python3
"""S-E2: replicate the informative R4 storage x cache x network subset."""
from __future__ import annotations
import argparse, csv, itertools, json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
IMPL = HERE.parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(IMPL / "code"))
from common import atomic_json, assert_live_preflight, campaign_lock, clear_live_network, utc_now, write_manifest
import run_v03_r4 as r4


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("run_root", type=Path)
    p.add_argument("--replicates", type=int, default=3)
    p.add_argument("--state-size", choices=tuple(r4.STATE_SIZES), default="medium")
    p.add_argument("--load", choices=r4.LOADS, default="loaded")
    p.add_argument("--timeout", type=int, default=180)
    args = p.parse_args()
    if args.replicates < 2:
        p.error("S-E2 requires at least two replicates; three are recommended")
    run_root = args.run_root.resolve()
    out_root = run_root / "raw" / "S-E2-r4-replicated-subset"
    out_root.mkdir(parents=True, exist_ok=True)
    atomic_json(out_root / "preflight.json", assert_live_preflight())
    rows = []
    with campaign_lock("strengthening-live"):
        r4.ensure_namespace()
        try:
            for rep in range(1, args.replicates + 1):
                rep_root = out_root / f"replicate-{rep:02d}"
                (rep_root / "raw" / "r4").mkdir(parents=True, exist_ok=True)
                for storage, image_state, network in itertools.product(r4.STORAGE, r4.IMAGE_STATES, r4.NETWORKS):
                    print(f"S-E2 rep {rep}/{args.replicates}: {storage}/{image_state}/{network}", flush=True)
                    row = r4.run_cell(rep_root, storage, image_state, args.state_size, network, args.load, args.timeout)
                    rows.append({"replicate": rep, **row})
                    atomic_json(out_root / "progress.json", {"updated_utc": utc_now(), "completed": len(rows), "target": args.replicates * 12})
        finally:
            r4.cleanup_cell(); clear_live_network()
    csv_path = run_root / "derived" / "S-E2-r4-replicated-subset.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    keys = sorted({k for row in rows for k in row if not isinstance(row[k], (dict, list))})
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys); w.writeheader()
        for row in rows: w.writerow({k: row.get(k) for k in keys})
    summary = {
        "experiment": "S-E2", "completed_utc": utc_now(), "replicates": args.replicates,
        "cells": len(rows), "expected_cells": args.replicates * 12,
        "state_size": args.state_size, "load": args.load,
        "accepted_evidence": sum(bool(r.get("accepted_evidence")) for r in rows),
        "expected_outcomes": sum(bool(r.get("expected_outcome_observed")) for r in rows),
        "output_csv": str(csv_path.relative_to(run_root)),
    }
    atomic_json(run_root / "derived" / "S-E2-summary.json", summary)
    write_manifest(run_root)
    print(json.dumps(summary, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
