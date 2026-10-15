# Legacy research-file retention audit

Source archive: `MAPE-CAP-WS_reproducibility_package_2026-09-26.zip`

Scope: every file under `RESULTS/`, `EXPERIMENTS/`, `EXTENSION_STUDIES/`, `CODE/`, `ANALYSIS/`, and `runbooks/` in the September 26 archive (with `implementation/` renamed to `CODE/` and `EXTENSION_STUDIES/2026-09-26/` flattened directly under `EXTENSION_STUDIES/`).

- Historical research-side files in scope: **13,134**
- Release-facing index files intentionally synchronized to the unified release: **4**
- Historical files verified against `provenance/LEGACY_RESEARCH_SHA256SUMS_2026-09-26.txt`: **13,130**
- Missing historical files: **0**
- SHA-256 mismatches among those files: **0**
- Status: **PASS**

The four intentionally synchronized index files are:

- `RESULTS/EXPERIMENT_INDEX.md`
- `RESULTS/KEY_OUTPUTS.md`
- `RESULTS/README.md`
- `RESULTS/RESULTS_INDEX.csv`

These files are navigation indexes rather than raw observations or executed experiment code. Top-level release documentation and `runbooks/` are synchronized with the unified directory layout (`CODE/` and `EXTENSION_STUDIES/`), while manuscript files (`PAPER/`) are excluded from the reproducibility package. Post-September-26 experiments (shared-airtime boundary study, three-host k3s replication, and E1/E2/E3 validation campaigns) are additive and are verified separately by `tools/verify_package.py`.

The exact historical hash list is `provenance/LEGACY_RESEARCH_SHA256SUMS_2026-09-26.txt`.
