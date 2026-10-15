from __future__ import annotations
import sys, math, itertools, json, hashlib, platform
from pathlib import Path
from dataclasses import replace
import numpy as np
import pandas as pd
from scipy.stats import binomtest, wilcoxon

ROOT=Path('/mnt/data/MAPE_CAP_BPLUS_COAUTHOR_REVISED_SUBMISSION_2026-09-15')
OUT=Path('/mnt/data/PROSPECTIVE_COMPUTATIONAL_CONFIRMATION_2026-09-15')
sys.path.insert(0,str(ROOT/'implementation'/'code'))
from mape_cap_bplus.generators import generate_problem
from mape_cap_bplus.models import RiskConfig, RelocationCost
from mape_cap_bplus.objective import evaluate_placement
import run_confirmatory_campaign as rc

RISK=RiskConfig(cvar_quantile=.8,cvar_weight=1.5,relocation_weight=1.0,slo_slack_weight=1000.0)
TARGETS=[0.50,0.90,1.00,1.10,1.25,1.50]
PRIMARY_TARGET=1.25
SEED_BLOCKS={6:range(11001,11051),7:range(22001,22051),8:range(33001,33051)}
BOOT_SEED=20260915
BOOT_N=100000

# Frozen wireless state from publication-facing external table.
trace_df=pd.read_csv(ROOT/'RESULTS'/'calibration'/'external'/'ns3_simulation_backed_traces.csv')
TRACE_DB={}
for sid,g in trace_df.groupby('scenario_id',sort=False):
    first=g.iloc[0]; links=[]; budgets={}
    for _,r in g.iterrows():
        cg=None if pd.isna(r.conflict_group) or str(r.conflict_group).strip()=='' else str(r.conflict_group)
        links.append({'source_rack':str(r.source_rack),'destination_rack':str(r.destination_rack),
                      'latency_ms':float(r.latency_ms),'goodput_bps':float(r.goodput_bps),
                      'available':bool(r.available),'path_id':str(r.path_id),'conflict_group':cg,
                      'provenance':str(r.provenance)})
        if cg and not pd.isna(r.budget_seconds): budgets[cg]=float(r.budget_seconds)
    TRACE_DB[str(sid)]={'scenario_id':str(sid),'weight':float(first.weight),'links':links,
                        'conflict_budgets_seconds':budgets,'intra_rack_latency_ms':.2,
                        'intra_rack_goodput_bps':1e11,'regime_duration_seconds':float(first.regime_duration_seconds)}

ids=['conflict-dense','partial-blockage','persistent-degradation']
raw=[TRACE_DB[i] for i in ids]
tot=sum(x['weight'] for x in raw)
SCENARIOS=tuple(rc.trace_to_scenario({**x,'weight':x['weight']/tot}) for x in raw)

def with_frozen_environment(replica_count:int, seed:int):
    p=generate_problem(replica_count=replica_count,rack_count=3,nodes_per_rack=1,scenario_count=3,seed=seed,decision_window_seconds=60.0)
    # Relabel the generator's rack-0/1/2 names to the frozen trace library's rack-a/b/c names.
    rack_map={'rack-0':'rack-a','rack-1':'rack-b','rack-2':'rack-c'}
    nodes=tuple(replace(n,rack_id=rack_map[n.rack_id]) for n in p.nodes)
    costs={r.replica_id:RelocationCost(r.replica_id,cost_units=4062.0,expected_seconds=4.062,
                                      uncertainty_units=690.0,provenance='frozen-kind-pilot-mean') for r in p.replicas}
    return replace(p,nodes=nodes,scenarios=SCENARIOS,relocation_costs=costs,
                   metadata={**p.metadata,'confirmation_environment':'frozen-simulation-backed-wireless-states'})

def scale_payload(p, factor:float):
    flows=tuple(replace(f,bits_per_window=f.bits_per_window*factor) for f in p.flows)
    return replace(p,flows=flows,metadata={**p.metadata,'payload_scale':factor})

def cluster_ok(p,pl):
    nodes=p.node_by_id; reps=p.replica_by_id
    cpu={n:0.0 for n in nodes}; mem={n:0.0 for n in nodes}; groups={n:set() for n in nodes}; mv=0
    for rid,nid in pl.items():
        if rid not in reps or nid not in nodes: return False
        r=reps[rid]
        if nid not in p.allowed_nodes_for(rid): return False
        cpu[nid]+=r.cpu_request; mem[nid]+=r.memory_request_mb
        if r.anti_affinity_group:
            if r.anti_affinity_group in groups[nid]: return False
            groups[nid].add(r.anti_affinity_group)
        mv += int(p.current_placement.get(rid)!=nid)
    if p.max_relocations is not None and mv>p.max_relocations: return False
    return all(cpu[n] <= nodes[n].cpu_capacity+1e-12 and mem[n] <= nodes[n].memory_capacity_mb+1e-12 for n in nodes)

def cross_metric(p,pl,mode):
    nodes=p.node_by_id; total=0.0
    for f in p.flows:
        if nodes[pl[f.source_replica]].rack_id != nodes[pl[f.destination_replica]].rack_id:
            total += f.bits_per_window if mode=='bytes' else f.requests_per_window
    return total

def move_count(p,pl):
    return sum(int(p.current_placement.get(r)!=n) for r,n in pl.items())

def max_util(p,ev):
    mx=0.0
    for s in p.scenarios:
        amap=ev.scenario_airtime_by_group.get(s.scenario_id,{})
        for g,b in s.conflict_budgets_seconds.items():
            if b>0: mx=max(mx,amap.get(g,0.0)/b)
    return mx

def enumerate_cluster_placements(p):
    reps=[r.replica_id for r in p.replicas]
    allowed=[p.allowed_nodes_for(r) for r in reps]
    out=[]
    for assign in itertools.product(*allowed):
        pl=dict(zip(reps,assign))
        if not cluster_ok(p,pl): continue
        # Evaluate unscaled once to screen non-airtime invalidity and store baseline mechanisms.
        ev=evaluate_placement(p,pl,RISK)
        nonair=[x for x in ev.reasons if not x.startswith('airtime budget')]
        if nonair: continue
        out.append(pl)
    return out

def select_affinity(p,placements,mode):
    return min(placements,key=lambda pl:(cross_metric(p,pl,mode),move_count(p,pl),tuple(sorted(pl.items()))))

def select_bplus(p,placements):
    cand=[]
    for pl in placements:
        ev=evaluate_placement(p,pl,RISK)
        if ev.feasible:
            cand.append((ev.total_objective,move_count(p,pl),tuple(sorted(pl.items())),pl,ev))
    if not cand: return None,None
    _,_,_,pl,ev=min(cand,key=lambda x:(x[0],x[1],x[2]))
    return pl,ev

def eval_row(p,pl):
    if pl is None:
        return {'feasible':False,'worst_conflict_util':np.nan,'headroom':np.nan,'cross_rack_bytes':np.nan,'cross_rack_requests':np.nan,'moves':np.nan,'objective':np.nan}
    ev=evaluate_placement(p,pl,RISK)
    u=max_util(p,ev)
    return {'feasible':bool(ev.feasible),'worst_conflict_util':u,'headroom':1-u,
            'cross_rack_bytes':cross_metric(p,pl,'bytes')/8.0,
            'cross_rack_requests':cross_metric(p,pl,'frequency'),
            'moves':move_count(p,pl),'objective':ev.total_objective if math.isfinite(ev.total_objective) else np.nan}

def one_sided_discordance(bplus_only, aff_only):
    n=bplus_only+aff_only
    if n==0: return 1.0
    # Under H0 discordant direction is p=.5; H1 B+ has more favorable discordance.
    return float(binomtest(bplus_only,n=n,p=.5,alternative='greater').pvalue)

def paired_boot_rd(b,a,n=BOOT_N,seed=BOOT_SEED):
    b=np.asarray(b,dtype=float); a=np.asarray(a,dtype=float); d=b-a
    rng=np.random.default_rng(seed)
    # chunked to avoid a huge index matrix
    means=[]; remaining=n
    while remaining:
        m=min(5000,remaining)
        idx=rng.integers(0,len(d),size=(m,len(d)))
        means.append(d[idx].mean(axis=1)); remaining-=m
    vals=np.concatenate(means)
    return float(d.mean()),float(np.quantile(vals,.025)),float(np.quantile(vals,.975))

def safe_wilcoxon(d,alternative='two-sided'):
    a=np.asarray(d,dtype=float); a=a[np.isfinite(a)]
    if len(a)==0 or np.allclose(a,0): return 1.0
    try:return float(wilcoxon(a,zero_method='wilcox',alternative=alternative,method='auto').pvalue)
    except Exception:return float('nan')

def main():
    rows=[]; exclusions=[]; placement_counts=[]
    total=sum(len(list(v)) for v in SEED_BLOCKS.values()); done=0
    for nrep,seeds in SEED_BLOCKS.items():
        for seed in seeds:
            base=with_frozen_environment(nrep,seed)
            current=dict(base.current_placement)
            if not cluster_ok(base,current):
                exclusions.append({'replica_count':nrep,'seed':seed,'reason':'invalid current placement'}); continue
            placements=enumerate_cluster_placements(base)
            if not placements:
                exclusions.append({'replica_count':nrep,'seed':seed,'reason':'no cluster-feasible placement'}); continue
            ev_cur=evaluate_placement(base,current,RISK)
            u0=max_util(base,ev_cur)
            if not math.isfinite(u0) or u0<=0:
                exclusions.append({'replica_count':nrep,'seed':seed,'reason':'zero/invalid current base utilization'}); continue
            placement_counts.append({'replica_count':nrep,'seed':seed,'cluster_feasible_placements':len(placements),'base_current_util':u0})
            # affinity decisions are determined from base graph; uniform bits scaling preserves their ranking.
            aff_f=select_affinity(base,placements,'frequency')
            aff_b=select_affinity(base,placements,'bytes')
            for target in TARGETS:
                factor=target/u0
                p=scale_payload(base,factor)
                bp,bpev=select_bplus(p,placements)
                for method,pl in [('Current',current),('Affinity-Frequency',aff_f),('Affinity-Bytes',aff_b),('BPlus-Exact',bp)]:
                    rr=eval_row(p,pl)
                    rows.append({'replica_count':nrep,'seed':seed,'instance_id':base.instance_id,'target_current_util':target,'payload_scale':factor,'method':method,**rr})
            done+=1
            if done%15==0: print(f'processed {done}/{total}',flush=True)
    df=pd.DataFrame(rows); ex=pd.DataFrame(exclusions); pc=pd.DataFrame(placement_counts)
    df.to_csv(OUT/'cell_results.csv',index=False)
    ex.to_csv(OUT/'exclusions.csv',index=False)
    pc.to_csv(OUT/'instance_audit.csv',index=False)

    summary=df.groupby(['target_current_util','method']).agg(n=('feasible','size'),feasible_rate=('feasible','mean'),
        mean_util=('worst_conflict_util','mean'),median_util=('worst_conflict_util','median'),mean_headroom=('headroom','mean'),
        mean_cross_rack_bytes=('cross_rack_bytes','mean'),median_cross_rack_bytes=('cross_rack_bytes','median'),mean_moves=('moves','mean')).reset_index()
    summary.to_csv(OUT/'summary.csv',index=False)
    by_size=df.groupby(['replica_count','target_current_util','method']).agg(n=('feasible','size'),feasible_rate=('feasible','mean'),mean_util=('worst_conflict_util','mean'),mean_cross_rack_bytes=('cross_rack_bytes','mean'),mean_moves=('moves','mean')).reset_index()
    by_size.to_csv(OUT/'summary_by_size.csv',index=False)

    tests=[]
    for aff in ['Affinity-Bytes','Affinity-Frequency']:
      for target in TARGETS:
        b=df[(df.method=='BPlus-Exact')&(df.target_current_util==target)].set_index(['replica_count','seed'])
        a=df[(df.method==aff)&(df.target_current_util==target)].set_index(['replica_count','seed'])
        idx=b.index.intersection(a.index)
        fb=b.loc[idx,'feasible'].astype(bool); fa=a.loc[idx,'feasible'].astype(bool)
        bo=int((fb & ~fa).sum()); ao=int((~fb & fa).sum())
        rd,lo,hi=paired_boot_rd(fb.astype(float).to_numpy(),fa.astype(float).to_numpy(),seed=BOOT_SEED+int(target*100)+(0 if aff=='Affinity-Bytes' else 1000))
        both=idx[fb & fa]
        du=(pd.to_numeric(b.loc[both,'worst_conflict_util'],errors='coerce')-pd.to_numeric(a.loc[both,'worst_conflict_util'],errors='coerce')).dropna() if len(both) else pd.Series(dtype=float)
        db=(pd.to_numeric(b.loc[both,'cross_rack_bytes'],errors='coerce')-pd.to_numeric(a.loc[both,'cross_rack_bytes'],errors='coerce')).dropna() if len(both) else pd.Series(dtype=float)
        tests.append({'affinity_baseline':aff,'target_current_util':target,'n':len(idx),
                      'bplus_feasible_rate':float(fb.mean()),'affinity_feasible_rate':float(fa.mean()),
                      'bplus_only_feasible':bo,'affinity_only_feasible':ao,'both_feasible':int((fb&fa).sum()),'neither_feasible':int((~fb&~fa).sum()),
                      'one_sided_exact_p_bplus_gt_affinity':one_sided_discordance(bo,ao),
                      'paired_feasibility_risk_difference':rd,'bootstrap95_low':lo,'bootstrap95_high':hi,
                      'both_feasible_mean_util_diff_bplus_minus_aff':float(du.mean()) if len(du) else np.nan,
                      'both_feasible_median_util_diff_bplus_minus_aff':float(du.median()) if len(du) else np.nan,
                      'both_feasible_util_wilcoxon_p':safe_wilcoxon(du),
                      'both_feasible_mean_bytes_diff_bplus_minus_aff':float(db.mean()) if len(db) else np.nan,
                      'both_feasible_median_bytes_diff_bplus_minus_aff':float(db.median()) if len(db) else np.nan,
                      'both_feasible_bytes_wilcoxon_p':safe_wilcoxon(db)})
    tests=pd.DataFrame(tests); tests.to_csv(OUT/'paired_tests.csv',index=False)

    # Size-stratified primary endpoint only.
    st=[]
    target=PRIMARY_TARGET; aff='Affinity-Bytes'
    for nrep in sorted(SEED_BLOCKS):
        b=df[(df.method=='BPlus-Exact')&(df.target_current_util==target)&(df.replica_count==nrep)].set_index('seed')
        a=df[(df.method==aff)&(df.target_current_util==target)&(df.replica_count==nrep)].set_index('seed')
        idx=b.index.intersection(a.index); fb=b.loc[idx,'feasible'].astype(bool); fa=a.loc[idx,'feasible'].astype(bool)
        bo=int((fb&~fa).sum()); ao=int((~fb&fa).sum())
        rd,lo,hi=paired_boot_rd(fb.astype(float).to_numpy(),fa.astype(float).to_numpy(),seed=BOOT_SEED+nrep)
        st.append({'replica_count':nrep,'n':len(idx),'bplus_feasible_rate':fb.mean(),'affinity_bytes_feasible_rate':fa.mean(),
                   'bplus_only':bo,'affinity_only':ao,'one_sided_exact_p':one_sided_discordance(bo,ao),'risk_difference':rd,'ci_low':lo,'ci_high':hi})
    pd.DataFrame(st).to_csv(OUT/'primary_by_size.csv',index=False)

    # Provenance, primary decision, and compact report.
    primary=tests[(tests.affinity_baseline=='Affinity-Bytes')&(np.isclose(tests.target_current_util,PRIMARY_TARGET))].iloc[0].to_dict()
    result={'primary_hypothesis_supported':bool(primary['one_sided_exact_p_bplus_gt_affinity']<0.05 and primary['paired_feasibility_risk_difference']>0),
            'primary':primary,'n_excluded':len(exclusions),'n_analyzed_instances':int(pc.shape[0])}
    (OUT/'primary_result.json').write_text(json.dumps(result,indent=2,default=str),encoding='utf-8')
    prov={'python':platform.python_version(),'numpy':np.__version__,'pandas':pd.__version__,
          'package_root':str(ROOT),'risk_config':RISK.__dict__,'targets':TARGETS,'primary_target':PRIMARY_TARGET,
          'seed_blocks':{str(k):[min(v),max(v)] for k,v in SEED_BLOCKS.items()}}
    (OUT/'provenance.json').write_text(json.dumps(prov,indent=2),encoding='utf-8')
    print('\nPRIMARY RESULT')
    print(json.dumps(result,indent=2,default=str))
    print('\nSUMMARY')
    print(summary.to_string(index=False))
    print('\nBY SIZE PRIMARY')
    print(pd.DataFrame(st).to_string(index=False))

if __name__=='__main__': main()
