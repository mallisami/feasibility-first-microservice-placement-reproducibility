#!/usr/bin/env python3
"""S-E3: generate genuinely new ns-3/WiGig trace identities with new parameters/seeds."""
from __future__ import annotations
import argparse, csv, json, sys
from pathlib import Path

HERE=Path(__file__).resolve().parent; IMPL=HERE.parent
sys.path.insert(0,str(HERE)); sys.path.insert(0,str(IMPL/"code"))
from common import atomic_json, docker_available, image_present, run, utc_now, write_manifest
from run_v03_r5_ns3 import run_cell

IMAGE="ns3-wigig:v0.3-full"
NEW_CELLS=[
 {"id":"independent-los-3m","coverage":"distance,los,new-identity","program":"test_beamformedlink_maintenance","args":"--simulationTime=1.2 --distance=3 --enableBlockage=false"},
 {"id":"independent-los-6m","coverage":"distance,los,new-identity","program":"test_beamformedlink_maintenance","args":"--simulationTime=1.2 --distance=6 --enableBlockage=false"},
 {"id":"independent-partial-blockage-10db","coverage":"partial-blockage,recovery,new-identity","program":"test_beamformedlink_maintenance","args":"--simulationTime=1.2 --distance=2 --blockageDb=-10 --blockageTime=0.35 --enableBlockage=true"},
 {"id":"independent-partial-blockage-30db","coverage":"partial-blockage,recovery,new-identity","program":"test_beamformedlink_maintenance","args":"--simulationTime=1.2 --distance=2 --blockageDb=-30 --blockageTime=0.70 --enableBlockage=true"},
 {"id":"independent-full-blockage-late","coverage":"full-blockage,recovery,new-identity","program":"test_beamformedlink_maintenance","args":"--simulationTime=1.5 --distance=2 --blockageDb=-100 --blockageTime=0.85 --enableBlockage=true"},
 {"id":"independent-dense-interference-6","coverage":"interference,conflict-groups,new-identity","program":"evaluate_qd_dense_scenario_single_ap","args":"--simulationTime=1.5 --numSTAs=6 --csv=false --directory=/evidence/ --qdChannelFolder=DenseScenario"},
 {"id":"independent-dense-interference-8","coverage":"interference,conflict-groups,new-identity","program":"evaluate_qd_dense_scenario_single_ap","args":"--simulationTime=1.5 --numSTAs=8 --csv=false --directory=/evidence/ --qdChannelFolder=DenseScenario"},
 {"id":"independent-spatial-sharing-mobile-3","coverage":"spatial-reuse,mobility,interference,new-identity","program":"evaluate_qd_channel_spatial_sharing","args":"--simulationTime=1.5 --parallelLinks=2 --csv=false --enableMobility=true --directory=/evidence/ --qdChannelFolder=SpatialSharingMobility2"}
]


def main()->int:
 p=argparse.ArgumentParser(description=__doc__); p.add_argument("run_root",type=Path); p.add_argument("--seeds",default="101,102,103"); p.add_argument("--image",default=IMAGE); args=p.parse_args()
 seeds=[int(x) for x in args.seeds.split(",") if x.strip()]
 if set(seeds)&{1,2,3}: p.error("S-E3 seeds must not reuse frozen R5 seeds 1-3")
 if not docker_available(): raise SystemExit("Docker is required for S-E3")
 if not image_present(args.image): raise SystemExit(f"missing image {args.image}; build it from implementation/kubernetes/simulator/Dockerfile.ns3-wigig-v03")
 root=args.run_root.resolve(); raw=root/"raw"/"S-E3-independent-wireless-traces"; raw.mkdir(parents=True,exist_ok=True)
 inspect=json.loads(run(["docker","image","inspect",args.image,"--format","{{json .}}"],timeout=60).stdout); atomic_json(raw/"image-inspect.json",inspect)
 rows=[]
 for cell in NEW_CELLS:
  for seed in seeds:
   run_id=f"{cell['id']}:seed{seed}"; d=raw/f"{cell['id']}-seed{seed}"
   print(f"S-E3 {run_id}",flush=True); result=run_cell(cell,seed,d,args.image)
   row={"run_id":run_id,"scenario":cell["id"],"seed":seed,"program":cell["program"],"coverage":cell["coverage"],"args":cell["args"],**result}; rows.append(row)
   atomic_json(d/"result.json",row)
   atomic_json(raw/"progress.json",{"updated_utc":utc_now(),"completed":len(rows),"target":len(NEW_CELLS)*len(seeds)})
 out=root/"derived"/"S-E3-independent-wireless-traces.csv"; out.parent.mkdir(parents=True,exist_ok=True)
 fields=["run_id","scenario","seed","program","coverage","args","status","returncode","runtime_seconds","timeseries_samples","error"]
 with out.open("w",newline="",encoding="utf-8") as f:
  w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows([{k:r.get(k) for k in fields} for r in rows])
 failures=[r for r in rows if r["status"]!="complete"]
 summary={"experiment":"S-E3","completed_utc":utc_now(),"new_trace_identities":len(NEW_CELLS),"seeds":seeds,"runs":len(rows),"failures":len(failures),"image":args.image,"output_csv":str(out.relative_to(root))}
 atomic_json(root/"derived"/"S-E3-summary.json",summary); write_manifest(root); print(json.dumps(summary,indent=2)); return 0 if not failures else 2

if __name__=="__main__": raise SystemExit(main())
