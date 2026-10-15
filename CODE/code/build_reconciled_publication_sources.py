#!/usr/bin/env python3
"""Build and verify canonical paper inputs from the complete evidence repository.

This script does not modify source evidence.  It extracts the frozen G11
generation from the cumulative confirmatory CSV, copies clean supporting datasets,
and records selection rules, row counts, and SHA-256 digests.
"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


SYSTEM = Path(__file__).resolve().parents[1]
PACKAGED = SYSTEM.name == "implementation" and (SYSTEM.parent / "RESULTS").exists()
ROOT = SYSTEM.parent
if PACKAGED:
    ARCHIVED = ROOT / "RESULTS" / "supporting" / "raw"
    V03_RUN = ROOT / "RESULTS" / "primary" / "v03-20260811T151500Z"
    OUTPUT = ROOT / "RESULTS" / "supporting" / "canonical"
    AUDIT = ROOT / "RESULTS" / "audit"
else:
    ARCHIVED = ROOT / "99_RAW_ARCHIVE_LOCAL" / "historical-results" / "results"
    V03_RUN = SYSTEM / "results" / "v0.3" / "runs" / "v03-20260811T151500Z"
    OUTPUT = SYSTEM / "results" / "publication" / "reconciled-20260812"
    AUDIT = SYSTEM / "audit"

APPS = {"APP_A", "APP_B"}
CONDITIONS = {
    "stable",
    "persistent_degradation",
    "conflict_dense",
    "outage_with_fallback",
}
METHODS = {
    "Current",
    "TrafficOnly-MAPE-CAP",
    "DeterministicNetworkAware",
    "BPlus-LNS",
    "BPlus-Exact",
}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def validate_confirmatory(rows: list[dict[str, str]]) -> None:
    if len(rows) != 1200:
        raise ValueError(f"Frozen confirmatory generation has {len(rows)} rows, expected 1200")
    if {row["application"] for row in rows} != APPS:
        raise ValueError("Unexpected application set in frozen confirmatory generation")
    if {row["network_condition"] for row in rows} != CONDITIONS:
        raise ValueError("Unexpected condition set in frozen confirmatory generation")
    if {row["method"] for row in rows} != METHODS:
        raise ValueError("Unexpected method set in frozen confirmatory generation")
    if len({row["run_id"] for row in rows}) != 1200:
        raise ValueError("Frozen confirmatory generation contains duplicate run IDs")
    if len({row["instance_id"] for row in rows}) != 240:
        raise ValueError("Frozen confirmatory generation must contain 240 paired instances")
    cells = Counter((row["application"], row["network_condition"], row["method"]) for row in rows)
    if set(cells.values()) != {30} or len(cells) != 40:
        raise ValueError("Frozen confirmatory generation is not a complete 2x4x5x30 design")

    # These frozen means reproduce confirmatory_statistics_summary.md.
    expected = {
        ("APP_A", "stable", "Current"): 6010.0,
        ("APP_A", "conflict_dense", "BPlus-Exact"): 21131.0,
        ("APP_A", "persistent_degradation", "Current"): 33466.4,
        ("APP_B", "conflict_dense", "BPlus-Exact"): 16471.4,
        ("APP_B", "persistent_degradation", "Current"): 34113.0,
    }
    for key, target in expected.items():
        values = [
            float(row["objective"])
            for row in rows
            if (row["application"], row["network_condition"], row["method"]) == key
            and row["status"] == "complete"
        ]
        observed = round(sum(values) / len(values), 1)
        if observed != target:
            raise ValueError(f"Frozen-statistics mismatch for {key}: {observed} != {target}")


def validate_clean_dataset(name: str, rows: list[dict[str, str]], expected_rows: int) -> None:
    if len(rows) != expected_rows:
        raise ValueError(f"{name} has {len(rows)} rows, expected {expected_rows}")
    if "run_id" in rows[0] and len({row["run_id"] for row in rows}) != expected_rows:
        raise ValueError(f"{name} has duplicate run IDs")


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, object]] = []

    cumulative = ARCHIVED / "confirmatory_campaign.csv"
    fields, cumulative_rows = read_csv(cumulative)
    frozen_rows = cumulative_rows[:1200]
    validate_confirmatory(frozen_rows)
    frozen_output = OUTPUT / "controlled_confirmatory_app_a_b_frozen_g11.csv"
    write_csv(frozen_output, fields, frozen_rows)
    entries.append(
        {
            "id": "C1",
            "family": "controlled confirmatory APP_A/APP_B",
            "role": "supporting controlled topology evidence",
            "source": str(cumulative.relative_to(ROOT)).replace("\\", "/"),
            "source_sha256": digest(cumulative),
            "selection_rule": "first 1200 rows; verified complete 2 applications x 4 conditions x 5 methods x 30 paired replicates; reproduces frozen G11 statistics",
            "output": str(frozen_output.relative_to(ROOT)).replace("\\", "/"),
            "output_sha256": digest(frozen_output),
            "rows": len(frozen_rows),
            "independent_units": 240,
            "status_counts": dict(Counter(row["status"] for row in frozen_rows)),
        }
    )

    supporting = [
        ("C2", "controlled confirmatory APP_C", ARCHIVED / "app_c_campaign.csv", 600, "supporting controlled topology evidence"),
        ("C3", "relocation and CVaR sensitivity", ARCHIVED / "relocation_sensitivity.csv", 144, "supporting sensitivity evidence"),
        ("C4", "multi-interval dynamic adaptation", ARCHIVED / "multi_interval_dynamic.csv", 200, "supporting controlled temporal evidence"),
        ("C5", "component ablations", ARCHIVED / "full_campaign" / "ablations.csv", 10, "supporting mechanism evidence"),
        ("C6", "controlled scenario sanity", ARCHIVED / "full_campaign" / "scenario_sanity.csv", 27, "supporting verification evidence"),
        ("C7", "controlled baseline fixture", ARCHIVED / "full_campaign" / "baselines.csv", 6, "supporting mechanism check"),
        ("C8", "controlled sensitivity fixture", ARCHIVED / "full_campaign" / "sensitivity.csv", 18, "supporting mechanism evidence"),
        ("C9", "controlled dynamic sequence", ARCHIVED / "full_campaign" / "dynamic_sequence.csv", 11, "supporting negative-control evidence"),
    ]
    for evidence_id, family, source, expected_rows, role in supporting:
        source_fields, source_rows = read_csv(source)
        validate_clean_dataset(family, source_rows, expected_rows)
        target = OUTPUT / source.name
        if target.exists() and target.name in {item.get("output", "") for item in entries}:
            raise ValueError(f"Duplicate publication output name: {target.name}")
        # Avoid the two generic sensitivity files colliding.
        if family == "controlled sensitivity fixture":
            target = OUTPUT / "controlled_fixture_sensitivity.csv"
        shutil.copyfile(source, target)
        entry: dict[str, object] = {
            "id": evidence_id,
            "family": family,
            "role": role,
            "source": str(source.relative_to(ROOT)).replace("\\", "/"),
            "source_sha256": digest(source),
            "selection_rule": "complete file; row count and unique run IDs validated where applicable",
            "output": str(target.relative_to(ROOT)).replace("\\", "/"),
            "output_sha256": digest(target),
            "rows": len(source_rows),
        }
        if "status" in source_fields:
            entry["status_counts"] = dict(Counter(row["status"] for row in source_rows))
        entries.append(entry)

    primary_files = [
        V03_RUN / "final" / "final-package.json",
        V03_RUN / "final" / "experiment-inventory.csv",
        V03_RUN / "derived" / "statistics" / "paired-statistics.csv",
        V03_RUN / "derived" / "phase-14-validation.json",
        V03_RUN / "derived" / "phase-2-classifier-freeze.json",
        AUDIT / "randomized_exact_vs_exhaustive_120_reproducible.json",
    ]
    for index, source in enumerate(primary_files, start=1):
        entries.append(
            {
                "id": f"P{index}",
                "family": "v0.3 primary or correctness evidence",
                "role": "primary/audit evidence",
                "source": str(source.relative_to(ROOT)).replace("\\", "/"),
                "source_sha256": digest(source),
                "selection_rule": "complete validated file; no row extraction",
            }
        )

    manifest = {
        "schema_version": "1.0",
        "generated_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "policy": "v0.3 is primary; corrected controlled studies are supporting; pilots are calibration; failures are provenance; heterogeneous counts are never pooled",
        "cumulative_confirmatory_warning": {
            "source_rows": len(cumulative_rows),
            "unique_run_ids": len({row["run_id"] for row in cumulative_rows}),
            "publication_rows": 1200,
            "excluded_later_generation_rows": len(cumulative_rows) - 1200,
            "reason": "later expanded generations reuse run IDs and are not one frozen homogeneous design",
        },
        "entries": entries,
    }
    manifest_path = OUTPUT / "publication-source-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    csv_path = OUTPUT / "publication-source-manifest.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["id", "family", "role", "source", "source_sha256", "selection_rule", "output", "output_sha256", "rows", "independent_units"],
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(entries)
    print(f"Built {len(entries)} verified publication-source entries in {OUTPUT}")


if __name__ == "__main__":
    main()
