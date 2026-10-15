#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, py_compile, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REQUIRED = [
    'README_RUN_ON_VM.md','RUN_ALL.sh','FREEZE_PREEXECUTION.sh',
    'E1_ns3_persistent_degradation/protocol/PD_ADMISSION_PROTOCOL.md',
    'E1_ns3_persistent_degradation/config/experiment.json',
    'E1_ns3_persistent_degradation/config/placement_plan.json',
    'E1_ns3_persistent_degradation/src/run_pd_validation.py',
    'E1_ns3_persistent_degradation/tests/test_pipeline.py',
    'E2_scale_admission/PROTOCOL.md','E2_scale_admission/run_scale.py',
    'E3_published_score_replay/PROTOCOL.md','E3_published_score_replay/RULE_CHECK.md',
    'E3_published_score_replay/FULLTEXT_RULE_VERIFICATION.md',
    'E3_published_score_replay/run_score_replay.py',
    'deps/requirements-lock.txt','DEPS_SHA256SUMS.txt'
]
PY = [
    'VERIFY_PACKAGE.py','POSTRUN_INVENTORY.py',
    'E1_ns3_persistent_degradation/src/build_plan.py',
    'E1_ns3_persistent_degradation/src/run_pd_validation.py',
    'E1_ns3_persistent_degradation/tests/test_pipeline.py',
    'E2_scale_admission/run_scale.py','E3_published_score_replay/run_score_replay.py'
]
OUTPUT_DIRS = [
    'E1_ns3_persistent_degradation/results',
    'E2_scale_admission/results',
    'E3_published_score_replay/results'
]

def sha256(p: Path) -> str:
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024), b''): h.update(b)
    return h.hexdigest()

def check_dep_manifest():
    bad=[]; checked=0
    for raw in (ROOT/'DEPS_SHA256SUMS.txt').read_text(encoding='utf-8').splitlines():
        raw=raw.strip()
        if not raw or raw.startswith('#'): continue
        parts=raw.split(None,1)
        if len(parts)!=2: continue
        digest, rel=parts
        rel=rel.lstrip('*').strip()
        p=ROOT/'deps'/rel
        if not p.exists() or sha256(p)!=digest: bad.append(rel)
        checked+=1
    if bad: raise SystemExit('Dependency hash mismatch/missing: '+', '.join(bad[:20]))
    return checked

def science_files():
    found=[]
    for d in OUTPUT_DIRS:
        p=ROOT/d
        if p.exists():
            for f in p.rglob('*'):
                if f.is_file() and f.name!='.gitkeep': found.append(str(f.relative_to(ROOT)))
    return found

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--frozen', action='store_true', help='also require PREEXECUTION_SHA256SUMS.txt')
    a=ap.parse_args()
    missing=[x for x in REQUIRED if not (ROOT/x).exists()]
    if missing: raise SystemExit('Missing required files: '+', '.join(missing))
    for rel in PY: py_compile.compile(str(ROOT/rel), doraise=True)
    n=check_dep_manifest()
    sf=science_files()
    if sf: raise SystemExit('Science result files already exist; use a clean pre-run package. First files: '+', '.join(sf[:10]))
    if a.frozen and not (ROOT/'PREEXECUTION_SHA256SUMS.txt').exists():
        raise SystemExit('Frozen execution requested but PREEXECUTION_SHA256SUMS.txt is missing')
    print(f'PACKAGE PRE-RUN VERIFICATION: PASS ({len(PY)} Python entry points compile; {n} dependency hashes checked; no science results present)')
if __name__=='__main__': main()
