#!/usr/bin/env python3
"""S-E1: execute the full B+ planner inside the live R3-style dynamic loop.

New evidence is written under RESULTS/strengthening and never overwrites frozen R3.
The experiment keeps sequence ID as the independent unit.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

HERE=Path(__file__).resolve().parent; IMPL=HERE.parent; REPO=IMPL.parent
sys.path.insert(0,str(HERE)); sys.path.insert(0,str(IMPL/"code"))
from common import atomic_json, assert_live_preflight, campaign_lock, clear_live_network, utc_now, write_manifest
from mape_cap_bplus.controller import PersistentRegimeDetector, accept_relocation
from mape_cap_bplus.exact import solve_exact
from mape_cap_bplus.lns import robust_lns
from mape_cap_bplus.models import RiskConfig
from mape_cap_bplus.objective import evaluate_placement
from run_v03_classifier import raw_label
from run_v03_r1 import apply_placement, build_problem, initial_placement, wait_healthy
from run_v03_r2 import NS, assert_healthy, kubectl
from run_v03_r3 import SEQUENCES, live_placement, measure_window, shape

REGIME_TO_R1={"stable":"stable","degradation":"persistent-degradation","recovery":"recovery"}
RISK=RiskConfig(cvar_quantile=0.8,cvar_weight=1.5,relocation_weight=1.0,slo_slack_weight=1000.0)


def choose_candidate(problem, current:dict[str,str], planner:str, seed:int, time_limit:float):
    operating_risk=replace(RISK,relocation_weight=0.0)
    started=time.perf_counter()
    if planner.lower()=="exact":
        candidate,meta=solve_exact(problem,operating_risk,time_limit_seconds=max(time_limit,1.0),require_optimal=False)
    elif planner.lower()=="lns":
        candidate,meta=robust_lns(problem,operating_risk,seed=seed,iterations=80,destroy_size=min(4,len(problem.replicas)),time_limit_seconds=time_limit,local_iterations=10)
    else:
        raise ValueError(planner)
    runtime=time.perf_counter()-started
    current_eval=evaluate_placement(problem,current,operating_risk)
    candidate_eval=evaluate_placement(problem,candidate,operating_risk)
    moved=[rid for rid,node in candidate.items() if current[rid]!=node]
    relocation_cost=sum(problem.relocation_costs[r].cost_units for r in moved)
    relocation_uncertainty=sum(problem.relocation_costs[r].uncertainty_units for r in moved)
    expected_seconds=max((problem.relocation_costs[r].expected_seconds for r in moved),default=0.0)
    accepted,net,reason=accept_relocation(current_eval.total_objective,candidate_eval.total_objective,relocation_cost,relocation_uncertainty)
    return candidate,{"planner":planner,"runtime_seconds":runtime,"metadata":{k:v for k,v in meta.items() if k not in {"iteration_log","candidate_log"}},"current_operating_objective":current_eval.total_objective,"candidate_operating_objective":candidate_eval.total_objective,"moved_replicas":moved,"relocation_cost_units":relocation_cost,"relocation_uncertainty_units":relocation_uncertainty,"expected_relocation_seconds":expected_seconds,"economic_accept":accepted,"net_benefit":net,"economic_reason":reason}


def run_sequence(out_root:Path,evidence_root:Path,sequence_id:int,planner:str,time_limit:float,duration:int)->list[dict]:
    regimes=SEQUENCES[sequence_id]
    seed=8300+sequence_id
    initial=initial_placement(f"S-E1-sequence-{sequence_id}",seed)
    apply_placement(initial,f"S-E1:sequence{sequence_id}:initial")
    detector=PersistentRegimeDetector(minimum_persistent_windows=3,horizon_safety_factor=1.25)
    observed=[]; current_regime="stable"; rows=[]
    try:
        for idx,truth in enumerate(regimes):
            cell=out_root/f"sequence-{sequence_id:02d}"/f"window-{idx:02d}"; cell.mkdir(parents=True,exist_ok=True)
            shaping=shape(truth,seed,idx); classified=raw_label(shaping["applied"],1.0); observed.append(classified)
            current=live_placement()
            # Conservative duration for detector before candidate is known: worst current declared relocation duration.
            probe_problem=build_problem(evidence_root,REGIME_TO_R1[truth],seed,current)
            expected=max((c.expected_seconds for c in probe_problem.relocation_costs.values()),default=0.0)
            decision=detector.evaluate(observed,current_regime,300.0,expected)
            planning={"executed":False}; relocation=None; candidate=dict(current); accepted=False
            if decision.should_replan:
                candidate,planning=choose_candidate(probe_problem,current,planner,seed*100+idx,time_limit)
                accepted=bool(planning["economic_accept"] and planning["moved_replicas"])
                if accepted:
                    relocation=apply_placement(candidate,f"S-E1:seq{sequence_id}:window{idx}")
                    current_regime=str(decision.candidate_regime)
                elif decision.candidate_regime is not None:
                    current_regime=str(decision.candidate_regime)
                planning["executed"]=True
            measured,samples,frontend_log=measure_window(duration)
            health=assert_healthy(False,False)
            row={
                "experiment":"S-E1","sequence_id":sequence_id,"seed":seed,"window_index":idx,"truth_regime":truth,
                "classified_regime":classified,"controller_regime_after":current_regime,"should_replan":decision.should_replan,
                "replan_reason":decision.reason,"candidate_regime":decision.candidate_regime,"planner":planner,
                "planner_executed":planning.get("executed",False),"planning":planning,"gate_accepted":accepted,
                "placement_before":current,"candidate_placement":candidate,"placement_after":live_placement(),
                "relocation":relocation,"relocation_seconds":None if relocation is None else relocation.get("rollout_seconds"),
                "shaping":shaping,**measured,"health":health,"completed_utc":utc_now(),
            }
            row["accepted_evidence"]=bool(health["healthy"] and measured["application"]["requests"]>0)
            atomic_json(cell/"result.json",row); atomic_json(cell/"resource-samples.json",samples); (cell/"frontend.log").write_text(frontend_log,encoding="utf-8")
            if not row["accepted_evidence"]: raise RuntimeError(f"S-E1 acceptance failed seq={sequence_id} window={idx}")
            rows.append(row)
    finally:
        clear_live_network()
        try: apply_placement(initial,f"S-E1:sequence{sequence_id}:cleanup")
        except Exception: pass
    return rows


def main()->int:
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("run_root",type=Path); p.add_argument("--evidence-run-root",type=Path,default=REPO/"RESULTS"/"primary"/"v03-20260811T151500Z"); p.add_argument("--planner",choices=["LNS","Exact"],default="LNS"); p.add_argument("--planner-time-limit",type=float,default=10.0); p.add_argument("--window-duration-seconds",type=int,default=15); p.add_argument("--sequences",default="1,2,3,4,5"); args=p.parse_args()
    seqs=[int(x) for x in args.sequences.split(",") if x.strip()]
    if not set(seqs)<=set(SEQUENCES): p.error("unknown sequence")
    if args.window_duration_seconds<10: p.error("window duration >=10 required")
    root=args.run_root.resolve(); evidence=args.evidence_run_root.resolve()
    if not evidence.exists(): raise SystemExit(f"frozen evidence root not found: {evidence}")
    out=root/"raw"/"S-E1-live-full-planner"; out.mkdir(parents=True,exist_ok=True); atomic_json(out/"preflight.json",assert_live_preflight())
    rows=[]
    with campaign_lock("strengthening-live"):
        kubectl("scale","deployment/bplus-controller-v03","-n",NS,"--replicas=0")
        health=wait_healthy();
        if not health["healthy"]: raise RuntimeError("Online Boutique is not healthy before S-E1")
        for seq in seqs:
            print(f"S-E1 sequence {seq}/{len(seqs)} planner={args.planner}",flush=True); rows.extend(run_sequence(out,evidence,seq,args.planner,args.planner_time_limit,args.window_duration_seconds)); atomic_json(out/"progress.json",{"updated_utc":utc_now(),"completed_sequences":len({r['sequence_id'] for r in rows}),"windows":len(rows)})
    csv_path=root/"derived"/"S-E1-live-full-planner.csv"; csv_path.parent.mkdir(parents=True,exist_ok=True)
    fields=["sequence_id","seed","window_index","truth_regime","classified_regime","should_replan","candidate_regime","planner","planner_executed","gate_accepted","relocation_seconds","accepted_evidence"]
    with csv_path.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows([{k:r.get(k) for k in fields} for r in rows])
    summary={"experiment":"S-E1","completed_utc":utc_now(),"planner":args.planner,"sequences":len(seqs),"windows":len(rows),"replans":sum(r["should_replan"] for r in rows),"accepted_relocations":sum(r["gate_accepted"] for r in rows),"all_evidence_accepted":all(r["accepted_evidence"] for r in rows),"frozen_traffic_source":str(evidence.relative_to(REPO)),"output_csv":str(csv_path.relative_to(root))}
    atomic_json(root/"derived"/"S-E1-summary.json",summary); write_manifest(root); print(json.dumps(summary,indent=2)); return 0

if __name__=="__main__": raise SystemExit(main())
