#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
need() { command -v "$1" >/dev/null 2>&1 || { echo "ERROR: required command '$1' is missing." >&2; return 1; }; }
need docker
need sha256sum
if ! docker version >/dev/null 2>&1; then
  echo "ERROR: Docker engine is not reachable. Start Docker Desktop and enable WSL integration." >&2
  return 1 2>/dev/null || exit 1
fi
choose_python() {
  local c
  for c in python3.13 python3.12 python3.11 python3; do
    if command -v "$c" >/dev/null 2>&1; then
      if "$c" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3,11) else 1)
PY
      then echo "$c"; return 0; fi
    fi
  done
  return 1
}
PYTHON_BIN="$(choose_python || true)"
if [[ -z "$PYTHON_BIN" ]]; then
  echo "ERROR: Python >=3.11 is required in WSL." >&2
  return 1 2>/dev/null || exit 1
fi
if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  "$PYTHON_BIN" -m venv "$ROOT/.venv"
fi
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"
python -m pip install --disable-pip-version-check -q -r "$ROOT/requirements-runner.txt"
python -m pip check
export PYTHONPATH="$ROOT/src:$ROOT/../k8s_affinity_wireless_confirmatory/src:$ROOT/../../implementation/code${PYTHONPATH:+:$PYTHONPATH}"
echo "Bootstrap OK: $(python --version), $(docker --version)"
