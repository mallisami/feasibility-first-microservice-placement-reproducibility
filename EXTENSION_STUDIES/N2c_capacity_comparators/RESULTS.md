# N2c results — capacity-aware affinity comparators (post hoc, protocol frozen before computation)

Run 2026-09-26 in WSL (Python 3.12.3, numpy 2.3.5, pandas 2.2.3; PYTHONHASHSEED=0). Script `run_n2c.py`
imports the frozen N2/N3 code unchanged.

Checks:
- The reconstructed full-model utilization matches the evaluator's for every candidate placement (max relative error 6e-16).
- The reproduction gate against N2/N3 (Affinity-Bytes and Affinity-Bytes+Admission admissibility at the six primary loads) has 0 mismatches.

## Binding constraint (independent check, `binding_groups` analysis)
| τ | graphs where Affinity-Bytes is inadmissible | violated planning-state groups | max conflict-dense (multi-pair) util |
|---|---|---|---|
| 1.00 | 7 | persistent-degradation cg-ac 5, cg-bc 1, cg-ab 1 | 0.705 |
| 1.25 | 24 | persistent-degradation cg-ac 14, cg-ab 8, cg-bc 2 | 0.881 |
| 1.50 | 42 | persistent-degradation cg-ab 20, cg-ac 17, cg-bc 5; partial-blockage cg-ac 5; conflict-dense cg-shared 3 | 1.057 |

Each persistent-degradation / partial-blockage group covers the two directions of one rack pair; only
conflict-dense has a group shared by several rack pairs.

## Comparators: graphs (of 150) admissible under the full MAPE-CAP-WS constraints
| τ | Affinity-Bytes | +LinkCap (a) | +PairAirtime (b) | +Admission (full) |
|---|---|---|---|---|
| 0.50 | 150 | 150 | 150 | 150 |
| 0.90 | 149 | 149 | 150 | 150 |
| 1.00 | 143 | 143 | 150 | 150 |
| 1.10 | 138 | 138 | 150 | 150 |
| 1.25 | 126 | 126 | 150 | 150 |
| 1.50 | 108 | 108 | 142 | 143 |

- **(a) Directed per-link capacity at the full state-dependent link rate.** It selects the same placement as Affinity-Bytes in 4,649 of the 4,650 graph × load cells (fine grid 0.50–2.00). The one exception is at τ = 2.0. It therefore prevents none of the violations.
- **(b) Half-duplex per-pair airtime budget.**
  - Its selections are identical to full admission on every graph up to τ = 1.30.
  - From τ = 1.35 the multi-pair conflict-dense group starts to bind: (b) admits placements that violate only that group on 2 graphs at 1.35, 3 at 1.40, 4 at 1.45 and 7 at 1.50. The count keeps rising at higher loads.

## Reading
In this library the violations come from state-dependent airtime budgets below the link rate that both
directions of a degraded rack pair share. A per-link rate-capacity model does not capture them; a per-pair
airtime budget does. For byte-affinity ranking, coupling across different rack pairs (the multi-pair form
of the conflict-group constraint) matters only from τ ≈ 1.35 upward. The paper's claims are sized accordingly.

## Addendum 2026-09-26: audit check (post hoc)
A second audit asked whether the last statement also holds for MAPE-CAP-WS's own ranking.
`audit_check_risk_ranking.py` answers this; its results are in `AUDIT_CHECK.md` and `audit_check_cells.csv`.
Its gates reproduce the published MAPE-CAP-WS placements in 900/900 cells and the N2c byte-affinity
selections in 13,950/13,950 cells.
- **MAPE-CAP-WS ranking with per-pair budgets only.** It exceeds the multi-pair conflict-dense budget on
  1 graph at τ = 1.20, 3 at τ = 1.25 (seeds 11037, 33008, 33024; 1.45, 1.03, 1.07 of the budget),
  5 at τ = 1.30 and 23 at τ = 1.50. Every one of these graphs has an admissible placement up to τ = 1.30.
- **MAPE-CAP-WS's own placements.** They reach 0.998 of the multi-pair budget at τ = 1.25, against
  0.881 for Affinity-Bytes. The multi-pair statement above therefore applies to byte-affinity ranking only.
- **Unshared per-direction budget.** Giving each direction the pair's budget without sharing it still
  leaves 21 of 24 Affinity-Bytes violations at τ = 1.25 (6 of 7 at τ = 1.0). Direction sharing is what binds.
- **(b)'s multi-pair violators.** They sit on graphs with no admissible placement in 2/2 cases at
  τ = 1.35, 3/3 at 1.40, 3/4 at 1.45 and 6/7 at 1.50.
