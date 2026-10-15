#!/usr/bin/env python3
"""S-E4: live Kubernetes topology-spread scheduler baseline versus B+ Exact.

The baseline deliberately uses the native kube-scheduler and PodTopologySpread,
so it requires no unvalidated third-party image and remains reproducible on the
existing Kind cluster. An optional --scheduler-name hook permits a separately
validated second scheduler without changing the evidence schema.
"""
from __future__ import annotations
import argparse, csv, json, sys, time
from pathlib import Path

HERE=Path(__file__).resolve().parent; IMPL=HERE.parent; REPO=IMPL.parent
sys.path.insert(0,str(HERE)); sys.path.insert(0,str(IMPL/"code"))
from common import atomic_json, assert_live_preflight, campaign_lock, clear_live_network, utc_now, write_manifest
from mape_cap_bplus.models import RiskConfig
from mape_cap_bplus.objective import evaluate_placement
from run_v03_r1 import CONDITIONS, SERVICES, apply_placement, build_problem, initial_placement, measure, plan, wait_healthy
from run_v03_r2 import NS, kubectl, kubectl_json
from run_v03_r3 import live_placement

RISK=RiskConfig(0.8,1.5,1.0,1000.0)
GROUP_KEY="bplus-strengthening-group"
GROUP_VALUE="se4-online-boutique"


def patch_deployment(service:str, patch:dict)->None:
    kubectl("patch","deployment",service,"-n",NS,"--type=merge","-p",json.dumps(patch))


def rollout_all()->None:
    for service in SERVICES:
        result=__import__("subprocess").run(["kubectl","rollout","status",f"deployment/{service}","-n",NS,"--timeout=420s"],capture_output=True,text=True,timeout=440)
        if result.returncode: raise RuntimeError(f"rollout failed {service}: {result.stderr[-1000:]}")
    health=wait_healthy()
    if not health["healthy"]: raise RuntimeError("Online Boutique unhealthy after scheduler patch")


def apply_topology_spread(scheduler_name:str, run_id:str)->None:
    constraint={
        "maxSkew":1,"topologyKey":"kubernetes.io/hostname","whenUnsatisfiable":"ScheduleAnyway",
        "labelSelector":{"matchLabels":{GROUP_KEY:GROUP_VALUE}}
    }
    for service in SERVICES:
        patch={"spec":{"template":{"metadata":{"labels":{GROUP_KEY:GROUP_VALUE},"annotations":{"bplus-strengthening/se4-run":run_id}},"spec":{"nodeSelector":None,"schedulerName":scheduler_name,"topologySpreadConstraints":[constraint]}}}}
        patch_deployment(service,patch)
    rollout_all()


def restore_initial(initial:dict[str,str],run_id:str)->None:
    for service in SERVICES:
        patch={"spec":{"template":{"metadata":{"labels":{GROUP_KEY:None},"annotations":{"bplus-strengthening/se4-run":run_id}},"spec":{"nodeSelector":{"kubernetes.io/hostname":initial[service]},"schedulerName":None,"topologySpreadConstraints":None}}}}
        patch_deployment(service,patch)
    rollout_all()


def app_projection(measured:dict)->dict:
    app=measured["application"]
    return {k:app.get(k) for k in ("requests","p95_ms","p99_ms","rps","errors","error_rate","slo_violations","timeouts")}


def baseline_cell(out:Path,evidence:Path,condition:str,rep:int,duration:int,scheduler_name:str,initial:dict[str,str])->dict:
    run_id=f"S-E4:{condition}:rep{rep}:KubeTopologySpread"
    apply_topology_spread(scheduler_name,run_id); placement=live_placement()
    problem=build_problem(evidence,condition,rep,initial); evaluation=evaluate_placement(problem,placement,RISK)
    time.sleep(5); measured,samples,log=measure(condition,rep,duration); health=wait_healthy()
    row={"run_id":run_id,"condition":condition,"replicate":rep,"method":"KubeTopologySpread","scheduler_name":scheduler_name,"initial_placement":initial,"placement":placement,"planning_objective":evaluation.total_objective,"planning_feasible":evaluation.feasible,"application":app_projection(measured),"resources":measured["resources"],"health":health,"completed_utc":utc_now()}
    row["accepted_evidence"]=bool(health["healthy"] and measured["application"]["requests"]>0)
    cell=out/condition/f"replicate-{rep:02d}"/"KubeTopologySpread"; cell.mkdir(parents=True,exist_ok=True); atomic_json(cell/"result.json",row); atomic_json(cell/"resource-samples.json",samples); (cell/"frontend.log").write_text(log,encoding="utf-8")
    restore_initial(initial,run_id+":restore")
    return row


def bplus_cell(out:Path,evidence:Path,condition:str,rep:int,duration:int,initial:dict[str,str])->dict:
    run_id=f"S-E4:{condition}:rep{rep}:BPlus-Exact"
    apply_placement(initial,run_id+":initial")
    problem=build_problem(evidence,condition,rep,initial); placement,planner,planner_seconds=plan("BPlus-Exact",problem,rep); relocation=apply_placement(placement,run_id); time.sleep(5)
    measured,samples,log=measure(condition,rep,duration); health=wait_healthy()
    row={"run_id":run_id,"condition":condition,"replicate":rep,"method":"BPlus-Exact","initial_placement":initial,"placement":placement,"planner":planner,"planner_runtime_seconds":planner_seconds,"relocation":relocation,"application":app_projection(measured),"resources":measured["resources"],"health":health,"completed_utc":utc_now()}
    row["accepted_evidence"]=bool(health["healthy"] and measured["application"]["requests"]>0 and planner["feasible"])
    cell=out/condition/f"replicate-{rep:02d}"/"BPlus-Exact"; cell.mkdir(parents=True,exist_ok=True); atomic_json(cell/"result.json",row); atomic_json(cell/"resource-samples.json",samples); (cell/"frontend.log").write_text(log,encoding="utf-8")
    apply_placement(initial,run_id+":restore")
    return row


def main()->int:
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("run_root",type=Path); p.add_argument("--evidence-run-root",type=Path,default=REPO/"RESULTS"/"primary"/"v03-20260811T151500Z"); p.add_argument("--replicates",type=int,default=5); p.add_argument("--duration-seconds",type=int,default=20); p.add_argument("--conditions",default=",".join(CONDITIONS)); p.add_argument("--scheduler-name",default="default-scheduler"); args=p.parse_args()
    conditions=[x for x in args.conditions.split(",") if x];
    if not set(conditions)<=set(CONDITIONS): p.error("unknown condition")
    if args.replicates<3: p.error("at least 3 replicates required; 5 recommended")
    root=args.run_root.resolve(); evidence=args.evidence_run_root.resolve(); out=root/"raw"/"S-E4-topology-spread-baseline"; out.mkdir(parents=True,exist_ok=True); atomic_json(out/"preflight.json",assert_live_preflight())
    rows=[]
    with campaign_lock("strengthening-live"):
        for ci,condition in enumerate(conditions):
            for rep in range(1,args.replicates+1):
                initial=initial_placement(f"S-E4-{condition}",9000+rep); apply_placement(initial,f"S-E4:{condition}:rep{rep}:paired-initial")
                order=["KubeTopologySpread","BPlus-Exact"] if (rep+ci)%2==0 else ["BPlus-Exact","KubeTopologySpread"]
                for method in order:
                    print(f"S-E4 {condition} rep {rep}/{args.replicates} {method}",flush=True)
                    row=baseline_cell(out,evidence,condition,rep,args.duration_seconds,args.scheduler_name,initial) if method=="KubeTopologySpread" else bplus_cell(out,evidence,condition,rep,args.duration_seconds,initial)
                    if not row["accepted_evidence"]: raise RuntimeError(f"S-E4 acceptance failed {row['run_id']}")
                    rows.append(row); atomic_json(out/"progress.json",{"updated_utc":utc_now(),"completed":len(rows),"target":len(conditions)*args.replicates*2})
        clear_live_network()
    csv_path=root/"derived"/"S-E4-topology-spread-baseline.csv"; csv_path.parent.mkdir(parents=True,exist_ok=True)
    fields=["condition","replicate","method","planning_objective","planning_feasible","planner_runtime_seconds","accepted_evidence"]
    with csv_path.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader();
        for r in rows: w.writerow({k:r.get(k) for k in fields})
    summary={"experiment":"S-E4","completed_utc":utc_now(),"conditions":conditions,"replicates":args.replicates,"methods":["KubeTopologySpread","BPlus-Exact"],"scheduler_name":args.scheduler_name,"cells":len(rows),"all_evidence_accepted":all(r["accepted_evidence"] for r in rows),"output_csv":str(csv_path.relative_to(root))}
    atomic_json(root/"derived"/"S-E4-summary.json",summary); write_manifest(root); print(json.dumps(summary,indent=2)); return 0

if __name__=="__main__": raise SystemExit(main())
