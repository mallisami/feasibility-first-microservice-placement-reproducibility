#!/usr/bin/env bash
# Additional relocation-calibration replicates (S-GAP2): re-powers the
# frozen 4+4 relocation-pilot calibration (RESULTS/calibration/external/
# relocation-pilot-kind-2026-08-07 and uncached-relocation), which
# PAPER/SCIENTIFIC_COMPLETION_CHECKLIST.md and VALIDATION_PROTOCOL.md Stage A
# flag as underpowered (n=4 per stratum). Adds N more create-ready-remove
# measurements, alternating cached/uncached image state and target node,
# using the existing measure_rolling_relocation.py script unmodified.
set -euo pipefail
cd "$(dirname "$0")/../.."
OUT_DIR="RESULTS/gap-closure/relocation-calibration-repower-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$OUT_DIR"
IMAGE="hashicorp/http-echo:1.0.0"
IMAGE_SIZE=4631705
NODES=(mape-cap-bplus-worker mape-cap-bplus-worker2 mape-cap-bplus-worker3)
N=${1:-16}

# NOTE: this sandboxed environment has no outbound registry access from
# inside kind node containers (proxyconnect refused; see gap-closure notes),
# so a genuine "uncached" (registry-pull) relocation cannot be exercised
# here. All replicates below are run "cached" (image pre-imported on the
# target node via `docker save | ctr images import` before relocation),
# strengthening only the cached stratum of the frozen pilot calibration.
# The uncached stratum remains only the original 4 pilot measurements.
for i in $(seq 1 "$N"); do
  current_node=$(kubectl -n mape-cap-bplus-pilot get pods -l app=relocation-echo -o jsonpath='{.items[0].spec.nodeName}')
  target=""
  for n in "${NODES[@]}"; do
    if [ "$n" != "$current_node" ]; then target="$n"; break; fi
  done
  cached=true
  docker save "$IMAGE" | docker exec -i "$target" ctr -n k8s.io images import - >/dev/null 2>&1 || true
  out="$OUT_DIR/measurement-$(printf '%02d' "$i")-$cached.json"
  echo "[$i/$N] target=$target cached=$cached"
  python implementation/kubernetes/scripts/measure_rolling_relocation.py \
    --target-node "$target" --output "$out" \
    --failed-requests 0 --image-cached "$cached" --image-size-bytes "$IMAGE_SIZE" \
    --timeout-seconds 180
done
echo "wrote $N measurements under $OUT_DIR"
