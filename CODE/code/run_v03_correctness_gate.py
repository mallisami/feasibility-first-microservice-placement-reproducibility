#!/usr/bin/env python3
"""Run and persist the v0.3 scientific correctness gate."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))

from mape_cap_bplus.v03_evidence import atomic_write_json, atomic_write_text, utc_now, write_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_root", type=Path)
    args = parser.parse_args()
    run_root = args.run_root.resolve()
    report_path = run_root / "raw" / "phase-1-correctness-gate.json"
    if report_path.exists():
        raise FileExistsError("correctness evidence already exists; refusing to overwrite it")

    python = Path(sys.executable)
    temp_root = run_root / "raw" / "temp"
    temp_root.mkdir(exist_ok=False)
    randomized_audit_output = temp_root / "randomized_exact_vs_exhaustive_120.json"
    commands = [
        [str(python), "-m", "unittest", "discover", "-s", "tests", "-v"],
        [str(python), "code/validate_examples.py"],
        [str(python), "code/run_randomized_exact_audit.py", "--output", str(randomized_audit_output)],
    ]
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["TEMP"] = str(temp_root)
    environment["TMP"] = str(temp_root)
    records = []
    for index, command in enumerate(commands, start=1):
        completed = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True)
        log = (completed.stdout or "") + (completed.stderr or "")
        log_path = run_root / "logs" / f"phase-1-command-{index}.log"
        atomic_write_text(log_path, log)
        records.append({"command": command, "returncode": completed.returncode, "log": str(log_path.relative_to(run_root))})

    passed = all(record["returncode"] == 0 for record in records)
    report = {
        "campaign_version": "B+ v0.3",
        "completed_utc": utc_now(),
        "passed": passed,
        "commands": records,
        "explicit_checks": {
            "objective_dimensional_contract": "audited in V03_SCIENTIFIC_CORRECTNESS_GATE_20260811.md",
            "relocation_single_charge": "test_conservative_net_benefit_gate plus relocation-weight exact/evaluator checks",
            "benefit_gate": "test_conservative_net_benefit_gate and test_controller_rejects_negative_costs",
            "outage_and_fallback": "test_outage_without_fallback_prohibits_failed_rack_pair and test_wired_fallback_is_available_but_costly",
            "solver_evaluator_equivalence": "120 randomized exact-versus-exhaustive matches",
            "feasibility_classification": "network/conflict/infeasibility unit checks",
        },
    }
    atomic_write_json(report_path, report)
    write_manifest(run_root, run_root / "manifests" / "run.sha256")
    if not passed:
        print(json.dumps(report, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
