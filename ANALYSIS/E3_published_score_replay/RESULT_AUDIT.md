# MAPE-CAP-WS E3 published-score replay result audit

Protocol: `mape-cap-ws-score-replay-v1.0`
Rule verification: Checked against Marchese & Tomarchio published node-scoring formulation (`FULLTEXT_RULE_VERIFICATION.md`)
Platform: 4-vCPU Ubuntu 24.04 LTS VM (CPython 3.12.3)

## Execution integrity
- Replay across all 150 controlled graphs under four load levels: $\tau \in \{1.0, 1.1, 1.25, 1.5\}$.
- Four heuristic scoring variants evaluated: `capped`, `capped_fixed_order`, `capped_requests`, and `uncapped`.
- All 150 graphs × 4 load levels × 4 variants evaluated (2,400 decision points across 600 graph-load cells).
- Full provenance recorded in `results/provenance.json` and cell-level outcomes in `results/score_replay_cells.csv`.
- Summary stored in `results/SUMMARY.json` and human-readable report in `results/RESULTS.md`.

## Key findings
- Direct evaluation of the published node-scoring baseline shows systematic violations under shared directional airtime constraints:
  - At load 1.0 (150 graphs): Affinity-Bytes produces 7 violations; Marchese–Tomarchio variants produce up to 35 violations.
  - At load 1.1 (150 graphs): Affinity-Bytes produces 12 violations; Marchese–Tomarchio variants produce up to 54 violations.
  - At load 1.25 (150 graphs): Affinity-Bytes produces 24 violations; Marchese–Tomarchio variants produce up to 79 violations.
  - At load 1.5 (150 graphs): Affinity-Bytes produces 42 violations; Marchese–Tomarchio variants produce up to 110 violations.
- Demonstrates that node-scoring heuristics lacking explicit directional shared-airtime admission incur frequent avoidable group-budget violations under load, whereas admission-aware placement enforces shared-airtime feasibility across all evaluated instances where an admissible placement exists.
