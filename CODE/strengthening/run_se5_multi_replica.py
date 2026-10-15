#!/usr/bin/env python3
"""S-E5: live same-service multi-replica B+ placement experiment.

Two selected Online Boutique Deployments are temporarily split into two one-pod
clone Deployments each. The original Services continue selecting label app=<service>,
so requests reach both live replicas while each clone can receive an independent
nodeSelector chosen by the replica-level optimizer.
"""
from __future__ import annotations
import argparse, copy, csv, json, sys, time
from pathlib import Path

HERE=Path(__file__).resolve().parent; IMPL=HERE.parent; REPO=IMPL.parent
sys.path.insert(0,str(HERE)); sys.path.insert(0,str(IMPL/"code"))
from common import atomic_json, assert_live_preflight, campaign_lock, clear_live_network, run, utc_now, write_manifest
from mape_cap_bplus.exact import solve_exact
from mape_cap_bplus.models import FlowSpec, ProblemInstance, RelocationCost, ReplicaSpec, RiskConfig
from mape_cap_bplus.objective import evaluate_placement
from run_v03_r1 import SERVICES, WORKERS, apply_placement, build_problem, initial_placement, measure, wait_healthy
from run_v03_r2 import NS, kubectl, kubectl_json

RISK=RiskConfig(0.8,1.5,1.0,1000.0)
SLOTS=("a","b")


def clone_name(service:str,slot:str)->str: return f"{service}-bplus-{slot}"


def apply_manifest(obj:dict)->None:
    res=run(["kubectl","apply","-f","-"],input_text=json.dumps(obj),timeout=180)


def create_clones(service:str,nodes:dict[str,str])->None:
    dep=kubectl_json("get","deployment",service,"-n",NS)
    kubectl("scale",f"deployment/{service}","-n",NS,"--replicas=0")
    for slot in SLOTS:
        spec=copy.deepcopy(dep["spec"]); spec["replicas"]=1
        spec.pop("progressDeadlineSeconds",None)
        selector=spec.setdefault("selector",{}).setdefault("matchLabels",{}); selector["bplus-replica-slot"]=slot
        tmpl=spec["template"]; labels=tmpl.setdefault("metadata",{}).setdefault("labels",{}); labels["bplus-replica-slot"]=slot; labels["app"]=service
        tmpl.setdefault("metadata",{}).setdefault("annotations",{})["bplus-strengthening/se5-slot"]=slot
        tmpl["spec"]["nodeSelector"]={"kubernetes.io/hostname":nodes[slot]}
        obj={"apiVersion":dep.get("apiVersion","apps/v1"),"kind":"Deployment","metadata":{"name":clone_name(service,slot),"namespace":NS,"labels":{"app":service,"bplus-strengthening":"se5"}},"spec":spec}
        apply_manifest(obj)
        r=run(["kubectl","rollout","status",f"deployment/{clone_name(service,slot)}","-n",NS,"--timeout=420s"],check=False,timeout=440)
        if r.returncode: raise RuntimeError(f"clone rollout failed {service}/{slot}: {r.stderr[-1000:]}")


def delete_clones(service:str,restore_node:str)->None:
    for slot in SLOTS:
        kubectl("delete","deployment",clone_name(service,slot),"-n",NS,"--ignore-not-found=true","--wait=true")
    patch={"spec":{"replicas":1,"template":{"metadata":{"annotations":{"bplus-strengthening/se5-restore":utc_now()}},"spec":{"nodeSelector":{"kubernetes.io/hostname":restore_node}}}}}
    kubectl("patch","deployment",service,"-n",NS,"--type=merge","-p",json.dumps(patch))


def selected_live_nodes(service:str)->dict[str,str]:
    pods=kubectl_json("get","pods","-n",NS,"-l",f"app={service}")["items"]
    result={}
    for pod in pods:
        slot=pod.get("metadata",{}).get("labels",{}).get("bplus-replica-slot"); node=pod.get("spec",{}).get("nodeName")
        if slot in SLOTS and node and not pod.get("metadata",{}).get("deletionTimestamp"): result[slot]=node
    if set(result)!=set(SLOTS): raise RuntimeError(f"missing live clone replicas for {service}: {result}")
    return result


def base_nonselected_nodes()->dict[str,str]:
    pods=kubectl_json("get","pods","-n",NS)["items"]; out={}
    for p in pods:
        app=p.get("metadata",{}).get("labels",{}).get("app"); slot=p.get("metadata",{}).get("labels",{}).get("bplus-replica-slot")
        if app in SERVICES and not slot and p.get("spec",{}).get("nodeName") and not p.get("metadata",{}).get("deletionTimestamp"): out[app]=p["spec"]["nodeName"]
    return out


def expand_problem(base:ProblemInstance,selected:list[str])->ProblemInstance:
    base_rep={r.replica_id:r for r in base.replicas}; ids={s:([f"{s}#a",f"{s}#b"] if s in selected else [s]) for s in SERVICES}
    reps=[]; reloc={}; current={}; non=base_nonselected_nodes()
    live_sel={s:selected_live_nodes(s) for s in selected}
    for service in SERVICES:
        src=base_rep[service]
        for rid in ids[service]:
            slot=rid.rsplit("#",1)[-1] if "#" in rid else None
            reps.append(ReplicaSpec(rid,service,src.cpu_request,src.memory_request_mb,src.allowed_nodes,service if service in selected else src.anti_affinity_group))
            c=base.relocation_costs[service]; reloc[rid]=RelocationCost(rid,c.cost_units,c.expected_seconds,c.uncertainty_units,c.provenance)
            current[rid]=live_sel[service][slot] if service in selected else non.get(service,base.current_placement[service])
    flows=[]
    for f in base.flows:
        srcs=ids[f.source_replica]; dsts=ids[f.destination_replica]; div=len(srcs)*len(dsts)
        for s in srcs:
            for d in dsts:
                flows.append(FlowSpec(f"{f.flow_id}:{s}->{d}",s,d,f.requests_per_window/div,f.bits_per_window/div,f.criticality,f.max_expected_latency_ms))
    return ProblemInstance(base.instance_id+"-multi-replica",base.decision_window_seconds,base.nodes,tuple(reps),tuple(flows),base.scenarios,current,reloc,max_relocations=min(6,len(reps)),metadata={**dict(base.metadata),"strengthening":"S-E5","replicated_services":selected})


def apply_replica_placement(placement:dict[str,str],selected:list[str],run_id:str)->dict:
    started=time.monotonic(); changed=[]
    for rid,node in placement.items():
        if "#" in rid:
            service,slot=rid.split("#",1); dep=clone_name(service,slot)
        else:
            service=rid; dep=service
        patch={"spec":{"template":{"metadata":{"annotations":{"bplus-strengthening/se5-run":run_id}},"spec":{"nodeSelector":{"kubernetes.io/hostname":node}}}}}
        kubectl("patch","deployment",dep,"-n",NS,"--type=merge","-p",json.dumps(patch)); changed.append(dep)
    for dep in sorted(set(changed)):
        r=run(["kubectl","rollout","status",f"deployment/{dep}","-n",NS,"--timeout=420s"],check=False,timeout=440)
        if r.returncode: raise RuntimeError(f"rollout failed {dep}: {r.stderr[-1000:]}")
    return {"deployments_touched":sorted(set(changed)),"rollout_seconds":time.monotonic()-started}


def main()->int:
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("run_root",type=Path); p.add_argument("--evidence-run-root",type=Path,default=REPO/"RESULTS"/"primary"/"v03-20260811T151500Z"); p.add_argument("--services",default="frontend,productcatalogservice"); p.add_argument("--conditions",default="stable,persistent-degradation"); p.add_argument("--replicates",type=int,default=5); p.add_argument("--duration-seconds",type=int,default=20); args=p.parse_args()
    selected=[x for x in args.services.split(",") if x]; conditions=[x for x in args.conditions.split(",") if x]
    if not selected or not set(selected)<=set(SERVICES): p.error("unknown selected service")
    root=args.run_root.resolve(); evidence=args.evidence_run_root.resolve(); out=root/"raw"/"S-E5-live-multi-replica"; out.mkdir(parents=True,exist_ok=True); atomic_json(out/"preflight.json",assert_live_preflight())
    rows=[]
    with campaign_lock("strengthening-live"):
        for ci,condition in enumerate(conditions):
            for rep in range(1,args.replicates+1):
                initial=initial_placement(f"S-E5-{condition}",10000+rep); apply_placement(initial,f"S-E5:{condition}:rep{rep}:initial")
                # Place the two clones on distinct deterministic nodes before both paired methods.
                for si,service in enumerate(selected):
                    nodes={"a":WORKERS[(rep+si)%len(WORKERS)],"b":WORKERS[(rep+si+1)%len(WORKERS)]}; create_clones(service,nodes)
                try:
                    if not wait_healthy()["healthy"]: raise RuntimeError("Online Boutique unhealthy after clone split")
                    base=build_problem(evidence,condition,rep,initial); problem=expand_problem(base,selected); current=dict(problem.current_placement)
                    methods=["Current-MultiReplica","BPlus-Exact-MultiReplica"] if (rep+ci)%2==0 else ["BPlus-Exact-MultiReplica","Current-MultiReplica"]
                    for method in methods:
                        apply_replica_placement(current,selected,f"S-E5:{condition}:rep{rep}:restore")
                        if method.startswith("BPlus"):
                            placement,meta=solve_exact(problem,RISK,time_limit_seconds=60,require_optimal=False)
                        else:
                            placement,meta=dict(current),{"baseline":"current split placement"}
                        evaln=evaluate_placement(problem,placement,RISK); relocation=apply_replica_placement(placement,selected,f"S-E5:{condition}:rep{rep}:{method}"); time.sleep(5)
                        measured,samples,log=measure(condition,rep,args.duration_seconds); health=wait_healthy()
                        row={"experiment":"S-E5","condition":condition,"replicate":rep,"method":method,"selected_services":selected,"replica_count":len(problem.replicas),"placement":placement,"planning_objective":evaln.total_objective,"planning_feasible":evaln.feasible,"solver":meta,"relocation":relocation,"application":measured["application"],"resources":measured["resources"],"health":health,"completed_utc":utc_now()}; row["accepted_evidence"]=bool(health["healthy"] and measured["application"]["requests"]>0 and (evaln.feasible if method.startswith("BPlus") else True))
                        cell=out/condition/f"replicate-{rep:02d}"/method; cell.mkdir(parents=True,exist_ok=True); atomic_json(cell/"result.json",row); atomic_json(cell/"resource-samples.json",samples); (cell/"frontend.log").write_text(log,encoding="utf-8")
                        if not row["accepted_evidence"]: raise RuntimeError("S-E5 evidence acceptance failed")
                        rows.append(row); atomic_json(out/"progress.json",{"updated_utc":utc_now(),"completed":len(rows),"target":len(conditions)*args.replicates*2})
                finally:
                    clear_live_network()
                    for service in selected:
                        try: delete_clones(service,initial[service])
                        except Exception: pass
                    time.sleep(5)
                    if not wait_healthy()["healthy"]: raise RuntimeError("Online Boutique failed to restore after S-E5")
    csv_path=root/"derived"/"S-E5-live-multi-replica.csv"; csv_path.parent.mkdir(parents=True,exist_ok=True)
    fields=["condition","replicate","method","replica_count","planning_objective","planning_feasible","accepted_evidence"]
    with csv_path.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows([{k:r.get(k) for k in fields} for r in rows])
    summary={"experiment":"S-E5","completed_utc":utc_now(),"selected_services":selected,"replicas_per_selected_service":2,"conditions":conditions,"replicates":args.replicates,"cells":len(rows),"all_evidence_accepted":all(r["accepted_evidence"] for r in rows),"output_csv":str(csv_path.relative_to(root))}
    atomic_json(root/"derived"/"S-E5-summary.json",summary); write_manifest(root); print(json.dumps(summary,indent=2)); return 0

if __name__=="__main__": raise SystemExit(main())
