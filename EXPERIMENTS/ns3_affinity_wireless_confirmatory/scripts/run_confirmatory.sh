#!/usr/bin/env bash
set -euo pipefail
EXP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$EXP_ROOT/../.." && pwd)"
cd "$EXP_ROOT"
export PYTHONDONTWRITEBYTECODE=1
mkdir -p operator_logs
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="$EXP_ROOT/operator_logs/operator-${STAMP}.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== MAPE-CAP B+ ns-3/WiGig Packet-Level Confirmation v1.1 ==="
echo "UTC start: $(date -u +%FT%TZ)"
echo "IMPORTANT: run after, not concurrently with, the Kubernetes campaign on the same machine."

# shellcheck disable=SC1091
source "$EXP_ROOT/scripts/bootstrap_tools.sh"

echo "[1/8] Verifying complete SSOT repository"
python "$REPO_ROOT/tools/verify_package.py"

echo "[2/8] Verifying packet-level experiment release"
python "$EXP_ROOT/tools/verify_release.py"

echo "[3/8] Running automated packet-level QA tests"
pytest -q -p no:cacheprovider "$EXP_ROOT/tests"

echo "[4/8] Running frozen scientific self-test"
python "$EXP_ROOT/src/ns3_confirmatory.py" self-test | tee "$EXP_ROOT/operator_logs/self-test-${STAMP}.json"

echo "[5/8] Running complete offline planning/rate audit (no packet outcomes)"
python "$EXP_ROOT/src/ns3_confirmatory.py" offline-audit > "$EXP_ROOT/operator_logs/offline-audit-${STAMP}.json"
python - "$EXP_ROOT/operator_logs/offline-audit-${STAMP}.json" <<'PY2'
import json,sys
j=json.load(open(sys.argv[1]))
print("Offline packet plan:", j["planned_packet_level_cells"], "cells; max stream", round(j["max_stream_mbps"],3), "Mbps; max total", round(j["max_total_offered_mbps"],3), "Mbps; B+ abstention rows", j["bplus_abstention_rows"])
PY2

echo "[6/8] Building/verifying pinned ns-3/WiGig images and running real six-stream packet smoke gate"
python "$EXP_ROOT/src/ns3_confirmatory.py" prepare | tee "$EXP_ROOT/operator_logs/prepare-${STAMP}.json"

echo "[7/8] Running/resuming 540-cell packet-level campaign"
python "$EXP_ROOT/src/ns3_confirmatory.py" run

echo "[8/8] Re-analyzing, refreshing, and verifying run manifest"
RUN_REL="$(cat "$EXP_ROOT/results/CURRENT_RUN.txt")"
RUN_ROOT="$EXP_ROOT/$RUN_REL"
python "$EXP_ROOT/src/ns3_confirmatory.py" analyze --run-root "$RUN_ROOT"
(
  cd "$RUN_ROOT"
  sha256sum -c SHA256SUMS.txt
)

echo "=== COMPLETE ==="
echo "Results: $RUN_ROOT"
echo "Primary result: $RUN_ROOT/PRIMARY_RESULT.json"
echo "Final report: $RUN_ROOT/FINAL_REPORT.md"
echo "Operator log: $LOG"
