# Kubernetes v1.37 post-freeze follow-up protocol

**Freeze time:** 2026-09-17, before application outcomes from these arms were inspected.  
**Evidence class:** append-only, post-freeze, single-host Kind follow-up. It is not the independently hosted decisive campaign defined in `PAPER/VALIDATION_PROTOCOL.md`.

## Shared environment

- Kind v0.33.0, Kubernetes v1.37.0, one control plane and three workers.
- Node image: `kindest/node:v1.37.0@sha256:a1ed56cfb0e7b93589bdf97c8cd566405a265939e3620fc4f5de89adff580ae5`.
- Online Boutique v0.10.1, one replica per service unless an arm states otherwise.
- Worker mapping: legacy `worker`, `worker2`, `worker3` map in order to `mcb-k137-worker`, `mcb-k137-worker2`, `mcb-k137-worker3`.
- Results are written under this experiment directory and do not overwrite R1--R9 or S-E1--S-E8.

## Arm 2: accepted full-planner live relocation

Use the lowest frozen accepted regime from `RESULTS/gap-closure/live-confirmatory-20260912/experiment-1/frozen-regime.json`: 40 ms adverse latency, 20 Mbit/s effective rate, load multiplier 2.0, 300 s planning horizon, frozen Exact-plan net benefit 93,099.25 units. Reconstruct its deterministic initial placement (`live-confirmatory`, replicate 42), then execute its four-service candidate move (adservice, emailservice, paymentservice, shippingservice). Record exact placement, readiness, rollout timing, frontend P50/P95/P99, completed requests, achieved rate, errors, and health before and after action. No post-outcome retuning is allowed. Roll back if readiness fails, error rate exceeds 5%, or post-action P95 exceeds 125% of the paired pre-action P95; otherwise restore after evidence capture so later arms start from a declared state.

## Arm 3: uncached-relocation calibration

Use the `relocation-echo` deployment and a registry-fetched image that is verified absent from the target node immediately before every measurement. Record image reference/digest/size, source and target node, image-presence check, pull events, create-to-ready time, full create-ready-remove rollout time, request failures from the concurrent probe, and final health. Alternate target workers. Collect 20 successful observations unless the bootstrap 95% half-width for the median is at most 20% of the median earlier; failed pulls remain recorded as infrastructure outcomes and are not replaced silently.

## Arm 4: request-rich R1 replication

Compare Current and BPlus-Exact across the original nine R1 conditions and 30 matched replicate IDs. Each cell uses a 420 s maximum measurement window and is accepted only with at least 1,000 successful non-health frontend requests, healthy final state, and a finite feasible planner result. Method order remains counterbalanced by the original runner. Individual requests are within-cell observations; the paired replicate remains the inferential unit. This arm improves tail estimation but does not create independent physical workers.

## Arm 5: native TAS/CompositePodGroup

Enable `GenericWorkload`, `TopologyAwareWorkloadScheduling`, and `CompositePodGroup` on the API server, controller manager, and scheduler, and enable `scheduling.k8s.io/v1alpha3`. Label all workers in one zone and three distinct racks. Use a two-level CompositePodGroup with two gang-scheduled leaf PodGroups: four request-path services and seven supporting services. The parent constrains the whole workload to one zone; each leaf group constrains its members to one rack. Validate API objects and actual pod placement, then collect the same application endpoint vector under the same 40 ms / 20 Mbit/s / 2x-load condition used by Arm 2. This is a native topology comparator, not a representation of B+'s directed wireless-risk objective.

## Reporting

All timeouts, zero-action results, pull failures, unschedulable groups, rollbacks, and partial results are retained. No arm may be described as decisive production validation because all workers share one WSL2 host.
