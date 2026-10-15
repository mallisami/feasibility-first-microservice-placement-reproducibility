"""Validate R2 evidence and derive matched descriptive overhead deltas."""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

from mape_cap_bplus.v03_evidence import atomic_write_json, utc_now

MODES = ["telemetry_off", "telemetry_on_controller_off", "telemetry_on_controller_on"]


def mean(rows: list[dict], path: tuple[str, ...]) -> float:
    values = []
    for row in rows:
        value = row
        for key in path:
            value = value[key]
        values.append(float(value))
    return statistics.fmean(values)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_root", type=Path)
    args = parser.parse_args()
    run_root = args.run_root.resolve()
    result_files = sorted((run_root / "raw" / "r2").glob("replicate-*/result.json"))
    rows = [json.loads(path.read_text(encoding="utf-8")) for path in result_files]
    failures: list[str] = []
    expected = {(replicate, mode) for replicate in (1, 2, 3) for mode in MODES}
    observed = {(row["replicate"], row["mode"]) for row in rows}
    if observed != expected:
        failures.append(f"cell matrix mismatch: missing={sorted(expected-observed)}, extra={sorted(observed-expected)}")
    for row in rows:
        label = f"r{row['replicate']}-{row['mode']}"
        if not row.get("accepted") or not row.get("health", {}).get("healthy"):
            failures.append(f"{label}: operational acceptance failed")
        if row["application"].get("requests", 0) <= 0:
            failures.append(f"{label}: no frontend requests")
        telemetry = row["mode"] != "telemetry_off"
        if telemetry:
            if not row.get("native_trace_windows"):
                failures.append(f"{label}: no native client spans")
            if not row.get("transport_flow_windows"):
                failures.append(f"{label}: no conntrack flow deltas")
            for index, record in enumerate(row.get("temporal_telemetry", [])):
                for field in ("source", "destination", "timestamp_utc", "window", "operation", "workload_phase", "request_bytes", "response_bytes"):
                    if field not in record or record[field] is None:
                        failures.append(f"{label}: temporal row {index} missing {field}")
                if record.get("evidence_type") == "native-opentelemetry-client-span":
                    for field in ("request_rate", "p50_ms", "p95_ms", "p99_ms", "errors"):
                        if record.get(field) is None:
                            failures.append(f"{label}: native span row {index} missing {field}")
        elif row.get("native_trace_windows") or row.get("transport_flow_windows"):
            failures.append(f"{label}: OFF mode contains telemetry records")

    by_mode = {mode: [row for row in rows if row["mode"] == mode] for mode in MODES}
    metrics = {
        "p50_ms": ("application", "p50_ms"),
        "p95_ms": ("application", "p95_ms"),
        "p99_ms": ("application", "p99_ms"),
        "throughput_rps": ("application", "throughput_requests_per_second"),
        "error_rate": ("application", "error_rate"),
        "cpu_cores": ("resources", "mean_cpu_cores"),
        "memory_mib": ("resources", "mean_memory_mib"),
        "network_Bps": ("resources", "network_bytes_per_second"),
    }
    mode_means = {
        mode: {name: mean(mode_rows, path) for name, path in metrics.items()}
        for mode, mode_rows in by_mode.items()
    }
    paired = {}
    for mode in MODES[1:]:
        deltas = {name: [] for name in metrics}
        for replicate in (1, 2, 3):
            base = next(row for row in by_mode["telemetry_off"] if row["replicate"] == replicate)
            treatment = next(row for row in by_mode[mode] if row["replicate"] == replicate)
            for name, path in metrics.items():
                left, right = base, treatment
                for key in path:
                    left, right = left[key], right[key]
                deltas[name].append(float(right) - float(left))
        paired[mode] = {
            name: {"deltas": values, "mean_delta": statistics.fmean(values)}
            for name, values in deltas.items()
        }
    controller_rows = by_mode["telemetry_on_controller_on"]
    report = {
        "validated_utc": utc_now(),
        "accepted": not failures,
        "failures": failures,
        "cell_count": len(rows),
        "mode_means": mode_means,
        "paired_differences_vs_off": paired,
        "controller_relocations": sum(int(row.get("controller_actions", 0)) for row in controller_rows),
        "controller_cells_with_relocation": sum(int(row.get("controller_actions", 0) > 0) for row in controller_rows),
        "interpretation_constraints": [
            "Three matched replicates support descriptive overhead estimates, not a definitive causal latency claim.",
            "Modes used the plan's OFF -> telemetry/controller-OFF -> telemetry/controller-ON order; cold-start/order effects are visible in latency tails.",
            "Controller-ON is intentionally not a pure observer-overhead condition because accepted persistent decisions may relocate a live service.",
            "Unsupported service edges retain exact transport bytes and packet rates but do not invent RPC latency or error fields.",
        ],
    }
    atomic_write_json(run_root / "derived" / "r2-validation.json", report)
    print(json.dumps(report, indent=2))
    return 0 if report["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
