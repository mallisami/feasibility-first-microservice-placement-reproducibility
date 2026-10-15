#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

if [[ -e PREEXECUTION_SHA256SUMS.txt ]]; then
  echo "Refusing to overwrite existing PREEXECUTION_SHA256SUMS.txt" >&2
  exit 1
fi

python3 VERIFY_PACKAGE.py
TMP="$(mktemp)"
find . -type f \
  ! -path './E1_ns3_persistent_degradation/results/*' \
  ! -path './E1_ns3_persistent_degradation/operator_logs/*' \
  ! -path './E2_scale_admission/results/*' \
  ! -path './E2_scale_admission/smoke_results/*' \
  ! -path './E3_published_score_replay/results/*' \
  ! -path './E3_published_score_replay/smoke_results/*' \
  ! -name 'PREEXECUTION_SHA256SUMS.txt' \
  ! -name 'RUN_ALL.log' \
  ! -name 'POSTRUN_INVENTORY.txt' \
  -print0 | sort -z | xargs -0 sha256sum > "$TMP"
{
  echo "# PRE-EXECUTION FREEZE MANIFEST"
  echo "# UTC: $(date -u +'%Y-%m-%dT%H:%M:%SZ')"
  echo "# No science result was present when VERIFY_PACKAGE.py passed."
  cat "$TMP"
} > PREEXECUTION_SHA256SUMS.txt
rm -f "$TMP"
echo "Created PREEXECUTION_SHA256SUMS.txt"
