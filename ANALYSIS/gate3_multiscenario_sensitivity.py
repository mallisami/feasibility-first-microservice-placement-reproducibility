#!/usr/bin/env python3
"""Read-only Gate-3 sensitivity analysis for AFF-K8S-MULTI.

Does not alter historical protocol/data. Recomputes:
- 24-graph post-pilot sensitivity (seeds 44007--44030)
- per-scenario paired mean differences
- deterministic scenario-weight sensitivity on the same 30 graphs
"""
from pathlib import Path
import json, csv
import numpy as np
from scipy.stats import wilcoxon

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'EXPERIMENTS/k8s_affinity_wireless_confirmatory/results/full-multiscenario-20260920.jsonl'
OUT = ROOT / 'ANALYSIS/derived/gate3_multiscenario'
OUT.mkdir(parents=True, exist_ok=True)
rows=[json.loads(x) for x in SRC.read_text(encoding='utf-8').splitlines() if x.strip()]
by={}
for r in rows:
    by.setdefault(int(r['seed']),{})[r['method']]=r
seeds=sorted(by)
def compdiff(seed):
    return by[seed]['BPlus-Exact']['composite_scheduled_completion_fraction']-by[seed]['Affinity-Bytes']['composite_scheduled_completion_fraction']
post=np.array([compdiff(s) for s in seeds if s>=44007],dtype=float)
rng=np.random.default_rng(20260920)
boot=np.array([rng.choice(post,size=len(post),replace=True).mean() for _ in range(100000)])
ci=np.quantile(boot,[.025,.975])
w=wilcoxon(post,alternative='greater',zero_method='wilcox')
scens=['conflict-dense','partial-blockage','persistent-degradation']
scenario_means={}
for sc in scens:
    d=[]
    for seed in seeds:
        d.append(by[seed]['BPlus-Exact']['per_scenario'][sc]-by[seed]['Affinity-Bytes']['per_scenario'][sc])
    scenario_means[sc]=float(np.mean(d))
weights={
 'frozen_normalized':(2/7,3/7,2/7),
 'equal':(1/3,1/3,1/3),
 'conflict_heavy':(.50,.25,.25),
 'partial_heavy':(.25,.50,.25),
 'persistent_heavy':(.25,.25,.50),
 'persistent_light':(.40,.40,.20),
}
weight_rows=[]
for name,ww in weights.items():
    vals=[]
    for seed in seeds:
        ds=[by[seed]['BPlus-Exact']['per_scenario'][sc]-by[seed]['Affinity-Bytes']['per_scenario'][sc] for sc in scens]
        vals.append(sum(a*b for a,b in zip(ww,ds)))
    weight_rows.append((name,*ww,float(np.mean(vals))))
summary={
 'post_pilot_n':len(post),'post_pilot_mean':float(post.mean()),
 'post_pilot_wins':int((post>0).sum()),'post_pilot_ties':int((post==0).sum()),'post_pilot_losses':int((post<0).sum()),
 'post_pilot_bootstrap_ci_95':[float(ci[0]),float(ci[1])], 'post_pilot_wilcoxon_one_sided_p':float(w.pvalue),
 'scenario_mean_differences':scenario_means,
 'note':'Read-only reanalysis of existing full campaign; not a new independent experiment.'
}
(OUT/'summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
with (OUT/'weight_sensitivity.csv').open('w',newline='',encoding='utf-8') as f:
    cw=csv.writer(f); cw.writerow(['weighting','conflict','partial','persistent','mean_difference']); cw.writerows(weight_rows)
with (OUT/'post_pilot_differences.csv').open('w',newline='',encoding='utf-8') as f:
    cw=csv.writer(f); cw.writerow(['seed','BPlus_minus_Affinity_composite']);
    for seed in seeds:
        if seed>=44007: cw.writerow([seed, f'{compdiff(seed):.12f}'])
print(json.dumps(summary,indent=2))
