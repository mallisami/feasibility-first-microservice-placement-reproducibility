# Complete-release QA — October 2026 unified release

## Scope

QA of `MAPE_CAP_WS_REPRODUCIBILITY_PACKAGE` containing the baseline historical research archive, the completed shared-airtime boundary study, the completed three-host Kubernetes replication, and the completed E1, E2, and E3 validation campaigns.

## Verified before release manifest generation

- Manuscript files (`PAPER/`) are excluded from the reproducibility package as requested.
- 13,130 historical research files across `RESULTS/`, `EXPERIMENTS/`, `EXTENSION_STUDIES/`, `CODE/`, `ANALYSIS/`, and `runbooks/` pass SHA-256 verification against `provenance/LEGACY_RESEARCH_SHA256SUMS_2026-09-26.txt`.
- N2/N3 and N2c critical mechanism evidence passes the package verifier.
- Shared-airtime run: 18/18 calibration and 108/108 science cells; internal SHA-256 manifest passes; primary values match the independent audit.
- Multi-host run: 6/6 pilot and 60/60 science cells; zero failed science attempts; internal 82-entry SHA-256 manifest passes; requested placements equal observed pod-node placements; all science cells use at least two VM/Kubernetes hosts.
- Three distinct multi-host InternalIPs and three distinct machine-ID SHA-256 hashes are retained in setup evidence.
- E1 persistent degradation run: 627 primary unique group cells across 3 RNG seeds (1,881 primary group-cell runs) plus 60 boundary-sweep cells across 3 RNG seeds (180 sweep runs), totaling 2,061 science simulations + 18 calibration runs; H1 supported ($p = 5.96 \times 10^{-8}$).
- E2 scale admission run: 600 evaluated cells across 150 graphs at scales $n \in \{12, 16, 24\}$ and four load levels.
- E3 published node-scoring heuristic replay: 150 graphs × 4 load levels × 4 variants verified.
- Exact source archives for all external studies are retained under `provenance/source_archives/` and match recorded SHA-256 hashes.

## Known boundaries retained rather than hidden

- The shared-airtime run archive did not contain its execution-machine `LAST_PREPARE.json`, duty-gate and smoke operator-log directories; they are not reconstructed.
- Neither ns-3 nor the multi-host Kubernetes run constitutes physical multi-rack 60-GHz RF validation.
