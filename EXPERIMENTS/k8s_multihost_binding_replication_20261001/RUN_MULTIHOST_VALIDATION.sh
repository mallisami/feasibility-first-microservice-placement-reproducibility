#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
[[ -f cluster/cluster.env ]] || { echo "Missing cluster/cluster.env. Complete cluster setup first; see 00_START_HERE.md" >&2; exit 2; }
command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 3; }
command -v kubectl >/dev/null || { echo "kubectl is required on the server" >&2; exit 3; }
if [[ ! -d .venv ]]; then
  python3 -m venv .venv || { echo "python3 venv unavailable. On Ubuntu install python3-venv, then rerun." >&2; exit 4; }
fi
source .venv/bin/activate
python -m pip install --upgrade pip >/dev/null
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python src/multihost_runner.py setup
python src/multihost_runner.py pilot
python src/multihost_runner.py science
python src/analyze_multihost.py
python tools/package_results.py
echo
echo "COMPLETE. Return the newest results/run-*.zip for independent audit."
