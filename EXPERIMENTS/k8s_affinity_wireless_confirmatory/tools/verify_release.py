#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
from pathlib import Path

EXP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EXP_ROOT.parents[1]


def fail(msg: str) -> None:
    raise SystemExit(f"CONFIRMATORY RELEASE VERIFICATION FAILED: {msg}")


def main() -> int:
    required = [
        "README.md", "RUN_CONFIRMATORY.ps1", "RUN_CONFIRMATORY_WSL.sh",
        "config/experiment.json", "config/kind-cluster-config.yaml",
        "protocol/LIVE_CONFIRMATORY_PROTOCOL_FROZEN.md", "src/live_confirmatory.py", "src/affinity_exact.py",
        "benchmark/benchmark_service.py", "benchmark/wireless_medium.py", "benchmark/bench_control.py",
        "benchmark/medium_control.py", "benchmark/Dockerfile", "requirements-runner.txt",
        "scripts/bootstrap_tools.sh", "scripts/run_confirmatory.sh", "tests/test_confirmatory_release.py",
    ]
    for rel in required:
        if not (EXP_ROOT / rel).is_file():
            fail(f"missing required file: {rel}")

    canonical_trace = REPO_ROOT / "RESULTS/calibration/external/ns3_simulation_backed_traces.csv"
    canonical_solver = REPO_ROOT / "implementation/code/mape_cap_bplus"
    if not canonical_trace.is_file():
        fail("canonical wireless trace is missing from repository RESULTS")
    if not canonical_solver.is_dir():
        fail("canonical mape_cap_bplus source is missing from implementation/code")

    # SSOT guards: no duplicated planner package, no copied trace, no superseded/amendment protocol tree, no nested archives.
    forbidden = [
        EXP_ROOT / "src/mape_cap_bplus",
        EXP_ROOT / "config/ns3_simulation_backed_traces.csv",
        EXP_ROOT / "protocol/history",
        EXP_ROOT / "protocol/PREEXECUTION_PROTOCOL_AMENDMENT.md",
        EXP_ROOT / "protocol/PREEXECUTION_SHARED_MEDIUM_QA_AMENDMENT.md",
        EXP_ROOT / "provenance",
    ]
    for path in forbidden:
        if path.exists():
            fail(f"single-source-of-truth violation: stale/duplicated path exists: {path.relative_to(EXP_ROOT)}")
    nested = [p for p in EXP_ROOT.rglob("*.zip") if p.is_file()]
    if nested:
        fail("nested package archive(s) present: " + ", ".join(str(p.relative_to(EXP_ROOT)) for p in nested))

    cfg = json.loads((EXP_ROOT / "config/experiment.json").read_text())
    if cfg.get("protocol_id") != "wireless-beyond-affinity-k8s-v1.1":
        fail("protocol_id is not frozen v1.1")
    if cfg.get("network_emulation_mode") != "shared-medium-proxy":
        fail("network emulation mode is not shared-medium-proxy")
    if cfg.get("held_out_seeds") != list(range(44001, 44031)):
        fail("held-out seed block changed")
    if cfg.get("specificity_seeds") != list(range(44001, 44006)):
        fail("specificity seed block changed")
    if cfg.get("methods") != ["Current", "Affinity-Bytes", "BPlus-Exact"]:
        fail("method set/order changed")
    if cfg.get("kind_version") != "v0.28.0" or cfg.get("kubectl_version") != "v1.33.1":
        fail("pinned Kubernetes tool versions changed")
    if "@sha256:" not in str(cfg.get("kind_node_image")):
        fail("kind node image is not digest-pinned")

    protocol = (EXP_ROOT / "protocol/LIVE_CONFIRMATORY_PROTOCOL_FROZEN.md").read_text(encoding="utf-8")
    for phrase in [
        "scheduled-request completion fraction", "shared-medium",
        "claim physical 60-GHz/RF interference measurement", "44001", "44030",
        "Incorporated pre-execution QA corrections",
    ]:
        if phrase.lower() not in protocol.lower():
            fail(f"canonical frozen protocol missing phrase: {phrase}")

    bad = []
    for path in EXP_ROOT.rglob("*"):
        if any(part in {".venv", ".tools", "results", "operator_logs"} for part in path.relative_to(EXP_ROOT).parts):
            continue
        if path.is_dir() and path.name == "__pycache__":
            bad.append(str(path.relative_to(EXP_ROOT)))
        elif path.is_file() and path.suffix in {".pyc", ".pyo"}:
            bad.append(str(path.relative_to(EXP_ROOT)))
    if bad:
        fail("cache artifacts present: " + ", ".join(bad[:10]))

    for base in (EXP_ROOT / "src", EXP_ROOT / "benchmark", EXP_ROOT / "tools", EXP_ROOT / "tests"):
        for py in sorted(base.rglob("*.py")):
            try:
                ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
            except SyntaxError as exc:
                fail(f"Python syntax error in {py.relative_to(EXP_ROOT)}: {exc}")

    print(json.dumps({
        "passed": True,
        "protocol_id": cfg["protocol_id"],
        "required_files": len(required),
        "canonical_planner_path": str(canonical_solver.relative_to(REPO_ROOT)),
        "canonical_trace_path": str(canonical_trace.relative_to(REPO_ROOT)),
        "ssot_guards": "passed",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
