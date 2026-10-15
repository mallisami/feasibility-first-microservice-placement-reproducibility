# MAPE-CAP-WS E2 scale-admission result audit

Protocol: `mape-cap-ws-scale-admission-v1.0`
Platform: 4-vCPU Ubuntu 24.04 LTS VM (CPython 3.12.3)

## Execution integrity
- Evaluated larger problem instances at scales $n \in \{12, 16, 24\}$ replicas (50 graphs per scale = 150 graphs) across four load levels ($\tau \in \{1.0, 1.1, 1.25, 1.5\}$).
- 150 problem instances generated, solved, and recorded under `results/graphs/`.
- `results/scale_cells.csv` records all 600 graph-load cell outcomes with solver timings, admission decisions, and objective evaluations.
- Provenance recorded in `results/provenance.json` with SHA-256 hashes of runner and protocol.
- Exit code 0, 0 deviations.

## Key findings
- Evaluates feasibility preservation and solution-time scaling of MAPE-CAP-WS versus heuristic and affinity baselines as replica count grows from 12 to 24 across four load levels.
- Supports solver scalability under LNS decomposition across the tested scales and move budgets.
- Demonstrates that explicit shared-airtime admission avoids the avoidable rack-pair group overloads incurred by unconstrained affinity ranking across the evaluated scale instances where admissible placements exist.
