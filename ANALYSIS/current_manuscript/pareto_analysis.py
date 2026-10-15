#!/usr/bin/env python3
from pathlib import Path
import subprocess, sys, tempfile, shutil, json
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
ENGINE=HERE/'recompute_derived_diagnostics.py'

with tempfile.TemporaryDirectory() as td:
    td=Path(td)
    subprocess.check_call([sys.executable, str(ENGINE), str(ROOT), str(td)])
    shutil.copy2(td/'pareto_per_discordant_graph.csv', HERE/'pareto_points.csv')
    shutil.copy2(td/'pareto_summary.csv', HERE/'pareto_summary.csv')
    s=json.loads((td/'summary.json').read_text())
    p=s['pareto']
    out={
      'analysis':'admitted-set three-objective Pareto diagnostic',
      'primary_load':1.25,
      'objectives':['cross-rack bytes','expected exposure','U_max'],
      'discordant_graphs':p['discordant_graphs'],
      'pareto_set_size':{'median':p['median_size'],'min':p['range'][0],'max':p['range'][1]},
      'nondominated_counts':{'Affinity-Bytes+Admission':p['affinity_plus_admission_nondominated'],'MAPE-CAP-WS':p['mape_cap_ws_nondominated']},
      'source':'Frozen N2/N3 AFF-C candidate enumeration; no new experiment.'
    }
    (HERE/'pareto_summary.json').write_text(json.dumps(out,indent=2)+'\n')
print('Wrote pareto_points.csv and pareto_summary.json')
