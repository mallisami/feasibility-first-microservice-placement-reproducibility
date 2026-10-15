#!/usr/bin/env python3
"""Autonomous resume-supervisor for the Experiment 2 (S-E6) confirmatory
campaign in F:\\Papers\\New experiment repo final\\e2-instrumented.

Repeatedly invokes the existing, unmodified
implementation/strengthening/run_se6_external_scheduler.py against the
frozen protocol recorded in FROZEN_PROTOCOL.json, always with
--keep-external-scheduler so the already-installed NetworkOverhead
scheduler-plugins release + CRDs are never torn down -- meaning no
outbound internet access is required for any resume after the first
successful attempt (which, in this campaign, has already happened: the
scheduler-plugins deployment and CRDs are already live in the cluster).

The underlying script already refuses to repeat a cell whose result.json
has accepted_evidence == true (see main()'s "Resuming saved cell" path),
so this supervisor never re-executes accepted cells; it only classifies
failures and decides whether to retry (local/transient) or stop and
report (protocol-integrity problem or an unrecoverable blocker).

Exit codes: 0 = target reached, summary generated.
            1 = unrecoverable blocker (needs user action).
            3 = protocol-integrity problem (frozen protocol violated).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

RUN_ROOT = Path(__file__).resolve().parent
REPO = Path("F:/Papers/New experiment repo final/New experiment repo final/New experiment repo/JOURNAL_REPRODUCIBILITY_REPOSITORY")
SCRIPT = REPO / "implementation" / "strengthening" / "run_se6_external_scheduler.py"
FROZEN_PATH = RUN_ROOT / "FROZEN_PROTOCOL.json"
OUT = RUN_ROOT / "raw" / "S-E6-external-scheduler"
PROGRESS = OUT / "progress.json"
BLOCKED = OUT / "S-E6_BLOCKED_OR_FAILED.json"
DERIVED_SUMMARY = RUN_ROOT / "derived" / "S-E6-summary.json"
STATUS = RUN_ROOT / "supervisor-status.json"

KUBE_CONTEXT = "kind-mape-cap-bplus"
TARGET_CELLS = 48
MAX_ATTEMPTS = 80
BASE_BACKOFF = 20.0
MAX_BACKOFF = 300.0
STUCK_THRESHOLD = 5  # consecutive attempts with zero net progress + same failure reason

TRANSIENT_PATTERNS = [
    r"timed out", r"timeout", r"TLS handshake timeout", r"Unable to connect to the server",
    r"paging file is too small", r"connection refused", r"EOF", r"i/o timeout",
    r"rollout timeout", r"command failed \(-?\d+\)", r"context deadline exceeded",
    r"Docker is unavailable", r"kubectl cannot reach a cluster", r"another strengthening campaign is already running",
]


def now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def status_write(payload: dict) -> None:
    payload["updated_utc"] = now()
    STATUS.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def next_log_index() -> int:
    existing = [int(m.group(1)) for p in RUN_ROOT.glob("resume*.stdout.log")
                if (m := re.match(r"resume(\d+)\.stdout\.log", p.name))]
    return (max(existing) + 1) if existing else 2


def protocol_snapshot(frozen: dict) -> dict:
    return {
        "methods": frozen["methods"], "conditions": frozen["conditions"],
        "matched_replicates": frozen["matched_replicates"],
        "measurement_seconds_per_cell": frozen["measurement_seconds_per_cell"],
        "bplus_gate_changed": frozen.get("bplus_gate_changed"),
    }


def scan_accepted_cells_for_integrity(frozen_conditions: set[str], frozen_replicates: int, frozen_methods_dirs: set[str]) -> list[str]:
    problems = []
    if not OUT.exists():
        return problems
    for result_path in OUT.glob("*/replicate-*/*/result.json"):
        condition = result_path.parents[2].name
        rep_dir = result_path.parents[1].name
        method_dir = result_path.parent.name
        if condition not in frozen_conditions:
            problems.append(f"accepted cell under unfrozen condition {condition!r}: {result_path}")
        m = re.match(r"replicate-(\d+)", rep_dir)
        if not m or not (1 <= int(m.group(1)) <= frozen_replicates):
            problems.append(f"accepted cell under out-of-range replicate {rep_dir!r}: {result_path}")
        if method_dir not in frozen_methods_dirs:
            problems.append(f"accepted cell under unfrozen method {method_dir!r}: {result_path}")
        row = load_json(result_path)
        if row is not None and row.get("accepted_evidence"):
            app = row.get("application", {})
            if app.get("requests") is not None and app["requests"] < 500:
                problems.append(f"accepted cell below minimum_accepted_completed_requests: {result_path}")
    return problems


def classify(reason: str) -> str:
    for pattern in TRANSIENT_PATTERNS:
        if re.search(pattern, reason, re.IGNORECASE):
            return "transient"
    return "unknown"


def docker_kubectl_ready(timeout_s: float = 120.0) -> bool:
    env = {**os.environ, "KUBE_CONTEXT": KUBE_CONTEXT}
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            d = subprocess.run(["docker", "info", "--format", "{{json .}}"], capture_output=True, text=True, timeout=20)
            k = subprocess.run(["kubectl", "--context", KUBE_CONTEXT, "get", "nodes"], capture_output=True, text=True, timeout=20)
            if d.returncode == 0 and k.returncode == 0:
                return True
        except Exception:
            pass
        time.sleep(5)
    return False


def main() -> int:
    frozen = load_json(FROZEN_PATH)
    if frozen is None:
        status_write({"status": "PROTOCOL_INTEGRITY_PROBLEM", "reason": "FROZEN_PROTOCOL.json missing or unreadable"})
        print("PROTOCOL INTEGRITY PROBLEM: FROZEN_PROTOCOL.json missing or unreadable.", file=sys.stderr)
        return 3
    reference = protocol_snapshot(frozen)

    conditions = ",".join(frozen["conditions"])
    replicates = int(frozen["matched_replicates"])
    duration = int(frozen["measurement_seconds_per_cell"])
    # Frozen protocol methods list includes BPlus-Exact; this supervisor's
    # mandate is only the 48 Native + NetworkOverhead cells (2 methods x 3
    # conditions x 8 replicates = 48), so BPlus-Exact is intentionally
    # excluded from --methods without altering FROZEN_PROTOCOL.json itself.
    cli_methods = "Native,External"
    method_dirs_frozen = {"Native", "External-NetworkOverhead"}
    conditions_set = set(frozen["conditions"])

    integrity_problems = scan_accepted_cells_for_integrity(conditions_set, replicates, method_dirs_frozen)
    if integrity_problems:
        status_write({"status": "PROTOCOL_INTEGRITY_PROBLEM", "problems": integrity_problems})
        print("PROTOCOL INTEGRITY PROBLEM in already-accepted cells:", file=sys.stderr)
        for p in integrity_problems:
            print(" -", p, file=sys.stderr)
        return 3

    backoff = BASE_BACKOFF
    stuck_streak = 0
    last_reason = None
    last_completed = -1

    for attempt in range(1, MAX_ATTEMPTS + 1):
        # Re-check protocol integrity every attempt: catches any external
        # edit to FROZEN_PROTOCOL.json mid-campaign.
        frozen_now = load_json(FROZEN_PATH)
        if frozen_now is None or protocol_snapshot(frozen_now) != reference:
            status_write({"status": "PROTOCOL_INTEGRITY_PROBLEM",
                          "reason": "FROZEN_PROTOCOL.json changed or disappeared mid-campaign",
                          "original": reference, "observed": protocol_snapshot(frozen_now) if frozen_now else None})
            print("PROTOCOL INTEGRITY PROBLEM: frozen protocol changed mid-campaign.", file=sys.stderr)
            return 3

        progress = load_json(PROGRESS) or {"completed": 0}
        completed_before = int(progress.get("completed", 0))
        if completed_before >= TARGET_CELLS and DERIVED_SUMMARY.exists():
            summary = load_json(DERIVED_SUMMARY)
            if summary and summary.get("cells", 0) >= TARGET_CELLS and summary.get("all_evidence_accepted"):
                status_write({"status": "COMPLETE", "cells": summary["cells"], "summary": str(DERIVED_SUMMARY)})
                print(json.dumps({"status": "COMPLETE", "summary": summary}, indent=2))
                return 0

        if not docker_kubectl_ready():
            status_write({"status": "RETRYING", "attempt": attempt, "reason": "docker/kubectl not ready before attempt"})
            time.sleep(backoff)
            backoff = min(backoff * 1.5, MAX_BACKOFF)
            continue

        idx = next_log_index()
        stdout_log = RUN_ROOT / f"resume{idx}.stdout.log"
        stderr_log = RUN_ROOT / f"resume{idx}.stderr.log"
        cmd = [sys.executable, str(SCRIPT), str(RUN_ROOT),
               "--replicates", str(replicates), "--duration-seconds", str(duration),
               "--conditions", conditions, "--methods", cli_methods,
               "--keep-external-scheduler"]
        env = {**os.environ, "KUBE_CONTEXT": KUBE_CONTEXT}
        status_write({"status": "RUNNING", "attempt": attempt, "log": stdout_log.name, "completed_before": completed_before})
        with stdout_log.open("w", encoding="utf-8") as so, stderr_log.open("w", encoding="utf-8") as se:
            try:
                proc = subprocess.run(cmd, cwd=str(REPO), env=env, stdout=so, stderr=se, timeout=3600 * 3)
                returncode = proc.returncode
            except subprocess.TimeoutExpired:
                returncode = -1
                se.write("\n[supervisor] subprocess exceeded 3h attempt timeout; treating as transient and retrying.\n")

        progress_after = load_json(PROGRESS) or {"completed": 0}
        completed_after = int(progress_after.get("completed", 0))
        made_progress = completed_after > completed_before

        if returncode == 0:
            summary = load_json(DERIVED_SUMMARY)
            if summary and summary.get("cells", 0) >= TARGET_CELLS and summary.get("all_evidence_accepted"):
                status_write({"status": "COMPLETE", "cells": summary["cells"], "summary": str(DERIVED_SUMMARY)})
                print(json.dumps({"status": "COMPLETE", "summary": summary}, indent=2))
                return 0
            # Exit 0 but methods list narrower than target (e.g. resumed run
            # ended early some other way) -- loop again defensively.
            backoff = BASE_BACKOFF
            stuck_streak = 0
            continue

        blocked = load_json(BLOCKED)
        reason = blocked.get("reason", "") if blocked else stderr_log.read_text(encoding="utf-8", errors="replace")[-2000:]
        kind = classify(reason)

        if made_progress:
            backoff = BASE_BACKOFF
            stuck_streak = 0
            last_reason = reason
            last_completed = completed_after
            continue

        if kind != "transient":
            # Unrecognized failure with no forward progress: could be a real
            # bug or an environment condition outside the known transient
            # set. Give it one more look before escalating.
            stuck_streak += 1
        elif reason == last_reason and completed_after == last_completed:
            stuck_streak += 1
        else:
            stuck_streak = 1
        last_reason = reason
        last_completed = completed_after

        if stuck_streak >= STUCK_THRESHOLD:
            status_write({
                "status": "BLOCKED", "reason": reason, "classification": kind,
                "attempt": attempt, "completed": completed_after, "target": TARGET_CELLS,
                "note": f"{stuck_streak} consecutive attempts with no forward progress",
            })
            print(f"UNRECOVERABLE BLOCKER after {stuck_streak} stuck attempts: {reason}", file=sys.stderr)
            return 1

        time.sleep(backoff)
        backoff = min(backoff * 1.5, MAX_BACKOFF)

    status_write({"status": "BLOCKED", "reason": f"exceeded MAX_ATTEMPTS={MAX_ATTEMPTS} without reaching target",
                  "completed": last_completed, "target": TARGET_CELLS})
    print(f"UNRECOVERABLE: exceeded {MAX_ATTEMPTS} attempts without reaching {TARGET_CELLS} cells.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
