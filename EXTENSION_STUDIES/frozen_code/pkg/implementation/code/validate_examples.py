#!/usr/bin/env python3
"""Validate example JSON documents and semantic timestamp rules."""
from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from mape_cap_bplus.validation import validate_relocation_document

ROOT = Path(__file__).resolve().parents[1]
PAIRS = (
    ("application.example.json", "application.schema.json"),
    ("cluster.example.json", "cluster.schema.json"),
    ("link_trace.example.json", "link_trace.schema.json"),
    ("relocation_cost.example.json", "relocation_cost.schema.json"),
    ("result.example.json", "result.schema.json"),
    ("experiment.example.json", "experiment.schema.json"),
)


def _reject_constant(value: str):
    raise ValueError(f"non-standard JSON constant {value}")


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_constant)


def main() -> int:
    for document_name, schema_name in PAIRS:
        document = _read(ROOT / "config" / "examples" / document_name)
        schema = _read(ROOT / "config" / "schemas" / schema_name)
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        errors = sorted(validator.iter_errors(document), key=lambda e: list(e.path))
        if errors:
            for error in errors:
                print(f"{document_name}: {list(error.path)}: {error.message}")
            return 1
        if document_name == "relocation_cost.example.json":
            valid, reasons = validate_relocation_document(document)
            if not valid:
                for reason in reasons:
                    print(f"{document_name}: {reason}")
                return 1
        print(f"{document_name}: OK")

    # The static result.example.json is validated above; no historical demo-output files are required.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
