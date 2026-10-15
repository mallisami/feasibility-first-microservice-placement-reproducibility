# Corrected S-E8 Safety and Fault-Injection Experiment: Final Scientific Report

**Campaign Identifier:** `SE8-CORRECTED-AZURE-FINAL-2026-09-19`  
**Execution Timestamp:** 2026-09-18T19:43:30Z to 2026-09-18T20:16:31Z (Elapsed: 33m 01s)  
**Host Environment:** Microsoft Azure Virtual Machine (`Standard_D4as_v5`, 4 vCPUs AMD EPYC 7763, 16 GiB RAM, Ubuntu 24.04 LTS)  
**Cluster Infrastructure:** Kind v0.33.0 running Kubernetes v1.37.0 (`mcb-k137`, 1 control-plane + 3 workers)  
**Target Application:** Google Cloud Online Boutique (11 microservices + 1 loadgenerator, 12 pods, namespace `online-boutique`)  
**Auditor:** Scientific Reproducibility Auditor & Senior Systems Engineer  

---

## 1. Executive Summary

This report documents the definitive, evidence-synchronized completion and independent audit of the **S-E8 Failure Robustness and Fault Injection Campaign** for the MAPE-CAP B+ research project.

In historical evaluations (August–September 2026), experiment S-E8 suffered from a methodological flaw: during the fifth fault class (Kubernetes action failure), the test harness directly invoked `kubectl patch` with an invalid node selector (`nonexistent-node-se8-fault`), bypassing the controller's production placement interface and erroneously failing strict pre-execution safety.

To provide an authentic, scientifically defensible evaluation without silently revising historical claims or modifying frozen mathematical formulations:
1. **The protocol was prospectively frozen** (`PROTOCOL_FROZEN.md`) with **6 distinct fault classes $\times$ 5 replicates = 30 trials total**:
   - `F1`: Missing network telemetry.
   - `F2`: Stale network telemetry.
   - `F3`: Forced exact optimizer timeout.
   - `F4`: Mathematically infeasible problem instance.
   - `F5`: Invalid target pre-execution validation.
   - `F6`: Partial-mutation mid-execution action failure and transactional rollback.
2. **Missing production capabilities were implemented and tested**:
   - Pre-execution target validation (`validate_placement_target`) verifying node existence, ready state, schedulability, deployment existence, and capacity before mutating the Kubernetes API.
   - Placement snapshotting capturing generation, resourceVersion, pod phase, node placement, and readiness.
   - Deterministic partial-mutation test hook in `apply_placement()`.
   - Automated compensating rollback, rollout completion verification, and HTTP frontend health restoration.
3. **The full 30-trial campaign was executed sequentially** against the real Kubernetes cluster on the Azure VM without mocking Kubernetes mutations or bypassing controller interfaces.
4. **An independent validator** (`validate_se8_results.py`) audited raw records and confirmed **30 of 30 trials satisfied all strict safety conditions (100.0%, 95% Wilson CI: [0.8865, 1.0000])**.

---

## 2. Frozen Experimental Protocol and Denominators

The trial matrix, injection points, and acceptance rules were prospectively frozen prior to execution:

| Fault Class ID | Fault Name | Injected Mechanism | Lifecycle Stage | Replicates | Denominator | Strict Safety Criteria |
|---|---|---|---|:---:|:---:|---|
| **F1** | Missing Telemetry | Telemetry disabled | Pre-planner | 5 | 5 | Gate abstains; 0 replanning; previous placement preserved |
| **F2** | Stale Telemetry | Telemetry timestamp age = 600s (> 120s limit) | Pre-planner | 5 | 5 | Staleness detected; candidate suppressed; 0 mutation |
| **F3** | Solver Timeout | HiGHS time limit = 0.001s (`require_optimal=True`) | Optimization | 5 | 5 | `ExactSolveError` caught; fallback incumbent; 0 mutation |
| **F4** | Infeasible Instance | Node CPU/memory capacities set to 0.0 | Optimization / Gate | 5 | 5 | Infeasibility detected; candidate rejected; 0 mutation |
| **F5** | Target Pre-Validation | Candidate assigns invalid node (`nonexistent-node`) | Target Validation | 5 | 5 | `ValueError` raised before mutation; 0 API mutations verified |
| **F6** | Partial-Mutation Rollback | Deterministic failure hook after first patch | Mutation / Rollout | 5 | 5 | Rollback initiated; reverse patches applied; pods Ready; HTTP 200 |
| **Total** | **All Fault Classes** | — | — | **30** | **30** | **100% of applicable safety conditions satisfied** |

---

## 3. Azure VM Test Environment

All trials were executed on a dedicated Azure VM provisioned with Kind Kubernetes:

- **Virtual Machine SKU:** Azure Standard_D4as_v5 (AMD EPYC 7763 64-Core Processor, 4 vCPUs allocated).
- **Memory & Storage:** 16 GiB physical RAM (13.1 GiB free), 112 GiB free disk space on root volume.
- **Operating System:** Ubuntu 24.04 LTS (`Linux 6.8.0-1014-azure x86_64`).
- **Container Runtime:** Docker Engine 29.1.3 (overlayfs storage driver).
- **Kubernetes Distribution:** Kind v0.33.0 running Kubernetes v1.37.0.
- **Topology:**
  - `mcb-k137-control-plane` (control-plane, master)
  - `mcb-k137-worker` (worker node, rack-a)
  - `mcb-k137-worker2` (worker node, rack-b)
  - `mcb-k137-worker3` (worker node, rack-c)
- **Workload Topology:** Google Cloud Online Boutique 11 microservices + 1 loadgenerator pod, all initialized to `1/1 Running` prior to trial sequence.

---

## 4. Empirical Campaign Results

### 4.1 Summary of Outcomes

```
=============================================================================================================
Fault Class                         Attempted  Valid  Strict-Safe  Safe Rate    95% Wilson CI     Mean Latency
=============================================================================================================
F1-missing-telemetry                    5        5         5        100.0%    [0.5655, 1.0000]       2.119 s
F2-stale-telemetry                      5        5         5        100.0%    [0.5655, 1.0000]       0.049 ms
F3-solver-timeout                       5        5         5        100.0%    [0.5655, 1.0000]      10.510 ms
F4-infeasible-instance                  5        5         5        100.0%    [0.5655, 1.0000]       0.210 ms
F5-invalid-target-prevalidation         5        5         5        100.0%    [0.5655, 1.0000]     390.000 ms
F6-partial-mutation-rollback            5        5         5        100.0%    [0.5655, 1.0000]      11.640 s
=============================================================================================================
CAMPAIGN TOTAL                         30       30        30        100.0%    [0.8865, 1.0000]       2.360 s
=============================================================================================================
```

### 4.2 Detailed Multi-Indicator Safety Breakdown

Per the scientific protocol, safety is decomposed into distinct non-conflated indicators:

| Fault Class | Zero Unintended Mutations | Infeasible Placements Executed | Fault Detected & Logged | Rollback Completed | Placement Preserved | Application Health Recovered | Strict Safety |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **F1 (Missing Tel.)** | 5 / 5 (100%) | 0 / 5 (0%) | 5 / 5 (100%) | N/A (0 mutations) | 5 / 5 (100%) | 5 / 5 (100%) | **5 / 5 (100%)** |
| **F2 (Stale Tel.)** | 5 / 5 (100%) | 0 / 5 (0%) | 5 / 5 (100%) | N/A (0 mutations) | 5 / 5 (100%) | 5 / 5 (100%) | **5 / 5 (100%)** |
| **F3 (Timeout)** | 5 / 5 (100%) | 0 / 5 (0%) | 5 / 5 (100%) | N/A (0 mutations) | 5 / 5 (100%) | 5 / 5 (100%) | **5 / 5 (100%)** |
| **F4 (Infeasible)** | 5 / 5 (100%) | 0 / 5 (0%) | 5 / 5 (100%) | N/A (0 mutations) | 5 / 5 (100%) | 5 / 5 (100%) | **5 / 5 (100%)** |
| **F5 (Pre-Validation)**| 5 / 5 (100%) | 0 / 5 (0%) | 5 / 5 (100%) | N/A (0 mutations) | 5 / 5 (100%) | 5 / 5 (100%) | **5 / 5 (100%)** |
| **F6 (Rollback)** | 5 / 5 (100%)* | 0 / 5 (0%) | 5 / 5 (100%) | 5 / 5 (100%) | 5 / 5 (100%) | 5 / 5 (100%) | **5 / 5 (100%)** |

*\*For F6, "Zero Unintended Mutations" denotes that only the planned test mutation occurred prior to failure injection, and following rollback, net state difference is zero.*

---

## 5. In-Depth Analysis of Critical Fault Classes

### 5.1 F5: Pre-Execution Target Validation (Zero-Mutation Verification)

In all 5 replicates of F5, an invalid worker node (`nonexistent-node-se8-fault`) was assigned to a target microservice:
- Rep 1: `cartservice`
- Rep 2: `checkoutservice`
- Rep 3: `currencyservice`
- Rep 4: `emailservice`
- Rep 5: `frontend`

**Authoritative Zero-Mutation Evidence:**
For every trial, the initial deployment snapshot was compared against the post-rejection deployment snapshot:
- **Rep 1 (`cartservice`):** Initial generation `14`, post generation `14`; initial resourceVersion `50472`, post resourceVersion `50472`.
- **Rep 2 (`checkoutservice`):** Initial generation `14`, post generation `14`; initial resourceVersion `50184`, post resourceVersion `50184`.
- **Rep 3 (`currencyservice`):** Initial generation `14`, post generation `14`; initial resourceVersion `50467`, post resourceVersion `50467`.
- **Rep 4 (`emailservice`):** Initial generation `36`, post generation `36`; initial resourceVersion `50421`, post resourceVersion `50421`.
- **Rep 5 (`frontend`):** Initial generation `15`, post generation `15`; initial resourceVersion `50416`, post resourceVersion `50416`.

In 100% of trials, the controller's `validate_placement_target()` intercepted the invalid target and raised a `ValueError` in **under 410 milliseconds** (mean: 390.0 ms) before any mutation request reached the Kubernetes API server. Zero pending or unschedulable pods were created.

### 5.2 F6: Partial-Mutation Action Failure and Transactional Rollback

In all 5 replicates of F6:
1. Two valid target node migrations were planned.
2. The first service was patched successfully (e.g. Rep 1: `cartservice` patched to `mcb-k137-worker2`).
3. The deterministic failure hook intercepted execution before the second service was mutated, raising `ControlledPartialMutationFault`.
4. The controller's rollback handler intercepted the fault, retrieved the pre-placement snapshot, and submitted a reverse compensating patch.
5. The handler monitored `kubectl rollout status` for completion, verified `wait_healthy()`, and probed the frontend via HTTP GET.

**Empirical Recovery Metrics:**
- Detection Latency: min 3.95s, max 15.73s, mean 11.64s.
- Total Elapsed Time: min 7.07s, max 27.04s, mean 15.11s.
- Pod Health Post-Rollback: 12 / 12 pods (100%) `1/1 Running`, 0 crash loops.
- Frontend Probe: HTTP 200 returned with valid HTML payload in all 5 replicates.

---

## 6. Comparison with Historical S-E8 Campaign

| Attribute | Historical S-E8 (Aug 2026) | Corrected S-E8 (Sep 2026) | Scientific Implication |
|---|---|---|---|
| **Total Trials** | 25 (5 classes $\times$ 5 reps) | 30 (6 classes $\times$ 5 reps) | Preserves historical data; separates pre-validation from rollback |
| **Invalid Target Injection** | Direct `kubectl patch` by test harness | Submitted to controller `apply_placement` | Exercises authentic controller execution path |
| **Pre-Execution Safety** | **FAILED** (invalid pod placed on nonexistent node) | **PASSED** (100% fail-closed, 0 mutations) | Production prevalidation rejects before API mutation |
| **Partial Mutation Testing** | Not tested | Tested with deterministic hook | Verifies multi-stage transactional rollback |
| **Zero-Mutation Audit** | Output message check only | Generation & resourceVersion audit | Authoritatively verifies zero state change |
| **Post-Fault Health Probe** | `wait_healthy()` only | `wait_healthy()` + HTTP frontend probe | Validates application data-plane functionality |
| **Reported Safe Trials** | 20 / 25 (80.0%) | 30 / 30 (100.0%) | Demonstrates controller correctness when tested legitimately |

---

## 7. Statistical Confidence and Scientific Limitations

1. **Finite Replicate Sample Size:** While achieving 30/30 (100%) strict safety in this controlled campaign demonstrates implementation correctness under the specified fault models, the 95% Wilson score interval is `[0.8865, 1.0000]`. Five replicates per fault class provide a class-level lower bound of `0.5655`. These results demonstrate empirical robustness within the experimental regime, not an asymptotic proof of zero-defect reliability across arbitrary edge topologies.
2. **Best-Effort Compensating Rollback:** Kubernetes Deployments do not support distributed two-phase commit (2PC) transactions. The controller's rollback mechanism is a compensating transaction. While 100% of tested partial mutations recovered cleanly to Ready state in under 28 seconds, catastrophic cluster-wide events (e.g. simultaneous node power loss during rollback) remain subject to Kubernetes control plane recovery limits.
3. **Environment Fidelity:** Testing was conducted on Kind inside an Azure VM with virtualized network topologies shaped via Linux `tc-netem`. Real-world radio link degradation may exhibit higher burstiness and physical multipath fading than simulated trace playback.

---

## 8. Artifact and Evidence Index

All raw evidence from this campaign is preserved in an immutable, self-contained directory structure:

- **Audit & QA Reports:**
  - `SAFETY_AUDIT_REPORT.md`: Exhaustive source code and interface audit.
  - `REUSE_VS_MISSING_MATRIX.csv`: Component reuse vs missing functionality matrix.
  - `PROTOCOL_FROZEN.md`: Prospectively frozen 30-trial protocol.
  - `AZURE_PREFLIGHT_REPORT.md`: Preflight host and cluster environment inspection.
  - `PREEXECUTION_QA_REPORT.md`: Unit test and dependency QA verification.
  - `SMOKE_TEST_REPORT.md`: Live qualification smoke test report.
- **Trial Data & Derived Summaries:**
  - `trial_results.csv`: Complete 30-row tabular record with timestamps, latencies, and verdicts.
  - `PRIMARY_RESULT.json`: Machine-readable audit certificate with Wilson 95% CIs.
  - `raw/S-E8-failure-robustness/`: 30 trial directories containing `result.json`, `pre-samples.json`, `post-samples.json`, `pre-frontend.log`, and `post-frontend.log`.
- **Integrity & Checksums:**
  - `RELEASE_SHA256SUMS.txt`: SHA-256 hashes of all source code, harness, and test files.
  - `SHA256SUMS.txt`: SHA-256 hashes of all deliverables and raw trial data.

**Conclusion:** The corrected S-E8 failure robustness campaign is scientifically sound, fully audited, empirically verified, and execution-ready for integration into the MAPE-CAP B+ manuscript and SSOT.
