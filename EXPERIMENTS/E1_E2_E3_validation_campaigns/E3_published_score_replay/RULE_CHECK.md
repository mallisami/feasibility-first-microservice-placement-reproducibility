# Verification record for the E3 published scoring-rule replay

**Status:** full algorithm and surrounding methodological description checked before any science run.

**Source:** A. Marchese and O. Tomarchio, "Extending the Kubernetes Platform with Network-Aware Scheduling Capabilities", ICSOC 2022, pp. 465–480, DOI:10.1007/978-3-031-20984-0_33.

See `FULLTEXT_RULE_VERIFICATION.md` for the complete verification record and the declared adaptations.

## Confirmed rule elements

| Published element | E3 implementation |
|---|---|
| Candidate node receives a communication-cost score for the Pod being scheduled | `cm_cost(...)` |
| Cost accumulates affinity weight × network cost over neighboring Pods | accumulation over incident communication flows and the peer placement |
| Final node score is the negative communication cost | E3 selects the candidate node with the lowest `cm_cost` |
| Affinity weights are proportional to measured traffic and normalized to 0–100 | planner traffic is used as a proportional proxy; node ranking is invariant to positive per-Pod rescaling |
| Network costs are proportional to measured latency and normalized to 1–100 | fixed weighted mean planning-state latency is used as a proportional cost proxy |
| Published rule has no shared-airtime/conflict-group admission input | E3 passes none |

## Declared adaptations that remain

1. The controlled study starts from an incumbent placement and replays the Pod-scoring rule iteratively; the published scheduler scores the Pod currently being scheduled.
2. The study retains directed traffic/state costs, whereas the published controller obtains node-to-node latency costs from RTT telemetry.
3. The primary replay uses the study's two-move cap for comparability. `uncapped` is prespecified as a sensitivity variant.
4. `capped_fixed_order` and `capped_requests` are prespecified sensitivity variants for replay order and traffic proxy.

## Manuscript boundary

The E3 result is evidence about a replay of the **published node-scoring rule** under this study's controlled placement representation. It is not a reproduction or performance evaluation of the authors' full Kubernetes scheduler/controller system.
