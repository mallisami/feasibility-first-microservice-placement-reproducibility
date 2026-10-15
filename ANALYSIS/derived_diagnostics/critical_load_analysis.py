#!/usr/bin/env python3
from pathlib import Path
import subprocess, sys, tempfile, shutil, json
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
ENGINE=HERE/'recompute_derived_diagnostics.py'

with tempfile.TemporaryDirectory() as td:
    td=Path(td)
    subprocess.check_call([sys.executable, str(ENGINE), str(ROOT), str(td)])
    shutil.copy2(td/'critical_load_per_graph.csv', HERE/'critical_load_results.csv')
    shutil.copy2(td/'critical_load_summary.csv', HERE/'critical_load_summary.csv')
    s=json.loads((td/'summary.json').read_text())
    out={
      'analysis':'placement-specific critical admissible load',
      'primary_load':1.25,
      'definition':'tau_c(x)=+infinity when U_max(x)=0; otherwise tau_c(x)=1/U_max(x) under uniform demand scaling. In the frozen AFF-C normalization the script computes the equivalent u0/u_plan ratio for each selected placement.',
      'median_tau_c':s['critical_load_medians'],
      'mean_delta_tau_c':{
         'admission_minus_affinity':{'estimate':s['admission_delta_mean_ci95'][0],'ci95':[s['admission_delta_mean_ci95'][1],s['admission_delta_mean_ci95'][2]]},
         'ranking_minus_admission':{'estimate':s['ranking_delta_mean_ci95'][0],'ci95':[s['ranking_delta_mean_ci95'][1],s['ranking_delta_mean_ci95'][2]]},
      },
      'source':'Frozen N2/N3 AFF-C candidate enumeration; no new experiment.'
    }
    (HERE/'critical_load_summary.json').write_text(json.dumps(out,indent=2)+'\n')
print('Wrote critical_load_results.csv and critical_load_summary.json')
