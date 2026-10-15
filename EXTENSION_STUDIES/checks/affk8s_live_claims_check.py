import pandas as pd
from pathlib import Path
# package layout: <root>/EXTENSION_STUDIES/2026-09-26/checks/ -> <root>/EXPERIMENTS/... (was an absolute path when executed)
b = str(Path(__file__).resolve().parents[3] / "EXPERIMENTS" / "k8s_affinity_wireless_confirmatory" / "results" / "run-20260920T045006Z") + "/"
d = pd.read_csv(b + "analysis_cells.csv")
d = d[d.target == 1.25]
w = d.pivot(index="seed", columns="method")
aff_inf = w["planned_feasible"]["Affinity-Bytes"] == False
print("graphs:", len(w), "affinity planned-infeasible:", int(aff_inf.sum()), "MAPE planned feasible:", int(w["planned_feasible"]["BPlus-Exact"].sum()))
sub = w[aff_inf]
print("of affinity-infeasible: executed util <= 1:", int((sub["offered_conflict_utilization"]["Affinity-Bytes"] <= 1.0 + 1e-9).sum()),
      " completion == 1:", int((sub["completion_fraction"]["Affinity-Bytes"] >= 1 - 1e-12).sum()))
print(sub[[("offered_conflict_utilization", "Affinity-Bytes"), ("completion_fraction", "Affinity-Bytes")]].to_string())
same = (w["completion_fraction"]["BPlus-Exact"] - w["completion_fraction"]["Affinity-Bytes"]).abs() < 1e-12
print("identical completion MAPE vs Affinity:", int(same.sum()), "of", len(w))
ab = w["planner_abstained"]["BPlus-Exact"] == True
print("abstained seeds:", list(w.index[ab]), "moves:", list(w["moves"]["BPlus-Exact"][ab]), "cross-rack bits MAPE vs Aff:",
      list(w["planned_cross_rack_bits"]["BPlus-Exact"][ab]), list(w["planned_cross_rack_bits"]["Affinity-Bytes"][ab]))
print("ceiling: graphs with MAPE completion >= 0.99:", int((w["completion_fraction"]["BPlus-Exact"] >= 0.99).sum()))
