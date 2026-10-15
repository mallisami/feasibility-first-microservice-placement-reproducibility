#!/usr/bin/env python3
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import wilcoxon

ROOT=Path(__file__).resolve().parents[1]
CFG=json.loads((ROOT/'config.json').read_text())
RES=ROOT/'results'/'science'
OUT=ROOT/'results'/'analysis'
OUT.mkdir(parents=True,exist_ok=True)
AFF='Affinity-Bytes'; ADM='Affinity-Bytes+Admission'; MC='MAPE-CAP-WS'
B=int(CFG['bootstrap_resamples']); SEED=int(CFG['bootstrap_seed'])


def load_cells():
    rows=[]; attempts=[]
    for cell in sorted(RES.glob('seed-*/*')):
        good=sorted(cell.glob('attempt-*/result.json'))
        bad=sorted(cell.glob('attempt-*/failure.json'))
        attempts.append({'cell':str(cell.relative_to(RES)),'accepted':len(good),'failed_attempts':len(bad)})
        if len(good)!=1: continue
        r=json.loads(good[0].read_text())
        e=r['endpoints']
        rows.append({'seed':r['seed'],'method':r['method'],'executed_state':r['executed_state'],
                     'planned_exec_util':r['planned_exec_util'],'planned_feasible':r['planned_feasible'],
                     'kubernetes_host_count':r['kubernetes_host_count'],'moves':r['moves'],
                     'cross_rack_bits':r['cross_rack_bits'],**e,
                     'rollout_s':r['relocation'].get('rollout_seconds')})
    return pd.DataFrame(rows),pd.DataFrame(attempts)


def boot_ci(vals):
    d=np.asarray(vals,float)
    rng=np.random.default_rng(SEED)
    idx=rng.integers(0,len(d),size=(B,len(d)))
    m=d[idx].mean(axis=1)
    return float(np.percentile(m,2.5)),float(np.percentile(m,97.5))


def contrast(df,metric,a,b,test=True):
    w=df.pivot(index='seed',columns='method',values=metric)
    d=(w[a]-w[b]).dropna()
    lo,hi=boot_ci(d.values)
    out={'metric':metric,'contrast':f'{a} - {b}','n':int(len(d)),
         'mean_a':float(w[a].mean()),'mean_b':float(w[b].mean()),'mean_diff':float(d.mean()),
         'median_diff':float(d.median()),'ci_lo':lo,'ci_hi':hi,
         'n_pos':int((d>0).sum()),'n_neg':int((d<0).sum()),'n_zero':int((d==0).sum())}
    if test:
        nz=d[d!=0]
        out['wilcoxon_p']=float(wilcoxon(nz).pvalue) if len(nz) else 1.0
    return out


def holm(ps):
    order=np.argsort(ps); adj=np.empty(len(ps)); running=0.0
    for k,i in enumerate(order):
        running=max(running,min(1.0,(len(ps)-k)*ps[i])); adj[i]=running
    return adj.tolist()


def main():
    df,att=load_cells()
    expected=len(CFG['science_seeds'])*len(CFG['methods'])
    if len(df)!=expected:
        raise SystemExit(f'incomplete science results: expected {expected}, found {len(df)}')
    if set(df.seed)!=set(CFG['science_seeds']): raise SystemExit('science seed set mismatch')
    if set(df.method)!=set(CFG['methods']): raise SystemExit('method set mismatch')
    df.to_csv(OUT/'multihost_cells.csv',index=False); att.to_csv(OUT/'multihost_attempts.csv',index=False)
    primary=[]
    for metric in ('sched_p95_ms','scheduled_completion'):
        fam=[contrast(df,metric,ADM,AFF),contrast(df,metric,MC,ADM)]
        for row,padj in zip(fam,holm([x['wilcoxon_p'] for x in fam])):
            row['holm_p']=padj; row['role']='primary' if metric=='sched_p95_ms' else 'co-primary'
        primary.extend(fam)
    sec=[]
    for metric in ('sched_p50_ms','sched_p99_ms','attempted_p95_ms','medium_mean_queue_wait_ms'):
        sec.extend([contrast(df,metric,ADM,AFF,False),contrast(df,metric,MC,ADM,False)])
    sec.extend([contrast(df,m,MC,AFF,False) for m in ('sched_p95_ms','scheduled_completion')])
    pd.DataFrame(primary).to_csv(OUT/'multihost_primary.csv',index=False)
    pd.DataFrame(sec).to_csv(OUT/'multihost_secondary.csv',index=False)
    summ=df.groupby('method').agg(n=('seed','size'),p95_mean=('sched_p95_ms','mean'),p95_median=('sched_p95_ms','median'),
        compl_mean=('scheduled_completion','mean'),compl_min=('scheduled_completion','min'),
        p50_mean=('sched_p50_ms','mean'),p99_mean=('sched_p99_ms','mean'),qwait_mean=('medium_mean_queue_wait_ms','mean'),
        exec_util_mean=('planned_exec_util','mean'),exec_util_max=('planned_exec_util','max'),
        hosts_used_min=('kubernetes_host_count','min'),hosts_used_max=('kubernetes_host_count','max'),
        rollout_mean_s=('rollout_s','mean')).reset_index()
    summ.to_csv(OUT/'multihost_summary.csv',index=False)
    quality={'cells_accepted':int(len(df)),'expected_cells':expected,'failed_attempts':int(att.failed_attempts.sum()),
             'all_cases_complete':bool(len(df)==expected),'all_cells_multihost':bool((df.kubernetes_host_count>=2).all()),
             'min_kubernetes_hosts_used':int(df.kubernetes_host_count.min()),'max_kubernetes_hosts_used':int(df.kubernetes_host_count.max()),
             'executed_states':df.executed_state.value_counts().to_dict()}
    (OUT/'RUN_QUALITY.json').write_text(json.dumps(quality,indent=2),encoding='utf-8')
    orig=(ROOT/'frozen/N5_source/original_n5_primary.csv').read_text(encoding='utf-8')
    lines=['# Multi-host Kubernetes validation result','',
           'This report is generated only after all 60 frozen science cells are present.','',
           '## Run quality','',f"- Accepted cells: **{quality['cells_accepted']}/{expected}**",
           f"- Failed attempts: **{quality['failed_attempts']}**",
           f"- Every cell used at least two Kubernetes/VM hosts: **{quality['all_cells_multihost']}**",
           f"- Kubernetes/VM hosts used per cell: **{quality['min_kubernetes_hosts_used']}–{quality['max_kubernetes_hosts_used']}**",'',
           '## Method summaries','',summ.to_markdown(index=False),'','## Frozen primary contrasts','',pd.DataFrame(primary).to_markdown(index=False),'',
           '## Interpretation boundary','',
           'This follow-up tests whether the original N5 S1 application-level admission/ranking behavior persists when the three logical racks are mapped to three distinct Kubernetes hosts. It is not physical 60-GHz validation and it does not re-estimate planner capacity from the smaller VMs.', '',
           '## Original N5 primary CSV retained for comparison','', '```csv',orig.strip(),'```','']
    (OUT/'FINAL_REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
    print('\n'.join(lines[:40]))

if __name__=='__main__': main()
