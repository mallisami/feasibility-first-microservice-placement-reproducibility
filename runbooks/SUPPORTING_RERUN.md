# Supporting controlled-study reruns

The supporting datasets used by the study are already frozen under `RESULTS/supporting/raw/` and `RESULTS/supporting/canonical/`. These studies are supporting evidence and are not pooled with the primary v0.3 R1-R8 campaign.

New reruns write to `RESULTS/supporting/reproduced/` so the frozen supplied evidence is never overwritten.

From the repository root:

```bash
python CODE/code/run_confirmatory_campaign.py
python CODE/code/run_app_c_campaign.py
python CODE/code/run_relocation_sensitivity.py
python CODE/code/run_multi_interval_dynamic.py
python CODE/code/run_full_campaign.py
python CODE/code/confirmatory_statistics.py
python CODE/code/app_c_statistics.py
```

The common simulation-backed trace inputs used by these supporting studies are retained under `RESULTS/calibration/external/`.

To rebuild the reconciled supporting source selection from the retained raw datasets:

```bash
python CODE/code/build_reconciled_publication_sources.py
python CODE/code/generate_reconciled_paper_assets.py
```
