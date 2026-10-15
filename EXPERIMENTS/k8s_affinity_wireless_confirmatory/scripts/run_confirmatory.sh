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

echo "=== MAPE-CAP B+ Kubernetes Confirmatory Experiment v1.1 (SSOT release) ==="
echo "UTC start: $(date -u +%FT%TZ)"

echo "[1/9] Bootstrapping pinned tools and Python environment"
# shellcheck disable=SC1091
source "$EXP_ROOT/scripts/bootstrap_tools.sh"

echo "[2/9] Verifying complete single-source-of-truth repository"
python "$REPO_ROOT/tools/verify_package.py"

echo "[3/9] Verifying confirmatory experiment SSOT structure"
python "$EXP_ROOT/tools/verify_release.py"

echo "[4/9] Running automated confirmatory QA tests"
pytest -q -p no:cacheprovider "$EXP_ROOT/tests"

echo "[5/9] Running local scientific self-test"
python "$EXP_ROOT/src/live_confirmatory.py" self-test | tee "$EXP_ROOT/operator_logs/self-test-${STAMP}.json"

echo "[6/9] Running full held-out offline planning audit (no live outcomes)"
python "$EXP_ROOT/src/live_confirmatory.py" offline-audit > "$EXP_ROOT/operator_logs/offline-audit-${STAMP}.json"
python - "$EXP_ROOT/operator_logs/offline-audit-${STAMP}.json" <<'PY2'
import json,sys
j=json.load(open(sys.argv[1])); r=j['rows']
print('Offline audit:', len(r), 'seeds;',
      'Affinity feasible', sum(x['affinity_feasible'] for x in r),
      'B+ feasible', sum(x['bplus_feasible'] for x in r),
      'B+ abstentions', sum(x['bplus_abstained'] for x in r))
PY2

echo "[7/9] Checking Docker/Kubernetes preflight and preparing cluster"
python "$EXP_ROOT/src/live_confirmatory.py" preflight | tee "$EXP_ROOT/operator_logs/preflight-${STAMP}.json"
python "$EXP_ROOT/src/live_confirmatory.py" prepare | tee "$EXP_ROOT/operator_logs/prepare-${STAMP}.json"

echo "[8/9] Running/resuming the frozen confirmatory campaign"
python "$EXP_ROOT/src/live_confirmatory.py" run

echo "[9/9] Re-running analysis and verifying result manifest"
RUN_REL="$(cat "$EXP_ROOT/results/CURRENT_RUN.txt")"
RUN_ROOT="$EXP_ROOT/$RUN_REL"
python "$EXP_ROOT/src/live_confirmatory.py" analyze --run-root "$RUN_ROOT"
(
  cd "$RUN_ROOT"
  sha256sum -c SHA256SUMS.txt
)

echo "=== COMPLETE ==="
echo "Results: $RUN_ROOT"
echo "Primary result: $RUN_ROOT/PRIMARY_RESULT.json"
echo "Final report: $RUN_ROOT/FINAL_REPORT.md"
echo "Operator log: $LOG"
