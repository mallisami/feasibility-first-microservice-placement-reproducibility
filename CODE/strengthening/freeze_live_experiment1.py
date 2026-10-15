"""Freeze a B+ regime using one accepted live telemetry capture."""
import json,sys
from dataclasses import replace
from pathlib import Path
HERE=Path(__file__).resolve().parent; REPO=HERE.parents[1]
sys.path[:0]=[str(HERE),str(HERE.parent/'code')]
from run_se1_live_full_planner import RISK,choose_candidate
from run_v03_r1 import SERVICES,WORKERS,RACKS,initial_placement,scenario
from mape_cap_bplus.models import NodeSpec,ReplicaSpec,FlowSpec,RelocationCost,ProblemInstance

root=REPO/'RESULTS/gap-closure/live-confirmatory-20260912'
capture=json.loads((root/'experiment-1/raw/r2/replicate-02-telemetry_on_controller_off/result.json').read_text())
by={}
for x in capture['native_trace_windows']:
 k=(x['source'],x['destination']); p=by.setdefault(k,[0,0,0]);p[0]+=x['requests'];p[1]+=x['request_bytes'];p[2]+=x['response_bytes']
current=initial_placement('live-confirmatory',42)
nodes=tuple(NodeSpec(n,RACKS[n],4.,6144.) for n in WORKERS)
replicas=tuple(ReplicaSpec(s,s,.1,128.) for s in SERVICES)
reloc={s:RelocationCost(s,4062.*(4 if s=='redis-cart' else 1),4.062*(4 if s=='redis-cart' else 1),690.*(4 if s=='redis-cart' else 1),'Kind measured create-ready-remove calibration') for s in SERVICES}
rows=[]
for latency,load,horizon in [(40.,2.,300.),(55.,2.,600.),(70.,2.,600.)]:
 flows=tuple(FlowSpec(f'{a}->{b}',a,b,max(.01,n/240*60*load*horizon/60),max(8.,(q+r)*8/240*60*load*horizon/60),1.,500.) for (a,b),(n,q,r) in by.items() if a in SERVICES and b in SERVICES)
 adverse=scenario(f'live-severe-{latency:g}',latency,20_000_000)
 stable=scenario('live-healthy',2.,1_000_000_000)
 p=ProblemInstance(f'live-telemetry-l{latency}',horizon,nodes,replicas,flows,(replace(adverse,weight=.7),replace(stable,weight=.3)),current,reloc,max_relocations=4,metadata={'telemetry_capture':'replicate-02','planning_horizon_seconds':horizon,'load_multiplier':load})
 cand,plan=choose_candidate(p,current,'Exact',42,30.)
 rows.append({'latency_ms':latency,'load_multiplier':load,'planning_horizon_seconds':horizon,'accepted':plan['economic_accept'],'net_benefit':plan['net_benefit'],'moved':plan['moved_replicas'],'candidate':cand,'gate':plan})
chosen=next(r for r in rows if r['accepted'])
(root/'experiment-1/frozen-regime.json').write_text(json.dumps({'telemetry_source':'raw/r2/replicate-02-telemetry_on_controller_off/result.json','application_requests':capture['application']['requests'],'candidates':rows,'frozen':chosen},indent=2)+'\n')
print(json.dumps(chosen,indent=2))
