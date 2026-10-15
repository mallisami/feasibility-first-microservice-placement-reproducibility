#!/usr/bin/env python3
"""Convert a simulator-export CSV into a validated B+ link-trace document."""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import sys

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))

from mape_cap_bplus.validation import validate_link_trace_document  # noqa: E402


def finite_number(raw: str, label: str, *, positive: bool = False, nonnegative: bool = False) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric: {raw!r}") from exc
    if not math.isfinite(value):
        raise ValueError(f"{label} must be finite")
    if positive and value <= 0:
        raise ValueError(f"{label} must be positive")
    if nonnegative and value < 0:
        raise ValueError(f"{label} must be non-negative")
    return value


def strict_bool(raw: str, label: str) -> bool:
    value = raw.strip().lower()
    if value in {"1", "true", "yes"}:
        return True
    if value in {"0", "false", "no"}:
        return False
    raise ValueError(f"{label} must be one of true/false, yes/no, or 1/0; got {raw!r}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--decision-window-seconds", type=float, default=60.0)
    args = parser.parse_args()
    if not math.isfinite(args.decision_window_seconds) or args.decision_window_seconds <= 0:
        parser.error("decision-window-seconds must be positive and finite")

    required = {
        "scenario_id", "weight", "source_rack", "destination_rack", "latency_ms",
        "goodput_bps", "available", "path_id", "conflict_group", "budget_seconds",
        "regime_duration_seconds", "provenance"
    }
    groups: dict[str, dict] = {}
    seen_pairs: dict[str, set[tuple[str, str]]] = {}
    with args.input.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(f"missing columns: {sorted(missing)}")
        for row_number, row in enumerate(reader, start=2):
            sid = row["scenario_id"].strip()
            if not sid:
                raise ValueError(f"row {row_number}: scenario_id cannot be empty")
            source = row["source_rack"].strip()
            destination = row["destination_rack"].strip()
            if not source or not destination:
                raise ValueError(f"row {row_number}: source_rack and destination_rack are required")
            if source == destination:
                raise ValueError(f"row {row_number}: explicit intra-rack links are not allowed")
            path_id = row["path_id"].strip()
            provenance = row["provenance"].strip()
            if not path_id or not provenance:
                raise ValueError(f"row {row_number}: path_id and provenance are required")

            weight = finite_number(row["weight"], f"row {row_number} weight", nonnegative=True)
            duration = finite_number(
                row["regime_duration_seconds"], f"row {row_number} regime_duration_seconds", positive=True
            )
            scenario = groups.get(sid)
            if scenario is None:
                scenario = {
                    "scenario_id": sid,
                    "weight": weight,
                    "regime_duration_seconds": duration,
                    "intra_rack_latency_ms": 0.2,
                    "intra_rack_goodput_bps": 100_000_000_000.0,
                    "conflict_budgets_seconds": {},
                    "links": [],
                    "metadata": {"source": "converted-simulator-trace"},
                }
                groups[sid] = scenario
                seen_pairs[sid] = set()
            elif not math.isclose(float(scenario["weight"]), weight, rel_tol=0, abs_tol=1e-12):
                raise ValueError(f"row {row_number}: inconsistent weight for scenario {sid}")
            elif not math.isclose(float(scenario["regime_duration_seconds"]), duration, rel_tol=0, abs_tol=1e-12):
                raise ValueError(f"row {row_number}: inconsistent regime duration for scenario {sid}")

            pair = (source, destination)
            if pair in seen_pairs[sid]:
                raise ValueError(f"row {row_number}: duplicate directed link {source}->{destination} in {sid}")
            seen_pairs[sid].add(pair)

            group = row["conflict_group"].strip()
            if group:
                budget = finite_number(row["budget_seconds"], f"row {row_number} budget_seconds", nonnegative=True)
                previous = scenario["conflict_budgets_seconds"].get(group)
                if previous is not None and not math.isclose(float(previous), budget, rel_tol=0, abs_tol=1e-12):
                    raise ValueError(f"row {row_number}: inconsistent budget for conflict group {group} in {sid}")
                scenario["conflict_budgets_seconds"][group] = budget

            available = strict_bool(row["available"], f"row {row_number} available")
            goodput = finite_number(row["goodput_bps"], f"row {row_number} goodput_bps", nonnegative=True)
            if available and goodput <= 0:
                raise ValueError(f"row {row_number}: available links require positive goodput")
            scenario["links"].append({
                "source_rack": source,
                "destination_rack": destination,
                "latency_ms": finite_number(row["latency_ms"], f"row {row_number} latency_ms", nonnegative=True),
                "goodput_bps": goodput,
                "available": available,
                "path_id": path_id,
                "conflict_group": group or None,
                "provenance": provenance,
            })

    document = {
        "schema_version": "1.0",
        "decision_window_seconds": args.decision_window_seconds,
        "scenarios": list(groups.values()),
    }
    schema = json.loads((ROOT / "config" / "schemas" / "link_trace.schema.json").read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(document),
        key=lambda error: list(error.path),
    )
    if errors:
        raise ValueError("generated document failed schema validation: " + "; ".join(error.message for error in errors))
    valid, reasons = validate_link_trace_document(document)
    if not valid:
        raise ValueError("generated document failed semantic validation: " + "; ".join(reasons))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Converted {len(groups)} validated scenarios to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
