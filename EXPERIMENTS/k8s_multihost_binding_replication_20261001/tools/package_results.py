#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,os,zipfile
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
RES=ROOT/'results'; OP=ROOT/'operator_logs'
if not (RES/'analysis'/'FINAL_REPORT.md').exists(): raise SystemExit('analysis FINAL_REPORT.md missing')
ts=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
run_dir=RES/f'run-{ts}'
run_dir.mkdir(parents=True,exist_ok=False)
# Copy stable output subset, excluding previous run archives.
import shutil
for src,name in [(RES/'science','science'),(RES/'pilot','pilot'),(RES/'analysis','analysis'),(OP,'operator_logs')]:
    if src.exists(): shutil.copytree(src,run_dir/name)
for src in [ROOT/'config.json', ROOT/'protocol'/'MULTIHOST_VALIDATION_PROTOCOL_FROZEN.md']:
    shutil.copy2(src,run_dir/src.name)
# provenance hashes for all files in run_dir
rows=[]
for p in sorted(x for x in run_dir.rglob('*') if x.is_file()):
    h=hashlib.sha256(p.read_bytes()).hexdigest(); rows.append((h,str(p.relative_to(run_dir))))
(run_dir/'SHA256SUMS.txt').write_text(''.join(f'{h}  {rel}\n' for h,rel in rows),encoding='utf-8')
summary={'utc':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'files_hashed':len(rows),
         'science_cells':len(list((run_dir/'science').glob('seed-*/*/attempt-*/result.json'))),
         'pilot_cells':len(list((run_dir/'pilot').glob('seed-*/*/attempt-*/result.json')))}
(run_dir/'PACKAGE_SUMMARY.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
zip_path=RES/f'run-{ts}.zip'
with zipfile.ZipFile(zip_path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    for p in sorted(x for x in run_dir.rglob('*') if x.is_file()): z.write(p,p.relative_to(run_dir.parent))
zh=hashlib.sha256(zip_path.read_bytes()).hexdigest(); (zip_path.with_suffix('.zip.sha256')).write_text(f'{zh}  {zip_path.name}\n')
print(zip_path)
print(zh)
