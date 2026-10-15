# N2/N3 results (run 2026-09-26)

Reproduction gate: 2700/2700 AFF-C cells (Current, Affinity-Bytes, MAPE-CAP-WS at six targets)
reproduced exactly — feasibility, cross-rack bytes (at scaled payload) and objective.
Environment: WSL Ubuntu 24.04, Python 3.12.3, numpy 2.3.5, scipy 1.17.0, pandas 2.2.3, PYTHONHASHSEED=0.

## Pre-registered primary tests (target 1.25, n = 150 graphs, Holm across 3)
| Test | Estimate (MAPE-CAP-WS − Affinity+Admission) | 95% CI | p (Holm) |
|---|---|---|---|
| N2-P(a) planning headroom | −0.139 (median −0.075; 106 non-zero pairs) | [−0.168, −0.111] | 1.6e−14 |
| N2-P(b) cross-rack bytes | +2.92e8 B | [+2.42e8, +3.44e8] | 1.2e−18 |
| N3-P held-out admissibility | 41.3% vs 22.0% (38 vs 9 discordant) | RD +0.193 [+0.107, +0.273] | 2.5e−5 |

Identical placements: 44/150.

Reading: on the planning states, admission-constrained affinity is the leaner placement (more
headroom, fewer bytes). MAPE-CAP-WS spends bytes and headroom to lower modeled delay
(expected 4429 vs 5652; CVaR 9123 vs 10327 request-ms) and is admissible on more withheld states.
Risk-off MAPE-CAP-WS is worst on held-out states (21/150), so the CVaR term drives the N3 gain.

## Secondary: mechanism (protocol-listed per-state breakdown)
At the primary target 1.25, all held-out differences arise in one withheld state
(outage-with-fallback, B–C down); on the other four withheld states every admission-constrained
method is 150/150 at 1.25. (Corrected 2026-09-26: at targets 0.9–1.1 the mixed-regime state has one
to three exceptions for Affinity+Admission or Risk-off, so the statement does not hold "at every
target ≤ 1.25" as first written.)

## N3b — POST HOC outage-rotation sensitivity (declared after N3 was seen)
Graphs admissible when the named rack pair is down (planning placements unchanged):

| target | method | A–B down | A–C down | B–C down | mean |
|---|---|---|---|---|---|
| 0.50 | Affinity+Admission | 21 | 36 | 49 | 35.3 |
| 0.50 | MAPE-CAP-WS | 7 | 126 | 114 | 82.3 |
| 1.25 | Affinity+Admission | 7 | 29 | 33 | 23.0 |
| 1.25 | Risk-off | 0 | 25 | 21 | 15.3 |
| 1.25 | MAPE-CAP-WS | 0 | 72 | 62 | 44.7 |
| 1.50 | Affinity+Admission | 4 | 17 | 22 | 14.3 |
| 1.50 | MAPE-CAP-WS | 1 | 34 | 25 | 20.0 |

Interpretation: tail-weighted ranking concentrates inter-rack traffic on the pair that is best in
the worst planning state (A–B in persistent degradation). This protects against outages of the
other pairs and fails on all graphs when the favoured pair fails. The held-out gain is therefore
conditional on which link fails; failures that matter must be placed in the admission set.

## Regime curve (fine grid 0.50–2.00, `fine_grid.csv`)
Used for the primary regime figure: admissibility of Current / Affinity-Bytes / admission-
constrained methods versus load, plus "locality-induced inadmissibility" (Current admissible,
Affinity-Bytes not): 1 graph at 0.90, 7 at 1.00.
