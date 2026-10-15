#!/usr/bin/env python3
"""Diagnostic: search library x scenario-set x condition-label combinations for one replicate."""
import itertools, json, math, sys
from pathlib import Path
import pandas as pd
HERE = Path(__file__).resolve().parent
PKG = HERE.parents[2]
sys.path.insert(0, str(PKG / "implementation" / "code"))
sys.path.insert(0, str(HERE.parent / "N2N3_admission_vs_ranking"))
from mape_cap_bplus.models import RiskConfig
from mape_cap_bplus.objective import evaluate_placement
import run_confirmatory_campaign as rc
import run_n2n3 as n2  # provides the CSV library as n2.LIB

RISK = RiskConfig(cvar_quantile=0.8, cvar_weight=1.5, relocation_weight=1.0, slo_slack_weight=1000.0)
libs = {"json": rc.load_link_trace(), "csv": n2.LIB}
ab = pd.read_csv(PKG / "RESULTS/supporting/canonical/controlled_confirmatory_app_a_b_frozen_g11.csv")
g = ab[(ab.application == "APP_B") & ab.network_condition.str.contains("outage") & (ab.replicate == 1)]
print(g[["method", "status", "objective", "scenario_count", "instance_id"]].to_string())
seed = int(g.instance_id.iloc[0].split("seed")[1])
cur = g[g.method == "Current"].iloc[0]
names = ["outage-with-fallback", "nominal-los", "mixed-regime", "recovery", "asymmetric-los", "partial-blockage"]
labels = ["outage_with_fallback", "outage_fallback", "outage"]
k = int(g.scenario_count.iloc[0])
for lib, db in libs.items():
    for ids in itertools.permutations(names, k):
        if ids[0] != "outage-with-fallback":
            continue
        raw = [db[s] for s in ids]
        tot = sum(x["weight"] for x in raw)
        sc = tuple(rc.trace_to_scenario({**x, "weight": x["weight"] / tot}) for x in raw)
        for lab in labels:
            p = rc.build_app_b_instance(sc, seed=seed, condition=lab)
            ev = evaluate_placement(p, json.loads(cur.placement), RISK)
            if ev.feasible and math.isclose(ev.total_objective, float(cur.objective), rel_tol=1e-6):
                print("MATCH", lib, ids, lab, ev.total_objective)
print("done")
