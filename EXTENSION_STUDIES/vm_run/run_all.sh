#!/bin/bash
# Unattended sequential chain for the 2026-09-26 revision experiments on the Azure VM.
#   N5 (live, ~2.5 h)  ->  N4 (offline solver scaling, ~3 h)
# Strictly sequential so that no live measurement shares the CPU with solver runs.
# Resumable: every phase skips completed cells/rows, so re-running this script is safe.
set -u
BASE="$HOME/revision_2026-09-26"
PY="$BASE/venv/bin/python"
LOG="$BASE/run_all.log"
STATUS="$BASE/STATUS.txt"
N5_EXPECTED=100   # S1: 20 graphs x 3 arms + S2: 10 graphs x 4 arms

exec 9>"$BASE/.run_all.lock"
if ! flock -n 9; then echo "another run_all.sh is active; exiting"; exit 0; fi

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { echo "[$(ts)] $*" | tee -a "$LOG"; }
status() { echo "$(ts) $*" > "$STATUS"; log "STATUS: $*"; }

cluster_ready() {
  for i in $(seq 1 20); do
    nr=$(kubectl --context kind-rev-n5 get nodes --no-headers 2>/dev/null | awk '$2!="Ready"' | wc -l)
    tot=$(kubectl --context kind-rev-n5 get nodes --no-headers 2>/dev/null | wc -l)
    if [ "$tot" -eq 4 ] && [ "$nr" -eq 0 ]; then return 0; fi
    log "rev-n5 not ready (nodes=$tot notready=$nr); waiting 30 s ($i/20)"; sleep 30
  done
  return 1
}

n5_count() { find "$BASE/N5/results/cells" -name result.json 2>/dev/null | wc -l; }

status "started"
log "host=$(hostname) load=$(cut -d' ' -f1-3 /proc/loadavg) mem_avail_MB=$(free -m | awk '/Mem:/{print $7}')"

# ---------------- N5 ----------------
status "N5 running"
if cluster_ready; then
  for attempt in 1 2 3; do
    have=$(n5_count)
    [ "$have" -ge "$N5_EXPECTED" ] && break
    log "N5 pass $attempt (accepted cells so far: $have/$N5_EXPECTED)"
    (cd "$BASE/N5" && "$PY" n5_runner.py run >> "$BASE/N5/run.log" 2>&1)
    log "N5 pass $attempt exited with code $?"
    cluster_ready || { log "cluster not ready after pass $attempt"; break; }
  done
else
  log "rev-n5 cluster never became ready; N5 skipped"
fi
log "N5 finished with $(n5_count)/$N5_EXPECTED accepted cells"
status "N5 done ($(n5_count)/$N5_EXPECTED cells); N4 running"

# ---------------- N4 ----------------
for attempt in 1 2 3; do
  [ -f "$BASE/N4/results/N4_DONE.json" ] && break
  log "N4 pass $attempt"
  (cd "$BASE/N4" && "$PY" n4_runner.py >> "$BASE/N4/run.log" 2>&1)
  log "N4 pass $attempt exited with code $?"
done
n4rows=$( [ -f "$BASE/N4/results/n4_rows.csv" ] && tail -n +2 "$BASE/N4/results/n4_rows.csv" | wc -l || echo 0)
log "N4 finished with $n4rows rows (expected 280)"

# ---------------- integrity ----------------
(cd "$BASE" && find N5/results N4/results -type f ! -name '*.tmp' -print0 | sort -z | xargs -0 sha256sum > RESULTS_SHA256SUMS.txt)
status "ALL DONE: N5 $(n5_count)/$N5_EXPECTED cells, N4 $n4rows/280 rows"
