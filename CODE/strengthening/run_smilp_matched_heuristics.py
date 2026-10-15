#!/usr/bin/env python3
"""S-MILP: matched 10-s LNS vs SCIP standard heuristic-emphasis configurations.

A matched Gurobi arm was attempted first, but a Gurobi license with
unrestricted model size was not available: 54/72 cells failed with
GurobiError 10010 ("Model too large for size-limited license"). This runner
was switched to SCIP (via PySCIPOpt, which bundles its own SCIP build and
needs no separate license) as a disclosed substitution, matching the same
three heuristic-emphasis modes; the original Gurobi adapter was removed
after the SCIP substitution completed successfully (71/72 cells) — see
IMPLEMENTATION_CORRECTION_2026-09-17-SCIP-SUBSTITUTION.md and the raw
per-cell results under RESULTS/strengthening/strengthening-20260814T223539Z/
for provenance of the original Gurobi attempt.
"""
from __future__ import annotations
import argparse,csv,json,math,sys,time
from pathlib import Path
HERE=Path(__file__).resolve().parent; IMPL=HERE.parent
sys.path.insert(0,str(HERE)); sys.path.insert(0,str(IMPL/"code"))
from common import atomic_json, utc_now, write_manifest
from scip_adapter import solve_scip
from mape_cap_bplus.generators import generate_problem
from mape_cap_bplus.lns import robust_lns
from mape_cap_bplus.models import RiskConfig
from mape_cap_bplus.objective import evaluate_placement

RISK=RiskConfig(0.9,1.5,1.0,1000.0)


def main()->int:
 p=argparse.ArgumentParser(description=__doc__); p.add_argument("run_root",type=Path); p.add_argument("--sizes",default="12,16,20,24,40,50"); p.add_argument("--seeds",default="1,2,3"); p.add_argument("--time-limit",type=float,default=10.0); p.add_argument("--modes",default="default,rins,feasibility-pump"); args=p.parse_args()
 sizes=[int(x) for x in args.sizes.split(",")]; seeds=[int(x) for x in args.seeds.split(",")]; modes=[x for x in args.modes.split(",") if x]
 try: import pyscipopt  # noqa:F401
 except ImportError: raise SystemExit("S-MILP is optional and requires: pip install pyscipopt")
 root=args.run_root.resolve(); raw=root/"raw"/"S-MILP-matched-heuristics"; raw.mkdir(parents=True,exist_ok=True); rows=[]
 for size in sizes:
  for seed in seeds:
   nodes_per_rack=max(2,math.ceil(size/18)); problem=generate_problem(replica_count=size,rack_count=3,nodes_per_rack=nodes_per_rack,scenario_count=3,seed=seed)
   methods=["LNS",*modes]
   for method in methods:
    run_id=f"r{size}:seed{seed}:{method}"; print(f"S-MILP {run_id}",flush=True); started=time.perf_counter()
    try:
     if method=="LNS":
      placement,meta=robust_lns(problem,RISK,seed=seed,iterations=80,destroy_size=min(4,size),time_limit_seconds=args.time_limit,local_iterations=10); status="complete"
     else:
      placement,meta=solve_scip(problem,RISK,args.time_limit,method); status="complete"
     ev=evaluate_placement(problem,placement,RISK); row={"run_id":run_id,"replica_count":size,"seed":seed,"method":method,"status":status,"objective":ev.total_objective,"feasible":ev.feasible,"runtime_seconds":time.perf_counter()-started,"metadata":meta,"placement":placement}
    except Exception as exc:
     row={"run_id":run_id,"replica_count":size,"seed":seed,"method":method,"status":"failure","runtime_seconds":time.perf_counter()-started,"error":repr(exc)}
    rows.append(row); atomic_json(raw/"progress.json",{"updated_utc":utc_now(),"completed":len(rows),"target":len(sizes)*len(seeds)*len(methods)})
    atomic_json(raw/(run_id.replace(":","_")+".json"),row)
 out=root/"derived"/"S-MILP-matched-heuristics.csv"; out.parent.mkdir(parents=True,exist_ok=True); fields=["run_id","replica_count","seed","method","status","objective","feasible","runtime_seconds"]
 with out.open("w",newline="",encoding="utf-8") as f:
  w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows([{k:r.get(k) for k in fields} for r in rows])
 summary={"experiment":"S-MILP","completed_utc":utc_now(),"sizes":sizes,"seeds":seeds,"time_limit_seconds":args.time_limit,"methods":["LNS",*modes],"runs":len(rows),"failures":sum(r["status"]!="complete" for r in rows),"output_csv":str(out.relative_to(root))}; atomic_json(root/"derived"/"S-MILP-summary.json",summary); write_manifest(root); print(json.dumps(summary,indent=2)); return 0 if summary["failures"]==0 else 2

if __name__=="__main__": raise SystemExit(main())
