#!/usr/bin/env bash
set -euo pipefail
if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <interface>" >&2
  exit 2
fi
if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "Must run as root" >&2
  exit 1
fi
tc qdisc del dev "$1" root 2>/dev/null || true
