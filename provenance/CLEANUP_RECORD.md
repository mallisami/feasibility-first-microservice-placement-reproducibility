# Synchronization / cleanup record — October 2026 unified release

This release was built from the September 26 reproducibility archive and unified with all post-manuscript and frozen validation campaigns.

Removed from the active code/data reproducibility package:

- manuscript and compiled publication files (`PAPER/`), which are archived separately outside the code/data reproducibility package;
- historical working drafts and competing paper-review/audit documents;
- redundant uncompressed `snrValues.csv` per-packet intermediate files from E1 (retaining all scientific summaries and the complete compressed `RETURN_NEW_EXPERIMENTS_20261003.tar.gz` archive).

Added/unified:

- frozen v1.1 shared-airtime execution package and complete accepted run (`run-20260930T163137Z`);
- frozen three-host Kubernetes replication package and complete accepted run (`run-20261001T151036Z`);
- completed frozen validation campaigns E1 (627 primary unique group cells; 2,061 science simulations + 18 calibration runs), E2 (600 scale admission cells), and E3 (published node-scoring heuristic replay across 150 graphs × 4 loads);
- independent result audits under `ANALYSIS/`;
- updated evidence scope, claim map, reviewer workflow, and package verifier (`tools/verify_package.py`).
