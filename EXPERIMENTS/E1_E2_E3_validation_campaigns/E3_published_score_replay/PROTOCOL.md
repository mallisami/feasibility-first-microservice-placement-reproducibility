# Protocol: replay of a published network-aware scoring rule on the 150 controlled graphs (E3)

**Status:** written before the rule was applied to any of the 150 science graphs. The script was exercised only on smoke seeds 99101-99103, 99201-99203 and 99301-99303, which are not science data. Record the folder hash before running.

**Why this study exists.** An earlier replay of this rule on the held-out-source partitions was reported in the supplement, but its code and outputs were not retained and that result cannot be reproduced. This study does not attempt to recover it. It asks a different, more direct question on the principal graph set, and archives everything.

## 1. Question

The paper's baseline, Affinity-Bytes, is defined by this study. Does a published network-aware scoring rule, which ranks nodes by traffic-weighted network cost and has no shared-airtime constraint, also select placements outside the declared shared-airtime region when an admissible placement exists?

## 2. Rule and adaptations

Source: Marchese and Tomarchio, "Extending the Kubernetes Platform with Network-Aware Scheduling Capabilities", ICSOC 2022, Algorithm 1 (node scoring). For a Pod p and candidate node n, the communication cost is the sum, over cluster nodes cn, of the traffic between p and the Pods on cn multiplied by the network cost between n and cn; the node score is the negative of that cost, and the Pod goes to the highest-scoring node.

Adaptations to this paper's setting, all fixed here:

- **Traffic:** the planner's bits per decision window for each directed flow incident to the Pod.
- **Network cost:** the declared directed latency between racks, averaged over the three planning states with their normalized design weights (the published scheduler uses measured latency averaged over time). Zero within a rack. Directed flows use the cost of their own direction.
- **Application to a placement:** starting from the incumbent, repeatedly move the single Pod whose best-scoring feasible node reduces its communication cost the most, until no Pod improves. Ties prefer staying, then lexicographic order.
- **Constraints:** the same allowed-node, CPU, memory and anti-affinity rules as every other method. The primary variant uses the same two-move budget as the other methods; section 3 lists the declared sensitivity variants.
- The rule receives no goodput, conflict-group, airtime-budget or CVaR information.

This is an independent implementation of the published scoring rule, not the authors' scheduler plugin, operators, descheduler or testbed, and it supports no performance claim about their system.

## 3. Verification status of the implementation

`FULLTEXT_RULE_VERIFICATION.md` and `RULE_CHECK.md` record the pre-execution full-text check. Algorithm 1, its complete inner loop, the node-selection rule, the traffic-derived affinity weights, and the latency-derived network costs were verified against the author-uploaded full text before any science run. The study still uses declared adaptations because it replays the scoring rule on an incumbent placement rather than executing the authors' complete Kubernetes scheduler/controller stack. The following sensitivity variants remain fixed in advance alongside the primary variant:

| Variant | Move budget | Traffic weight | Which Pod moves |
|---|---|---|---|
| `capped` (primary) | two moves | bits per window | largest cost reduction |
| `capped_fixed_order` | two moves | bits per window | first Pod in lexicographic order that can improve |
| `capped_requests` | two moves | requests per window | largest cost reduction |
| `uncapped` | none | bits per window | largest cost reduction |

The full-text verification does not remove the study-specific replay adaptations. Results must therefore be described as an independent replay of the published node-scoring rule under the controlled graph representation, not as a reproduction of the authors' complete scheduler, plugin, controllers, or testbed.

## 4. Outcomes (descriptive)

On the 150 graphs at loads 1.00, 1.10, 1.25 (primary) and 1.50: the number of graphs on which the rule's placement violates a declared airtime budget; how many of those violations are avoidable; how many coincide with Affinity-Bytes violations; identical-placement count with Affinity-Bytes; mean worst utilization and moves. No significance test: the admission-constrained methods satisfy the constraint by construction.

**Interpretation rule.** If the primary variant produces avoidable violations and the sensitivity variants agree in direction, the finding that network-aware ranking without shared-airtime admission can leave the admissible region is not specific to the study-defined baseline. If it produces none, that is reported as such, and the paper's claim stays limited to byte affinity.

## 5. Boundary

Planning-model feasibility only; no packet or application execution. A greedy single-Pod scorer is compared with exhaustive optimizers, so differences in optimization power are part of the comparison.
