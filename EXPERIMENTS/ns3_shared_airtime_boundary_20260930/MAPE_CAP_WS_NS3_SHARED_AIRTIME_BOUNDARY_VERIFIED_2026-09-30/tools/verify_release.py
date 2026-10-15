from pathlib import Path
import hashlib, sys
ROOT=Path(__file__).resolve().parents[1]
manifest=ROOT/'PACKAGE_SHA256SUMS.txt'
if not manifest.exists(): raise SystemExit('PACKAGE_SHA256SUMS.txt missing')
def sha(p):
 h=hashlib.sha256();
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''): h.update(b)
 return h.hexdigest()
for line in manifest.read_text().splitlines():
 if not line.strip(): continue
 expected,rel=line.split('  ',1); p=ROOT/rel
 if not p.exists() or sha(p)!=expected: raise SystemExit(f'FAIL {rel}')
print('PASS: package hashes verified')
