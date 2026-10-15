#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$ROOT/EXPERIMENTS/k8s_affinity_wireless_confirmatory/RUN_CONFIRMATORY_WSL.sh"
