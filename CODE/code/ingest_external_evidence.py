#!/usr/bin/env python3
"""Strictly validate and atomically ingest an external evidence batch."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import re

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT / "code"))

from mape_cap_bplus.validation import (  # noqa: E402
    validate_link_trace_document,
    validate_relocation_document,
)


def reject_nonstandard_constant(value: str):
    raise ValueError(f"non-standard JSON numeric constant is not allowed: {value}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_json(path: Path, schema_path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_nonstandard_constant)
    schema = json.loads(schema_path.read_text(encoding="utf-8"), parse_constant=reject_nonstandard_constant)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(document),
        key=lambda error: list(error.path),
    )
    if errors:
        messages = [f"{list(error.path)}: {error.message}" for error in errors]
        raise ValueError(f"{path} failed schema validation: {'; '.join(messages)}")
    return document


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--relocation-json", type=Path)
    parser.add_argument("--link-trace-json", type=Path)
    parser.add_argument("--probe-results", type=Path, help="optional CSV/JSON active-probe output")
    parser.add_argument("--label", required=True, help="immutable evidence-batch label")
    args = parser.parse_args()
    if not any((args.relocation_json, args.link_trace_json, args.probe_results)):
        parser.error("provide at least one evidence file")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", args.label):
        parser.error("label must use only letters, digits, dot, underscore, or hyphen")

    destination_root = REPO / "RESULTS" / "calibration" / "external"
    destination = destination_root / args.label
    if destination.exists():
        raise SystemExit(f"evidence label already exists and will not be overwritten: {destination}")
    destination_root.mkdir(parents=True, exist_ok=True)

    # Validate everything before creating the immutable final destination.
    validated: dict[str, dict | None] = {}
    if args.relocation_json:
        document = validate_json(args.relocation_json, ROOT / "config" / "schemas" / "relocation_cost.schema.json")
        valid, reasons = validate_relocation_document(document)
        if not valid:
            raise ValueError("relocation semantic validation failed: " + "; ".join(reasons))
        validated["relocation"] = document
    if args.link_trace_json:
        document = validate_json(args.link_trace_json, ROOT / "config" / "schemas" / "link_trace.schema.json")
        valid, reasons = validate_link_trace_document(document)
        if not valid:
            raise ValueError("link-trace semantic validation failed: " + "; ".join(reasons))
        validated["link_trace"] = document
    if args.probe_results and (not args.probe_results.exists() or not args.probe_results.is_file()):
        raise ValueError(f"probe-results file does not exist: {args.probe_results}")

    with tempfile.TemporaryDirectory(prefix="mape-cap-evidence-", dir=destination_root) as temporary_directory:
        temporary = Path(temporary_directory)
        manifest = {"label": args.label, "files": [], "validation": {}}

        if args.relocation_json:
            target = temporary / "relocation_measurements.json"
            shutil.copy2(args.relocation_json, target)
            manifest["validation"]["relocation"] = "schema-format-and-semantics-passed"
            manifest["files"].append({"path": "relocation_measurements.json", "sha256": sha256(target)})

        if args.link_trace_json:
            target = temporary / "link_trace.json"
            shutil.copy2(args.link_trace_json, target)
            manifest["validation"]["link_trace"] = "schema-and-semantics-passed; simulator provenance still requires audit"
            manifest["files"].append({"path": "link_trace.json", "sha256": sha256(target)})

        if args.probe_results:
            target = temporary / f"probe_results{args.probe_results.suffix.lower()}"
            shutil.copy2(args.probe_results, target)
            manifest["validation"]["probe_results"] = "copied; format-specific statistical audit pending"
            manifest["files"].append({"path": target.name, "sha256": sha256(target)})

        manifest_path = temporary / "MANIFEST.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(destination)

    print(f"External evidence ingested atomically without rerunning the local campaign: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
