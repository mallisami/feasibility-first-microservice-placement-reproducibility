import pandas as pd, numpy as np
from pathlib import Path
B = str(Path(__file__).resolve().parents[1]) + "/"  # EXTENSION_STUDIES/2026-09-26/ (package layout; was an absolute path when executed)
c = pd.read_csv(B + "N2N3_admission_vs_ranking/cell_results.csv")
t = c[np.isclose(c.target, 1.25)].set_index(["replica_count", "seed"])
M, A = t[t.method == "MAPE-CAP-WS"], t[t.method == "Affinity-Bytes+Admission"]
idx = M.index.intersection(A.index)
diff = M.loc[idx, "placement"] != A.loc[idx, "placement"]
d_h = (M.loc[idx, "headroom"] - A.loc[idx, "headroom"])[diff]
d_b = (M.loc[idx, "cross_rack_bytes"] - A.loc[idx, "cross_rack_bytes"])[diff]
print("differing graphs:", int(diff.sum()), "mean headroom diff:", d_h.mean(), "mean bytes diff:", d_b.mean(),
      "MAPE more headroom on:", int((d_h > 1e-12).sum()), "equal headroom:", int((d_h.abs() <= 1e-12).sum()),
      "bytes diff >=0 on all:", bool((d_b >= -1e-6).all()))
d_all_b = M.loc[idx, "cross_rack_bytes"] - A.loc[idx, "cross_rack_bytes"]
print("all-150 bytes diff min:", d_all_b.min(), "zeros:", int((d_all_b.abs() < 1e-6).sum()))
# held-out per state at tau<=1.25 for admission-constrained methods
h = pd.read_csv(B + "N2N3_admission_vs_ranking/heldout_by_state.csv")
for tgt in (0.5, 0.9, 1.0, 1.1, 1.25):
    s = h[np.isclose(h.target, tgt) & h.method.isin(["Affinity-Bytes+Admission", "MAPE-CAP-WS", "MAPE-CAP-WS Risk-off"])]
    print(tgt, {col.replace("ho_ok_", ""): {m: int(g[col].sum()) for m, g in s.groupby("method")} for col in s.columns if col.startswith("ho_ok_") and "outage" not in col})
# N5 per-graph utilization S1
n5 = pd.read_csv(B + "N5_live_binding_state/analysis/n5_cells.csv")
s1 = n5[n5.stratum == "S1"].pivot(index="seed", columns="method", values="planned_exec_util")
dd = s1["MAPE-CAP-WS"] - s1["Affinity-Bytes+Admission"]
print("N5 S1 MAPE util vs Aff+Adm: higher", int((dd > 1e-9).sum()), "equal", int((dd.abs() <= 1e-9).sum()), "lower", int((dd < -1e-9).sum()))
qs = n5[n5.stratum == "S1"].pivot(index="seed", columns="method", values="medium_mean_queue_wait_ms")
print("N5 S1 queue wait MAPE - AffAdm mean:", (qs["MAPE-CAP-WS"] - qs["Affinity-Bytes+Admission"]).mean())
