#!/usr/bin/env python3
from __future__ import annotations
import argparse, csv, hashlib, json, math, os, platform, random, shutil, statistics, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CFG=json.loads((ROOT/'config/experiment.json').read_text())
SHAPES=json.loads((ROOT/'config/case_shapes.json').read_text())['cases']
RESULTS=ROOT/'results'; CURRENT=RESULTS/'CURRENT_RUN.txt'

def now(): return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(1<<20),b''):h.update(b)
    return h.hexdigest()
def dump(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp'); tmp.write_text(json.dumps(obj,indent=2,sort_keys=True),encoding='utf-8'); os.replace(tmp,path)
def run(args,timeout=300,check=True):
    p=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
    if check and p.returncode:
        raise RuntimeError(f"command failed ({p.returncode}): {' '.join(map(str,args))}\nstdout:\n{p.stdout[-4000:]}\nstderr:\n{p.stderr[-4000:]}")
    return p
def docker_ok(): return shutil.which('docker') is not None and run(['docker','version'],timeout=60,check=False).returncode==0
def image_id(name):
    p=run(['docker','image','inspect',name,'--format','{{.Id}}'],timeout=60,check=False); return p.stdout.strip() if p.returncode==0 else ''
def image_commit(name):
    p=run(['docker','run','--rm',name,'git','rev-parse','HEAD'],timeout=60,check=False); return p.stdout.strip() if p.returncode==0 else ''
def free_gib(path): return shutil.disk_usage(path).free/(1024**3)

def self_test():
    assert CFG['protocol_id']=='mape-cap-ws-ns3-shared-airtime-boundary-v1.1'
    assert CFG['shared_dti_fraction']==0.25
    assert CFG['utilization_ratios']==[0.8,1.0,1.2]
    assert CFG['science_rng_runs']==[401,402,403]
    assert CFG['calibration_rng_runs']==[301,302,303]
    assert CFG['duty_gate_rng_run']==991102
    assert CFG['duty_gate_sta_index']==0
    assert CFG['duty_gate_offer_mbps']==6000.0
    assert 0.0 < CFG['duty_gate_min_throughput_ratio'] < CFG['duty_gate_max_throughput_ratio'] < 1.0
    assert len(SHAPES)==12 and CFG['planned_science_cells']==108
    seeds=[c['seed'] for c in SHAPES]
    assert seeds==[44002,44029,44007,44027,44023,44003,44014,44028,44012,44020,44021,44019]
    for c in SHAPES:
        r=c['raw_pair_rates_mbps']; w=c['normalized_pair_weights']
        assert len(r)==len(w)==6 and sum(r)>0 and all(x>=0 for x in r)
        assert abs(sum(w)-1)<1e-10
        src=ROOT/c['source_plan_file']; assert src.exists() and sha(src)==c['source_plan_sha256']
    align=json.loads((ROOT/'canonical_inputs/model/MODEL_ALIGNMENT.json').read_text())
    trace=ROOT/align['source_trace_file']; assert trace.exists() and sha(trace)==align['source_trace_sha256']
    assert align['scenario_id']=='conflict-dense' and align['conflict_group']=='cg-shared'
    assert len(align['member_directed_pairs'])==6 and float(align['budget_seconds'])==15.0
    assert float(align['planner_decision_window_seconds'])==60.0
    assert math.isclose(float(align['normalized_budget_fraction']),CFG['shared_dti_fraction'],rel_tol=0,abs_tol=1e-12)
    planner_src=ROOT/align['planner_source_snapshot']; assert planner_src.exists() and sha(planner_src)==align['planner_source_snapshot_sha256']
    planner_cfg=ROOT/align['planner_experiment_config_snapshot']; assert planner_cfg.exists() and sha(planner_cfg)==align['planner_experiment_config_snapshot_sha256']
    planner_text=planner_src.read_text(); assert 'decision_window_seconds=60.0' in planner_text
    cpp=(ROOT/'simulator/evaluate_shared_airtime_boundary.cc').read_text()
    for forbidden in ['planned_feasible','worst_conflict_utilization']:
        assert forbidden not in cpp, f'simulator contains forbidden planner outcome term: {forbidden}'
    assert 'AllocateCbapPeriod' in cpp and 'dutyFraction' in cpp
    assert 'StartApplication ();' not in cpp and 'StopApplication ();' not in cpp
    assert 'TrafficStartGuard' in cpp
    if free_gib(RESULTS)<float(CFG['min_results_free_gib']):
        raise RuntimeError('insufficient free disk space for frozen minimum')
    return {'passed':True,'selected_seeds':seeds,'science_cells':108,'calibration_cells':18,'free_gib':free_gib(RESULTS)}

def container_spec(evidence,rates,rng,duty,name):
    rates_csv=','.join(f'{x:.6f}' for x in rates)
    spec=(f"evaluate_shared_airtime_boundary --simulationTime={CFG['simulation_seconds']} "
          f"--packetSize={CFG['packet_size_bytes']} --socketType={CFG['socket_type']} "
          f"--numSTAs={CFG['num_streams']} --ratesMbpsCsv={rates_csv} --csv=true "
          f"--reportDataSnr=true --directory=/evidence/ --qdChannelFolder={CFG['qd_channel_folder']} "
          f"--phyMode={CFG['phy_mode']} --dutyFraction={duty:.12g} --trafficStartSeconds={CFG['traffic_start_seconds']} --minimumAssociationLeadMs={CFG['minimum_association_lead_ms']} --RngRun={rng}")
    cmd=['docker','run','--rm','--name',name,'-v',f'{evidence.resolve()}:/evidence',CFG['experiment_image'],
         '/bin/bash','-lc',f"set -o pipefail; mkdir -p Traces; ./waf --run-no-build {json.dumps(spec)}"]
    return cmd,spec

def parse_packet(path,expected_rates,require_positive=True):
    if not path.exists(): raise RuntimeError('packet_summary.csv missing')
    rows=list(csv.DictReader(path.open(newline='',encoding='utf-8')))
    active={i:r for i,r in enumerate(expected_rates) if r>0}
    got={int(r['sta_index']):r for r in rows}
    if set(got)!=set(active): raise RuntimeError(f'active STA mismatch: expected {sorted(active)}, got {sorted(got)}')
    out=[]
    for i,offered in active.items():
        row=got[i]; configured=float(row['configured_mbps']); achieved=float(row['achieved_mbps']); delivered=float(row['delivered_fraction']); active_s=float(row['active_seconds'])
        if not math.isclose(configured,offered,rel_tol=1e-6,abs_tol=1e-3): raise RuntimeError('configured rate mismatch')
        if active_s<=0: raise RuntimeError('non-positive active interval')
        if require_positive and achieved<=0: raise RuntimeError('non-positive achieved throughput')
        out.append({'sta_index':i,'offered_mbps':offered,'achieved_mbps':achieved,'delivered_fraction':delivered,'active_seconds':active_s,'rx_bytes':int(row['rx_bytes'])})
    return out

def parse_resource(path,duty):
    rows=list(csv.DictReader(path.open(newline='',encoding='utf-8')))
    if len(rows)!=1: raise RuntimeError('resource_summary.csv must contain one row')
    r=rows[0]
    if not math.isclose(float(r['duty_fraction']),duty,rel_tol=0,abs_tol=1e-9): raise RuntimeError('duty fraction mismatch')
    if int(r['traffic_started'])!=1: raise RuntimeError('pre-traffic association/resource gate failed')
    if duty<0.999999 and int(r['scheduled_cbap_duration_us'])<=0: raise RuntimeError('shared CBAP was not scheduled')
    if not math.isclose(float(r['traffic_start_seconds']),float(CFG['traffic_start_seconds']),rel_tol=0,abs_tol=1e-9): raise RuntimeError('traffic start mismatch')
    if float(r['association_lead_seconds']) + 1e-9 < float(CFG['minimum_association_lead_ms'])/1000.0: raise RuntimeError('association lead guard not met')
    return r

def prepare():
    st=self_test()
    if not docker_ok(): raise RuntimeError('Docker is required. On Windows start Docker Desktop and enable WSL integration.')
    base=CFG['base_image']; exp=CFG['experiment_image']
    if not image_id(base):
        run(['docker','build','--pull=false','-f',str(ROOT/'simulator/Dockerfile.ns3-wigig'),'-t',base,str(ROOT/'simulator')],timeout=7200)
    if image_commit(base)!=CFG['wigig_commit']: raise RuntimeError('base WiGig commit mismatch')
    run(['docker','build','--pull=false','-t',exp,str(ROOT/'simulator')],timeout=3600)
    if image_commit(exp)!=CFG['wigig_commit']: raise RuntimeError('experiment WiGig commit mismatch')
    h=run(['docker','run','--rm',exp,'./waf','--run-no-build','evaluate_shared_airtime_boundary --PrintHelp'],timeout=120)
    help_text=h.stdout+h.stderr
    for flag in ['dutyFraction','trafficStartSeconds','minimumAssociationLeadMs']:
        if flag not in help_text: raise RuntimeError(f'custom simulator does not expose {flag}')
    smoke=ROOT/'operator_logs'/f"smoke-{now()}"; smoke.mkdir(parents=True,exist_ok=True)
    rates=[float(CFG['smoke_rate_mbps_per_stream'])]*6
    cmd,spec=container_spec(smoke,rates,int(CFG['smoke_rng_run']),float(CFG['shared_dti_fraction']),'mape-airtime-smoke')
    p=run(cmd,timeout=CFG['cell_timeout_seconds'],check=False); (smoke/'stdout.log').write_text(p.stdout+p.stderr,encoding='utf-8')
    if p.returncode: raise RuntimeError('packet smoke failed')
    parse_packet(smoke/'packet_summary.csv',rates,True); parse_resource(smoke/'resource_summary.csv',float(CFG['shared_dti_fraction']))

    # Engineering-only duty-effect gate. A saturated single stream is run once
    # with the original full DTI and once with the frozen 25% shared CBAP. The
    # science campaign cannot start if the limited allocation is not materially
    # constraining packet service. This gate uses no selected science shape.
    gate=ROOT/'operator_logs'/f"duty-gate-{now()}"; gate.mkdir(parents=True,exist_ok=True)
    gate_rates=[0.0]*int(CFG['num_streams']); gate_rates[int(CFG['duty_gate_sta_index'])]=float(CFG['duty_gate_offer_mbps'])
    gate_results={}
    for label,duty in [('full',1.0),('limited',float(CFG['shared_dti_fraction']))]:
        edir=gate/label; edir.mkdir(parents=True,exist_ok=True)
        cmd,spec=container_spec(edir,gate_rates,int(CFG['duty_gate_rng_run']),duty,f'mape-airtime-duty-gate-{label}')
        (edir/'command.txt').write_text(spec+'\n',encoding='utf-8')
        p=run(cmd,timeout=CFG['cell_timeout_seconds'],check=False); (edir/'stdout.log').write_text(p.stdout+p.stderr,encoding='utf-8')
        if p.returncode: raise RuntimeError(f'duty-effect gate {label} run failed')
        packets=parse_packet(edir/'packet_summary.csv',gate_rates,True); resource=parse_resource(edir/'resource_summary.csv',duty)
        gate_results[label]={'aggregate_achieved_mbps':sum(x['achieved_mbps'] for x in packets),'resource':resource}
    full=gate_results['full']['aggregate_achieved_mbps']; limited=gate_results['limited']['aggregate_achieved_mbps']
    if full<=0: raise RuntimeError('duty-effect gate produced non-positive full-DTI throughput')
    ratio=limited/full
    lo=float(CFG['duty_gate_min_throughput_ratio']); hi=float(CFG['duty_gate_max_throughput_ratio'])
    if not (lo <= ratio <= hi):
        raise RuntimeError(f'duty-effect gate failed: limited/full throughput ratio={ratio:.6f}, expected in [{lo},{hi}]')
    gate_results['limited_to_full_ratio']=ratio
    dump(gate/'DUTY_GATE.json',gate_results)

    rec={'prepared':True,'base_image_id':image_id(base),'experiment_image_id':image_id(exp),'wigig_commit':CFG['wigig_commit'],'self_test':st,'smoke_dir':str(smoke.relative_to(ROOT)),'duty_gate_dir':str(gate.relative_to(ROOT)),'duty_gate_ratio':ratio}
    dump(ROOT/'operator_logs/LAST_PREPARE.json',rec); return rec

def run_cell(root,phase,cid,rates,rng,duty,extra):
    croot=root/'cells'/phase/cid; accepted=croot/'accepted.json'
    if accepted.exists(): return json.loads(accepted.read_text())
    for attempt in range(1,int(CFG['max_cell_attempts'])+1):
        adir=croot/f'attempt-{attempt}'; adir.mkdir(parents=True,exist_ok=True)
        name=('mape-airtime-'+cid+'-a'+str(attempt)).lower().replace('.','p').replace('_','-')[:120]
        cmd,spec=container_spec(adir,rates,rng,duty,name)
        (adir/'command.txt').write_text(spec+'\n',encoding='utf-8')
        t0=time.time()
        try:
            p=run(cmd,timeout=int(CFG['cell_timeout_seconds']),check=False)
        except subprocess.TimeoutExpired:
            subprocess.run(['docker','rm','-f',name],capture_output=True,text=True); p=None
        elapsed=time.time()-t0
        if p is not None:
            (adir/'stdout_stderr.log').write_text(p.stdout+p.stderr,encoding='utf-8')
        if p is None or p.returncode!=0:
            dump(adir/'failure.json',{'timeout':p is None,'returncode':None if p is None else p.returncode,'elapsed_seconds':elapsed}); continue
        try:
            packets=parse_packet(adir/'packet_summary.csv',rates,True); resource=parse_resource(adir/'resource_summary.csv',duty)
            total_off=sum(x['offered_mbps'] for x in packets); total_ach=sum(x['achieved_mbps'] for x in packets)
            rec={'phase':phase,'cell_id':cid,'rng_run':rng,'duty_fraction':duty,'rates_mbps':rates,'aggregate_offered_mbps':total_off,'aggregate_achieved_mbps':total_ach,'aggregate_delivered_fraction':min(1.0,total_ach/total_off) if total_off>0 else 1.0,'packets':packets,'resource':resource,'attempt':attempt,'elapsed_seconds':elapsed,**extra}
            dump(accepted,rec); return rec
        except Exception as e:
            dump(adir/'failure.json',{'validation_error':str(e),'elapsed_seconds':elapsed}); continue
    raise RuntimeError(f'cell failed after frozen attempt limit: {cid}')

def median(xs): return statistics.median(xs)
def calibration(root):
    cells=[]; offered=float(CFG['calibration_offer_mbps'])
    for sta in range(6):
        for rng in CFG['calibration_rng_runs']:
            rates=[0.0]*6; rates[sta]=offered
            cid=f'sta{sta}-rng{rng}'
            cells.append(run_cell(root,'calibration',cid,rates,int(rng),1.0,{'sta_index':sta}))
    goodputs=[]; outrows=[]
    for sta in range(6):
        vals=[c['aggregate_achieved_mbps'] for c in cells if c['sta_index']==sta]
        dfs=[c['aggregate_delivered_fraction'] for c in cells if c['sta_index']==sta]
        g=median(vals); df=median(dfs)
        if g<=0: raise RuntimeError(f'zero calibration goodput for STA {sta}')
        if df>=0.98: raise RuntimeError(f'calibration offer did not demonstrably saturate STA {sta}; frozen protocol must not be silently changed')
        goodputs.append(g); outrows.append({'sta_index':sta,'median_solo_goodput_mbps':g,'median_delivered_fraction_at_6000mbps':df,'rng_values_mbps':vals})
    with (root/'calibration_summary.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=['sta_index','median_solo_goodput_mbps','median_delivered_fraction_at_6000mbps']); w.writeheader();
        for r in outrows: w.writerow({k:r[k] for k in w.fieldnames})
    dump(root/'calibration_summary.json',{'solo_goodputs_mbps':goodputs,'rows':outrows})
    return goodputs

def planned_science(goodputs):
    duty=float(CFG['shared_dti_fraction']); cells=[]
    for shape in SHAPES:
        raw=[float(x) for x in shape['raw_pair_rates_mbps']]
        denom=sum(r/g for r,g in zip(raw,goodputs) if r>0)
        if denom<=0: raise RuntimeError('invalid zero airtime shape')
        for rho in CFG['utilization_ratios']:
            scale=float(rho)*duty/denom; rates=[r*scale for r in raw]
            implied=sum(r/g for r,g in zip(rates,goodputs) if r>0)/duty
            if not math.isclose(implied,float(rho),rel_tol=1e-9,abs_tol=1e-9): raise RuntimeError('utilization construction mismatch')
            if max(rates)>float(CFG['max_science_rate_mbps_per_stream']): raise RuntimeError('science rate exceeds frozen guard')
            for rng in CFG['science_rng_runs']:
                cells.append({'shape_id':shape['shape_id'],'seed':shape['seed'],'hhi':shape['hhi'],'active_streams':shape['active_streams'],'target_utilization_ratio':float(rho),'rng_run':int(rng),'rates_mbps':rates,'implied_utilization_ratio':implied})
    rnd=random.Random(int(CFG['run_order_seed'])); rnd.shuffle(cells); return cells

def bootstrap_ci(vals,seed,n):
    rnd=random.Random(seed); means=[]; m=len(vals)
    for _ in range(n): means.append(sum(vals[rnd.randrange(m)] for __ in range(m))/m)
    means.sort(); return means[int(.025*n)],means[min(n-1,int(.975*n))]
def analyze(root):
    records=[]
    for p in sorted((root/'cells/science').glob('*/accepted.json')): records.append(json.loads(p.read_text()))
    if len(records)!=int(CFG['planned_science_cells']): raise RuntimeError(f'expected 108 accepted science cells, found {len(records)}')
    by={}
    for r in records: by.setdefault((r['shape_id'],r['target_utilization_ratio']),[]).append(r['aggregate_delivered_fraction'])
    shape_rows=[]
    for shape in SHAPES:
        sid=shape['shape_id']
        for rho in CFG['utilization_ratios']:
            vals=by[(sid,float(rho))]
            if len(vals)!=3: raise RuntimeError('missing RNG replicate')
            shape_rows.append({'shape_id':sid,'seed':shape['seed'],'hhi':shape['hhi'],'active_streams':shape['active_streams'],'target_utilization_ratio':float(rho),'mean_delivered_fraction':sum(vals)/len(vals),'min_delivered_fraction':min(vals),'max_delivered_fraction':max(vals)})
    with (root/'shape_level_results.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(shape_rows[0])); w.writeheader(); w.writerows(shape_rows)
    with (root/'science_cells.csv').open('w',newline='',encoding='utf-8') as f:
        fields=['shape_id','seed','hhi','active_streams','target_utilization_ratio','rng_run','implied_utilization_ratio','aggregate_offered_mbps','aggregate_achieved_mbps','aggregate_delivered_fraction']
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader();
        for r in sorted(records,key=lambda x:(x['shape_id'],x['target_utilization_ratio'],x['rng_run'])): w.writerow({k:r[k] for k in fields})
    levels={}
    for rho in CFG['utilization_ratios']:
        vals=[r['mean_delivered_fraction'] for r in shape_rows if r['target_utilization_ratio']==float(rho)]
        lo,hi=bootstrap_ci(vals,int(CFG['bootstrap_seed'])+int(rho*100),int(CFG['bootstrap_resamples']))
        levels[str(rho)]={'mean':sum(vals)/len(vals),'median':median(vals),'ci95':[lo,hi],'n_shapes':len(vals)}
    d08={r['shape_id']:r['mean_delivered_fraction'] for r in shape_rows if r['target_utilization_ratio']==0.8}
    d12={r['shape_id']:r['mean_delivered_fraction'] for r in shape_rows if r['target_utilization_ratio']==1.2}
    diffs=[d12[k]-d08[k] for k in sorted(d08)]
    lo,hi=bootstrap_ci(diffs,int(CFG['bootstrap_seed'])+999,int(CFG['bootstrap_resamples']))
    monotone=sum(d12[k]<d08[k] for k in d08)
    thr=float(CFG['observed_feasible_delivery_threshold']); confusion={'TP':0,'FP':0,'FN':0,'TN':0}
    for r in shape_rows:
        pred=r['target_utilization_ratio']<=1.0; obs=r['mean_delivered_fraction']>=thr
        if pred and obs: confusion['TP']+=1
        elif pred and not obs: confusion['FP']+=1
        elif not pred and obs: confusion['FN']+=1
        else: confusion['TN']+=1
    summary={'protocol_id':CFG['protocol_id'],'levels':levels,'primary_contrast_1.2_minus_0.8':{'mean_difference':sum(diffs)/len(diffs),'median_difference':median(diffs),'ci95':[lo,hi],'n_shapes':len(diffs)},'shapes_with_lower_delivery_at_1.2_than_0.8':monotone,'classification_threshold':thr,'confusion_predicted_feasible_u_le_1_vs_observed_delivery':confusion,'interpretation_rule':'Supports construct only if delivery degrades above the boundary; do not reinterpret null/opposite results as validation.'}
    dump(root/'SUMMARY.json',summary)
    report=['# Final report — ns-3 shared-airtime boundary validation','',f"Protocol: `{CFG['protocol_id']}`",'', '## Primary result',f"Mean paired delivery difference (U=1.20 minus U=0.80): **{summary['primary_contrast_1.2_minus_0.8']['mean_difference']:.6f}** (95% bootstrap CI {lo:.6f} to {hi:.6f}; n=12 traffic shapes).",'',f"Shapes with lower delivery at U=1.20 than U=0.80: **{monotone}/12**.",'','## Delivery by target utilization']
    for rho in CFG['utilization_ratios']:
        q=levels[str(rho)]; report.append(f"- U={rho:.1f}: mean D={q['mean']:.6f}, median={q['median']:.6f}, 95% bootstrap CI [{q['ci95'][0]:.6f}, {q['ci95'][1]:.6f}].")
    report += ['', '## Secondary threshold classification',f"Observed feasible is frozen descriptively as mean delivered fraction >= {thr:.2f}. Confusion counts: {confusion}.",'','## Evidence boundary','This is packet-level construct validation in a pinned IEEE 802.11ad/WiGig simulator. It is not a physical RF deployment and does not independently calibrate a real data-center 60-GHz channel.','', '## Interpretation rule','A negative primary contrast with degradation concentrated above U=1 supports the aggregate shared-airtime admission construct. A null or positive contrast does not. No post-hoc parameter tuning is permitted.','']
    (root/'FINAL_REPORT.md').write_text('\n'.join(report),encoding='utf-8')
    return summary

def manifest(root):
    lines=[]
    for p in sorted(root.rglob('*')):
        if p.is_file() and p.name!='SHA256SUMS.txt': lines.append(f"{sha(p)}  {p.relative_to(root).as_posix()}")
    (root/'SHA256SUMS.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')

def provenance():
    return {'protocol_id':CFG['protocol_id'],'platform':platform.platform(),'python':sys.version,'config_sha256':sha(ROOT/'config/experiment.json'),'shapes_sha256':sha(ROOT/'config/case_shapes.json'),'simulator_sha256':sha(ROOT/'simulator/evaluate_shared_airtime_boundary.cc'),'protocol_sha256':sha(ROOT/'protocol/SHARED_AIRTIME_BOUNDARY_PROTOCOL_FROZEN.md'),'base_image_id':image_id(CFG['base_image']) if docker_ok() else None,'experiment_image_id':image_id(CFG['experiment_image']) if docker_ok() else None,'wigig_commit':CFG['wigig_commit']}

def execute():
    prepare()
    if CURRENT.exists(): runroot=Path(CURRENT.read_text().strip())
    else:
        runroot=RESULTS/f"run-{now()}"; runroot.mkdir(parents=True); CURRENT.write_text(str(runroot.resolve())+'\n',encoding='utf-8'); dump(runroot/'provenance.json',provenance())
    goodputs=calibration(runroot); cells=planned_science(goodputs); dump(runroot/'science_plan.json',{'cells':cells,'solo_goodputs_mbps':goodputs})
    for i,c in enumerate(cells,1):
        cid=f"{c['shape_id']}-u{c['target_utilization_ratio']:.1f}-rng{c['rng_run']}"
        extra={k:c[k] for k in ['shape_id','seed','hhi','active_streams','target_utilization_ratio','implied_utilization_ratio']}
        run_cell(runroot,'science',cid,c['rates_mbps'],c['rng_run'],float(CFG['shared_dti_fraction']),extra)
        print(f"[{i}/{len(cells)}] {cid}",flush=True)
    analyze(runroot); manifest(runroot); print(f"COMPLETE: {runroot}")

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('command',choices=['self-test','prepare','run','analyze']); ap.add_argument('--run-root',type=Path); a=ap.parse_args()
    if a.command=='self-test': print(json.dumps(self_test(),indent=2))
    elif a.command=='prepare': print(json.dumps(prepare(),indent=2))
    elif a.command=='run': execute()
    elif a.command=='analyze':
        rr=a.run_root or (Path(CURRENT.read_text().strip()) if CURRENT.exists() else None)
        if rr is None: raise SystemExit('no run root available')
        print(json.dumps(analyze(rr),indent=2)); manifest(rr)
if __name__=='__main__': main()
