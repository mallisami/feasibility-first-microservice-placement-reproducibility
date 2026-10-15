# Claims-to-Evidence Map

This map is limited to evidence that materially supports the submitted IEEE Transactions on Cloud Computing manuscript:

> **Feasibility-First Microservice Placement under State-Dependent Datacenter Network Constraints**

Historical and exploratory material may remain in the repository for provenance or robustness, but the table below identifies the principal evidence trail for the paper.

| Evidence role | Claim / quantity | Primary artifact(s) | Independent/checking artifact(s) |
|---|---|---|---|
| **RQ1 — admission** | At `tau=1.25`, Affinity-Bytes is admissible on **126/150** graphs, while Affinity-Bytes+Admission and MAPE-CAP-WS are admissible on **150/150**; the difference exposes 24 primary discordant graphs | `EXTENSION_STUDIES/N2N3_admission_vs_ranking/cell_results.csv`, `primary_tests.json`, `RESULTS.md` | `ANALYSIS/current_manuscript/run_n2n3_fixed.py` |
| **RQ1 — capacity mechanism** | Independent per-link/capacity-style checks do not reproduce the coupled shared-airtime admissible region; unshared per-direction airtime leaves most primary violations unresolved | `EXTENSION_STUDIES/N2c_capacity_comparators/n2c_cells.csv`, `n2c_summary.csv`, `AUDIT_CHECK.md` | `audit_check_cells.csv`, `audit_check_risk_ranking.py` |
| **RQ1 — packet construct** | Packet execution degrades as the declared shared-airtime resource becomes over-budget; the boundary campaign preserves calibration and science cells | `RESULTS/post-manuscript/shared-airtime-boundary-20260930/run-20260930T163137Z/science_cells.csv`, `FINAL_REPORT.md` | `ANALYSIS/shared_airtime_boundary/RESULT_AUDIT.md` |
| **RQ1/RQ2 — admission execution effect** | Across 150 E1 graphs, admission minus affinity improves mean delivered fraction by about **+0.02143**; 17 graphs gain sustained delivery with no reverse discordance | `EXPERIMENTS/E1_E2_E3_validation_campaigns/E1_ns3_persistent_degradation/results/run-20261003T005802Z/SUMMARY.json`, `cell_results.csv` | `ANALYSIS/E1_ns3_persistent_degradation/RESULT_AUDIT.md`, `ANALYSIS/E1_u_delivery_margin/` |
| **RQ1 — scale** | The scale-admission campaign contains **600 graph-load cells** over 12/16/24 replicas and four load intensities | `EXPERIMENTS/E1_E2_E3_validation_campaigns/E2_scale_admission/results/scale_cells.csv`, `SUMMARY.json` | `ANALYSIS/E2_scale_admission/RESULT_AUDIT.md` |
| **RQ1 — external heuristic replay** | Published node-scoring replay is evaluated over 150 graphs × 4 loads with explicit shared-resource violation accounting | `EXPERIMENTS/E1_E2_E3_validation_campaigns/E3_published_score_replay/results/score_replay_cells.csv`, `RESULTS.md` | `ANALYSIS/E3_published_score_replay/RESULT_AUDIT.md` |
| **RQ1 — derived structure** | Critical admissible load, admitted-set Pareto structure, and finite exact-penalty diagnostics are computed from frozen candidate sets | `ANALYSIS/current_manuscript/critical_load_*`, `pareto_*`, `exact_penalty_*` | scripts in `ANALYSIS/current_manuscript/` |
| **RQ2 — binding-state Kubernetes** | In the selected 20-graph multi-host binding-state study, admission raises mean scheduled completion from about **0.9014 to 1.0000**; ranking after admission produces a completion tie | `RESULTS/post-manuscript/multihost-k3s-n5-20261001/run-20261001T151036Z/analysis/multihost_primary.csv`, `FINAL_REPORT.md` | `ANALYSIS/multihost_k3s/RESULT_AUDIT.md` |
| **RQ2 — original live study** | The original binding-state study and frozen protocol are retained independently of the later host-separated replication | `EXTENSION_STUDIES/N5_live_binding_state/PROTOCOL_FROZEN.md`, `RESULTS.md`, `analysis/` | later multi-host replication above |
| **RQ3 — exact correctness** | The Exact optimizer is checked against exhaustive enumeration on **120 randomized instances** | `RESULTS/audit/randomized_exact_vs_exhaustive_120_reproducible.json` | implementation/tests under `CODE/` |
| **RQ3 — matched-budget scaling** | Exact and bounded LNS are compared under declared finite budgets; uncertified rows are not labeled optimal | `EXTENSION_STUDIES/N4_solver_scaling/RESULTS.md`, `analysis/` | independent 20-seed replication below |
| **RQ3 — independent solver replication** | Fresh seeds 111–130: Exact certifies **20/20** at 16 replicas, **20/20** at 20, and **11/20** at 24; LNS returns an admissible placement on **20/20** at each size | `ANALYSIS/solver_replication_20seed/ext_rows.csv` | `ANALYSIS/solver_replication_20seed/solver_scale_ext.py` |
| **RQ3 — controller/fault path** | Controller relocation, calibration, and abstention/fault handling are preserved with frozen protocols and trial-level evidence | `RESULTS/se8_corrected_campaign/PROTOCOL_FROZEN.md`, `trial_results.csv`, `FINAL_SAFETY_REPORT.md` | `SAFETY_AUDIT_REPORT.md` |

## Interpretation guardrail

The repository distinguishes:

1. **model/mechanism evidence**;
2. **packet/emulation execution evidence**;
3. **Kubernetes application evidence**.

A result from one layer should not be silently promoted into a stronger physical-deployment claim.

For environment details and rerun instructions, see [`REPRODUCIBILITY.md`](REPRODUCIBILITY.md).
