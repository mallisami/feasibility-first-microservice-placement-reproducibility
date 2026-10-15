"""N5 pre-registered analysis (PROTOCOL_FROZEN.md, section "Analysis").

Unit = graph. Paired differences, 100,000-resample bootstrap 95% CI of the mean difference
(seed 20260926), two-sided Wilcoxon signed-rank. Primary: S1 scheduled P95, contrasts
(a) Affinity+Admission - Affinity-Bytes, (b) MAPE-CAP-WS - Affinity+Admission, Holm over (a),(b).
Co-primary: scheduled completion, same contrasts, Holm within completion. S2: all pairwise
contrasts, descriptive intervals only.

Usage: python analyze_n5.py <results_dir> <out_dir>
"""
import itertools
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import wilcoxon

RES = Path(sys.argv[1])
OUT = Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)
B = 100_000
SEED = 20260926
AFF, ADM, MC, CUR = "Affinity-Bytes", "Affinity-Bytes+Admission", "MAPE-CAP-WS", "Current"


def load_cells():
    rows, attempts = [], []
    for cell in sorted((RES / "cells").glob("*/seed-*/*")):
        files = sorted(cell.glob("attempt-*/result.json"))
        fails = sorted(cell.glob("attempt-*/failure.json"))
        attempts.append({"cell": str(cell.relative_to(RES)), "accepted": len(files), "failed_attempts": len(fails)})
        if not files:
            continue
        r = json.loads(files[0].read_text(encoding="utf-8"))
        e = r["endpoints"]
        rows.append({"stratum": r["stratum"], "seed": r["seed"], "method": r["method"], "tau": r["tau"],
                     "executed_state": r["executed_state"], "planned_exec_util": r["planned_exec_util"],
                     "planned_feasible": r["planned_feasible"], "moves": r["moves"],
                     "cross_rack_bits": r["cross_rack_bits"], **e,
                     "loadavg_before": r.get("loadavg_1m_before"), "loadavg_after": r.get("loadavg_1m_after"),
                     "rollout_s": r["relocation"].get("rollout_seconds")})
    return pd.DataFrame(rows), pd.DataFrame(attempts)


def boot_ci(d, rng):
    d = np.asarray(d, float)
    idx = rng.integers(0, len(d), size=(B, len(d)))
    m = d[idx].mean(axis=1)
    return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def contrast(df, stratum, metric, a, b, test=True):
    w = df[df.stratum == stratum].pivot(index="seed", columns="method", values=metric)
    d = (w[a] - w[b]).dropna()
    rng = np.random.default_rng(SEED)
    lo, hi = boot_ci(d.values, rng)
    out = {"stratum": stratum, "metric": metric, "contrast": f"{a} - {b}", "n": int(len(d)),
           "mean_a": float(w[a].mean()), "mean_b": float(w[b].mean()),
           "mean_diff": float(d.mean()), "median_diff": float(d.median()), "ci_lo": lo, "ci_hi": hi,
           "n_pos": int((d > 0).sum()), "n_neg": int((d < 0).sum()), "n_zero": int((d == 0).sum())}
    if test:
        nz = d[d != 0]
        out["wilcoxon_p"] = float(wilcoxon(nz).pvalue) if len(nz) > 0 else 1.0
    return out


def holm(ps):
    order = np.argsort(ps)
    adj = np.empty(len(ps))
    running = 0.0
    for k, i in enumerate(order):
        running = max(running, min(1.0, (len(ps) - k) * ps[i]))
        adj[i] = running
    return adj.tolist()


def main():
    df, att = load_cells()
    df.to_csv(OUT / "n5_cells.csv", index=False)
    att.to_csv(OUT / "n5_attempts.csv", index=False)

    primary = []
    for metric in ("sched_p95_ms", "scheduled_completion"):
        fam = [contrast(df, "S1", metric, ADM, AFF), contrast(df, "S1", metric, MC, ADM)]
        for r, p in zip(fam, holm([r["wilcoxon_p"] for r in fam])):
            r["holm_p"] = p
            r["role"] = "primary" if metric == "sched_p95_ms" else "co-primary"
        primary += fam
    # secondary S1 endpoints and the MAPE-CAP-WS vs Affinity-Bytes total contrast, descriptive
    sec = []
    for metric in ("sched_p50_ms", "sched_p99_ms", "attempted_p95_ms", "medium_mean_queue_wait_ms"):
        sec += [contrast(df, "S1", metric, ADM, AFF, test=False), contrast(df, "S1", metric, MC, ADM, test=False)]
    sec += [contrast(df, "S1", m, MC, AFF, test=False) for m in ("sched_p95_ms", "scheduled_completion")]
    s2 = []
    methods = [CUR, AFF, ADM, MC]
    for metric in ("sched_p95_ms", "scheduled_completion"):
        for a, b in itertools.combinations(methods, 2):
            s2.append(contrast(df, "S2", metric, b, a, test=False))
    pd.DataFrame(primary).to_csv(OUT / "n5_primary.csv", index=False)
    pd.DataFrame(sec).to_csv(OUT / "n5_secondary_S1.csv", index=False)
    pd.DataFrame(s2).to_csv(OUT / "n5_S2_descriptive.csv", index=False)

    summ = df.groupby(["stratum", "method"]).agg(
        n=("seed", "size"), p95_mean=("sched_p95_ms", "mean"), p95_median=("sched_p95_ms", "median"),
        p95_at_timeout=("sched_p95_ms", lambda s: int((s >= 3000).sum())),
        compl_mean=("scheduled_completion", "mean"), compl_min=("scheduled_completion", "min"),
        p50_mean=("sched_p50_ms", "mean"), qwait_mean=("medium_mean_queue_wait_ms", "mean"),
        exec_util_mean=("planned_exec_util", "mean"), exec_util_max=("planned_exec_util", "max"),
        planned_feasible=("planned_feasible", "sum"), moves_mean=("moves", "mean"),
        errors=("errors", "sum")).reset_index()
    summ.to_csv(OUT / "n5_summary.csv", index=False)
    load = {"loadavg_before_mean": float(df.loadavg_before.mean()), "loadavg_before_max": float(df.loadavg_before.max()),
            "loadavg_after_mean": float(df.loadavg_after.mean()), "loadavg_after_max": float(df.loadavg_after.max()),
            "cells_accepted": int(len(df)), "failed_attempts": int(att.failed_attempts.sum()),
            "executed_states": df.groupby("stratum").executed_state.value_counts().to_dict().__repr__()}
    (OUT / "n5_run_quality.json").write_text(json.dumps(load, indent=2), encoding="utf-8")

    pd.set_option("display.width", 250, "display.max_columns", 30)
    print(summ.to_string(index=False))
    print(pd.DataFrame(primary).to_string(index=False))
    print(pd.DataFrame(sec).to_string(index=False))
    print(pd.DataFrame(s2).to_string(index=False))
    print(json.dumps(load, indent=2))


if __name__ == "__main__":
    main()
