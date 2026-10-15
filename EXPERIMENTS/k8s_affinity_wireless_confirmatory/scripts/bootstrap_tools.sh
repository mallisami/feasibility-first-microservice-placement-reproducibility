#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS="$ROOT/.tools/bin"
mkdir -p "$TOOLS"
export PATH="$TOOLS:$PATH"

KIND_VERSION="v0.28.0"
KUBECTL_VERSION="v1.33.1"

need() { command -v "$1" >/dev/null 2>&1 || { echo "ERROR: required command '$1' is missing." >&2; return 1; }; }
need curl
need sha256sum
need docker

if ! docker version >/dev/null 2>&1; then
  echo "ERROR: Docker engine is not reachable from this WSL/Linux shell. Start Docker Desktop and enable WSL integration." >&2
  return 1 2>/dev/null || exit 1
fi

case "$(uname -m)" in
  x86_64|amd64) ARCH=amd64 ;;
  aarch64|arm64) ARCH=arm64 ;;
  *) echo "ERROR: unsupported architecture $(uname -m)" >&2; return 1 2>/dev/null || exit 1 ;;
esac

fetch_verified() {
  local url="$1" checksum_url="$2" out="$3" checksum_file="$4"
  if [[ -x "$out" ]]; then return 0; fi
  echo "Downloading $(basename "$out")..."
  curl -fL --retry 3 --connect-timeout 20 -o "$out.tmp" "$url"
  curl -fL --retry 3 --connect-timeout 20 -o "$checksum_file" "$checksum_url"
  local expected
  expected="$(awk '{print $1}' "$checksum_file" | tr -d '\r\n')"
  local actual
  actual="$(sha256sum "$out.tmp" | awk '{print $1}')"
  if [[ "$expected" != "$actual" ]]; then
    rm -f "$out.tmp"
    echo "ERROR: checksum mismatch for $(basename "$out")" >&2
    return 1
  fi
  mv "$out.tmp" "$out"
  chmod +x "$out"
}

fetch_verified \
  "https://github.com/kubernetes-sigs/kind/releases/download/${KIND_VERSION}/kind-linux-${ARCH}" \
  "https://github.com/kubernetes-sigs/kind/releases/download/${KIND_VERSION}/kind-linux-${ARCH}.sha256sum" \
  "$TOOLS/kind" "$TOOLS/kind.sha256"

fetch_verified \
  "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${ARCH}/kubectl" \
  "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${ARCH}/kubectl.sha256" \
  "$TOOLS/kubectl" "$TOOLS/kubectl.sha256"

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
  echo "ERROR: Python >=3.11 is required in WSL. Install Python 3.11/3.12/3.13, then rerun." >&2
  return 1 2>/dev/null || exit 1
fi

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  "$PYTHON_BIN" -m venv "$ROOT/.venv"
fi
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"
python -m pip install --disable-pip-version-check -q -r "$ROOT/requirements-runner.txt"
python -m pip check

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
echo "Bootstrap OK: $(python --version), $(kind version), kubectl $(kubectl version --client -o json | python -c 'import json,sys; print(json.load(sys.stdin)["clientVersion"]["gitVersion"])')"
