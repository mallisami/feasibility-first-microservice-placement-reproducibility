# S-E8 Smoke Test and Live Qualification Report

**Execution Timestamp**: 2026-09-18T19:34:45Z  
**Environment**: Azure Virtual Machine (Standard_D4as_v5, 4 vCPUs AMD EPYC 7763, 16 GiB RAM, Ubuntu 24.04 LTS)  
**Cluster Context**: Kind v0.33.0 on Kubernetes v1.37.0 (`mcb-k137`)  
**Target Namespace**: `online-boutique` (11 microservices + 1 loadgenerator)  
**Evaluator**: Scientific Reproducibility Auditor & Senior Systems Engineer  

---

## 1. Objective and Qualification Scope

Before executing the full 30-trial frozen safety campaign (6 fault classes $\times$ 5 replicates), Phase 7 requires a live qualification smoke test on the actual Azure Kubernetes cluster to verify the core safety mechanisms under real execution conditions:
1. **Pre-execution Target Validation (F5)**: The controller must inspect placement candidates and fail-closed before any mutating Kubernetes API request reaches the API server when an invalid target node is specified.
2. **Partial-Mutation Transactional Rollback (F6)**: A deterministic failure hook injected after at least one real Kubernetes mutation has succeeded must trigger immediate transactional rollback, restoring original scheduling constraints, verifying pod readiness, and confirming application health recovery.
3. **Artifact and Evidence Persistence**: Raw JSON records, initial/final placement snapshots, sample metrics, and frontend logs must be written cleanly to disk.

Per scientific protocol, smoke test results are qualification evidence only and **are not counted** toward the final 30 scientific replicates.

---

## 2. Qualification Execution Summary

```
========================================================================================
Fault Class                        Rep  Status   Detection Latency  Elapsed  Verdict
========================================================================================
F5-invalid-target-prevalidation     01   PASS         0.380 s       0.699 s  STRICT SAFE
F6-partial-mutation-rollback        01   PASS        15.746 s      27.010 s  STRICT SAFE
========================================================================================
```

---

## 3. Detailed Empirical Evidence

### 3.1 Trial 1: `S-E8:F5-invalid-target-prevalidation:rep1`

* **Injected Fault**: Candidate placement specifies `nonexistent-node-se8-fault` for microservice `cartservice`.
* **Execution Path**: Real controller interface `apply_placement()` invoked directly with production `validate_placement_target()` prevalidation active.
* **Pre-Execution Snapshot**:
  * Microservice: `cartservice`
  * `pre_generation`: `14`
  * `pre_resource_version`: `"50472"`
  * `node_selector`: `{"kubernetes.io/hostname": "mcb-k137-worker"}`
* **Rejection Details**:
  * Exception Caught: `ValueError: placement pre-execution validation failed: invalid target nodes: {'cartservice': 'nonexistent-node-se8-fault (node not found)'}`
  * Detection Latency: `0.380 s`
  * Pre-execution Rejected: `True`
* **Zero-Mutation Verification**:
  * `post_generation`: `14` (Delta: 0)
  * `post_resource_version`: `"50472"` (Delta: 0)
  * `zero_mutations_verified`: `True`
  * Cluster Node Status: All 3 workers remained Ready, 0 pending pods created.
* **Health and Placement Verification**:
  * `placement_preserved`: `True` (all 11 services at previous node assignments)
  * `controller_recovered`: `True` (`assert_healthy() == True`)
* **Strict Safety Verdict**: **PASS (100% Strict Safe)**

### 3.2 Trial 2: `S-E8:F6-partial-mutation-rollback:rep1`

* **Injected Fault**: Deterministic test hook inside `apply_placement()` raises `ControlledPartialMutationFault` immediately after successfully mutating `cartservice` to `mcb-k137-worker2`, but before mutating `checkoutservice`.
* **First Mutation Succeeded**:
  * Target: `cartservice` patched to `mcb-k137-worker2`
  * Mutated Timestamp: `2026-09-18T19:34:08.589784Z`
  * Prevented Subsequent Actions: `checkoutservice` mutation aborted before submission.
* **Failure Detection & Rollback**:
  * Injected Exception Caught: `ControlledPartialMutationFault: deterministic failure after patching cartservice; rollback submitted`
  * Rollback Handler Activated: Re-patches `cartservice` back to original node `mcb-k137-worker`
  * Rollout Status Verified: All affected deployments rolled out cleanly
  * Detection Latency: `15.746 s`
  * Total Elapsed Time: `27.010 s`
* **Restoration Verification**:
  * `rollback_initiated`: `True`
  * `rollback_completed`: `True`
  * `placement_preserved`: `True` (`cartservice` back on `mcb-k137-worker`, all 11 services match initial placement)
  * `pods_ready`: `True` (12/12 pods 1/1 Running in `online-boutique`)
  * `frontend_probe_ok`: `True` (HTTP 200 from frontend service)
  * `health_recovered`: `True`
* **Strict Safety Verdict**: **PASS (100% Strict Safe)**

---

## 4. Independent Verification Audit

The standalone auditor `validate_se8_results.py` was executed directly against `/home/azureuser/mcb/RESULTS/smoke-se8-qualification`:
* Validated trial schema structure: **PASS**
* Validated pre/post snapshots and zero mutations for F5: **PASS**
* Validated partial mutation and complete rollback for F6: **PASS**
* Validated pod phase and frontend readiness: **PASS**
* Unexecuted trials (F1–F4 and replicates 2–5) flagged as absent as expected for qualification.

---

## 5. Qualification Decision

All pre-execution qualification criteria specified in Phase 7 are **MET**:
1. Invalid target rejected before any mutation with zero Kubernetes API mutations verified.
2. Controlled partial mutation triggered rollback, restored original placement, and returned all pods to Ready.
3. Application health and synthetic frontend traffic verified operational.
4. No memory leaks, dangling pods, or dirty cluster state remained.

**Status: QUALIFIED TO PROCEED TO PHASE 8 (RELEASE FREEZE) AND PHASE 9 (SCIENTIFIC CAMPAIGN).**
