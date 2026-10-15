# Gap-closure evidence (2026-09-11/12)

New evidence collected to address the open items flagged in
`PAPER/SCIENTIFIC_COMPLETION_CHECKLIST.md` and `PAPER/ISSUE_RESOLUTION_MATRIX.md`.
This directory is append-only alongside `RESULTS/primary` and
`RESULTS/strengthening`; nothing here overwrites frozen evidence.

## 1. Latency x goodput crossed sensitivity (VALIDATION_PROTOCOL Stage G)

`gap-r9-latgood-20260910T190004593531Z-p12924/`

The one experiment family with no prior driver at all. New script
`implementation/code/run_v03_r9_latency_goodput_sensitivity.py` independently
crosses low/nominal/high latency and goodput perturbations (+/-15%) around
each of the 8 frozen effective wireless states used by R6, holding outage and
airtime semantics fixed, and re-solves the B+ placement/relocation decision
(ExpectedValue and BPlus-CVaR-0.90) at each of the 9 grid points per state.

- 144/144 grid cells solved (8 states x 9 grid points x 2 methods).
- Overall feasibility-stability rate: 1.0.
- Overall placement/relocate-decision stability rate: 0.979.
- One exception: `recovery` state under BPlus-CVaR-0.90 is only 0.667 stable
  (2 of 9 grid points diverge from the nominal decision) -- see
  `derived/phase-9-latency-goodput-stability.json`.

This closes the previously fully-missing experiment family.

## 2. Relocation-cost calibration re-power

`relocation-calibration-repower-20260911T012259Z/` (+ `run_relocation_calibration_repower.sh`)

16 additional create-ready-remove relocation measurements via the existing
`measure_rolling_relocation.py`, alternating target node among the 3 kind
workers, adding to the original 4+4 pilot measurements
(`RESULTS/calibration/external/relocation-pilot-kind-2026-08-07` and
`uncached-relocation`). n=16, mean rollout 16.9s, stdev 6.6s (see
`summary.json`).

**Limitation, disclosed:** this sandbox has no outbound container-registry
access from inside kind node containers (proxyconnect refused to the
sandbox's own egress proxy), so a genuine "uncached" relocation (one that
requires a real image pull) cannot be exercised here. All 16 new
measurements are "cached" replicates; the "uncached" stratum still rests on
only the original 4 pilot measurements. This strengthens the cached stratum
only -- it does not fully close the "independently calibrate... relocation
cost" open item, which still needs an environment with real registry access
for the uncached side.

## 3. Extended live full-planner sequences (S-E1 gap-closure)

Same run root as above: `gap-closure-20260911T011711866992Z-p10652/raw/S-E1-live-full-planner/`
and `derived/S-E1-extended-summary.json` / `S-E1-extended-sequences-6-10.csv`.

The original S-E1 (`RESULTS/strengthening/`) ran 5 live sequences / 7 replan
opportunities, all rejected by the frozen economic gate -- the paper's
central open item ("observe... the outcome of an accepted complete-planner
relocation"). Per `VALIDATION_PROTOCOL.md`'s integration rule, the gate,
detector, and formulation are not retuned. Instead, 5 new sequences
(ids 6-10, added to `SEQUENCES` in `implementation/code/run_v03_r3.py`) were
run live against the same unmodified gate, to test whether more trials
change the outcome.

**Finding:** all 5 new replan opportunities were rejected, with
`net_benefit` deterministically `-9567.33` every time the
persistent-degradation regime triggered a replan. This is because the R1
condition -> scenario mapping (`build_problem` / `scenarios_for`) is fixed
per condition label, not randomized per sequence seed -- so new sequences
replicate rather than resample the underlying economics. Combined with the
original 5 sequences, this is now **10 sequences / 12 replan opportunities,
all rejected** -- a reproducible, structural negative result under the
current frozen regime definitions and relocation-cost calibration, not a
sampling artifact of the original 5-sequence run. Observing an accepted
full-planner relocation would require either a new controlled regime
definition with a materially larger benefit-to-relocation-cost ratio (a
scope decision for the authors, since it touches the CONDITIONS taxonomy)
or a lower calibrated relocation cost from a re-powered calibration (see
item 2) -- neither of which this gap-closure session changed, consistent
with not retuning the frozen formulation post hoc.

## Infra notes for reproducing this locally

- Requires a `mape-cap-bplus` kind cluster (1 control-plane + 3 workers,
  `implementation/kubernetes/kind-cluster-config.yaml`) with Online Boutique
  v0.10.1 + the `online-boutique-otel-v03.yaml` + `online-boutique-loadgen.yaml`
  manifests applied, and the `mape-cap-bplus-pilot` namespace +
  `relocation-echo.yaml` applied.
- In a sandboxed/offline Docker environment, `imagePullPolicy: Always` in
  the manifests will fail (no registry egress from kind node containers);
  patch affected deployments to `IfNotPresent` and pre-import images via
  `docker save <image> | docker exec -i <node> ctr -n k8s.io images import -`
  for each node.
- Under CPU-constrained hosts, the stock JVM-service readiness/liveness
  probes (1s timeout) and `run_v03_r1.py`'s `frontend_probe` (originally a
  hard 10s subprocess timeout with no exception handling) are too tight;
  this session loosened probe timeouts on the live Deployments and patched
  `frontend_probe` to treat a probe timeout as a failed sample rather than
  a crash (see git diff on `implementation/code/run_v03_r1.py`). Neither
  change touches scientific gate/formulation constants.
