#!/usr/bin/env bash
# Execute E1 + E2 + E3 on a 4-vCPU Ubuntu VM without overlapping the E1/E2 science phases.
# This script sets execution order only; scientific parameters are defined inside the frozen protocols/configs.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

python3 VERIFY_PACKAGE.py --frozen

test -f PREEXECUTION_SHA256SUMS.txt || {
  echo "PREEXECUTION_SHA256SUMS.txt is missing. Run: bash FREEZE_PREEXECUTION.sh" >&2
  exit 1
}

mkdir -p E1_ns3_persistent_degradation/operator_logs E1_ns3_persistent_degradation/results
python3 E1_ns3_persistent_degradation/tests/test_pipeline.py | tail -1

# Stage 1: E1 image build/smoke/duty preparation uses little CPU while E2 uses three workers.
(
  cd E1_ns3_persistent_degradation
  python3 src/run_pd_validation.py prepare > operator_logs/PREPARE_STAGE1.log 2>&1
) &
PREP=$!

(
  cd E2_scale_admission
  python3 run_scale.py run --workers 3
)

if ! wait "$PREP"; then
  echo "E1 prepare failed. Preserve and inspect E1_ns3_persistent_degradation/operator_logs/PREPARE_STAGE1.log" >&2
  exit 1
fi

# Stage 2: E1 science gets all four CPUs. The prepare step is repeated quickly from the cached image.
(
  cd E1_ns3_persistent_degradation
  bash scripts/run_all.sh --workers 4
)

# Stage 3: E3 is inexpensive and runs only after E1/E2 are complete.
(
  cd E3_published_score_replay
  python3 run_score_replay.py run
)

python3 POSTRUN_INVENTORY.py > POSTRUN_INVENTORY.txt

echo "ALL THREE EXPERIMENTS COMPLETED"
echo "Return the whole folder, including PREEXECUTION_SHA256SUMS.txt, RUN_ALL.log, POSTRUN_INVENTORY.txt, all results, and operator logs."
