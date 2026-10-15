#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p operator_logs results
python3 src/build_plan.py --check | tee operator_logs/PLAN_CHECK.txt
python3 src/run_pd_validation.py self-test | tee operator_logs/SELF_TEST.json
python3 src/run_pd_validation.py run "$@" 2>&1 | tee -a operator_logs/RUN.log
