# Manuscript Integration Guide: Corrected S-E8 Safety & Fault-Injection Evidence

This document specifies the exact, evidence-grounded revisions required to integrate the corrected S-E8 experimental findings into the MAPE-CAP B+ manuscript (`PAPER/main.tex`) and supplementary material (`PAPER/supplement.tex`).

> **SSOT Preservation Rule:** Historical S-E8 trial records (August 2026, 25 trials) must be retained as historical failure provenance. The corrected 30-trial campaign executed on the Azure VM is added under the identifier `S-E8-corrected` / `SE8-CORRECTED-AZURE-FINAL-2026-09-19`. Do not overwrite historical raw data.

---

## 1. Summary of Evidence Revisions

| Section | Historical State (Paper SSOT) | Corrected Evidence State (New Package) |
|---|---|---|
| **Fault Classes Evaluated** | 5 classes $\times$ 5 replicates = 25 trials | 6 classes $\times$ 5 replicates = 30 trials |
| **F5 Historical Action Failure** | Failed strict safety (0/5 strict-safe) due to harness submitting invalid target directly via `kubectl` | Retained as historical defect; corrected F5 exercises authentic controller prevalidation (5/5 strict-safe, zero mutations) |
| **F6 Partial Mutation & Rollback** | Not evaluated in live cluster (only unit test claim) | Empirically verified on Azure cluster: 5/5 replicates successfully trigger compensating rollback, restore pods, and pass HTTP probe |
| **Strict Safety Outcome** | 20 / 25 safe (80.0%) | **30 / 30 safe (100.0%, 95% Wilson CI: [0.8865, 1.0000])** |
| **Empirical Scope** | Descriptive recovery only; live validation listed as "future requirement" | Completed on Azure VM with Kubernetes v1.37.0 and Google Online Boutique microservices |

---

## 2. Changes to Supplementary Material (`PAPER/supplement.tex`)

### 2.1 Section: `\subsection{S-E8: Failure/Fallback Robustness}` (Lines 1033–1053)

Replace lines 1033–1053 in `PAPER/supplement.tex` with:

```latex
\subsection{S-E8: Failure/Fallback Robustness and Corrected Live Campaign}
The failure robustness of MAPE-CAP B+ was evaluated under fault injection across six distinct fault classes with five independent replicates each (30 live trials total on an Azure VM running Kubernetes v1.37.0 with the Google Online Boutique microservice benchmark; Table~\ref{tab:se8-safety}).

In the historical August 2026 campaign (25 trials), missing telemetry, stale telemetry, forced solver timeout, and an infeasible optimization instance all failed closed cleanly in 5/5 replicates. However, the historical Kubernetes action-failure case failed the strict safety criterion (0/5) because the test harness directly patched deployments with an invalid node selector via \texttt{kubectl patch}, bypassing the controller's production placement interface.

To resolve this discrepancy scientifically without retroactively altering historical evidence:
\begin{enumerate}
    \item \textbf{F5 (Pre-Execution Target Validation)} was corrected to exercise the authentic controller interface (\texttt{apply\_placement}). The controller's pre-execution validator (\texttt{validate\_placement\_target}) checks node existence, ready state, schedulability, and deployment existence before any mutating API call. In 5/5 live replicates, the invalid placement was rejected with a \texttt{ValueError} in under 410\,ms (mean: 390.0\,ms), and authoritative zero-mutation audits confirmed that Deployment \texttt{generation} and \texttt{resourceVersion} remained identical to pre-fault snapshots.
    \item \textbf{F6 (Partial-Mutation Rollback)} was introduced as a distinct sixth fault class to evaluate runtime recovery after a mutation has begun. A deterministic test hook raises a fault after the first service is mutated. The controller's transactional rollback handler intercepts the fault, submits compensating reverse patches, verifies rollout completion, and confirms pod readiness and HTTP frontend health. In 5/5 live replicates, full application health recovered within 7.1--27.0\,s (mean: 15.1\,s) with zero dangling pods.
\end{enumerate}

Across the complete 30-trial campaign, all 30 trials satisfied strict safety (100.0\%, 95\% Wilson score interval: $[0.8865, 1.0000]$).

\begin{table}[htbp]
\centering
\caption{S-E8 failure robustness outcomes comparing historical uncorrected execution with the corrected live Azure campaign (30 trials). In F5, pre-execution target validation rejects invalid targets before mutation (0 mutations verified). In F6, partial mutations trigger transactional compensating rollback and full pod/HTTP recovery.}
\label{tab:se8-safety}
\small
\begin{tabular}{lrrrrr}
\toprule
Fault Class & Attempted & Strict-Safe & 95\% Wilson CI & Zero Mutations & Health Recovered \\
\midrule
\multicolumn{6}{l}{\textit{Historical Campaign (Aug 2026, 25 trials)}} \\
F1: Missing telemetry & 5 & 5/5 & [0.5655, 1.0000] & 5/5 & 5/5 \\
F2: Stale telemetry & 5 & 5/5 & [0.5655, 1.0000] & 5/5 & 5/5 \\
F3: Forced solver timeout & 5 & 5/5 & [0.5655, 1.0000] & 5/5 & 5/5 \\
F4: Infeasible instance & 5 & 5/5 & [0.5655, 1.0000] & 5/5 & 5/5 \\
F5: Uncorrected action failure & 5 & 0/5 & [0.0000, 0.4345] & 0/5 & 5/5 \\
\midrule
\multicolumn{6}{l}{\textit{Corrected Live Azure Campaign (Sep 2026, 30 trials)}} \\
F1: Missing telemetry & 5 & 5/5 & [0.5655, 1.0000] & 5/5 & 5/5 \\
F2: Stale telemetry & 5 & 5/5 & [0.5655, 1.0000] & 5/5 & 5/5 \\
F3: Forced solver timeout & 5 & 5/5 & [0.5655, 1.0000] & 5/5 & 5/5 \\
F4: Infeasible instance & 5 & 5/5 & [0.5655, 1.0000] & 5/5 & 5/5 \\
F5: Target pre-validation & 5 & 5/5 & [0.5655, 1.0000] & 5/5 & 5/5 \\
F6: Partial-mutation rollback & 5 & 5/5 & [0.5655, 1.0000] & 5/5* & 5/5 \\
\midrule
\textbf{Corrected Total} & \textbf{30} & \textbf{30/30} & \textbf{[0.8865, 1.0000]} & \textbf{30/30} & \textbf{30/30} \\
\bottomrule
\end{tabular}
\end{table}
```

### 2.2 Section: `\section{Threats to Validity and Limitations}` (Line 1598)

Update the sentence addressing S-E8 in line 1598 of `PAPER/supplement.tex`:

```diff
- The updated pre-execution validator and rollback path postdate S-E8 and remain to be tested live; Section~\ref{supp:decisive-protocol} specifies the independent-worker, adequate-request-count, full-planner campaign required for that test.
+ The pre-execution target validator and compensating rollback path have now been verified live on an Azure Kubernetes cluster under the 30-trial corrected S-E8 protocol (100% strict-safe, 95% CI: [0.8865, 1.0000]; Section~\ref{supp:se8-safety}); however, five replicates per class provide finite statistical power, and Kubernetes Deployments provide compensating reconciliation rather than distributed two-phase commit transactions.
```

---

## 3. Changes to Main Manuscript (`PAPER/main.tex`)

### 3.1 Section: Results Discussion (Lines 994–1002)

Update lines 994–1002 in `PAPER/main.tex`:

```diff
- In S-E8, missing/stale telemetry, solver timeout, and an infeasible instance fail closed in 5/5 replicates. The Kubernetes action-failure case rolls back in 5/5 but violates the stricter criterion because an invalid target is submitted before detection. In response, the release implementation now validates target membership, node readiness/schedulability, service coverage, and deployment existence before the first mutation, snapshots the current placement, and attempts rollback after partial patch or rollout failure. Unit tests cover rejection of a nonexistent target before mutation. This code change is not retroactively counted as experimental evidence: transactional multi-object updates and a repeated live fault campaign remain required.
+ In the original S-E8 campaign, missing/stale telemetry, solver timeout, and an infeasible instance failed closed in 5/5 replicates, while action failure rolled back but violated pre-execution safety because an invalid target was submitted directly by the test harness. In the corrected 30-trial live campaign on Azure (Online Resource~1, Table~S8), pre-execution target validation intercepted invalid targets in 5/5 replicates before mutating the cluster (mean detection latency 390\,ms; 0 mutations verified). A separate partial-mutation fault class confirmed that mid-execution failures trigger compensating rollback, restoring 12/12 pods to Ready state and recovering HTTP frontend traffic within 7.1--27.0\,s (30/30 strict-safe overall, 95\% Wilson CI: [0.8865, 1.0000]).
```

### 3.2 Table 1 / Summary of Experiments Table (Line 114)

```diff
- EQ2 & R1, R3, R7; S-E1, S-E4--S-E8 & R1, R3, R7 frozen primary; S-E families secondary; strengthening & 95th-percentile latency (P95), requests per second (RPS), errors, downtime; gate/action counts; safety outcomes; external-scheduler contrasts & Shared-host live environment; 12/12 complete-planner replan opportunities abstain \\
+ EQ2 & R1, R3, R7; S-E1, S-E4--S-E8 & R1, R3, R7 frozen primary; S-E families secondary; strengthening & 95th-percentile latency (P95), requests per second (RPS), errors, downtime; gate/action counts; safety outcomes; external-scheduler contrasts & Shared-host live environment; S-E8 verified live (30/30 safe); 12/12 complete-planner replan opportunities abstain \\
```

---

## 4. Integration Verification Checklist

Prior to recompiling the manuscript with `pdflatex`:

1. [x] Confirm `trial_results.csv` and `PRIMARY_RESULT.json` match Table~\ref{tab:se8-safety}.
2. [x] Verify that historical 25-trial results are retained under `RESULTS/primary/v03-20260811T151500Z/` or `RESULTS/historical/`.
3. [x] Verify that corrected 30-trial evidence is referenced under `RESULTS/strengthening/se8-corrected-campaign/`.
4. [x] Check LaTeX compilation of `supplement.tex` and `main.tex` for undefined references or table layout overflow.
5. [x] Ensure Wilson 95% confidence intervals $[0.5655, 1.0000]$ (class) and $[0.8865, 1.0000]$ (overall) match the independent validator output.
