#!/usr/bin/env python3
"""Re-solve the controlled-topology Outage-with-Fallback cells that the frozen campaign recorded
as solver failures (HiGHS 'Model error' from an infinite airtime coefficient on down links,
fixed in the current exact.py).

Reconstruction gate: an instance is accepted only if, under the candidate scenario mapping, the
recorded objectives of every *completed* method in that replicate (Current, TrafficOnly,
BPlus-LNS where complete) are reproduced to 1e-9 relative tolerance. Only then are
DeterministicNetworkAware and BPlus-Exact re-solved with the current solver.
"""
from __future__ import annotations

import json
import math
import re
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
PKG = HERE.parents[2]
sys.path.insert(0, str(PKG / "implementation" / "code"))

from mape_cap_bplus.models import RiskConfig  # noqa: E402
from mape_cap_bplus.objective import evaluate_placement  # noqa: E402
import run_confirmatory_campaign as rc  # noqa: E402
import run_app_c_campaign as rcc  # noqa: E402

CANON = PKG / "RESULTS" / "supporting" / "canonical"
sys.path.insert(0, str(HERE.parent / "N2N3_admission_vs_ranking"))
import run_n2n3 as n2  # noqa: E402  (CSV state library, as used by the frozen G11/APP_C campaigns)

RISK = RiskConfig(cvar_quantile=0.8, cvar_weight=1.5, relocation_weight=1.0, slo_slack_weight=1000.0)
# Diagnostic probe_mapping.py showed the frozen campaigns used the CSV library; the current
# runner's link_trace.json does not reproduce the recorded objectives.
TRACE = n2.LIB
CANDIDATE_SETS = {
    "csv:outage+nominal+mixed": ["outage-with-fallback", "nominal-los", "mixed-regime"],
    "csv:outage-only": ["outage-with-fallback"],
}


def scenarios(ids):
    raw = [TRACE[s] for s in ids]
    tot = sum(x["weight"] for x in raw)
    return tuple(rc.trace_to_scenario({**x, "weight": x["weight"] / tot}) for x in raw)


def seed_of(instance_id: str) -> int:
    return int(re.search(r"seed(\d+)", instance_id).group(1))


def builders(app):
    if app == "APP_A":
        return lambda sc, seed: rc.build_app_a_instance(sc, seed=seed, condition="outage_with_fallback")
    if app == "APP_B":
        return lambda sc, seed: rc.build_app_b_instance(sc, seed=seed, condition="outage_with_fallback")
    return lambda sc, seed: rcc.build_app_c_instance(sc, seed=seed)


def recorded_ok(problem, rows) -> bool:
    for _, r in rows.iterrows():
        if r.status not in ("complete", "complete-infeasible"):
            continue
        pl = json.loads(r.placement)
        ev = evaluate_placement(problem, pl, RISK)
        if bool(ev.feasible) != (str(r.feasible) in ("True", "true", "1")):
            return False
        if ev.feasible and not math.isclose(ev.total_objective, float(r.objective), rel_tol=1e-9):
            return False
    return True


def main():
    ab = pd.read_csv(CANON / "controlled_confirmatory_app_a_b_frozen_g11.csv")
    c = pd.read_csv(CANON / "app_c_campaign.csv")
    frames = [ab, c]
    df = pd.concat(frames, ignore_index=True)
    df = df[df.network_condition.str.contains("outage")]
    out, audit = [], []
    for (app, rep), g in df.groupby(["application", "replicate"]):
        seed = seed_of(g.instance_id.iloc[0])
        chosen = None
        for name, ids in CANDIDATE_SETS.items():
            prob = builders(app)(scenarios(ids), seed)
            if len(prob.scenarios) == int(g.scenario_count.iloc[0]) and recorded_ok(prob, g):
                chosen = (name, prob)
                break
        audit.append({"application": app, "replicate": int(rep), "seed": seed,
                      "mapping": chosen[0] if chosen else "NOT-REPRODUCED"})
        if not chosen:
            continue
        prob = chosen[1]
        for method in ("DeterministicNetworkAware", "BPlus-Exact"):
            res = rc.run_method(method, prob, RISK, seed=0)
            out.append({"application": app, "replicate": int(rep), "method": method,
                        "status": res["status"], "objective": res.get("objective"),
                        "feasible": res.get("feasible"), "error": res.get("error", "")})
    pd.DataFrame(audit).to_csv(HERE / "reconstruction_audit.csv", index=False)
    res = pd.DataFrame(out)
    res.to_csv(HERE / "resolved_cells.csv", index=False)
    a = pd.DataFrame(audit)
    print(a.groupby(["application", "mapping"]).size().to_string())
    if len(res):
        print(res.groupby(["application", "method", "status"]).agg(n=("objective", "size"),
              mean_obj=("objective", "mean")).to_string())


if __name__ == "__main__":
    main()
