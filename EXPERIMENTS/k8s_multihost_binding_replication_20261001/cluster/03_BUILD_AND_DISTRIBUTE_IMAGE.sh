#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${CLUSTER_ENV:-$ROOT/cluster/cluster.env}"
[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE" >&2; exit 2; }
# shellcheck disable=SC1090
source "$ENV_FILE"
: "${WORKER_B_PRIVATE_IP:?}"; : "${WORKER_C_PRIVATE_IP:?}"; : "${SSH_USER:?}"
command -v docker >/dev/null || { echo "Docker is required on the server to build the frozen benchmark image." >&2; exit 3; }
docker info >/dev/null
IMAGE=mape-cap-multihost-bench:2026-10-01
BASE=python:3.12-slim
if ! docker image inspect "$BASE" >/dev/null 2>&1; then docker pull "$BASE"; fi
docker build --pull=false --build-arg BASE_IMAGE="$BASE" -t "$IMAGE" "$ROOT/frozen/EXPERIMENTS/k8s_affinity_wireless_confirmatory/benchmark"
mkdir -p "$ROOT/operator_logs"
TAR="$ROOT/operator_logs/benchmark-image.tar"
docker save "$IMAGE" -o "$TAR"
sudo k3s ctr images import "$TAR" >/dev/null
for IP in "$WORKER_B_PRIVATE_IP" "$WORKER_C_PRIVATE_IP"; do
  echo "Importing benchmark image on $IP"
  scp -q "$TAR" "$SSH_USER@$IP:/tmp/mcap-benchmark-image.tar"
  ssh "$SSH_USER@$IP" 'sudo k3s ctr images import /tmp/mcap-benchmark-image.tar >/dev/null && rm -f /tmp/mcap-benchmark-image.tar'
done
sha256sum "$TAR" > "$ROOT/operator_logs/benchmark-image.tar.sha256"
echo "IMAGE DISTRIBUTION COMPLETE"
