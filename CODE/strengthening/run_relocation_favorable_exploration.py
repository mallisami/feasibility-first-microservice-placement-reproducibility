"""Exploratory B+ regime sweep.  No gate or risk constant is changed."""
from __future__ import annotations
import csv, json, sys
from dataclasses import replace
from pathlib import Path

HERE=Path(__file__).resolve().parent; REPO=HERE.parents[1]
sys.path[:0]=[str(HERE.parent/'code'),str(HERE)]
from run_se1_live_full_planner import RISK, choose_candidate
from run_v03_r1 import build_problem, initial_placement, scenario
from mape_cap_bplus.models import FlowSpec
from mape_cap_bplus.objective import evaluate_placement

EVIDENCE=REPO/'RESULTS/primary/v03-20260811T151500Z'
OUT=REPO/'RESULTS/gap-closure/relocation-favorable-exploration-20260912'

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    rows=[]
    # Horizon scales the same measured per-minute exposure into cumulative
    # exposure; all relocation calibration and gate constants remain untouched.
    for latency in (40.,70.,100.):
      for load in (2.,4.,6.):
       for horizon in (300.,600.,900.):
        current=initial_placement('relocation-favorable',17)
        base=build_problem(EVIDENCE,'persistent-degradation',17,current)
        adverse=scenario(f'explore-{latency:g}ms',latency,20_000_000)
        stable=scenario('stable',2.,1_000_000_000)
        multiplier=load*horizon/60.
        flows=tuple(replace(f,requests_per_window=f.requests_per_window*multiplier,bits_per_window=f.bits_per_window*multiplier) for f in base.flows)
        problem=replace(base,instance_id=f'explore-l{latency}-q{load}-h{horizon}',decision_window_seconds=horizon,
                        flows=flows,scenarios=(replace(adverse,weight=.7),replace(stable,weight=.3)),
                        metadata={**base.metadata,'exploratory':True,'latency_ms':latency,'load_multiplier':load,'planning_horizon_seconds':horizon})
        candidate,plan=choose_candidate(problem,current,'Exact',17,20.)
        cur=evaluate_placement(problem,current,replace(RISK,relocation_weight=0.0))
        cand=evaluate_placement(problem,candidate,replace(RISK,relocation_weight=0.0))
        row={'latency_ms':latency,'request_load_multiplier':load,'planning_horizon_seconds':horizon,
             'current_objective':cur.total_objective,'candidate_objective':cand.total_objective,
             'communication_benefit':cur.expected_delay_cost-cand.expected_delay_cost,
             'weighted_cvar_benefit':RISK.cvar_weight*(cur.cvar_delay_cost-cand.cvar_delay_cost),
             'relocation_cost':plan['relocation_cost_units'],'uncertainty':plan['relocation_uncertainty_units'],
             'net_benefit':plan['net_benefit'],'accepted':plan['economic_accept'],'moved':';'.join(plan['moved_replicas'])}
        rows.append(row)
    with (OUT/'sweep.csv').open('w',newline='',encoding='utf-8') as f:
      w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    accepted=[r for r in rows if r['accepted']]
    selected=min(accepted,key=lambda r:(r['latency_ms'],r['request_load_multiplier'],r['planning_horizon_seconds'])) if accepted else None
    (OUT/'summary.json').write_text(json.dumps({'evidence_type':'exploratory-model-based-regime-sweep','gate':'unchanged B+ conservative gate','cells':len(rows),'accepted_cells':len(accepted),'selected_smallest_accepted':selected},indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'cells':len(rows),'accepted_cells':len(accepted),'selected':selected},indent=2))
if __name__=='__main__':main()
