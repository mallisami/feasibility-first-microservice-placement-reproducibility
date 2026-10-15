"""Append-only evidence and checkpoint primitives for the v0.3 campaign."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def new_run_id(prefix: str = "v03") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{prefix}-{stamp}-p{os.getpid()}"


def create_run_root(base: Path, run_id: str | None = None) -> Path:
    """Create a new run root and refuse to reuse an existing identity."""
    root = base.resolve() / (run_id or new_run_id())
    root.mkdir(parents=True, exist_ok=False)
    for name in ("raw", "checkpoints", "logs", "derived", "manifests"):
        (root / name).mkdir()
    return root


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def atomic_write_csv(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    materialized = list(rows)
    if not materialized:
        raise ValueError("refusing to write an empty evidence CSV")
    fields: list[str] = []
    for row in materialized:
        for key in row:
            if key not in fields:
                fields.append(key)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(materialized)
    os.replace(temporary, path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_manifest(root: Path, destination: Path) -> None:
    entries = []
    for path in sorted(p for p in root.rglob("*") if p.is_file() and p != destination):
        entries.append(f"{sha256(path)}  {path.relative_to(root).as_posix()}")
    atomic_write_text(destination, "\n".join(entries) + "\n")


def _docker_info() -> dict[str, Any]:
    command = ["docker", "info", "--format", "{{json .}}"]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=20)
        if completed.returncode != 0:
            return {"available": False, "error": completed.stderr.strip()}
        doc = json.loads(completed.stdout)
        return {
            "available": True,
            "memory_bytes": int(doc.get("MemTotal", 0)),
            "cpus": int(doc.get("NCPU", 0)),
            "driver": doc.get("Driver"),
        }
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        return {"available": False, "error": str(exc)}


def resource_snapshot(storage_path: Path) -> dict[str, Any]:
    usage = shutil.disk_usage(storage_path)
    snapshot: dict[str, Any] = {
        "timestamp_utc": utc_now(),
        "storage_path": str(storage_path.resolve()),
        "disk_total_bytes": usage.total,
        "disk_free_bytes": usage.free,
        "docker": _docker_info(),
    }
    try:
        import psutil  # type: ignore

        memory = psutil.virtual_memory()
        snapshot["host_memory_total_bytes"] = int(memory.total)
        snapshot["host_memory_available_bytes"] = int(memory.available)
    except ImportError:
        snapshot["host_memory_note"] = "psutil unavailable; host memory gate must be supplied by the orchestrator"
    return snapshot


def assert_resource_gate(
    snapshot: Mapping[str, Any], *, min_disk_gib: float, min_host_available_gib: float = 0.0,
    min_docker_gib: float = 0.0,
) -> None:
    gib = 1024**3
    failures = []
    if int(snapshot["disk_free_bytes"]) < min_disk_gib * gib:
        failures.append(f"free disk is below {min_disk_gib:.1f} GiB")
    host_available = snapshot.get("host_memory_available_bytes")
    if min_host_available_gib and host_available is not None and int(host_available) < min_host_available_gib * gib:
        failures.append(f"available host memory is below {min_host_available_gib:.1f} GiB")
    docker = snapshot.get("docker", {})
    if min_docker_gib and (not docker.get("available") or int(docker.get("memory_bytes", 0)) < min_docker_gib * gib):
        failures.append(f"Docker memory is below {min_docker_gib:.1f} GiB or unavailable")
    if failures:
        raise RuntimeError("resource gate failed: " + "; ".join(failures))

