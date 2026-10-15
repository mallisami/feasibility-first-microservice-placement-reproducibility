# Full v0.3 rerun

The frozen primary results are already supplied. A full rerun is optional and requires the external Kubernetes/Docker/ns-3 prerequisites documented in `../ENVIRONMENT.md`, `RESULTS/audit/` (environment captures) and `CODE/kubernetes/`. Never overwrite `RESULTS/primary/v03-20260811T151500Z/`; create a new run ID.

## 1. Initialize a new run

From the repository root:

```bash
python CODE/code/run_v03_campaign.py init --run-id <new-run-id>
```

The command prints/creates the new run root. Use that path as `<RUN_ROOT>` below.

## 2. Execute phases in campaign order

```bash
python CODE/code/capture_v03_infrastructure.py <RUN_ROOT>
python CODE/code/run_v03_correctness_gate.py <RUN_ROOT>
python CODE/code/run_v03_classifier.py <RUN_ROOT>
python CODE/code/run_v03_r6.py <RUN_ROOT>
python CODE/code/run_v03_r8.py <RUN_ROOT>
python CODE/code/run_v03_r5_ns3.py <RUN_ROOT>
python CODE/code/capture_v03_phase6.py <RUN_ROOT>
python CODE/code/run_v03_r2.py <RUN_ROOT>
python CODE/code/validate_v03_r2.py <RUN_ROOT>
python CODE/code/run_v03_r1.py <RUN_ROOT>
python CODE/code/run_v03_r3.py <RUN_ROOT>
python CODE/code/run_v03_r4.py <RUN_ROOT>
python CODE/code/run_v03_r7.py <RUN_ROOT>
python CODE/code/run_v03_postprocess.py <RUN_ROOT> all
```

The declared sequential campaign configuration is `CODE/config/campaign/v03_sequential_campaign.json`. Use that file as the authoritative phase/order reference if command-line options need to be adjusted for the target machine.

## 3. R5 repair/retry scripts

Do **not** run the R5 repair/retry utilities by default. They are retained because repaired/failed attempts form part of the frozen provenance. Use them only when a newly executed R5 campaign fails its declared acceptance gate.

## 4. External assets

- R5 uses the pinned WiGig/ns-3 source under `CODE/kubernetes/simulator/wigig-module/`.
- R7 uses the retained DeathStarBench deployment/workload assets under `CODE/kubernetes/deathstarbench/` plus the Kubernetes manifests in `CODE/kubernetes/manifests/`.
- Cluster/environment snapshots for the frozen run are in `CODE/environment/` and `RESULTS/audit/`.

## 5. Validate a new run

After post-processing, inspect the new run's `final/`, `derived/`, and run-local SHA-256 manifest. Do not mix a new rerun with the supplied frozen v0.3 evidence.
