#!/usr/bin/env python3
from pathlib import Path
import subprocess, sys, tempfile, shutil, json
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
ENGINE=HERE/'recompute_derived_diagnostics.py'

with tempfile.TemporaryDirectory() as td:
    td=Path(td)
    subprocess.check_call([sys.executable, str(ENGINE), str(ROOT), str(td)])
    shutil.copy2(td/'penalty_threshold_per_graph.csv', HERE/'exact_penalty_results.csv')
    shutil.copy2(td/'penalty_threshold_summary.csv', HERE/'exact_penalty_summary.csv')
    s=json.loads((td/'summary.json').read_text())
    q=s['penalty_threshold']
    out={
      'analysis':'finite exact-penalty sufficient-threshold diagnostic',
      'primary_load':1.25,
      'violation_definition':'V(x)=max(0,U_max(x)-1)',
      'objective':'J(x)=the frozen full MAPE-CAP-WS objective on the finite cluster-feasible candidate set',
      'threshold':'Any M > R_J/delta is sufficient, where R_J=max J-min J and delta is the minimum positive V(x).',
      'graph_count':q['n'],
      'RJ_over_delta':{k:q[k] for k in ['median','p10','p90','min','max']},
      'scaling_caveat':'Absolute R_J/delta values depend on the fixed objective and violation scaling. The substantive result is the large instance-to-instance variation, not a physically invariant magnitude.',
      'source':'Frozen N2/N3 AFF-C candidate enumeration; no new experiment.'
    }
    (HERE/'exact_penalty_summary.json').write_text(json.dumps(out,indent=2)+'\n')
print('Wrote exact_penalty_results.csv and exact_penalty_summary.json')
