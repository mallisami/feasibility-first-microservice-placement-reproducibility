import sys, csv, time, math, json, os
PKG=sys.argv[1]           # path to dir containing mape_cap_bplus
OUT=sys.argv[2]
BUDGET=float(sys.argv[3]) if len(sys.argv)>3 else 30.0
SIZES=[int(x) for x in sys.argv[4].split(",")] if len(sys.argv)>4 else [16,20,24,32]
SEEDS=list(range(111,131))
sys.path.insert(0,PKG)
from mape_cap_bplus.exact import solve_exact
from mape_cap_bplus.lns import robust_lns
from mape_cap_bplus.generators import generate_problem
from mape_cap_bplus.models import RiskConfig
from mape_cap_bplus.objective import evaluate_placement
RISK=RiskConfig(cvar_quantile=0.9,cvar_weight=1.5,relocation_weight=1.0,slo_slack_weight=1000.0)
os.makedirs(OUT,exist_ok=True)
CSV=os.path.join(OUT,"ext_rows.csv")
FIELDS=["n","seed","arm","proven_optimal","feasible","objective","mip_gap","runtime_s","iters"]
done=set()
if os.path.exists(CSV):
    for r in csv.DictReader(open(CSV)):
        done.add((int(r["n"]),int(r["seed"]),r["arm"]))
newfile=not os.path.exists(CSV)
fh=open(CSV,"a",newline=""); w=csv.writer(fh)
if newfile: w.writerow(FIELDS)
def prob(n,seed):
    return generate_problem(replica_count=n,rack_count=3,nodes_per_rack=max(2,math.ceil(n/18)),scenario_count=3,seed=seed)
for n in SIZES:
    for seed in SEEDS:
        p=None
        for arm in ("Exact","LNS"):
            if (n,seed,arm) in done: continue
            if p is None: p=prob(n,seed)
            t=time.perf_counter()
            try:
                if arm=="Exact":
                    pl,meta=solve_exact(p,RISK,BUDGET,require_optimal=False); ev=evaluate_placement(p,pl,RISK)
                    w.writerow([n,seed,arm,bool(meta.get("proven_optimal")),ev.feasible,f"{ev.total_objective:.6f}",meta.get("mip_gap"),f"{time.perf_counter()-t:.2f}",""])
                else:
                    pl,meta=robust_lns(p,RISK,seed=seed,destroy_size=min(4,n),time_limit_seconds=BUDGET,iterations=80,local_iterations=10); ev=evaluate_placement(p,pl,RISK)
                    w.writerow([n,seed,arm,"",ev.feasible,f"{ev.total_objective:.6f}","",f"{time.perf_counter()-t:.2f}",meta.get("iterations_completed")])
            except Exception as e:
                w.writerow([n,seed,arm,"ERR","ERR",repr(e)[:60],"","",""])
            fh.flush()
            print(f"n={n} seed={seed} {arm} done",flush=True)
fh.close()
print("ALL DONE")
