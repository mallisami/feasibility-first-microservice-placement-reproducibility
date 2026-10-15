#!/usr/bin/env python3
"""Aggregate completed strengthening evidence and compute a separate Holm family.

These tests are intentionally kept separate from the frozen primary v0.3 Holm
family unless/until the manuscript's multiplicity plan is explicitly revised.
"""
from __future__ import annotations
import argparse,csv,json,math,sys
from collections import defaultdict
from pathlib import Path
import numpy as np
from scipy.stats import ttest_rel
HERE=Path(__file__).resolve().parent; sys.path.insert(0,str(HERE))
from common import atomic_json, utc_now, write_manifest

METRICS=("p95_ms","p99_ms","rps","errors")
PAIR_SPECS={
 "S-E4-topology-spread-baseline":("KubeTopologySpread","BPlus-Exact","condition"),
 "S-E5-live-multi-replica":("Current-MultiReplica","BPlus-Exact-MultiReplica","condition"),
 "S-GRACE-recovery-guard":("Immediate","GraceGuard","horizon_seconds"),
 "S-E6-external-scheduler":[
   ("Native","BPlus-Exact","condition"),
   ("External","BPlus-Exact","condition"),
   ("Native","External","condition"),
 ],
}

# S-E7 overhead contrasts (replicate-level, not paired-method)
OVERHEAD_CONTRASTS=[
 ("O2","O1","telemetry_overhead"),
 ("O3","O2","gating_overhead"),
 ("O4","O3","exact_optimization_overhead"),
 ("O5","O3","lns_optimization_overhead"),
 ("O4","O5","exact_vs_lns_overhead"),
]


def holm(pvals:list[float])->list[float]:
 n=len(pvals); order=sorted(range(n),key=lambda i:pvals[i]); adj=[1.0]*n; running=0.0
 for rank,i in enumerate(order):
  val=min(1.0,(n-rank)*pvals[i]); running=max(running,val); adj[i]=running
 return adj


def app_metric(row:dict,name:str):
 app=row.get("application",{}); v=app.get(name)
 try:return float(v)
 except (TypeError,ValueError):return math.nan


def load_results(base:Path)->list[dict]:
 rows=[]
 for p in base.glob("**/result.json"):
  try:
   r=json.loads(p.read_text(encoding="utf-8")); r["_path"]=str(p.relative_to(base)); rows.append(r)
  except Exception: pass
 return rows


def paired_tests_for_family(raw:Path, family:str, method_a:str, method_b:str, group_key:str)->list[dict]:
 rows=load_results(raw/family); tests=[]
 if not rows: return tests
 groups=defaultdict(list)
 for r in rows: groups[r.get(group_key)].append(r)
 for group,items in groups.items():
  by={(r.get("replicate"),r.get("method",r.get("scheduler"))):r for r in items}
  reps=sorted({k[0] for k in by if k[0] is not None and (k[0],method_a) in by and (k[0],method_b) in by})
  for metric in METRICS:
   va=np.array([app_metric(by[(rep,method_a)],metric) for rep in reps],dtype=float)
   vb=np.array([app_metric(by[(rep,method_b)],metric) for rep in reps],dtype=float)
   mask=np.isfinite(va)&np.isfinite(vb); va=va[mask]; vb=vb[mask]
   if len(va)>=2:
    stat,pv=ttest_rel(vb,va,nan_policy="omit"); diff=vb-va
    tests.append({"family":family,"group":group,"metric":metric,"method_a":method_a,"method_b":method_b,"n":len(diff),"mean_a":float(np.mean(va)),"mean_b":float(np.mean(vb)),"mean_difference_b_minus_a":float(np.mean(diff)),"sd_difference":float(np.std(diff,ddof=1)) if len(diff)>1 else 0.0,"t":float(stat),"p_raw":float(pv)})
 return tests


def overhead_contrasts(raw:Path)->list[dict]:
 rows=load_results(raw/"S-E7-isolated-overhead")
 if not rows: return []
 by_mode=defaultdict(list)
 for r in rows: by_mode[r.get("mode")].append(r)
 tests=[]
 for mode_b, mode_a, label in OVERHEAD_CONTRASTS:
  reps_a={r["replicate"]:r for r in by_mode.get(mode_a,[])}
  reps_b={r["replicate"]:r for r in by_mode.get(mode_b,[])}
  common=sorted(set(reps_a)&set(reps_b))
  for metric in METRICS:
   va=np.array([app_metric(reps_a[rep],metric) for rep in common],dtype=float)
   vb=np.array([app_metric(reps_b[rep],metric) for rep in common],dtype=float)
   mask=np.isfinite(va)&np.isfinite(vb); va=va[mask]; vb=vb[mask]
   if len(va)>=2:
    stat,pv=ttest_rel(vb,va,nan_policy="omit"); diff=vb-va
    tests.append({"family":"S-E7-isolated-overhead","group":label,"metric":metric,"method_a":mode_a,"method_b":mode_b,"n":len(diff),"mean_a":float(np.mean(va)),"mean_b":float(np.mean(vb)),"mean_difference_b_minus_a":float(np.mean(diff)),"sd_difference":float(np.std(diff,ddof=1)) if len(diff)>1 else 0.0,"t":float(stat),"p_raw":float(pv)})
 return tests


def safety_summary(raw:Path)->dict:
 rows=load_results(raw/"S-E8-failure-robustness")
 if not rows: return {"available":False}
 by_fault=defaultdict(list)
 for r in rows: by_fault[r.get("fault_type")].append(r)
 summary={"available":True,"total_cells":len(rows),"faults":{}}
 for fault,items in by_fault.items():
  verdicts=[r.get("verdict",{}) for r in items]
  summary["faults"][fault]={
   "cells":len(items),
   "all_safe":all(v.get("safe",False) for v in verdicts),
   "safe_count":sum(1 for v in verdicts if v.get("safe",False)),
   "failure_handling_rate":sum(1 for v in verdicts if v.get("failure_logged",False))/max(1,len(verdicts)),
   "recovery_rate":sum(1 for v in verdicts if v.get("controller_recovered",False))/max(1,len(verdicts)),
  }
 summary["all_safe"]=all(f["all_safe"] for f in summary["faults"].values())
 return summary


def main()->int:
 p=argparse.ArgumentParser(description=__doc__); p.add_argument("run_root",type=Path); args=p.parse_args(); root=args.run_root.resolve(); raw=root/"raw"
 tests=[]; inventory=[]

 # Standard paired families
 for family,spec in PAIR_SPECS.items():
  if isinstance(spec,list):
   for a,b,gk in spec:
    t=paired_tests_for_family(raw,family,a,b,gk); tests.extend(t)
    inventory.append({"family":family,"pair":f"{a} vs {b}","tests":len(t)})
  else:
   a,b,gk=spec
   t=paired_tests_for_family(raw,family,a,b,gk); tests.extend(t)
   inventory.append({"family":family,"pair":f"{a} vs {b}","tests":len(t)})

 # S-E7 overhead contrasts
 oc=overhead_contrasts(raw); tests.extend(oc)
 inventory.append({"family":"S-E7-isolated-overhead","pair":"mode contrasts","tests":len(oc)})

 # Holm correction across all tests
 if tests:
  adjusted=holm([x["p_raw"] for x in tests])
  for row,padj in zip(tests,adjusted): row["p_holm_strengthening_family"]=padj

 out=root/"derived"/"strengthening_paired_statistics.csv"; out.parent.mkdir(parents=True,exist_ok=True)
 fields=list(tests[0].keys()) if tests else ["family","group","metric","method_a","method_b","n","p_raw","p_holm_strengthening_family"]
 with out.open("w",newline="",encoding="utf-8") as f:
  w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(tests)

 # S-E8 safety summary
 safety=safety_summary(raw)
 if safety["available"]:
  atomic_json(root/"derived"/"S-E8-safety-summary.json",safety)

 summary={"completed_utc":utc_now(),"inventory":inventory,"paired_tests":len(tests),"holm_family":"strengthening experiments only; not merged with frozen v0.3 primary family","statistics_csv":str(out.relative_to(root)),"safety_analysis":safety}
 atomic_json(root/"derived"/"strengthening-postprocess-summary.json",summary); write_manifest(root); print(json.dumps(summary,indent=2)); return 0
if __name__=="__main__": raise SystemExit(main())
