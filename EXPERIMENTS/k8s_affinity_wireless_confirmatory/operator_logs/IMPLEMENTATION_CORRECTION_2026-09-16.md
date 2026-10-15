# Implementation correction — 2026-09-16

## What was wrong
`src/live_confirmatory.py`, function `apply_placement` (line 505), called:

```
kubectl rollout status deployment -n <ns> --all --timeout=<N>s
```

`kubectl rollout status` has never accepted an `--all` flag for a bare
`deployment` resource type in any kubectl release, including the frozen
pinned version `v1.33.1` (`config/experiment.json`). Every smoke-gate
attempt (seed 44001, target 0.50) failed with:

```
error: unknown flag: --all
```

This is a CLI-syntax defect in the orchestration/implementation code. It
does not touch any frozen scientific parameter (seeds, methods, targets,
risk/relocation weights, wireless traces, load anchor, retry limits,
statistical tests, or evidence boundary).

## What was changed
`apply_placement` now waits on each deployment named in the placement
individually (`kubectl rollout status deployment/<name> -n <ns>
--timeout=<remaining>s`), looping over `problem.replicas` against the same
overall `max_rollout_seconds` deadline that previously bounded the single
`--all` call. Net effect: still blocks until every deployment in the
placement is rolled out (or the shared deadline is exceeded), with the same
timeout budget as before — only the kubectl invocation syntax changed.

## Provenance
- File: `EXPERIMENTS/k8s_affinity_wireless_confirmatory/src/live_confirmatory.py`
- Old SHA-256: `1c1cfad195727a9cfc8399d44b90d3879593b78a2b9add6e651d9aa44ea8f8d5`
- New SHA-256: `15a1b6ef23add662b6dccdc81eb0d0b4fe7a8fafbe47260e62ab4e5acff906b7`
- `SHA256SUMS.txt` entry for this file updated to the new hash, same line,
  same path.
- Failed attempts preserved, not deleted:
  `results/run-20260916T051604Z/smoke/target-0.50/seed-44001/Current/attempt-01/failure.json`
  `results/run-20260916T051604Z/smoke/target-0.50/seed-44001/Current/attempt-02/failure.json`
- Authorized by user request and by the run instructions themselves
  (`CODEX_PROMPT_RUN_ALL_CONFIRMATORY.txt`): "diagnose and correct only
  environment or implementation defects that do not alter the scientific
  treatment ... document every correction before resuming."
