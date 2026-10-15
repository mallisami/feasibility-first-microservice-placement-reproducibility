"""Validated JSON loading for versioned MAPE-CAP B+ experiments."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .models import (
    FlowSpec,
    LinkState,
    NodeSpec,
    ProblemInstance,
    RelocationCost,
    ReplicaSpec,
    RiskConfig,
    Scenario,
)
from .validation import validate_link_trace_document, validate_problem


class InputValidationError(ValueError):
    pass


def _reject_nonstandard_constant(value: str):
    raise InputValidationError(f"non-standard JSON numeric constant is not allowed: {value}")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_nonstandard_constant,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise InputValidationError(f"could not read valid JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise InputValidationError(f"{path}: top-level JSON value must be an object")
    return value


def _read_and_validate(document_path: Path, schema_path: Path) -> dict[str, Any]:
    document = _read_json(document_path)
    schema = _read_json(schema_path)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(document), key=lambda e: list(e.path))
    if errors:
        rendered = "; ".join(f"{list(e.path)}: {e.message}" for e in errors)
        raise InputValidationError(f"{document_path}: {rendered}")
    return document


def _resolve_under(base: Path, relative_name: str) -> Path:
    candidate = (base / relative_name).resolve()
    try:
        candidate.relative_to(base.resolve())
    except ValueError as exc:
        raise InputValidationError(f"referenced file escapes experiment directory: {relative_name}") from exc
    return candidate


def load_experiment(experiment_path: str | Path, schema_directory: str | Path | None = None):
    experiment_path = Path(experiment_path).resolve()
    base = experiment_path.parent
    schema_directory = Path(schema_directory or base.parent / "schemas").resolve()

    experiment = _read_and_validate(experiment_path, schema_directory / "experiment.schema.json")
    application = _read_and_validate(
        _resolve_under(base, experiment["application_file"]),
        schema_directory / "application.schema.json",
    )
    cluster = _read_and_validate(
        _resolve_under(base, experiment["cluster_file"]),
        schema_directory / "cluster.schema.json",
    )
    link_trace = _read_and_validate(
        _resolve_under(base, experiment["link_trace_file"]),
        schema_directory / "link_trace.schema.json",
    )
    trace_valid, trace_reasons = validate_link_trace_document(link_trace)
    if not trace_valid:
        raise InputValidationError("link-trace semantic validation failed: " + "; ".join(trace_reasons))

    nodes = tuple(NodeSpec(**record) for record in cluster["nodes"])
    replicas = tuple(
        ReplicaSpec(
            replica_id=record["replica_id"],
            service_id=record["service_id"],
            cpu_request=record["cpu_request"],
            memory_request_mb=record["memory_request_mb"],
            allowed_nodes=tuple(record.get("allowed_nodes", ())),
            anti_affinity_group=record.get("anti_affinity_group"),
        )
        for record in application["replicas"]
    )
    flows = tuple(FlowSpec(**record) for record in application["flows"])

    requested_scenarios = tuple(experiment["scenario_ids"])
    requested_set = set(requested_scenarios)
    available_scenarios = {record["scenario_id"] for record in link_trace["scenarios"]}
    unknown_scenarios = sorted(requested_set - available_scenarios)
    if unknown_scenarios:
        raise InputValidationError(f"unknown selected scenario IDs: {unknown_scenarios}")

    scenarios_by_id: dict[str, Scenario] = {}
    for record in link_trace["scenarios"]:
        if record["scenario_id"] not in requested_set:
            continue
        links = {}
        for link_record in record["links"]:
            link = LinkState(**link_record)
            key = (link.source_rack, link.destination_rack)
            if key in links:
                raise InputValidationError(
                    f"scenario {record['scenario_id']} contains duplicate directed link {key}"
                )
            links[key] = link
        scenarios_by_id[record["scenario_id"]] = Scenario(
            scenario_id=record["scenario_id"],
            weight=record["weight"],
            links=links,
            conflict_budgets_seconds=record["conflict_budgets_seconds"],
            intra_rack_latency_ms=record.get("intra_rack_latency_ms", 0.2),
            intra_rack_goodput_bps=record.get("intra_rack_goodput_bps", 100_000_000_000.0),
            regime_duration_seconds=record["regime_duration_seconds"],
            metadata=record.get("metadata", {}),
        )
    scenarios = tuple(scenarios_by_id[scenario_id] for scenario_id in requested_scenarios)

    relocation_costs = {
        replica_id: RelocationCost(replica_id=replica_id, **record)
        for replica_id, record in experiment["relocation_costs"].items()
    }
    problem = ProblemInstance(
        instance_id=experiment["instance_id"],
        decision_window_seconds=link_trace["decision_window_seconds"],
        nodes=nodes,
        replicas=replicas,
        flows=flows,
        scenarios=scenarios,
        current_placement=experiment["current_placement"],
        relocation_costs=relocation_costs,
        max_relocations=experiment.get("max_relocations"),
        metadata=experiment.get("metadata", {}),
    )
    valid, reasons = validate_problem(problem)
    if not valid:
        raise InputValidationError("semantic validation failed: " + "; ".join(reasons))
    risk = RiskConfig(**experiment["risk"])
    risk.validate()
    return problem, risk
