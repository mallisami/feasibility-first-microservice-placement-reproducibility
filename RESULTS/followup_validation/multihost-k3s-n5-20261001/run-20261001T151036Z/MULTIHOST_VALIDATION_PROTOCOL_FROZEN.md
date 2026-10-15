# Multi-host Kubernetes follow-up — frozen protocol v1.1

**Freeze:** 2026-10-01, before any new multi-host application measurement.

## Purpose

This follow-up addresses one limitation only: the original N5 binding-state study mapped three logical racks to three Kind worker containers on one Azure VM. The follow-up replays the original N5 **primary S1** cases on **three distinct Kubernetes hosts**, one host per logical rack.

It is not a new planner-capacity experiment and it is not physical 60-GHz validation.

## Multi-host topology

- rack-a: k3s server/control-plane, also schedulable for benchmark pods;
- rack-b: k3s agent on a second VM/machine;
- rack-c: k3s agent on a third VM/machine.

The three nodes must have distinct Kubernetes `InternalIP` values and be labelled `mape-cap-ws/rack=rack-a|rack-b|rack-c`. The server is additionally labelled `mape-cap-ws/role=server`.

Before the pilot, a short-lived pod on each node hashes the host OS `/etc/machine-id`. Only the SHA-256 digests are retained. The three digests must be distinct; this strengthens evidence that the Kubernetes nodes are backed by three distinct VM/OS instances without publishing raw host identifiers.

K3s is pinned to **v1.33.1+k3s1**, yielding kubelet build **v1.33.1+k3s1** (upstream Kubernetes **v1.33.1**), matching the original N5 Kubernetes version while changing the host topology.

## Source cases

All 20 original N5 S1 enrolled graphs are replayed. No case is selected using the new multi-host outcomes.

Seeds:

55011, 55014, 55025, 55028, 55033, 55035, 55037, 55043, 55046, 55058,
55063, 55064, 55067, 55068, 55075, 55076, 55081, 55082, 55084, 55085.

For every seed the follow-up reuses the source package's:

- tau = 1.25 calibration;
- exact rack-level placement for Affinity-Bytes;
- exact rack-level placement for Affinity-Bytes+Admission;
- exact rack-level placement for MAPE-CAP-WS;
- executed wireless state chosen in the original N5 enrollment;
- frozen three-state scenario library and shared-medium emulator.

The runner reconstructs the original planning problem using the original N5 node capacities and refuses execution if Affinity-Bytes is no longer inadmissible, either admission-aware method is infeasible, the reconstructed Current utilization differs from tau, or the executed state differs from the source snapshot.

## Execution-only resource reservations

The smaller follow-up machines are **not** used to redefine the planner's capacity model. Benchmark pods therefore use fixed execution reservations of **100 mCPU and 128 MiB** per service. This is a Kubernetes scheduling reservation only; it does not alter the frozen flow rates, wireless states, placement identities, airtime budgets or planner feasibility labels.

This choice makes the follow-up a host-separation replication rather than a new capacity-planning experiment. The paper must disclose this distinction.

The server node must expose at least **1.8 allocatable CPU** and **3000 MiB allocatable memory**; each agent must expose at least **0.9 allocatable CPU** and **1200 MiB allocatable memory** before the experiment starts. These gates are consistent with the intended 2-vCPU server + 1-vCPU + 1-vCPU agents when the server has at least about 4 GiB RAM and each agent at least about 2 GiB RAM, leaving headroom for K3s plus the frozen workload.

## Methods

1. Affinity-Bytes
2. Affinity-Bytes+Admission
3. MAPE-CAP-WS

No Current arm is added because the purpose is to replicate the original N5 S1 admission/ranking comparison, not enlarge the benchmark family.

## Cell procedure

For each graph and method:

1. apply the exact frozen rack-level placement to the three Kubernetes/VM nodes;
2. verify observed pod node names exactly match that placement;
3. settle for 5 s;
4. configure the same executed-state shared-medium emulator;
5. run the application traffic for **40 s**;
6. collect scheduled-request latency, completion and emulator metrics;
7. verify deployment health;
8. accept/reject the cell using infrastructure checks only.

Method order is randomized per graph using the original N5 seed rule `20260926 + graph_seed`.

At most two attempts are permitted per cell. Failed attempts remain in the results package.

## Engineering pilot

Before science, seeds **55011 and 55014** are run for 10 s per method. Pilot outcomes are **not analysed** and are used only to verify infrastructure, image availability, cross-host service routing and result capture. No latency/completion threshold gates entry to science.

## Science matrix

20 graphs × 3 methods = **60 scientific cells**.

## Endpoints and analysis

The endpoints reproduce N5:

- primary: scheduled-request P95 latency;
- co-primary: scheduled completion fraction;
- secondary: scheduled P50/P99, attempted-request P95, mean shared-medium queue wait, executed-state planned utilization and moves.

Paired graph-level contrasts:

- Affinity-Bytes+Admission minus Affinity-Bytes;
- MAPE-CAP-WS minus Affinity-Bytes+Admission.

For P95 and completion, report paired mean difference, 100,000-resample bootstrap 95% CI using the original N5 bootstrap seed `20260926`, two-sided Wilcoxon signed-rank p-value and Holm adjustment within endpoint family. The original N5 primary CSV is retained beside the follow-up output for contextual comparison; it is not pooled with the new data.

## Interpretation rule

A result strengthens the host-separation evidence if the experiment executes successfully across three distinct hosts and the admission/ranking pattern can be reported without changing the frozen design. A null or reversed performance result must be reported as such. No cell is removed because its performance is inconvenient.

The follow-up can support the statement that the application-level finding was tested on a **three-host Kubernetes deployment**. It cannot support a claim of three physical 60-GHz racks or RF validation.
