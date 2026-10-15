#!/usr/bin/env bash
set -euo pipefail
RACK_ID="${RACK_ID:-}"
SERVER_PRIVATE_IP="${SERVER_PRIVATE_IP:-}"
THIS_PRIVATE_IP="${THIS_PRIVATE_IP:-}"
K3S_VERSION="${K3S_VERSION:-v1.33.1+k3s1}"
[[ "$RACK_ID" == "rack-b" || "$RACK_ID" == "rack-c" ]] || { echo "RACK_ID must be rack-b or rack-c" >&2; exit 2; }
: "${SERVER_PRIVATE_IP:?SERVER_PRIVATE_IP required}"
: "${THIS_PRIVATE_IP:?THIS_PRIVATE_IP required}"
if [[ -z "${K3S_TOKEN:-}" ]]; then
  read -rsp "Paste k3s server node token: " K3S_TOKEN; echo
  export K3S_TOKEN
fi
if command -v k3s >/dev/null 2>&1; then
  echo "k3s already exists; refusing to modify an existing worker automatically." >&2
  exit 3
fi
curl -sfL https://get.k3s.io | sudo env \
  INSTALL_K3S_VERSION="$K3S_VERSION" \
  K3S_URL="https://${SERVER_PRIVATE_IP}:6443" \
  K3S_TOKEN="$K3S_TOKEN" \
  sh -s - agent \
  --node-name "$RACK_ID" \
  --node-ip "$THIS_PRIVATE_IP" \
  --node-label "mape-cap-ws/rack=$RACK_ID" \
  --node-label "mape-cap-ws/role=worker" \
  --node-label "topology.kubernetes.io/zone=$RACK_ID"
echo "WORKER $RACK_ID INSTALLED. Return to the server and run kubectl get nodes -o wide."
