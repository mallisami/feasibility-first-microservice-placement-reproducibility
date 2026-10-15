# CHANGELOG: Corrected S-E8 Failure Robustness and Fault Injection Campaign

All notable changes made to audit, complete, and execute the S-E8 failure robustness experiment within the MAPE-CAP B+ SSOT are documented in this file.

The project adheres to scientific reproducibility and strict semantic tracking.

---

## [1.0.0-corrected] - 2026-09-19

### Scientific Protocol and Experimental Design
- **Prospective Protocol Freeze (`PROTOCOL_FROZEN.md`)**:
  - Reconciled historical S-E8 flaw where invalid target injection bypassed controller validation by manually calling `kubectl patch`.
  - Bifurcated historical action-failure into two distinct scientific fault classes:
    - `F5-invalid-target-prevalidation`: Pre-execution target validation before first Kubernetes mutation.
    - `F6-partial-mutation-rollback`: Controlled partial-mutation failure with transactional rollback and recovery verification.
  - Frozen immutable denominator of 6 fault classes $\times$ 5 replicates = **30 trials**.

### Implementation and Controller Enhancements
- **Pre-Execution Target Validation (`implementation/code/run_v03_r1.py:validate_placement_target`)**:
  - Implemented strict prevalidation checks before any mutating API calls:
    - Target node existence in cluster.
    - Node Ready condition and unschedulable (cordoned) status.
    - Deployment existence in target namespace (`online-boutique`).
    - CPU and memory capacity bounds.
  - Enforced fail-closed behavior with diagnostic `ValueError`.
- **Dynamic Worker Discovery (`implementation/code/run_v03_r1.py:_detect_workers`)**:
  - Added dynamic node detection via `kubectl get nodes` to automatically discover active worker node topologies (supporting both `mcb-k137-worker` and `mape-cap-bplus-worker` prefixes) while preserving explicit override via `MCB_R1_WORKERS`.
- **Rich Placement Snapshots (`implementation/code/run_v03_r1.py:capture_placement_snapshot`)**:
  - Implemented full-fidelity snapshot mechanism capturing:
    - Deployment generation and `observedGeneration`.
    - Deployment and pod `resourceVersion`.
    - NodeSelector assignments.
    - Actual pod phase, node placement, and container readiness.
    - Cluster node states.
- **Partial-Mutation Test Hook (`implementation/code/run_v03_r1.py:apply_placement`)**:
  - Added optional testing `fault_hook` callback executed deterministically after at least one real Kubernetes patch succeeds but before rollout completes.
  - Triggered transactional rollback handler upon failure.
- **Rollback and Health Recovery Handler (`implementation/code/run_v03_r1.py:apply_placement`)**:
  - Enhanced rollback handler to apply compensating reverse patches to all previously mutated services.
  - Awaits `kubectl rollout status` on restored deployments.
  - Executes `wait_healthy()` and HTTP frontend probing (`frontend_probe()`) to ensure complete service recovery.
- **Resilient Tracing Controller (`implementation/code/run_v03_r2.py:set_tracing`)**:
  - Added discovery check for `deployment/opentelemetrycollector` to prevent crashes when executing against core application clusters where optional telemetry collectors are omitted.

### Test Harness & Validation Tools
- **Test Runner (`implementation/strengthening/run_se8_failure_robustness.py`)**:
  - Added `inject_f5_invalid_target_prevalidation` asserting zero mutations via pre/post generation and resourceVersion equality.
  - Added `inject_f6_partial_mutation_rollback` asserting single forward patch, hook interception, compensating rollback, and full pod readiness.
  - Preserved historical `inject_f5_k8s_action_failure` for provenance comparison.
  - Added per-trial frontend structured request logs and resource snapshots.
- **Independent Scientific Validator (`implementation/strengthening/validate_se8_results.py`)**:
  - Built standalone evaluator reading immutable raw JSON artifacts without relying on runner-internal success flags.
  - Audits zero mutations for F5, partial mutation and rollback for F6, pod readiness, and frontend probes.
  - Computes Wilson score 95% confidence intervals per fault class and across the full campaign.
- **Unit and Local QA Tests (`implementation/tests/test_v03_r1_safety.py`)**:
  - Fixed test runner defect in `progress()` signature.
  - Added unit tests for snapshot capture, target prevalidation rejection, zero mutations, and fault hooks.
  - All 60/60 unit tests pass.

### Execution Evidence and Deliverables
- **Live Smoke Qualification (`SMOKE_TEST_REPORT.md`)**:
  - Verified F5 pre-execution rejection (0 mutations, latency 0.380s).
  - Verified F6 mid-mutation rollback (latency 15.746s, 100% recovery).
- **Full Campaign Execution**:
  - Executed all 30 frozen trials on Azure VM (`Standard_D4as_v5`, Kind v0.33.0, Kubernetes v1.37.0).
  - Result: 30 / 30 trials **Strict-Safe** (100.0%, 95% CI [0.8865, 1.0000]).
- **Self-Contained Package (`MCB_SE8_CORRECTED_AZURE_FINAL.zip`)**:
  - Created complete archive containing all reports, raw evidence, logs, implementation, and manuscript integration guide.
