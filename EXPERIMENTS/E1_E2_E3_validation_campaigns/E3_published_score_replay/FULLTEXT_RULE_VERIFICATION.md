# Full-text verification of the published E3 scoring rule

**Verification date:** 2026-10-03 (before any E3 science run in this package)

**Published source:** Angelo Marchese and Orazio Tomarchio, *Extending the Kubernetes Platform with Network-Aware Scheduling Capabilities*, ICSOC 2022, pp. 465–480, DOI: 10.1007/978-3-031-20984-0_33.

**Full-text source consulted:** author-uploaded full text available through the paper's ResearchGate record. The verification was performed against the complete algorithm and surrounding methodological text, not title/abstract snippets.

## What the full text confirms

1. **Algorithm 1 (Node scoring algorithm).** For the Pod being scheduled and each candidate node, communication cost starts at zero; the algorithm iterates over cluster nodes and Pods on those nodes, and for each neighboring Pod accumulates `network cost × affinity weight`. The returned node score is the negative of that communication cost. Thus, when this custom score is considered alone, the selected node is the node with minimum communication cost.
2. **Affinity weights.** The traffic-aware controller derives preferred inter-Pod affinity-rule weights from measured inter-microservice traffic. The weights are directly proportional to traffic averaged over a configurable interval and are normalized to integer values in the range 0–100.
3. **Network costs.** The topology controller derives node-pair costs from measured network latency averaged over a configurable interval and normalizes them to the range 1–100. The same-node label is assigned a value of 1.
4. **No shared-airtime variable appears in Algorithm 1.** The scoring rule consumes affinity weights and node-pair network costs; it does not include the conflict-group/shared-airtime admission constraint evaluated in this study.

## How `run_score_replay.py` maps that rule into this study

The implementation reproduces the published scoring structure `sum(affinity weight × network cost)` and chooses the lowest-cost candidate node. The following are **declared adaptations**, because this study replays the scoring rule on already-instantiated controlled placement graphs rather than running the authors' Kubernetes scheduler/controller stack:

- planner traffic values are used as the affinity-weight proxy; positive per-Pod rescaling does not change that Pod's candidate-node ranking;
- the declared planning-state latency is averaged using the study's fixed design weights and used as the network-cost proxy; positive affine normalization of all candidate-node costs does not change a Pod's node ranking;
- directed flow costs are retained to match this paper's directional state representation, whereas the published implementation obtains costs from measured node-to-node RTT labels;
- the rule is iteratively replayed from the controlled incumbent placement; the published scheduler scores the Pod currently being scheduled;
- the study applies the same allowed-node/resource/anti-affinity restrictions and the same primary two-move cap as its other placement comparisons;
- sensitivity variants (`capped_fixed_order`, `capped_requests`, and `uncapped`) are retained to expose dependence on replay ordering, traffic proxy, and move cap.

## Permitted manuscript wording

Use wording such as:

> "an independent replay of the published Marchese–Tomarchio node-scoring rule on the controlled graph set, with prespecified adaptations to the study's traffic/state representation and incumbent-placement replay."

Do **not** call it the authors' scheduler implementation, Kubernetes plugin, controller stack, descheduler, or testbed.
