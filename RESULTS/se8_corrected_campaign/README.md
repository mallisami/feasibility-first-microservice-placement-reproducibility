# MCB S-E8 Corrected Safety & Fault-Injection Experiment Package

**Package Name:** `MCB_SE8_CORRECTED_AZURE_FINAL`  
**Protocol:** `SE8-CORRECTED-FROZEN-v1.0`  
**Execution Host:** Azure Virtual Machine (`Standard_D4as_v5`, 4 vCPUs AMD EPYC 7763, 16 GiB RAM, Ubuntu 24.04 LTS)  
**Cluster:** Kubernetes v1.37.0 on Kind v0.33.0 (`mcb-k137`, 3 worker nodes)  
**Target Application:** Google Cloud Online Boutique (11 microservices + 1 loadgenerator, 12 pods)  
**Evaluator:** Scientific Reproducibility Auditor & Senior Systems Engineer  

---

## 1. Overview

This self-contained package contains the complete audit, verified implementation, raw trial evidence, analysis scripts, and manuscript integration diffs for the corrected **S-E8 Failure Robustness and Fault Injection Campaign** of the MAPE-CAP B+ project.

### Core Scientific Findings
- **Total Trials:** 30 trials (6 distinct fault classes $\times$ 5 replicates).
- **Overall Strict Safety:** **30 / 30 (100.0%)**, 95% Wilson score confidence interval: **[0.8865, 1.0000]**.
- **Pre-Execution Target Validation (F5):** Intercepted invalid target specifications in 5/5 replicates before any mutation (mean latency: 390 ms). Authoritatively verified 0 Kubernetes API mutations via unchanged deployment generations and resourceVersions.
- **Partial-Mutation Transactional Rollback (F6):** A deterministic test hook injected failure after the first microservice mutation. The controller detected the failure, initiated compensating rollback, restored original node selectors, returned all 12/12 pods to `1/1 Running`, and recovered HTTP frontend probes in under 28 seconds (mean: 15.1 s).

---

## 2. Directory Structure

```
MCB_SE8_CORRECTED_AZURE_FINAL/
|-- README.md                    # This document
|-- SAFETY_AUDIT_REPORT.md       # Phase 1-2 source code and interface audit
|-- REUSE_VS_MISSING_MATRIX.csv  # Inventory of reused vs newly developed components
|-- PROTOCOL_FROZEN.md           # Prospectively frozen 30-trial protocol
|-- AZURE_PREFLIGHT_REPORT.md    # Host hardware, kernel, Docker, and cluster inspection
|-- PREEXECUTION_QA_REPORT.md    # Unit test and pre-execution QA verification
|-- SMOKE_TEST_REPORT.md         # Live qualification smoke test report
|-- FINAL_SAFETY_REPORT.md       # Comprehensive scientific findings and statistical analysis
|-- PRIMARY_RESULT.json          # Authoritative machine-readable validation certificate
|-- trial_results.csv            # 30-trial tabular outcomes, latencies, and verdicts
|-- CHANGELOG.md                 # Complete record of modifications and additions
|-- MANUSCRIPT_INTEGRATION.md    # Precise diffs and LaTeX text replacements for paper SSOT
|-- RELEASE_SHA256SUMS.txt       # Frozen release file checksums
|-- SHA256SUMS.txt               # SHA-256 hashes of all deliverable files
|-- implementation/              # Source code, runners, tests, and validator
|   |-- code/                    # Core controller and placement implementations
|   |-- strengthening/           # S-E8 campaign runner and independent validator
|   `-- tests/                   # Safety and unit regression tests
`-- evidence/                    # Complete empirical trial data
    |-- raw/                     # 30 trial cells with snapshots, samples, and logs
    `-- derived/                 # Tabular CSV and summary JSON
```

---

## 3. How to Verify Reproducibility

### 3.1 Verify File Hashes
```bash
sha256sum -c SHA256SUMS.txt
```

### 3.2 Run Unit Regression Tests
```bash
python3 -m pytest implementation/tests/test_v03_r1_safety.py
```

### 3.3 Re-run Independent Validation
To verify all 30 trial records without running new cluster mutations:
```bash
python3 implementation/strengthening/validate_se8_results.py evidence
```
Expected output:
```
INDEPENDENT VERIFICATION RESULT: PASS (100% STRICT SAFE)
```

---

## 4. Manuscript Integration

Refer to `MANUSCRIPT_INTEGRATION.md` for exact LaTeX snippets to update `PAPER/main.tex` and `PAPER/supplement.tex`. Historical 25-trial data is preserved as provenance; the new 30-trial evidence is integrated as `S-E8-corrected`.
