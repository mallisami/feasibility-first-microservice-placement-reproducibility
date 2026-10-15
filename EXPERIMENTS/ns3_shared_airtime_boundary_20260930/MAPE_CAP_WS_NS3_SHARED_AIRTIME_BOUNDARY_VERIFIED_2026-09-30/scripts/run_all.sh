#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
python3 src/run_boundary_validation.py self-test | tee operator_logs/SELF_TEST.json
python3 src/run_boundary_validation.py run
