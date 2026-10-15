# ANALYSIS: Post-Hoc Confirmatory Decomposition

This directory contains the executable post-hoc analysis scripts and derived results referenced in the manuscript (§4.1) and Electronic Supplementary Material (§S-4, Table 10 and Table 11).

## Contents

- `posthoc_weakness1.py`: Executable standard-library Python script. Reads the accepted analysis tables from the Kubernetes and ns-3 confirmatory campaigns, decomposes the paired graph-level performance into committed (28 graphs) and abstained (2 graphs: seeds 44013, 44020) strata, verifies all published point estimates, and outputs machine-readable CSV and JSON summaries.
- `derived/`:
  - `kubernetes_seed_matched_decomposition_original.csv`: Seed-matched paired differences for original Kubernetes confirmatory run.
  - `ns3_seed_matched_decomposition_original.csv`: Seed-matched paired differences for original ns-3 confirmatory run.
  - `kubernetes_seed_matched_decomposition_postfix.csv`: Seed-matched paired differences for post-fix Kubernetes confirmatory run.
  - `ns3_seed_matched_decomposition_postfix.csv`: Seed-matched paired differences for post-fix ns-3 confirmatory run.
  - `posthoc_decomposition_summary.json`: Consolidated machine-readable statistical summary.

## Execution

No external dependencies are required; runs under standard Python 3.10+:

```bash
python ANALYSIS/posthoc_weakness1.py
```
