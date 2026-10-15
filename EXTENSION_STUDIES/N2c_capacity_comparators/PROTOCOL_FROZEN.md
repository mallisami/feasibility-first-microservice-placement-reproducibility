# N2c — Capacity-aware affinity comparators on the 150-graph set

**Freeze:** 2026-09-26, written before any N2c comparator outcome is computed.
**Evidence class:** offline controlled computation, **motivated post hoc**. An audit of N1/N2 found that
every Affinity-Bytes airtime violation at loads 1.0 and 1.25 overloads a single rack pair's
(two-direction) group in persistent degradation, and that the multi-pair conflict-dense group
binds only at load 1.5 (3 graphs). N2c quantifies what that implies for capacity-aware
comparators. The binding-group fact was known when this protocol was written; the comparator
selections and their admissibility were not.

## Question
Reviewers asked for an "Affinity + per-link capacity (MUMIPLOP-style)" baseline. Which part of the
MAPE-CAP-WS admission constraint does the evaluated library actually exercise?
(a) a directed per-link capacity at full link rate over the window (no airtime budget, directions
    independent — the usual per-link capacity model);
(b) a state-aware, half-duplex per-rack-pair airtime budget (both directions of a pair share the
    pair's budget; no coupling across different rack pairs);
(full) the MAPE-CAP-WS admission constraint (b plus the multi-pair group of the conflict-dense state).

## Instances, states, load (unchanged from N2/N3)
AFF-C 150 graphs (6/7/8 replicas, seeds 11001–11050, 22001–22050, 33001–33050), 3 racks × 1 node,
planning states conflict-dense, partial-blockage, persistent-degradation from
`ns3_simulation_backed_traces.csv`, T_w = 60 s, payload scaled so Current's worst planning
utilization equals τ. Grid: τ ∈ {0.50, 0.90, 1.00, 1.10, 1.25, 1.50} and the fine grid 0.50–2.00 (0.05).
Candidate set: the N2/N3 cluster-feasible placements that pass the AFF-C non-airtime screen.

## Comparators (all minimize cross-rack bytes; ties: fewer moves, then lexicographic key)
- **Affinity-Bytes+LinkCap (a):** subject to, for every planning state ω and every available
  directed rack pair (r,s): bits_rs / G_rs^ω ≤ T_w.
- **Affinity-Bytes+PairAirtime (b):** subject to, for every planning state ω and every unordered
  rack pair {r,s}: bits_rs/G_rs^ω + bits_sr/G_sr^ω ≤ B_{r,s}^ω, where B is the pair's own group budget
  in partial blockage and persistent degradation, and the conflict-dense shared budget (15 s)
  applied to each pair separately in conflict dense.
- Reference rows reused from N2/N3: Affinity-Bytes, Affinity-Bytes+Admission, MAPE-CAP-WS.

## Endpoints
Per graph × τ × comparator: admissibility under the full MAPE-CAP-WS planning constraints; whether the
comparator itself found a candidate; cross-rack bytes of the selection.
Primary summary: number of graphs (of 150) admissible under the full model, per τ and comparator,
and the number of graphs where (b) selects a placement that violates only the multi-pair group.

## Interpretation rules
- Descriptive only; no hypothesis test (outcomes follow deterministically from the constraint sets).
- If (b) matches full admission at τ ≤ 1.25, the paper states that the evaluated violations exercise
  state-dependent, direction-shared per-pair airtime and that multi-pair coupling binds only at the
  highest loads; it does not claim that multi-pair coupling drives the reported results.
- Any outcome is reported.
