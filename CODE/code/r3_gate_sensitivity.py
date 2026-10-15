#!/usr/bin/env python3
"""Replay the frozen R3 economic gate under alternative floor/reserve/horizon constants.

This is an offline sensitivity analysis. It does not rerun Kubernetes, alter classifier
outputs, or change the selected single-move candidate. It recomputes only the economic
gate from retained R2 transport rates and R3 window records.
"""
from pathlib import Path
import json
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "RESULTS" / "primary" / "v03-20260811T151500Z"
SERVICES = {
    "adservice","cartservice","checkoutservice","currencyservice","emailservice",
    "frontend","paymentservice","productcatalogservice","recommendationservice",
    "redis-cart","shippingservice",
}
FLOORS = [0, 2048, 4096, 8192, 16384, 32768]
RESERVES = [0.0, 0.025, 0.05, 0.10, 0.20, 0.50]
HORIZONS = [30, 60, 120, 300, 600]
BASE_FLOOR, BASE_RESERVE, BASE_HORIZON = 4096, 0.05, 300

def r2_traffic():
    rows=[]
    for p in sorted((RUN/"raw"/"r2").glob("replicate-*-telemetry_on_controller_off/result.json")):
        rows.append(json.loads(p.read_text(encoding="utf-8")))
    total_seconds=sum(float(r["duration_seconds"]) for r in rows)
    req, byt = {}, {}
    for r in rows:
        for tr in r["native_trace_windows"]:
            pair=(tr["source"],tr["destination"])
            req[pair]=req.get(pair,0.0)+float(tr["requests"])
        for fl in r["transport_flow_windows"]:
            pair=(fl["source"],fl["destination"])
            byt[pair]=byt.get(pair,0.0)+float(fl["request_bytes"]+fl["response_bytes"])
    pairs=set(req)|set(byt)
    return {pair:(req.get(pair,0.0)/total_seconds,byt.get(pair,0.0)/total_seconds)
            for pair in pairs if pair[0] in SERVICES and pair[1] in SERVICES}

traffic=r2_traffic()
raw_reloc={}
for svc in SERVICES:
    incident=sum(rate for (src,dst),(_,rate) in traffic.items() if src==svc or dst==svc)
    raw_reloc[svc]=incident*4.062

records=[]
for p in sorted((RUN/"raw"/"r3").glob("sequence-*/window-*/result.json")):
    r=json.loads(p.read_text(encoding="utf-8"))
    e=r["gate"]["economics"]
    records.append({
        "seq":r["sequence_id"],"w":r["window_index"],"truth":r["truth_regime"],
        "candidate_regime":r["gate"]["candidate_regime"],
        "should_replan":bool(r["gate"]["should_replan"]),
        "accepted_original":bool(r["gate"]["accepted"]),
        "service":e["service"],
        "improvement_bytes_per_second":e["current_cross_node_bytes_per_second"]-e["candidate_cross_node_bytes_per_second"],
        "raw_relocation_equivalent_bytes":raw_reloc[e["service"]],
    })
inputs=pd.DataFrame(records)

grid=[]
for floor in FLOORS:
    for reserve in RESERVES:
        for horizon in HORIZONS:
            positives=accepted=0
            min_net=float("inf")
            for row in records:
                benefit=row["improvement_bytes_per_second"]*horizon
                relocation=max(float(floor),row["raw_relocation_equivalent_bytes"])
                uncertainty=max(float(floor),benefit*reserve)
                net=benefit-relocation-uncertainty
                min_net=min(min_net,net)
                economic=net>0
                positives+=int(economic)
                accepted+=int(row["should_replan"] and row["candidate_regime"]=="degradation" and economic)
            grid.append({
                "floor_bytes":floor,"reserve_fraction":reserve,"horizon_seconds":horizon,
                "economic_positive_windows":positives,"accepted_gate_windows":accepted,
                "min_net_benefit_bytes":min_net,
            })
grid=pd.DataFrame(grid)

oat=[]
for param, vals in [("floor_bytes",FLOORS),("forecast_reserve_fraction",RESERVES),("forecast_horizon_seconds",HORIZONS)]:
    for val in vals:
        floor=val if param=="floor_bytes" else BASE_FLOOR
        reserve=val if param=="forecast_reserve_fraction" else BASE_RESERVE
        horizon=val if param=="forecast_horizon_seconds" else BASE_HORIZON
        row=grid[(grid.floor_bytes==floor)&(grid.reserve_fraction==reserve)&(grid.horizon_seconds==horizon)].iloc[0]
        oat.append({
            "parameter":param,"value":val,"held_floor_bytes":floor,
            "held_reserve_fraction":reserve,"held_horizon_seconds":horizon,
            "economic_positive_windows":int(row.economic_positive_windows),
            "accepted_gate_windows":int(row.accepted_gate_windows),
            "min_net_benefit_bytes":float(row.min_net_benefit_bytes),
        })
oat=pd.DataFrame(oat)

out=ROOT/"RESULTS"/"supporting"/"reviewer_revision"/"r3_gate_sensitivity"
out.mkdir(parents=True,exist_ok=True)
inputs.to_csv(out/"r3_gate_replay_inputs.csv",index=False)
grid.to_csv(out/"r3_gate_sensitivity_full_grid.csv",index=False)
oat.to_csv(out/"r3_gate_sensitivity_one_at_a_time.csv",index=False)
print(oat.to_string(index=False))
