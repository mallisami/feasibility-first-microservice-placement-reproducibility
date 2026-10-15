# Differences between this folder and the files as executed

The studies in this folder were executed from a working directory whose layout differed from this package. Six scripts contained paths that depended on that layout. They were changed in this copy so that they run from the package root without editing. No study logic, parameter, seed, data file or protocol was changed. The original per-file hashes at execution time are preserved in `SHA256SUMS_as_executed.txt` (renamed from `SHA256SUMS.txt`; it covered this folder only). The root `SHA256SUMS.txt` covers the files as shipped.

| File | Line(s) | Executed version | Package version |
|---|---|---|---|
| `checks/verify_audit_numbers.py` | 2 | absolute path to the working `experiments/` folder | `Path(__file__).resolve().parents[1]` (this folder) |
| `checks/model_sizes_plan.py` | 2 | absolute path to `N2N3_admission_vs_ranking` | relative to this folder |
| `checks/affk8s_live_claims_check.py` | 2 | absolute path to `EXPERIMENTS/k8s_affinity_wireless_confirmatory/results/run-20260920T045006Z/` | `parents[3] / "EXPERIMENTS" / ...` (package root) |
| `N2c_capacity_comparators/binding_groups.py` | 3 | absolute path to `N2N3_admission_vs_ranking` | relative to this folder |
| `N2N3_admission_vs_ranking/make_figures.py` | 22 | `HERE.parents[1] / "paper_full" / "figures" / "rev"` | `HERE.parents[2] / "PAPER" / "figures" / "rev"` |
| `figure_layout/regen_tradeoff_figure.py` | 9, 23 | `M / "REVISION_2026-09-26" / "paper_full" / "figures" / "v03"` | `M / "PAPER" / "figures" / "v03"` |

Unchanged but layout-dependent by design:

- `N4_solver_scaling/n4_runner.py` and `N5_live_binding_state/n5_runner.py` expect the frozen code subset at `~/revision_2026-09-26/pkg`, which is how they ran on the execution host. Pass `--pkg <path to frozen_code/pkg>` to the N4 runner; for N5 copy `frozen_code/pkg` to that location (see `README.md` §"Re-running the live study").
- `run_n2n3.py`, `run_n3b_outage_rotation.py`, `run_n2c.py`, `audit_check_risk_ranking.py`, `T4_outage_resolve/*.py` locate the canonical planner at `HERE.parents[2] / "implementation" / "code"`, which resolves to the package root. They ran unchanged.
- Log files, `provenance.json` files and `raw/results/frozen/preexecution_manifest.json` record the execution host's paths (`/home/azureuser/revision_2026-09-26/...`, hostname `mcb-k8s-v137`). They are frozen records and were not edited.
