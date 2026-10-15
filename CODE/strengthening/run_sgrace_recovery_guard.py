#!/usr/bin/env python3
"""S-GRACE: live recovery-horizon guard experiment.

Compares the same economically positive B+ candidate with and without a
forecast-horizon grace guard. The network is scripted to recover after a known
horizon; this directly tests the mechanism implicated by the R7 recovery trace.
"""
from __future__ import annotations
import argparse, csv, json, sys, threading, time
from dataclasses import replace
from pathlib import Path

HERE=Path(__file__).resolve().parent; IMPL=HERE.parent; REPO=IMPL.parent
sys.path.insert(0,str(HERE)); sys.path.insert(0,str(IMPL/"code"))
from common import atomic_json, assert_live_preflight, campaign_lock, clear_live_network, utc_now, write_manifest
from mape_cap_bplus.controller import accept_relocation
from mape_cap_bplus.exact import solve_exact
from mape_cap_bplus.models import RiskConfig
from mape_cap_bplus.objective import evaluate_placement
from run_v03_r1 import apply_placement, build_problem, initial_placement, wait_healthy
from run_v03_r2 import assert_healthy
from run_v03_r3 import measure_window, shape

RISK=RiskConfig(0.8,1.5,1.0,1000.0)


def candidate(evidence:Path,rep:int,initial:dict[str,str]):
    problem=build_problem(evidence,"persistent-degradation",9500+rep,initial)
    op=replace(RISK,relocation_weight=0.0)
    placement,meta=solve_exact(problem,op,time_limit_seconds=45.0,require_optimal=False)
    cur=evaluate_placement(problem,initial,op); cand=evaluate_placement(problem,placement,op)
    moved=[r for r,n in placement.items() if initial[r]!=n]
    move_cost=sum(problem.relocation_costs[r].cost_units for r in moved)
    uncertainty=sum(problem.relocation_costs[r].uncertainty_units for r in moved)
    expected=max((problem.relocation_costs[r].expected_seconds for r in moved),default=0.0)
    economic,net,reason=accept_relocation(cur.total_objective,cand.total_objective,move_cost,uncertainty)
    return problem,placement,{"moved":moved,"move_cost_units":move_cost,"uncertainty_units":uncertainty,"expected_relocation_seconds":expected,"current_objective":cur.total_objective,"candidate_objective":cand.total_objective,"economic_accept":economic,"net_benefit":net,"reason":reason,"solver":meta}


def one_cell(out:Path,evidence:Path,horizon:float,rep:int,method:str,post_recovery:float)->dict:
    initial=initial_placement(f"S-GRACE-{horizon}-{rep}",9600+rep); apply_placement(initial,f"S-GRACE:{horizon}:rep{rep}:initial")
    problem,target,plan=candidate(evidence,rep,initial)
    shaping=shape("degradation",9700+rep,rep)
    horizon_ok=horizon > 1.25*plan["expected_relocation_seconds"]
    execute=bool(plan["economic_accept"] and plan["moved"] and (method=="Immediate" or horizon_ok))
    recovery_event={"scheduled_after_seconds":horizon,"fired":False,"fired_utc":None}
    def recover():
        time.sleep(horizon); clear_live_network(); recovery_event["fired"]=True; recovery_event["fired_utc"]=utc_now()
    thread=threading.Thread(target=recover,daemon=True); thread.start()
    relocation=None
    started=time.monotonic()
    if execute: relocation=apply_placement(target,f"S-GRACE:{horizon}:rep{rep}:{method}")
    observe=max(10.0,horizon+post_recovery-(time.monotonic()-started))
    measured,samples,log=measure_window(int(round(observe)))
    thread.join(timeout=max(1.0,horizon+5)); clear_live_network(); health=assert_healthy(False,False)
    row={"experiment":"S-GRACE","horizon_seconds":horizon,"replicate":rep,"method":method,"horizon_guard_pass":horizon_ok,"execution_accepted":execute,"planning":plan,"shaping":shaping,"recovery_event":recovery_event,"relocation":relocation,"application":measured["application"],"resources":measured["resources"],"health":health,"completed_utc":utc_now()}
    row["accepted_evidence"]=bool(health["healthy"] and measured["application"]["requests"]>0)
    cell=out/f"horizon-{int(horizon):03d}s"/f"replicate-{rep:02d}"/method; cell.mkdir(parents=True,exist_ok=True); atomic_json(cell/"result.json",row); atomic_json(cell/"resource-samples.json",samples); (cell/"frontend.log").write_text(log,encoding="utf-8")
    apply_placement(initial,f"S-GRACE:{horizon}:rep{rep}:{method}:restore")
    return row


def main()->int:
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("run_root",type=Path); p.add_argument("--evidence-run-root",type=Path,default=REPO/"RESULTS"/"primary"/"v03-20260811T151500Z"); p.add_argument("--horizons",default="5,15,60"); p.add_argument("--replicates",type=int,default=5); p.add_argument("--post-recovery-seconds",type=float,default=20.0); args=p.parse_args()
    horizons=[float(x) for x in args.horizons.split(",") if x]; root=args.run_root.resolve(); evidence=args.evidence_run_root.resolve(); out=root/"raw"/"S-GRACE-recovery-guard"; out.mkdir(parents=True,exist_ok=True); atomic_json(out/"preflight.json",assert_live_preflight())
    rows=[]
    with campaign_lock("strengthening-live"):
        if not wait_healthy()["healthy"]: raise RuntimeError("Online Boutique unhealthy before S-GRACE")
        for hi,h in enumerate(horizons):
            for rep in range(1,args.replicates+1):
                order=["Immediate","GraceGuard"] if (rep+hi)%2==0 else ["GraceGuard","Immediate"]
                for method in order:
                    print(f"S-GRACE horizon={h}s rep={rep}/{args.replicates} {method}",flush=True); row=one_cell(out,evidence,h,rep,method,args.post_recovery_seconds); rows.append(row)
                    if not row["accepted_evidence"]: raise RuntimeError("S-GRACE evidence acceptance failed")
                    atomic_json(out/"progress.json",{"updated_utc":utc_now(),"completed":len(rows),"target":len(horizons)*args.replicates*2})
    csv_path=root/"derived"/"S-GRACE-recovery-guard.csv"; csv_path.parent.mkdir(parents=True,exist_ok=True)
    fields=["horizon_seconds","replicate","method","horizon_guard_pass","execution_accepted","accepted_evidence"]
    with csv_path.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows([{k:r.get(k) for k in fields} for r in rows])
    summary={"experiment":"S-GRACE","completed_utc":utc_now(),"horizons_seconds":horizons,"replicates":args.replicates,"cells":len(rows),"guard_abstentions":sum(r["method"]=="GraceGuard" and not r["execution_accepted"] for r in rows),"all_evidence_accepted":all(r["accepted_evidence"] for r in rows),"output_csv":str(csv_path.relative_to(root))}
    atomic_json(root/"derived"/"S-GRACE-summary.json",summary); write_manifest(root); print(json.dumps(summary,indent=2)); return 0

if __name__=="__main__": raise SystemExit(main())
