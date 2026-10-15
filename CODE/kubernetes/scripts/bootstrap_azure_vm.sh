#!/usr/bin/env bash
set -euo pipefail

KIND_VERSION="v0.33.0"
KUBECTL_VERSION="v1.37.0"
REPO_ROOT="${HOME}/mcb"

sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  ca-certificates curl docker.io git iproute2 iptables jq \
  python3-pip python3-venv socat conntrack
sudo systemctl enable --now docker
sudo usermod -aG docker "${USER}"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "${tmp_dir}"' EXIT

curl -fsSLo "${tmp_dir}/kubectl" \
  "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl"
curl -fsSLo "${tmp_dir}/kubectl.sha256" \
  "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl.sha256"
printf '%s  %s\n' "$(cat "${tmp_dir}/kubectl.sha256")" "${tmp_dir}/kubectl" | sha256sum --check
sudo install -m 0755 "${tmp_dir}/kubectl" /usr/local/bin/kubectl

curl -fsSLo "${tmp_dir}/kind-linux-amd64" \
  "https://kind.sigs.k8s.io/dl/${KIND_VERSION}/kind-linux-amd64"
curl -fsSLo "${tmp_dir}/kind.sha256" \
  "https://kind.sigs.k8s.io/dl/${KIND_VERSION}/kind-linux-amd64.sha256sum"
(cd "${tmp_dir}" && sha256sum --check kind.sha256)
sudo install -m 0755 "${tmp_dir}/kind-linux-amd64" /usr/local/bin/kind

sudo tee /etc/sysctl.d/99-mcb-kind.conf >/dev/null <<'EOF'
fs.inotify.max_user_instances=512
fs.inotify.max_user_watches=524288
EOF
sudo sysctl --system >/dev/null

python3 -m venv "${REPO_ROOT}/implementation/.venv"
"${REPO_ROOT}/implementation/.venv/bin/python" -m pip install --upgrade pip
"${REPO_ROOT}/implementation/.venv/bin/pip" install -r "${REPO_ROOT}/implementation/requirements-lock.txt"

docker --version || sudo docker --version
kind version
kubectl version --client
"${REPO_ROOT}/implementation/.venv/bin/python" --version
