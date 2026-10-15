import json, pathlib, subprocess, sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
p=subprocess.run([sys.executable,str(ROOT/'src/run_boundary_validation.py'),'self-test'],capture_output=True,text=True)
assert p.returncode==0,p.stderr
d=json.loads(p.stdout); assert d['passed'] and d['science_cells']==108 and d['calibration_cells']==18
assert not list(ROOT.rglob('__pycache__')), 'release contains __pycache__'
cpp=(ROOT/'simulator/evaluate_shared_airtime_boundary.cc').read_text(encoding='utf-8')
assert 'AllocateCbapPeriod' in cpp and 'dutyFraction' in cpp
assert 'planned_feasible' not in cpp and 'worst_conflict_utilization' not in cpp
cfg=json.loads((ROOT/'config/experiment.json').read_text())
assert cfg['shared_dti_fraction']==0.25 and cfg['planned_science_cells']==108
assert cfg['duty_gate_min_throughput_ratio']==0.05 and cfg['duty_gate_max_throughput_ratio']==0.60

assert 'StartApplication ();' not in cpp and 'StopApplication ();' not in cpp
assert 'TrafficStartGuard' in cpp
assert cfg['traffic_start_seconds']==2.0 and cfg['minimum_association_lead_ms']==250
align=json.loads((ROOT/'canonical_inputs/model/MODEL_ALIGNMENT.json').read_text())
assert align['scenario_id']=='conflict-dense' and align['conflict_group']=='cg-shared'
assert align['normalized_budget_fraction']==0.25 and len(align['member_directed_pairs'])==6
print('PASS')
