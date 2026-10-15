# Feasibility-First Microservice Placement under State-Dependent Datacenter Network Constraints

Reproducibility artifacts for the manuscript submitted to **IEEE Transactions on Cloud Computing**.

This repository contains the **code, experiment configurations, frozen protocols, claim-supporting raw/derived results, and analysis scripts** used for the reported computational and experimental evidence.

## Scope

The paper studies feasibility-first cloud-native microservice placement under a **coupled, state-dependent network resource constraint**. Directional shared airtime is the evaluated realization.

The repository supports the reported evidence for that realization. It does **not** claim:

- physical 60-GHz rack validation;
- deployment-wide generalization to every datacenter fabric or workload;
- universal application-performance superiority of post-admission ranking;
- a uniform approximation guarantee for bounded LNS.

### Public-release boundaries

This public repository intentionally contains **no manuscript or submission files**:

- no manuscript PDF;
- no supplementary-paper PDF;
- no `main.tex` or `supplement.tex`;
- no Word manuscript;
- no cover letter.

A separate related **Paper2 / Paper II / B5** research line is also excluded from this repository.

## Repository structure

```text
ANALYSIS/            Reanalysis, independent checks, and manuscript-facing diagnostics
CODE/                Implementation, tests, Kubernetes/ns-3 support, and analysis code
EXPERIMENTS/         Executed E1/E2/E3 and other validation campaigns
EXTENSION_STUDIES/   N-series mechanism, comparator, solver, and live-system studies
RESULTS/             Audit records, post-campaign results, replications, and fault-path evidence
provenance/          Source-lineage, redaction, cleanup, and retention records
runbooks/            Execution guidance
tools/               Utility scripts
```

Root support files include `requirements-lock.txt`, run scripts, `.gitignore`, and `.gitattributes`.

## Where reviewers should start

For a direct paper-claim-to-file map, see:

**[`CLAIMS_TO_EVIDENCE.md`](CLAIMS_TO_EVIDENCE.md)**

For environments, commands, rerun guidance, study organization, and interpretation boundaries, see:

**[`REPRODUCIBILITY.md`](REPRODUCIBILITY.md)**

## Evidence overview

### RQ1 — Shared-resource admission and post-admission ranking

Key evidence:

- `EXTENSION_STUDIES/N2N3_admission_vs_ranking/`
- `EXTENSION_STUDIES/N2c_capacity_comparators/`
- `EXPERIMENTS/E1_E2_E3_validation_campaigns/E1_ns3_persistent_degradation/`
- `EXPERIMENTS/E1_E2_E3_validation_campaigns/E2_scale_admission/`
- `EXPERIMENTS/E1_E2_E3_validation_campaigns/E3_published_score_replay/`
- `ANALYSIS/current_manuscript/`

### RQ2 — Application effects in binding and nonbinding regimes

Key evidence:

- `EXTENSION_STUDIES/N5_live_binding_state/`
- `RESULTS/post-manuscript/multihost-k3s-n5-20261001/`
- `ANALYSIS/multihost_k3s/`

The repository retains negative/nonbinding evidence as well as the selected binding-state results.

### RQ3 — Solver certification and controller execution

Key evidence:

- `RESULTS/audit/randomized_exact_vs_exhaustive_120_reproducible.json`
- `EXTENSION_STUDIES/N4_solver_scaling/`
- `ANALYSIS/solver_replication_20seed/`
- `RESULTS/se8_corrected_campaign/`

Exact optimality is claimed only where certified. Bounded-LNS outputs outside that range are treated as admissible/incumbent evidence rather than approximation guarantees.

## Reproducibility philosophy

The artifact separates three evidence layers:

1. **model/mechanism evidence**;
2. **packet/emulation execution evidence**;
3. **Kubernetes application evidence**.

Evidence from one layer should not be interpreted as a stronger claim from another layer. Full infrastructure-heavy reruns are not required to inspect the archived results.

See `REPRODUCIBILITY.md` for detailed instructions.
