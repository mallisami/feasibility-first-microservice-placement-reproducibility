#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PYTHON="${PYTHON:-python3}"
"$PYTHON" generate_conceptual_figures.py
"$PYTHON" generate_v03_figures.py
"$PYTHON" generate_affinity_feasibility_tradeoff.py
"$PYTHON" generate_r1_forest.py
"$PYTHON" generate_multiscenario_forest.py
"$PYTHON" generate_v137_followup_p95.py
"$PYTHON" generate_abstention_fix_comparison.py
echo "ALL_FIGURES_REGENERATED"
