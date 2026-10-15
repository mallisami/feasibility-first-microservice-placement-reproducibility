#!/usr/bin/env python3
from pathlib import Path
import hashlib
ROOT=Path(__file__).resolve().parent
roots=[
 'E1_ns3_persistent_degradation/results','E1_ns3_persistent_degradation/operator_logs',
 'E2_scale_admission/results','E3_published_score_replay/results'
]
print('# POST-RUN INVENTORY')
for r in roots:
    p=ROOT/r
    fs=sorted(f for f in p.rglob('*') if f.is_file()) if p.exists() else []
    print(f'\n## {r}: {len(fs)} files')
    for f in fs:
        h=hashlib.sha256(f.read_bytes()).hexdigest()
        print(f'{h}  {f.relative_to(ROOT)}')
