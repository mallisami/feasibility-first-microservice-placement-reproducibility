#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="${CLUSTER_ENV:-$HERE/cluster.env}"
[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE. Copy cluster.env.example to cluster.env and fill private IPs." >&2; exit 2; }
# shellcheck disable=SC1090
source "$ENV_FILE"
: "${SERVER_PRIVATE_IP:?SERVER_PRIVATE_IP required}"
K3S_VERSION="${K3S_VERSION:-v1.33.1+k3s1}"
if command -v k3s >/dev/null 2>&1; then
  echo "k3s already exists; refusing to modify an existing cluster automatically." >&2
  echo "If this is the intended fresh server, remove the old k3s installation manually first." >&2
  exit 3
fi
curl -sfL https://get.k3s.io | sudo env INSTALL_K3S_VERSION="$K3S_VERSION" sh -s - server \
  --node-name rack-a \
  --node-ip "$SERVER_PRIVATE_IP" \
  --node-label mape-cap-ws/rack=rack-a \
  --node-label mape-cap-ws/role=server \
  --node-label topology.kubernetes.io/zone=rack-a \
  --write-kubeconfig-mode 644 \
  --disable traefik \
  --disable servicelb
mkdir -p "$HOME/.kube"
sudo cp /etc/rancher/k3s/k3s.yaml "$HOME/.kube/config"
sudo chown "$(id -u):$(id -g)" "$HOME/.kube/config"
chmod 600 "$HOME/.kube/config"
mkdir -p "$(dirname "$HERE")/operator_private"
sudo cat /var/lib/rancher/k3s/server/node-token > "$(dirname "$HERE")/operator_private/node-token"
chmod 600 "$(dirname "$HERE")/operator_private/node-token"
echo "SERVER INSTALLED. Private join token saved locally under operator_private/node-token (do not publish it)."
kubectl get nodes -o wide
