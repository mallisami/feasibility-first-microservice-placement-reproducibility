#!/usr/bin/env python3
"""Static validation for strengthening configuration, runner imports, and experiment registry."""
from __future__ import annotations
import ast, json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent; IMPL = HERE.parent; REPO = IMPL.parent
cfg = json.loads((IMPL / "config" / "campaign" / "strengthening_sequential_campaign.json").read_text())
errors = []

EXPECTED_EXPERIMENTS = {
    "S-E1-live-full-planner", "S-E2-r4-replicated-subset", "S-E3-independent-wireless-traces",
    "S-E4-topology-spread-baseline", "S-E5-live-multi-replica", "S-E6-external-scheduler",
    "S-E7-isolated-overhead", "S-E8-failure-robustness", "S-GRACE-recovery-guard",
    "S-MILP-matched-heuristics",
}
EXPECTED_RUNNERS = {
    "run_se1_live_full_planner.py", "run_se2_r4_replicated_subset.py",
    "run_se3_independent_wireless_traces.py", "run_se4_scheduler_baseline.py",
    "run_se5_multi_replica.py", "run_se6_external_scheduler.py",
    "run_se7_isolated_overhead.py", "run_se8_failure_robustness.py",
    "run_sgrace_recovery_guard.py", "run_smilp_matched_heuristics.py",
}
EXPECTED_CELL_COUNTS = {
    "S-E1-live-full-planner": 55, "S-E2-r4-replicated-subset": 36,
    "S-E3-independent-wireless-traces": 24, "S-E4-topology-spread-baseline": 90,
    "S-E5-live-multi-replica": 20, "S-E6-external-scheduler": 135,
    "S-E7-isolated-overhead": 25, "S-E8-failure-robustness": 30,
    "S-GRACE-recovery-guard": 30, "S-MILP-matched-heuristics": 72,
}

# 1. Phase namespace
for phase in cfg["execution_order"]:
    if not phase.startswith("S-"):
        errors.append(f"phase does not use strengthening namespace: {phase}")

# 2. All expected experiments registered
registered = set(cfg.get("experiments", {}).keys())
missing_experiments = EXPECTED_EXPERIMENTS - registered
extra_experiments = registered - EXPECTED_EXPERIMENTS
if missing_experiments:
    errors.append(f"missing experiments in config: {sorted(missing_experiments)}")
if extra_experiments:
    errors.append(f"unexpected experiments in config: {sorted(extra_experiments)}")

# 3. All execution_order entries have a registered experiment
for phase in cfg["execution_order"]:
    if phase not in registered:
        errors.append(f"execution_order references unregistered experiment: {phase}")

# 4. Python syntax for all .py files
py_files = sorted(HERE.glob("*.py"))
for path in py_files:
    try:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        errors.append(f"{path.name}: {exc}")

# 5. Runner files exist
actual_runners = {p.name for p in py_files if p.name.startswith("run_s")}
missing_runners = EXPECTED_RUNNERS - actual_runners
if missing_runners:
    errors.append(f"missing runner files: {sorted(missing_runners)}")

# 6. Cell counts match
for exp_id, expected in EXPECTED_CELL_COUNTS.items():
    cfg_cells = cfg.get("experiments", {}).get(exp_id, {}).get("cells")
    if cfg_cells is not None and cfg_cells != expected:
        errors.append(f"{exp_id}: config says {cfg_cells} cells, expected {expected}")

# 7. Resource constraints
if cfg["minimum_resources"]["absolute_minimum_docker_memory_gib"] > cfg["minimum_resources"]["recommended_docker_memory_gib"]:
    errors.append("Docker minimum exceeds recommendation")

# 8. Frozen primary protection
frozen = REPO / "RESULTS" / "primary" / "v03-20260811T151500Z"
if not frozen.is_dir():
    errors.append(f"frozen primary directory not found: {frozen}")

# 9. Result directory isolation
results_root = cfg.get("results_root", "")
if "primary" in results_root:
    errors.append("results_root must not write into primary evidence tree")

# 10. S-E6 counterbalanced orders
se6 = cfg.get("experiments", {}).get("S-E6-external-scheduler", {})
orders = se6.get("counterbalanced_orders", [])
if len(orders) < 5:
    errors.append(f"S-E6 needs at least 5 counterbalanced orders, found {len(orders)}")

# 11. Experiment matrix frozen flag
if not cfg.get("experiment_matrix_frozen"):
    errors.append("experiment_matrix_frozen should be True")

if errors:
    print("VALIDATION FAILED")
    print("\n".join("- " + x for x in errors))
    raise SystemExit(1)

total = sum(EXPECTED_CELL_COUNTS.values())
print(f"OK: {len(py_files)} Python files parsed; {len(cfg['execution_order'])} phases in execution order; {len(registered)} experiments registered")
print(f"Total cells: {total} (without MILP: {total - EXPECTED_CELL_COUNTS['S-MILP-matched-heuristics']})")
print("STRENGTHENING EXPERIMENT MATRIX FROZEN")
