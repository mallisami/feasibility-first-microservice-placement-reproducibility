# Reproducibility Guide

This document describes the environments, experiment hierarchy, commands, and interpretation boundaries for the reproducibility artifact accompanying:

> **Feasibility-First Microservice Placement under State-Dependent Datacenter Network Constraints**

## 1. Common analysis environment

The repository includes `requirements-lock.txt` for the common Python analysis environment.

A typical setup is:

```bash
python -m venv .venv
```

Linux/macOS:

```bash
source .venv/bin/activate
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Then install the pinned Python dependencies:

```bash
pip install -r requirements-lock.txt
```

The cleaned artifact was verified using a Python 3.12-class environment. The pinned environment includes the NumPy, SciPy, pandas, matplotlib, pytest, PyYAML, and psutil versions recorded in `requirements-lock.txt`.

Different experimental layers have additional infrastructure requirements described by their frozen protocols and runbooks.

---

## 2. Experiment map

### 2.1 Controlled admission and mechanism studies

#### N2/N3 — Admission versus ranking

Directory:

```text
EXTENSION_STUDIES/N2N3_admission_vs_ranking/
```

Purpose:

- evaluates 150 controlled graphs;
- separates affinity-only placement, feasibility admission, and post-admission risk-aware ranking;
- retains complete cells, primary tests, held-out-state analysis, and outage-rotation analysis.

Representative rerun:

```bash
cd EXTENSION_STUDIES/N2N3_admission_vs_ranking
python run_n2n3.py
python analyze_heldout_mechanism.py
python run_n3b_outage_rotation.py
```

These exhaustive-placement analyses can be CPU-intensive.

#### N2c — Capacity comparators

Directory:

```text
EXTENSION_STUDIES/N2c_capacity_comparators/
```

Purpose:

- tests whether independent/per-link capacity abstractions reproduce the coupled shared-airtime admissible region;
- preserves the primary violation audit.

Representative rerun:

```bash
cd EXTENSION_STUDIES/N2c_capacity_comparators
python run_n2c.py
python binding_groups.py
python audit_check_risk_ranking.py
```

#### Packet-level shared-airtime boundary study

Directory:

```text
RESULTS/followup_validation/shared-airtime-boundary-20260930/
```

Purpose:

- preserves calibration and science cells for the packet-level shared-airtime boundary execution.

#### E1 — Persistent degradation

Directory:

```text
EXPERIMENTS/E1_E2_E3_validation_campaigns/E1_ns3_persistent_degradation/
```

Purpose:

- packet-level execution of the persistent-degradation state;
- supports the admission-effect execution result;
- retains the claim-supporting cell-level and summary outputs.

#### E2 — Scale admission

Directory:

```text
EXPERIMENTS/E1_E2_E3_validation_campaigns/E2_scale_admission/
```

Purpose:

- evaluates the scale-admission mechanism over 12, 16, and 24 replicas and four declared load intensities.

#### E3 — Published score replay

Directory:

```text
EXPERIMENTS/E1_E2_E3_validation_campaigns/E3_published_score_replay/
```

Purpose:

- replays the external node-scoring comparator across the controlled graph/load grid;
- records explicit shared-resource violation accounting.

---

## 3. Application execution studies

### N5 live binding-state study

Directory:

```text
EXTENSION_STUDIES/N5_live_binding_state/
```

Contains the original live binding-state Kubernetes evaluation and its frozen protocol.

### Multi-host k3s replication

Directory:

```text
RESULTS/followup_validation/multihost-k3s-n5-20261001/
```

The replication uses three distinct VM/OS-backed Kubernetes hosts, one per logical rack.

This establishes separation at the VM/OS host level. It does **not** establish that the cloud provider placed those VMs on three distinct physical servers.

The selected 20-graph binding-state study should be interpreted as a **conditional selected-regime study**, not a deployment-wide population estimate.

---

## 4. Solver and controller studies

### Exact-versus-exhaustive correctness

Artifact:

```text
RESULTS/audit/randomized_exact_vs_exhaustive_120_reproducible.json
```

This preserves the randomized exact-versus-exhaustive correctness check.

### N4 matched-budget solver scaling

Directory:

```text
EXTENSION_STUDIES/N4_solver_scaling/
```

Exact and bounded LNS are evaluated under declared finite budgets.

Rows without an Exact proof certificate are not converted into optimality claims.

### Independent 20-seed solver replication

Directory:

```text
ANALYSIS/solver_replication_20seed/
```

Raw rows:

```text
ANALYSIS/solver_replication_20seed/ext_rows.csv
```

Execution script:

```text
ANALYSIS/solver_replication_20seed/solver_scale_ext.py
```

The archived replication uses fresh seeds 111–130 at 16, 20, and 24 replicas under the recorded 30-second budget.

### Controller and fault-path evidence

Directory:

```text
RESULTS/controller_safety_and_fault_path/
```

Contains the frozen protocol, trial-level evidence, relocation/calibration records, and controller execution/abstention safety results.

---

## 5. Deterministic manuscript-facing analyses

Directory:

```text
ANALYSIS/derived_diagnostics/
```

This directory contains deterministic analyses derived from frozen candidate sets:

- critical admissible load (`tau_c`);
- admitted-set Pareto analysis;
- finite exact-penalty diagnostics.

A combined recomputation entry point is:

```bash
python ANALYSIS/derived_diagnostics/recompute_derived_diagnostics.py
```

The component analyses can also be run independently:

```bash
python ANALYSIS/derived_diagnostics/critical_load_analysis.py
python ANALYSIS/derived_diagnostics/pareto_analysis.py
python ANALYSIS/derived_diagnostics/exact_penalty_bound.py
```

The E1 utilization/delivery reanalysis is located at:

```text
ANALYSIS/E1_u_delivery_margin/
```

Representative rerun:

```bash
python ANALYSIS/E1_u_delivery_margin/u_delivery_margin.py
```

The stored output preserves the observed low-utilization delivery anomaly rather than forcing a monotonic interpretation.

---

## 6. ns-3 and Kubernetes reruns

Full live or packet-level campaigns require infrastructure beyond the common Python environment.

### ns-3 / WiGig

Relevant implementation and build material is under:

```text
CODE/kubernetes/simulator/
```

Study-specific execution details are preserved in the associated frozen protocols and runbooks.

The ns-3/WiGig evidence is simulation/emulation evidence and must not be interpreted as physical 60-GHz rack calibration.

### Kubernetes / k3s

Study-specific Kubernetes requirements are recorded under the corresponding:

```text
EXPERIMENTS/.../protocol/
```

or:

```text
EXTENSION_STUDIES/.../PROTOCOL_FROZEN.md
```

The multi-host k3s execution records are under:

```text
RESULTS/followup_validation/multihost-k3s-n5-20261001/
```

Because live-system timings are environment-sensitive, the paper separates mechanism/correctness claims from environment-specific performance observations.

---

## 7. Expected reproduction cost

Approximate qualitative costs:

| Task | Expected cost |
|---|---|
| CSV/JSON inspection and lightweight reanalysis | seconds to minutes |
| deterministic manuscript diagnostics | seconds to minutes |
| exhaustive N2/N3/N2c analysis | potentially hours |
| N4 solver campaign | order of hours |
| ns-3 campaigns | hours and environment-dependent |
| live Kubernetes/k3s campaigns | hours and infrastructure-dependent |

These times are operational guidance, not performance claims.

---

## 8. Interpretation boundaries

The artifact supports:

- feasibility-first placement under the declared coupled state-dependent resource contract;
- directional shared airtime as the evaluated realization;
- controlled admission/mechanism studies;
- per-link/capacity comparator diagnostics;
- packet-level ns-3/WiGig execution;
- selected Kubernetes binding/nonbinding evidence;
- VM/OS-separated k3s replication;
- exact-versus-exhaustive correctness;
- finite-budget Exact/LNS scaling;
- independent fresh-seed solver replication;
- controller/fault-path/abstention studies;
- deterministic analyses of frozen candidate sets.

The artifact does **not** establish:

- physical 60-GHz rack calibration;
- universal transfer to every datacenter fabric;
- deployment-wide superiority of post-admission risk-aware ranking;
- a uniform approximation guarantee for bounded LNS;
- a deterministic replica-count threshold at which Exact must stop certifying;
- physical-server separation underneath the cloud-provider VM layer.

---

## 9. Public repository and data hygiene

The public reproducibility repository intentionally excludes manuscript/submission files and the separate Paper2/Paper-II/B5 research line.

The distributed repository retains code, protocols/configurations, claim-supporting raw and derived outputs, and analysis material needed for the paper-level evidence trail.

Extremely high-volume packet/telemetry traces that are unnecessary for checking the reported manuscript-level quantities are not included in the public Git repository.

Where public-cloud addressing information required removal from distribution copies, the corresponding provenance record is retained under:

```text
provenance/
```

No private-key or credential file is intended for distribution.
