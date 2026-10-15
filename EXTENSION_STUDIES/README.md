# Extension studies added in the 26 September 2026 revision

These studies support Sections 6.1–6.3 of the main manuscript and the "Extension Studies" section of Online Resource 1. Each study folder holds the protocol written before execution (`PROTOCOL_FROZEN.md`), the code that ran, its raw outputs, the analysis script, its outputs and a `RESULTS.md` with the numbers as reported. The original evidence under `../../RESULTS`, `../../EXPERIMENTS` and `../../implementation` is imported, not copied, except for the exact code subset that was uploaded to the execution host (`frozen_code/pkg/`).

| Folder | Study | Ran where | Paper location |
|---|---|---|---|
| `N2N3_admission_vs_ranking/` | **N1** regime map over 31 loads; **N2** Affinity-Bytes+Admission and Risk-off comparators; **N3** withheld-state admissibility; **N3b** outage rotation (post hoc) | offline (WSL) | Main §6.1: Fig. 3 (regime map), Table 7, Fig. 5 (rotation); OR1 |
| `N2c_capacity_comparators/` | **N2c** which airtime group binds; byte affinity with per-link rate capacity and with a per-pair airtime budget (protocol frozen before computation); `audit_check_risk_ranking.py` adds the post-hoc per-direction budget and MAPE-CAP-WS-ranking checks | offline | Main §6.1 "Which part of the admission constraint binds"; OR1 |
| `T4_outage_resolve/` | **T4** re-solve of the controlled-topology outage cells that failed with a solver model error in the original campaign; reconstruction gate reproduces every completed method first | offline | Main Table 4 (rows marked r); OR1 |
| `N5_live_binding_state/` | **N5** live Kind study executing the binding wireless state; 100 cells (20 + 10 graphs) | Azure VM | Main §6.2 Table 8; OR1 |
| `N4_solver_scaling/` | **N4** Exact vs LNS under a matched 30-s budget, 10–100 replicas, 10 seeds, 280 rows | Azure VM | Main §6.3 Table 11; OR1 |
| `checks/` | Independent verification scripts used in the final audit: MILP sizes on the real planning instances, live-comparison claims, derived counts quoted in §6.1 | offline | — |
| `figure_layout/` | Re-plots the 24-graph trade-off figure from the original generator's data loader with a clearer layout (data unchanged) | offline | Main Fig. 4 |
| `frozen_code/pkg/` | The exact code subset uploaded to the VM for N5 and N4 (planner package, live harness, canonical trace); hashes recorded in `N5_live_binding_state/raw/results/frozen/preexecution_manifest.json` | — | — |
| `vm_run/` | Sequential runner used on the VM (`run_all.sh`), its log and status, the checksums computed on the VM at completion (`RESULTS_SHA256SUMS.txt`), and the environment record | Azure VM | — |
| `tools/setup_venv.sh` | Creates a virtual environment with the pinned versions | — | — |
| `ENVIRONMENT.md` | Hardware, OS, container and library versions for the offline and VM runs | | |
| `PATCH_NOTES.md` | The six path edits made so the scripts run from this package | | |
| `SHA256SUMS_as_executed.txt` | Per-file hashes of this folder at execution time (before the path edits) | | |

## Headline numbers (as reported; recompute commands below)

- **N2/N3 (τ = 1.25, 150 graphs), MAPE-CAP-WS minus Affinity-Bytes+Admission:** headroom −0.139 [−0.168, −0.111]; cross-rack bytes +2.92e8 [2.42e8, 3.44e8]; admissible on all withheld states 41.3 % vs 22.0 %, RD +0.193 [+0.107, +0.273], Holm p = 2.5e−5. Identical placements 44/150. The whole withheld-state difference arises in the outage state; N3b shows it depends on which rack pair fails (72 / 62 / 0 vs 29 / 33 / 7 graphs).
- **N2c:** every Affinity-Bytes violation at τ = 1.0 and 1.25 overloads one rack pair's two-direction group in persistent degradation. Per-link rate capacity reproduces plain affinity in 4,649 of 4,650 cells. A per-pair airtime budget matches full admission up to τ = 1.30; the multi-pair group binds for byte affinity from τ = 1.35. Post-hoc check: an unshared per-direction budget still leaves 21 of 24 violations; the MAPE-CAP-WS ranking with per-pair budgets only exceeds the multi-pair budget on 3 of 150 graphs at τ = 1.25.
- **T4:** all 90 outage instances reconstructed; all 180 re-solved cells complete and admissible. Means DetNet / MAPE-CAP-WS: A 11291.6 / 11291.6; B 10557.1 / 8906.2; C 11970.3 / 8981.2.
- **N5 (S1, 20 graphs):** admission lowers scheduled-request P95 by 2,123 ms [1,627, 2,523] (20/20, Holm p = 4e−6) and raises completion from 0.901 to 1.000; ranking adds +19.8 ms [2.5, 41.9] (14/20, Holm p = 0.040). All 100 cells accepted on the first attempt.
- **N4:** Exact proves optimality on 10/10 instances up to 16 replicas and on none from 40; skipping the LNS initialization is worse on 20/20 instances at 40–50 replicas (Wilcoxon p = 0.002 each); one Exact input-validation rejection (50 replicas, seed 105).

## Recompute from raw records (seconds each)

From this folder, with the pinned environment (`bash tools/setup_venv.sh`, or `pip install -r ../../implementation/requirements-lock.txt`):

```bash
python N5_live_binding_state/analyze_n5.py N5_live_binding_state/raw/results out/n5
python N4_solver_scaling/analyze_n4.py N4_solver_scaling/raw/results/n4_rows.csv out/n4
python N2N3_admission_vs_ranking/analyze_heldout_mechanism.py
python N2N3_admission_vs_ranking/make_figures.py            # writes ../../PAPER/figures/rev/
python checks/verify_audit_numbers.py
python checks/affk8s_live_claims_check.py
```

Compare `out/n5` with `N5_live_binding_state/analysis/` and `out/n4` with `N4_solver_scaling/analysis/`.

## Recompute the offline studies from their instances (CPU only)

```bash
python N2N3_admission_vs_ranking/run_n2n3.py                 # 1–3 h; reproduction gate on 2,700 original cells first
python N2N3_admission_vs_ranking/run_n3b_outage_rotation.py  # minutes
python N2c_capacity_comparators/run_n2c.py                   # 1–2 h
python N2c_capacity_comparators/audit_check_risk_ranking.py  # ~1 h
python N2c_capacity_comparators/binding_groups.py            # minutes
python T4_outage_resolve/resolve_outage_cells.py             # minutes
python checks/model_sizes_plan.py                            # minutes (150 exact solves)
python N4_solver_scaling/n4_runner.py --pkg frozen_code/pkg  # ~2 h; writes N4_solver_scaling/results/
```

Each run script writes next to itself; compare with the shipped CSV/JSON outputs listed in `RESULTS.md`.

## Re-running the live study (N5)

Requires Docker, Kind v0.33 or compatible and kubectl on a Linux host with ≥ 16 GiB RAM. The runner expects the frozen code subset at `~/revision_2026-09-26/pkg`:

```bash
mkdir -p ~/revision_2026-09-26 && cp -r frozen_code/pkg ~/revision_2026-09-26/pkg
cd N5_live_binding_state
python n5_runner.py setup     # builds the cluster and the benchmark image
python n5_runner.py screen    # planning-only enrollment (writes results/screening.csv)
python n5_runner.py run       # 100 cells, ~2.5 h; resumable
python analyze_n5.py results out
```

`vm_run/run_all.sh` is the exact unattended sequence used (N5 then N4, strictly sequential).

## Integrity

`../../SHA256SUMS.txt` (package root) covers every file here as shipped. `vm_run/RESULTS_SHA256SUMS.txt` holds the hashes computed on the VM at completion; the copied raw files were verified against it (110/110). `SHA256SUMS_as_executed.txt` holds this folder's hashes before the six path edits described in `PATCH_NOTES.md`.
