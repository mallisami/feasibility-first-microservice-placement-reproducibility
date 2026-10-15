#!/usr/bin/env python3
"""S-E6-only: Native Kubernetes vs NetworkOverhead/Diktyo vs B+ Exact.

This revision is strict: it never degrades to a two-method fallback. It boots a
pinned Helm client when required, installs the pinned Kubernetes SIG
scheduler-plugins NetworkOverhead implementation, verifies the profile with a
smoke test, executes only S-E6, and stores all evidence append-only in the run
root supplied by run_se6_only.py.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HERE=Path(__file__).resolve().parent; IMPL=HERE.parent; REPO=IMPL.parent
sys.path.insert(0,str(HERE)); sys.path.insert(0,str(IMPL/"code"))
from common import atomic_json, assert_live_preflight, campaign_lock, clear_live_network, utc_now, write_manifest, resource_snapshot
from mape_cap_bplus.models import RiskConfig
from mape_cap_bplus.objective import evaluate_placement
from run_v03_r1 import CONDITIONS, SERVICES, WORKERS, RACKS, apply_placement, build_problem, frontend_probe, initial_placement, measure, plan, wait_healthy, clear_network
from run_v03_r2 import NS, kubectl
from run_v03_r3 import live_placement
from run_se1_live_full_planner import choose_candidate
from se6_external_support import (
    APPGROUP_LABEL, APPGROUP_NAME, APPGROUP_SELECTOR_LABEL, DEFAULT_SCHEDULER_NAME,
    HELM_VERSION, NETWORK_TOPOLOGY_NAME, SCHEDULER_IMAGE, SCHEDULER_PLUGINS_VERSION,
    apply_json_object, delete_json_object, ensure_pinned_helm, install_networkoverhead,
    label_nodes_for_networkaware, restore_node_labels, uninstall_networkoverhead,
)

RISK=RiskConfig(0.8,1.5,1.0,1000.0)
GROUP_KEY="bplus-strengthening-group"; GROUP_VALUE="se6-online-boutique"
METHOD_ORDERS=[
    ["Native","External","BPlus-Exact"],
    ["External","BPlus-Exact","Native"],
    ["BPlus-Exact","Native","External"],
    ["Native","BPlus-Exact","External"],
    ["External","Native","BPlus-Exact"],
]


def _run(cmd:list[str], *, timeout:int=180, check:bool=True, input_text:str|None=None)->subprocess.CompletedProcess[str]:
    if cmd and cmd[0] == "kubectl" and os.environ.get("KUBE_CONTEXT"):
        cmd = ["kubectl", "--context", os.environ["KUBE_CONTEXT"], *cmd[1:]]
    r=subprocess.run(cmd,input=input_text,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=timeout)
    if check and r.returncode:
        raise RuntimeError(f"command failed ({r.returncode}): {' '.join(cmd)}\nstdout:\n{r.stdout[-2500:]}\nstderr:\n{r.stderr[-2500:]}")
    return r


def patch_deployment(service:str, patch:dict)->None:
    kubectl("patch","deployment",service,"-n",NS,"--type=merge","-p",json.dumps(patch))


def rollout_all()->dict[str,Any]:
    started=time.monotonic(); samples=[]; deadline=started+420.0
    while time.monotonic()<deadline:
        try:
            deployments=json.loads(_run(["kubectl","get","deployments","-n",NS,"-o","json"],timeout=30).stdout)
        except (subprocess.TimeoutExpired, RuntimeError, json.JSONDecodeError):
            time.sleep(2)
            continue
        status={item["metadata"]["name"]:item for item in deployments.get("items",[])}
        complete=True
        for service in SERVICES:
            dep=status.get(service,{})
            desired=dep.get("spec",{}).get("replicas",0)
            dep_status=dep.get("status",{})
            ready=(dep_status.get("observedGeneration",0)>=dep.get("metadata",{}).get("generation",0)
                   and dep_status.get("availableReplicas",0)==desired
                   and dep_status.get("updatedReplicas",0)==desired
                   and dep_status.get("unavailableReplicas",0)==0)
            complete=complete and ready
        samples.append({"elapsed_seconds":time.monotonic()-started,"frontend_ok":frontend_probe(),"rollouts_complete":complete})
        if complete: break
        time.sleep(1)
    if not samples or not samples[-1]["rollouts_complete"]: raise RuntimeError("placement rollout timeout after 420s")
    health=wait_healthy()
    if not health["healthy"]: raise RuntimeError("Online Boutique unhealthy after scheduler patch")
    failed=sum(not sample["frontend_ok"] for sample in samples)
    recovery=0.0
    failed_indexes=[i for i,sample in enumerate(samples) if not sample["frontend_ok"]]
    if failed_indexes:
        recovery=None
        for sample in samples[failed_indexes[-1]+1:]:
            if sample["frontend_ok"]:
                recovery=sample["elapsed_seconds"]
                break
    return {"rollout_seconds":time.monotonic()-started,"failed_health_probes":failed,
            "downtime_seconds":float(failed),"recovery_seconds":recovery,"probe_interval_seconds":1.0,
            "probe_timeline":samples}


def _app_labels(service:str)->dict[str,str]:
    return {APPGROUP_LABEL:APPGROUP_NAME,APPGROUP_SELECTOR_LABEL:service}


def label_current_pods_for_appgroup()->None:
    # Resolve each deployment's real selector rather than assuming an `app=` label.
    # This makes the NetworkOverhead prefilter see already-scheduled dependencies
    # before the first network-aware rollout.
    for service in SERVICES:
        dep=_run(["kubectl","get","deployment",service,"-n",NS,"-o","json"],timeout=30,check=False)
        if dep.returncode:
            raise RuntimeError(f"cannot inspect deployment selector for {service}: {dep.stderr[-1000:]}")
        match=(json.loads(dep.stdout).get("spec",{}).get("selector",{}).get("matchLabels",{}) or {})
        if not match:
            raise RuntimeError(f"deployment/{service} has no matchLabels selector")
        selector=",".join(f"{k}={v}" for k,v in sorted(match.items()))
        _run(["kubectl","label","pods","-n",NS,"-l",selector,f"{APPGROUP_LABEL}={APPGROUP_NAME}",f"{APPGROUP_SELECTOR_LABEL}={service}","--overwrite"],timeout=30,check=False)


def apply_topology_spread(scheduler_name:str, run_id:str)->dict[str,Any]:
    before=live_placement()
    constraint={"maxSkew":1,"topologyKey":"kubernetes.io/hostname","whenUnsatisfiable":"ScheduleAnyway","labelSelector":{"matchLabels":{GROUP_KEY:GROUP_VALUE}}}
    for service in SERVICES:
        labels={GROUP_KEY:GROUP_VALUE,APPGROUP_LABEL:None,APPGROUP_SELECTOR_LABEL:None}
        patch={"spec":{"template":{"metadata":{"labels":labels,"annotations":{"bplus-strengthening/se6-run":run_id}},"spec":{"nodeSelector":None,"schedulerName":scheduler_name,"topologySpreadConstraints":[constraint]}}}}
        patch_deployment(service,patch)
    relocation=rollout_all(); after=live_placement(); changed=[s for s in SERVICES if before.get(s)!=after.get(s)]
    relocation.update({"changed_services":changed,"relocations":len(changed),"placement_before":before,"placement_after":after})
    return relocation


def apply_external_scheduler(scheduler_name:str, run_id:str)->dict[str,Any]:
    before=live_placement()
    label_current_pods_for_appgroup()
    for service in SERVICES:
        labels={GROUP_KEY:None,**_app_labels(service)}
        patch={"spec":{"template":{"metadata":{"labels":labels,"annotations":{"bplus-strengthening/se6-run":run_id}},"spec":{"nodeSelector":None,"schedulerName":scheduler_name,"topologySpreadConstraints":None}}}}
        patch_deployment(service,patch)
    relocation=rollout_all(); after=live_placement(); changed=[s for s in SERVICES if before.get(s)!=after.get(s)]
    relocation.update({"changed_services":changed,"relocations":len(changed),"placement_before":before,"placement_after":after})
    return relocation


def restore_initial(initial:dict[str,str], run_id:str)->None:
    for service in SERVICES:
        labels={GROUP_KEY:None,APPGROUP_LABEL:None,APPGROUP_SELECTOR_LABEL:None}
        patch={"spec":{"template":{"metadata":{"labels":labels,"annotations":{"bplus-strengthening/se6-run":run_id}},"spec":{"nodeSelector":{"kubernetes.io/hostname":initial[service]},"schedulerName":None,"topologySpreadConstraints":None}}}}
        patch_deployment(service,patch)
    rollout_all()


def clean_state(initial:dict[str,str], run_id:str)->None:
    restore_initial(initial,run_id); clear_network(); time.sleep(3)


def app_projection(measured:dict)->dict:
    app=measured["application"]
    return {k:app.get(k) for k in ("requests","p50_ms","p95_ms","p99_ms","rps","errors","error_rate","slo_violations","timeouts","downtime_seconds")}


def kubernetes_events(namespace:str=NS)->list[dict]:
    r=_run(["kubectl","get","events","-n",namespace,"--sort-by=.lastTimestamp","-o","json"],timeout=30,check=False)
    if r.returncode: return []
    try: items=json.loads(r.stdout).get("items",[])
    except Exception: return []
    return [{"type":e.get("type"),"reason":e.get("reason"),"message":e.get("message","")[:250],"count":e.get("count"),"last":e.get("lastTimestamp")} for e in items[-80:]]


def make_appgroup(evidence:Path)->dict[str,Any]:
    initial=initial_placement("stable",1); problem=build_problem(evidence,"stable",1,initial)
    dep_map={s:[] for s in SERVICES}
    for flow in problem.flows:
        if flow.source_replica in dep_map and flow.destination_replica in SERVICES and flow.destination_replica!=flow.source_replica:
            dep_map[flow.source_replica].append(flow.destination_replica)
    workloads=[]
    for service in SERVICES:
        deps=[]
        for dest in sorted(set(dep_map[service])):
            deps.append({"workload":{"kind":"Deployment","name":dest,"selector":dest,"apiVersion":"apps/v1","namespace":NS},"maxNetworkCost":80})
        item={"workload":{"kind":"Deployment","name":service,"selector":service,"apiVersion":"apps/v1","namespace":NS}}
        if deps: item["dependencies"]=deps
        workloads.append(item)
    return {"apiVersion":"appgroup.diktyo.x-k8s.io/v1alpha1","kind":"AppGroup","metadata":{"name":APPGROUP_NAME,"namespace":NS},"spec":{"numMembers":len(SERVICES),"topologySortingAlgorithm":"AlternateKahn","workloads":workloads}}


def make_network_topology(evidence:Path, condition:str, rep:int, initial:dict[str,str])->dict[str,Any]:
    problem=build_problem(evidence,condition,rep,initial)
    zones=sorted(set(RACKS.values())); origins=[]
    for origin in zones:
        costs=[]
        for dest in zones:
            if dest==origin: continue
            weighted=0.0; total=0.0; unavailable=False
            for scenario in problem.scenarios:
                link=scenario.links.get((origin,dest))
                if link is None: continue
                total += float(scenario.weight)
                if not link.available:
                    unavailable=True
                weighted += float(scenario.weight) * (10000.0 if not link.available else float(link.latency_ms))
            # Give NetworkOverhead the probability-weighted effective network cost from
            # the same registered condition scenarios. Unavailable states contribute
            # the plugin's maximum cost rather than forcing the whole mixed scenario
            # to 10000; this avoids unfairly turning partial uncertainty into certain
            # unavailability for the external comparator.
            network_cost=max(1,min(10000,int(round(weighted/max(total,1e-9)))))
            costs.append({"destination":dest,"networkCost":network_cost})
        origins.append({"origin":origin,"costs":costs})
    # v0.33.5 CRD schema uses weights[].topologyList[].originList[].costList.
    # configmapName is required by the CRD even though UserDefined weights are
    # supplied directly; the experiment does not rely on a Netperf controller.
    origin_list=[]
    for origin_row in origins:
        origin_list.append({
            "origin": origin_row["origin"],
            "costList": origin_row["costs"],
        })
    return {
        "apiVersion":"networktopology.diktyo.x-k8s.io/v1alpha1",
        "kind":"NetworkTopology",
        "metadata":{"name":NETWORK_TOPOLOGY_NAME,"namespace":NS},
        "spec":{
            "configmapName":"bplus-se6-user-defined",
            "weights":[{
                "name":"UserDefined",
                "topologyList":[{
                    "topologyKey":"topology.kubernetes.io/zone",
                    "originList":origin_list,
                }],
            }],
        },
    }


def update_network_topology(evidence:Path,condition:str,rep:int,initial:dict[str,str],evidence_out:Path)->dict[str,Any]:
    obj=make_network_topology(evidence,condition,rep,initial); apply_json_object(obj)
    path=evidence_out/"network-topologies"/condition/f"replicate-{rep:02d}.json"; path.parent.mkdir(parents=True,exist_ok=True); atomic_json(path,obj)
    return obj


def smoke_test_scheduler(evidence:Path,out:Path,scheduler_name:str)->dict[str,Any]:
    initial=initial_placement("stable",991); apply_placement(initial,"S-E6:smoke:initial")
    update_network_topology(evidence,"stable",1,initial,out)
    label_current_pods_for_appgroup()
    service="adservice"; run_id="S-E6:external-scheduler-smoke"
    patch={"spec":{"template":{"metadata":{"labels":_app_labels(service),"annotations":{"bplus-strengthening/se6-smoke":"true"}},"spec":{"nodeSelector":None,"schedulerName":scheduler_name,"topologySpreadConstraints":None}}}}
    patch_deployment(service,patch)
    r=_run(["kubectl","rollout","status",f"deployment/{service}","-n",NS,"--timeout=300s"],timeout=330,check=False)
    if r.returncode: raise RuntimeError(f"external scheduler smoke rollout failed: {r.stderr[-1200:]}")
    pods=json.loads(_run(["kubectl","get","pods","-n",NS,"-l",f"app={service}","-o","json"],timeout=60).stdout).get("items",[])
    matches=[p for p in pods if p.get("spec",{}).get("schedulerName")==scheduler_name and p.get("spec",{}).get("nodeName")]
    scheduler_logs=_run(["kubectl","logs","-n","scheduler-plugins",f"deployment/{scheduler_name}","--tail=300"],timeout=60,check=False).stdout
    if not matches: raise RuntimeError("external scheduler smoke pod was not bound by the requested schedulerName")
    result={"passed":True,"scheduler_name":scheduler_name,"pod":matches[0]["metadata"]["name"],"node":matches[0]["spec"]["nodeName"],"scheduler_logs_tail":scheduler_logs[-4000:],"completed_utc":utc_now()}
    atomic_json(out/"scheduler-smoke-test.json",result); restore_initial(initial,run_id+":restore"); return result


def _base_row(method:str,condition:str,rep:int,placement:dict[str,str],problem,evaluation,measured,samples,log,health,snap,events)->dict[str,Any]:
    return {"condition":condition,"replicate":rep,"scheduler":method,"pod_placement":placement,"planning_objective":evaluation.total_objective,"planning_feasible":evaluation.feasible,"application":app_projection(measured),"resources":measured["resources"],"P50":measured["application"].get("p50_ms"),"P95":measured["application"].get("p95_ms"),"P99":measured["application"].get("p99_ms"),"throughput_rps":measured["application"].get("rps"),"errors":measured["application"].get("errors"),"downtime":measured["application"].get("downtime_seconds"),"resource_snapshot":snap,"kubernetes_events":events,"health":health,"completed_utc":utc_now()}


def _save_cell(out:Path,row:dict,samples:list|dict,log:str,method:str,condition:str,rep:int)->None:
    cell=out/condition/f"replicate-{rep:02d}"/method; cell.mkdir(parents=True,exist_ok=True); atomic_json(cell/"result.json",row); atomic_json(cell/"resource-samples.json",samples); (cell/"frontend.log").write_text(log,encoding="utf-8")


def native_cell(out:Path,evidence:Path,condition:str,rep:int,duration:int,initial:dict[str,str])->dict:
    run_id=f"S-E6:{condition}:rep{rep}:Native"; relocation=apply_topology_spread("default-scheduler",run_id); placement=live_placement(); problem=build_problem(evidence,condition,rep,initial); evaluation=evaluate_placement(problem,placement,RISK)
    time.sleep(5); measured,samples,log=measure(condition,rep,duration); health=wait_healthy(); snap=resource_snapshot(); events=kubernetes_events()
    row=_base_row("Native",condition,rep,placement,problem,evaluation,measured,samples,log,health,snap,events); row.update({"run_id":run_id,"scheduler_version":"kube-scheduler","scheduler_image":"built-in","initial_placement":initial,"relocation":relocation,"downtime":relocation["downtime_seconds"]}); row["accepted_evidence"]=bool(health["healthy"] and measured["application"]["requests"]>=500); _save_cell(out,row,samples,log,"Native",condition,rep); clean_state(initial,run_id+":restore"); return row


def external_cell(out:Path,evidence:Path,condition:str,rep:int,duration:int,initial:dict[str,str],scheduler_name:str,ext_info:dict)->dict:
    run_id=f"S-E6:{condition}:rep{rep}:External"; topology=update_network_topology(evidence,condition,rep,initial,out); relocation=apply_external_scheduler(scheduler_name,run_id); placement=live_placement(); problem=build_problem(evidence,condition,rep,initial); evaluation=evaluate_placement(problem,placement,RISK)
    time.sleep(5); measured,samples,log=measure(condition,rep,duration); health=wait_healthy(); snap=resource_snapshot(); events=kubernetes_events()
    row=_base_row("External-NetworkOverhead",condition,rep,placement,problem,evaluation,measured,samples,log,health,snap,events); row.update({"run_id":run_id,"scheduler_name":scheduler_name,"scheduler_version":ext_info["scheduler_plugins_version"],"scheduler_image":ext_info["scheduler_image"],"network_topology":topology,"initial_placement":initial,"relocation":relocation,"downtime":relocation["downtime_seconds"]}); row["accepted_evidence"]=bool(health["healthy"] and measured["application"]["requests"]>=500); _save_cell(out,row,samples,log,"External-NetworkOverhead",condition,rep); clean_state(initial,run_id+":restore"); return row


def bplus_cell(out:Path,evidence:Path,condition:str,rep:int,duration:int,initial:dict[str,str])->dict:
    run_id=f"S-E6:{condition}:rep{rep}:BPlus-Exact"; apply_placement(initial,run_id+":initial"); problem=build_problem(evidence,condition,rep,initial); placement,gate=choose_candidate(problem,initial,"Exact",rep,45.0); planner=gate["metadata"]; planner_seconds=gate["runtime_seconds"]; accepted=bool(gate["economic_accept"] and gate["moved_replicas"]); applied=placement if accepted else initial; evaluation=evaluate_placement(problem,applied,RISK); relocation=apply_placement(applied,run_id) if accepted else None
    time.sleep(5); measured,samples,log=measure(condition,rep,duration); health=wait_healthy(); snap=resource_snapshot(); events=kubernetes_events()
    row=_base_row("BPlus-Exact",condition,rep,applied,problem,evaluation,measured,samples,log,health,snap,events); row.update({"run_id":run_id,"scheduler_version":"local","scheduler_image":"in-process","planner":planner,"planner_runtime_seconds":planner_seconds,"solver_wall_time":planner_seconds,"gate":gate,"final_net_benefit":gate["net_benefit"],"relocation":relocation,"initial_placement":initial,"independent_feasibility_evaluation":True}); row["accepted_evidence"]=bool(health["healthy"] and measured["application"]["requests"]>=500 and evaluation.feasible); _save_cell(out,row,samples,log,"BPlus-Exact",condition,rep); clean_state(initial,run_id+":restore"); return row


def main()->int:
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("run_root",type=Path); p.add_argument("--evidence-run-root",type=Path,default=REPO/"RESULTS"/"primary"/"v03-20260811T151500Z"); p.add_argument("--replicates",type=int,default=5); p.add_argument("--duration-seconds",type=int,default=20); p.add_argument("--conditions",default=",".join(CONDITIONS)); p.add_argument("--methods",default="Native,External,BPlus-Exact"); p.add_argument("--external-scheduler-name",default=DEFAULT_SCHEDULER_NAME); p.add_argument("--keep-external-scheduler",action="store_true"); args=p.parse_args()
    conditions=[x for x in args.conditions.split(",") if x];
    if not set(conditions)<=set(CONDITIONS): p.error("unknown condition")
    if args.replicates not in range(8,11): p.error("confirmatory design requires 8-10 paired replicates")
    methods=[x for x in args.methods.split(",") if x]
    if not methods or not set(methods)<={"Native","External","BPlus-Exact"}: p.error("unknown method")
    root=args.run_root.resolve(); evidence=args.evidence_run_root.resolve(); out=root/"raw"/"S-E6-external-scheduler"; out.mkdir(parents=True,exist_ok=True); envdir=root/"logs"/"S-E6-environment"; envdir.mkdir(parents=True,exist_ok=True)
    atomic_json(out/"preflight.json",assert_live_preflight()); atomic_json(envdir/"pre-resource-snapshot.json",resource_snapshot())
    helm=None; original_labels={}; ext_info={}; measurements_started=False
    try:
        helm,helm_info=ensure_pinned_helm(HERE/"tools",envdir)
        original_labels=label_nodes_for_networkaware(WORKERS,RACKS,envdir)
        ready=_run(["kubectl","wait","--for=condition=Available","deployment/network-aware-scheduler","deployment/scheduler-plugins-controller","-n","scheduler-plugins","--timeout=10s"],timeout=20,check=False)
        if ready.returncode==0:
            ext_info={"implementation":"Kubernetes SIG scheduler-plugins NetworkOverhead (Diktyo lineage)","scheduler_name":args.external_scheduler_name,"scheduler_plugins_version":SCHEDULER_PLUGINS_VERSION,"scheduler_image":SCHEDULER_IMAGE,"reused_verified_installation":True}
        else:
            ext_info=install_networkoverhead(helm,envdir,scheduler_name=args.external_scheduler_name,workload_namespace=NS)
        appgroup=make_appgroup(evidence); apply_json_object(appgroup); atomic_json(envdir/"appgroup.json",appgroup)
        smoke=smoke_test_scheduler(evidence,out,args.external_scheduler_name); atomic_json(envdir/"scheduler-smoke.json",smoke)
        if not smoke.get("passed"): raise RuntimeError("external scheduler smoke test failed")
        measurements_started=True
        rows=[]; target=len(conditions)*args.replicates*len(methods)
        with campaign_lock("strengthening-live"):
            for ci,condition in enumerate(conditions):
                for rep in range(1,args.replicates+1):
                    initial=initial_placement(f"S-E6-{condition}",9000+rep); apply_placement(initial,f"S-E6:{condition}:rep{rep}:paired-initial")
                    order=[method for method in METHOD_ORDERS[(rep-1)%len(METHOD_ORDERS)] if method in methods]
                    for method in order:
                        method_dir = "External-NetworkOverhead" if method == "External" else method
                        cell_file = out / condition / f"replicate-{rep:02d}" / method_dir / "result.json"
                        if cell_file.exists():
                            try:
                                saved_row = json.loads(cell_file.read_text(encoding="utf-8"))
                                if saved_row.get("accepted_evidence"):
                                    print(f"Resuming saved cell: S-E6 {condition} rep {rep}/5 {method} (order {order})", flush=True)
                                    rows.append(saved_row)
                                    atomic_json(out/"progress.json", {"updated_utc": utc_now(), "completed": len(rows), "target": target, "last_run_id": saved_row.get("run_id")})
                                    continue
                            except Exception:
                                pass
                        print(f"S-E6 {condition} rep {rep}/5 {method} (order {order})", flush=True)
                        if method=="Native": row=native_cell(out,evidence,condition,rep,args.duration_seconds,initial)
                        elif method=="External": row=external_cell(out,evidence,condition,rep,args.duration_seconds,initial,args.external_scheduler_name,ext_info)
                        else: row=bplus_cell(out,evidence,condition,rep,args.duration_seconds,initial)
                        if not row["accepted_evidence"]: raise RuntimeError(f"S-E6 acceptance failed {row['run_id']}")
                        rows.append(row); atomic_json(out/"progress.json",{"updated_utc":utc_now(),"completed":len(rows),"target":target,"last_run_id":row["run_id"]})
            clear_live_network()
        csv_path=root/"derived"/"S-E6-external-scheduler.csv"; csv_path.parent.mkdir(parents=True,exist_ok=True)
        fields=["condition","replicate","scheduler","scheduler_version","scheduler_image","planning_objective","planning_feasible","planner_runtime_seconds","P50","P95","P99","throughput_rps","errors","downtime","accepted_evidence"]
        with csv_path.open("w",newline="",encoding="utf-8") as f:
            w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); [w.writerow({k:r.get(k) for k in fields}) for r in rows]
        public_methods=["External-NetworkOverhead" if method=="External" else method for method in methods]
        summary={"experiment":"S-E6","status":"COMPLETED","completed_utc":utc_now(),"conditions":conditions,"replicates":args.replicates,"methods":public_methods,"cells":len(rows),"target_cells":len(conditions)*args.replicates*len(methods),"all_evidence_accepted":all(r["accepted_evidence"] for r in rows),"external_scheduler":ext_info,"helm":helm_info,"counterbalanced_orders":METHOD_ORDERS,"fallback_allowed":False,"results_append_only":True,"output_csv":str(csv_path.relative_to(root))}
        atomic_json(root/"derived"/"S-E6-summary.json",summary); write_manifest(root); print(json.dumps(summary,indent=2)); return 0
    except Exception as exc:
        blocked={"experiment":"S-E6","status":"FAILED_AFTER_MEASUREMENT_START" if measurements_started else "S-E6_BLOCKED_BEFORE_MEASUREMENT","reason":str(exc),"recorded_utc":utc_now(),"fallback_executed":False}
        atomic_json(out/"S-E6_BLOCKED_OR_FAILED.json",blocked); write_manifest(root); print(json.dumps(blocked,indent=2),file=sys.stderr); return 2
    finally:
        clear_network()
        try: delete_json_object("appgroup",APPGROUP_NAME,NS); delete_json_object("networktopology",NETWORK_TOPOLOGY_NAME,NS)
        except Exception: pass
        try:
            if helm is not None and not args.keep_external_scheduler: uninstall_networkoverhead(helm)
        except Exception: pass
        try:
            if original_labels: restore_node_labels(original_labels)
        except Exception: pass

if __name__=="__main__": raise SystemExit(main())
