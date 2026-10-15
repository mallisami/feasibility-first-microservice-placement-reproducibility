# Protocol Frozen: S-E8 Corrected Failure Robustness and Transactional Fallback Campaign

**Protocol ID:** `SE8-CORRECTED-FROZEN-v1.0`  
**Date Frozen:** 2026-09-19  
**Freeze Status:** Prospectively frozen prior to scientific campaign execution. Denominator and acceptance criteria are immutable.  
**Execution Environment:** Azure Virtual Machine `mcb-k8s-v137` (`<public-ip-redacted-for-distribution>`), Kind cluster `mcb-k137` (Kubernetes v1.37.0).  

---

## 1. Scientific Motivation and Historical Discrepancy Reconciliation

The historical S-E8 campaign evaluated 5 fault classes $\times$ 5 replicates (25 trials total):
- F1 (Missing telemetry): Fail-closed, 0 mutations.
- F2 (Stale telemetry): Fail-closed, 0 mutations.
- F3 (Optimizer timeout): Fail-closed, 0 mutations.
- F4 (Infeasible instance): Fail-closed, 0 mutations.
- F5 (Kubernetes action failure): Handled and recovered, but failed strict pre-execution safety because the test runner manually executed an invalid node patch (`nonexistent-node-se8-fault`) directly via `kubectl patch`, bypassing the controller's target validation.

To establish scientific validity and comparability without retroactively altering historical evidence:
1. **F5 is corrected to test Pre-Execution Target Validation**: The candidate placement containing an invalid target is submitted to the genuine controller interface (`apply_placement`). The controller's `validate_placement_target` check must reject the request before any Kubernetes mutation occurs (authoritatively audited via unchanged object generations and resourceVersions).
2. **F6 is introduced as a scientifically distinct fault class**: **Partial-Mutation Action Failure and Transactional Rollback**. This exercises the controller's runtime compensation path when a failure occurs *after* at least one valid mutation has succeeded. A deterministic test hook raises an exception during rollout, requiring the controller to detect the failure, execute compensating reverse patches, await pod readiness, and restore application health.

**Frozen Denominator:** Exactly 6 fault classes $\times$ 5 replicates = **30 trials**.

---

## 2. Frozen Trial Matrix

| Replicate | Seed Offset | Target Service | Candidate Modification | Injection Lifecycle Point | Expected Controller Action |
|---|---|---|---|---|---|
| **F1: Missing Telemetry** (Reps 01–05) | 20001–20005 | N/A | Telemetry collector disabled | Detection pre-planner | Gate abstains; zero replanning; initial placement preserved |
| **F2: Stale Telemetry** (Reps 01–05) | 20001–20005 | N/A | Timestamp age = 600s (> 120s limit) | Staleness filter | Gate abstains; zero replanning; initial placement preserved |
| **F3: Solver Timeout** (Reps 01–05) | 20001–20005 | N/A | `time_limit_seconds = 0.001` | Solver invocation | ExactSolveError caught; fallback to previous placement; zero mutation |
| **F4: Infeasible Instance** (Reps 01–05) | 20001–20005 | N/A | Node capacities set to 0.0 | Post-solve feasibility check | Infeasibility detected; candidate discarded; zero mutation |
| **F5: Target Pre-Validation** (Reps 01–05) | 20001–20005 | `SERVICES[rep % 11]` | Node: `nonexistent-node-se8-fault` | `validate_placement_target` | Controller raises `ValueError`; zero Kubernetes mutations |
| **F6: Partial Mutation Rollback** (Reps 01–05) | 20001–20005 | `SERVICES[rep % 11]`, `SERVICES[(rep+1) % 11]` | 2 valid worker targets | Post-first patch hook | Rollback reverse patches submitted; pods return to Ready; frontend health verified |

---

## 3. Operational Limits and Timeouts

- **Pre-fault measurement window:** 20 seconds.
- **Post-fault measurement window:** 20 seconds.
- **Rollout completion timeout (`ROLLOUT_TIMEOUT_SECONDS`):** 45 seconds.
- **Health stabilization deadline:** 30 seconds.
- **HTTP frontend probe timeout:** 5 seconds per probe.
- **Retry Policy:** Zero retries permitted. If a trial fails an acceptance condition, it is permanently recorded as failed or unsafe.

---

## 4. Multi-Indicator Safety Acceptance Criteria

A trial is classified as **Strict-Safe** if and only if **all** of the following indicators evaluate to `True`:
1. `invalid_placement_executed == False`: No invalid or unauthorized target specification reached the Kubernetes mutating API.
2. `infeasible_placement_executed == False`: No capacity-violating or mathematically infeasible placement was committed.
3. `unbounded_relocation_loop == False`: No thrashing or repetitive rescheduling occurred.
4. `failure_logged == True`: The injected fault was explicitly detected and logged with diagnostic context.
5. `last_valid_placement_preserved == True`: The cluster state matches the pre-fault baseline placement.
6. `controller_recovered == True`: All required pods returned to `phase=Running`, `ready=True`, and HTTP frontend health probe returned HTTP 200.

For F5 specifically:
- `zero_mutations_authoritative == True`: Initial and final deployment generation and resourceVersion must match exactly.

For F6 specifically:
- `partial_mutation_succeeded == True`: Exactly one forward patch was applied before failure was injected.
- `rollback_completed == True`: Compensating patch was applied, pod returned to original worker, and all pods reached Ready.

---

## 5. Raw Evidence Retention Policy

For every trial, the runner must generate and persist:
- `result.json`: Comprehensive trial outcome, timestamps, latencies, snapshots, and verdict.
- `pre-samples.json` & `post-samples.json`: Structured per-request telemetry samples.
- `pre-frontend.log` & `post-frontend.log`: Authoritative frontend request logs.
- `pre_snapshot` & `post_snapshot`: Full cluster state snapshots (deployments, pods, nodes, versions).

No intermediate data may be discarded or overwritten.
