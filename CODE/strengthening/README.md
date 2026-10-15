# Post-review strengthening experiments

This directory adds **new experiments only**. It does not mutate the frozen v0.3 R1–R8 evidence. All results are written to `RESULTS/strengthening/<timestamp>/`.

## Why the IDs are `S-E*`

The historical repository audit already used `E1` and `E2` for infrastructure prechecks. Reviewer-requested experiments therefore use a separate `S-E*` namespace so old provenance remains unambiguous.

## One-command sequential execution

From `implementation/`:

```bash
python strengthening/run_strengthening_campaign.py
```

This launches, in order:

1. **S-E1** — full B+ LNS planner in the live dynamic loop (5 sequences × 11 windows).
2. **S-E4** — native kube-scheduler topology-spread baseline vs B+ Exact (9 conditions × 5 paired replicates × 2 methods).
3. **S-E5** — live same-service multi-replica placement (frontend + productcatalogservice, stable/degraded, 5 replicates).
4. **S-GRACE** — immediate relocation vs recovery-horizon grace guard at 5/15/60-s recovery horizons.
5. **S-E2** — replicated R4 subset (storage × cache × network, medium state, loaded, 3 replicates = 36 cells).
6. **S-E3** — eight genuinely new ns-3/WiGig trace identities × seeds 101–103.

The optional **S-MILP** matched-heuristic comparison is not run unless `--include-milp` is supplied because it needs `pyscipopt` (a free, license-free SCIP build; no separate license or registration required).

The orchestrator intentionally **does not run phases in parallel**. Before S-E3 it stops the running Kind containers to release Docker RAM, runs ns-3, and starts those same containers again. Use `--keep-kind-running-for-ns3` only on a host with ample RAM.

## Selective execution

```bash
python strengthening/run_strengthening_campaign.py --only S-E1-live-full-planner,S-E2-r4-replicated-subset
python strengthening/run_strengthening_campaign.py --only S-MILP-matched-heuristics --include-milp
python strengthening/run_strengthening_campaign.py --dry-run
```

## Preflight images

```bash
python strengthening/image_preflight.py --groups online_boutique,r4 --pull-missing
python strengthening/image_preflight.py --groups ns3
```

The frozen repository contains `RESULTS/primary/v03-20260811T151500Z/raw/phase-6-boutique-images.tar`, which can be loaded with `docker load -i ...` and contains the ten Online Boutique service images plus `redis:7-alpine`. The loadgenerator image is not in that archive and may need to be pulled separately.

The ns-3 image is local (`ns3-wigig:v0.3-full`). If missing, build it from the pinned simulator tree using the v0.3 Dockerfile before S-E3.

## What remains future work

`E6` physical 60-GHz hardware and `E7` production multi-rack deployment are deliberately not automated here. They require hardware/infrastructure outside the current evidence scope and are not submission blockers if the manuscript keeps its present scope statement.

## Post-processing after successful runs

After all requested experiments finish, run:

```bash
python strengthening/postprocess_strengthening.py ../RESULTS/strengthening/<run-id>
```

It produces a separate strengthening-experiment paired-test/Holm family. It intentionally does **not** silently merge new tests into the frozen v0.3 multiplicity family; that decision must be made when the manuscript is updated.
