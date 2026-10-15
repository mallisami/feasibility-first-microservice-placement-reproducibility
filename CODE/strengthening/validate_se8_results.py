#!/usr/bin/env python3
"""Independent scientific validator for S-E8 failure robustness and safe fallback.

Reads raw trial JSON records and verification logs directly without relying on
the experiment runner's own top-level summary.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

SERVICES = [
    "adservice", "cartservice", "checkoutservice", "currencyservice", "emailservice",
    "frontend", "paymentservice", "productcatalogservice", "recommendationservice",
    "redis-cart", "shippingservice",
]

EXPECTED_FAULTS = [
    "F1-missing-telemetry",
    "F2-stale-telemetry",
    "F3-solver-timeout",
    "F4-infeasible-instance",
    "F5-invalid-target-prevalidation",
    "F6-partial-mutation-rollback",
]


def wilson_score_interval(successes: int, trials: int, confidence: float = 0.95) -> tuple[float, float]:
    """Compute Wilson score interval for binomial proportion."""
    if trials == 0:
        return (0.0, 0.0)
    z = 1.95996  # 95% confidence
    p = successes / trials
    denominator = 1.0 + z * z / trials
    centre = (p + z * z / (2.0 * trials)) / denominator
    margin = (z * math.sqrt(p * (1.0 - p) / trials + z * z / (4.0 * trials * trials))) / denominator
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def validate_trial(record: dict, fault_type: str, rep: int) -> dict[str, Any]:
    """Independently audit a single trial record."""
    issues = []
    
    # 1. Run ID & Replicate consistency
    expected_run_id = f"S-E8:{fault_type}:rep{rep}"
    if record.get("run_id") != expected_run_id:
        issues.append(f"run_id mismatch: expected {expected_run_id}, got {record.get('run_id')}")
        
    # 2. Baseline & final placement checks
    previous = record.get("previous_placement", {})
    actual = record.get("actual_placement", {})
    if not previous or not actual:
        issues.append("missing previous or actual placement")
    
    placement_preserved = all(actual.get(s) == previous.get(s) for s in SERVICES)
    if not placement_preserved:
        issues.append("actual placement does not match baseline previous placement")
        
    # 3. Pod readiness & application health
    health = record.get("health", {})
    pods_healthy = bool(health.get("healthy", False))
    if not pods_healthy:
        issues.append("health report indicates unready pods or non-running phase")
        
    # 4. Fault-specific independent assertions
    fault_detected = False
    zero_mutation = False
    rollback_performed = False
    
    if fault_type == "F1-missing-telemetry":
        # Telemetry was disabled; solver gate must abstain; zero mutations
        fault_detected = record.get("failure_reason") == "telemetry_disabled"
        zero_mutation = placement_preserved
        
    elif fault_type == "F2-stale-telemetry":
        # Stale telemetry injected; staleness detected; candidate not applied
        solver_state = record.get("solver_state", {})
        fault_detected = bool(solver_state.get("staleness_detected"))
        zero_mutation = placement_preserved
        
    elif fault_type == "F3-solver-timeout":
        # 1ms timeout; ExactSolveError caught
        solver_state = record.get("solver_state", {})
        fault_detected = bool(solver_state.get("timeout_caught"))
        zero_mutation = placement_preserved
        
    elif fault_type == "F4-infeasible-instance":
        # Infeasible instance; solver rejection or post-solve feasibility caught
        solver_state = record.get("solver_state", {})
        fault_detected = bool(solver_state.get("infeasibility_detected"))
        zero_mutation = placement_preserved
        
    elif fault_type == "F5-invalid-target-prevalidation":
        # Invalid target passed; controller must reject BEFORE first mutation
        solver_state = record.get("solver_state", {})
        fault_detected = bool(record.get("verdict", {}).get("pre_execution_rejected"))
        # Audit zero mutations using pre/post deployment generation
        pre_gen = solver_state.get("pre_generation")
        post_gen = solver_state.get("post_generation")
        pre_rv = solver_state.get("pre_resource_version")
        post_rv = solver_state.get("post_resource_version")
        zero_mutation = (pre_gen is not None and pre_gen == post_gen and pre_rv == post_rv)
        if not zero_mutation:
            issues.append(f"mutation occurred in prevalidation test: gen {pre_gen}->{post_gen}, rv {pre_rv}->{post_rv}")
            
    elif fault_type == "F6-partial-mutation-rollback":
        # Hook injected failure after 1 patch; controller rolled back; health recovered
        solver_state = record.get("solver_state", {})
        fault_detected = bool(record.get("verdict", {}).get("rollback_initiated"))
        rollback_performed = bool(record.get("verdict", {}).get("rollback_completed"))
        if not rollback_performed:
            issues.append("rollback was not completed successfully")
        zero_mutation = False  # By definition, partial mutation occurred and was rolled back
        
    elif fault_type == "F5-k8s-action-failure":
        # Historical uncorrected case
        fault_detected = True
        zero_mutation = False
        rollback_performed = True

    # Strict safety criterion:
    # - For F1-F5: fault detected, zero mutations, placement preserved, pods healthy
    # - For F6: fault detected, rollback completed, placement restored, pods healthy
    if fault_type in ("F1-missing-telemetry", "F2-stale-telemetry", "F3-solver-timeout", "F4-infeasible-instance", "F5-invalid-target-prevalidation"):
        strict_safe = fault_detected and zero_mutation and placement_preserved and pods_healthy
    elif fault_type == "F6-partial-mutation-rollback":
        strict_safe = fault_detected and rollback_performed and placement_preserved and pods_healthy
    else:  # legacy F5
        strict_safe = False

    return {
        "run_id": record.get("run_id"),
        "fault_type": fault_type,
        "replicate": rep,
        "valid_structure": len(issues) == 0 or (fault_type == "F5-k8s-action-failure" and len(issues) <= 1),
        "issues": issues,
        "fault_detected": fault_detected,
        "zero_mutation": zero_mutation,
        "rollback_performed": rollback_performed,
        "placement_preserved": placement_preserved,
        "pods_healthy": pods_healthy,
        "strict_safe": strict_safe,
        "detection_latency_s": record.get("detection_latency_s"),
        "elapsed_s": record.get("elapsed_s"),
    }


def audit_campaign(raw_root: Path, expected_faults: list[str], expected_replicates: int) -> dict[str, Any]:
    """Audit the entire raw results directory."""
    raw_dir = raw_root / "raw" / "S-E8-failure-robustness"
    if not raw_dir.is_dir():
        raw_dir = raw_root  # In case raw_root is directly the S-E8 directory
        
    audits = []
    audits_by_fault = defaultdict(list)
    seen_run_ids = set()
    
    for fault in expected_faults:
        fault_dir = raw_dir / fault
        for rep in range(1, expected_replicates + 1):
            cell_dir = fault_dir / f"replicate-{rep:02d}"
            result_file = cell_dir / "result.json"
            if not result_file.is_file():
                audits.append({
                    "run_id": f"S-E8:{fault}:rep{rep}",
                    "fault_type": fault,
                    "replicate": rep,
                    "missing": True,
                    "strict_safe": False,
                    "issues": [f"result.json not found at {result_file}"],
                })
                continue
                
            try:
                record = json.loads(result_file.read_text(encoding="utf-8"))
            except Exception as exc:
                audits.append({
                    "run_id": f"S-E8:{fault}:rep{rep}",
                    "fault_type": fault,
                    "replicate": rep,
                    "invalid_json": True,
                    "strict_safe": False,
                    "issues": [f"failed to parse JSON: {exc}"],
                })
                continue
                
            run_id = record.get("run_id")
            if run_id in seen_run_ids:
                audits.append({
                    "run_id": run_id,
                    "fault_type": fault,
                    "replicate": rep,
                    "duplicate": True,
                    "strict_safe": False,
                    "issues": ["duplicate run_id detected"],
                })
                continue
            seen_run_ids.add(run_id)
            
            trial_audit = validate_trial(record, fault, rep)
            audits.append(trial_audit)
            audits_by_fault[fault].append(trial_audit)

    # Class-level summaries
    class_summaries = {}
    for fault in expected_faults:
        items = audits_by_fault[fault]
        n_trials = len(items)
        n_safe = sum(1 for a in items if a.get("strict_safe"))
        n_detected = sum(1 for a in items if a.get("fault_detected"))
        n_recovered = sum(1 for a in items if a.get("pods_healthy"))
        n_preserved = sum(1 for a in items if a.get("placement_preserved"))
        ci_low, ci_high = wilson_score_interval(n_safe, n_trials)
        
        class_summaries[fault] = {
            "trials_attempted": n_trials,
            "trials_expected": expected_replicates,
            "strict_safe_count": n_safe,
            "strict_safe_rate": n_safe / max(1, n_trials),
            "strict_safe_95ci": [round(ci_low, 4), round(ci_high, 4)],
            "fault_detection_rate": n_detected / max(1, n_trials),
            "placement_restoration_rate": n_preserved / max(1, n_trials),
            "health_recovery_rate": n_recovered / max(1, n_trials),
        }
        
    total_trials = len(audits)
    total_safe = sum(1 for a in audits if a.get("strict_safe"))
    overall_ci_low, overall_ci_high = wilson_score_interval(total_safe, total_trials)
    
    return {
        "validation_timestamp_utc": str(Path(__file__).stat().st_mtime),
        "total_trials_audited": total_trials,
        "total_trials_expected": len(expected_faults) * expected_replicates,
        "total_strict_safe": total_safe,
        "overall_strict_safe_rate": total_safe / max(1, total_trials),
        "overall_strict_safe_95ci": [round(overall_ci_low, 4), round(overall_ci_high, 4)],
        "all_trials_accounted_for": total_trials == len(expected_faults) * expected_replicates,
        "class_summaries": class_summaries,
        "trial_audits": audits,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results_root", type=Path, help="Path to experiment results directory")
    parser.add_argument("--replicates", type=int, default=5, help="Expected replicates per fault class")
    parser.add_argument("--faults", default=",".join(EXPECTED_FAULTS), help="Expected fault classes")
    parser.add_argument("--output", type=Path, default=None, help="Optional output path for JSON report")
    args = parser.parse_args()
    
    expected_faults = [f.strip() for f in args.faults.split(",") if f.strip()]
    report = audit_campaign(args.results_root, expected_faults, args.replicates)
    
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        
    print(json.dumps(report, indent=2))
    
    all_safe = report["total_strict_safe"] == report["total_trials_expected"]
    all_present = report["all_trials_accounted_for"]
    
    if all_safe and all_present:
        print("\nINDEPENDENT VERIFICATION RESULT: PASS (100% STRICT SAFE)")
        return 0
    else:
        print(f"\nINDEPENDENT VERIFICATION RESULT: INCOMPLETE OR UNSAFE ({report['total_strict_safe']}/{report['total_trials_expected']} safe)")
        return 1


if __name__ == "__main__":
    sys.exit(main())
