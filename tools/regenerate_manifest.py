#!/usr/bin/env python3
from pathlib import Path
import hashlib

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "SHA256SUMS.txt"
files = sorted(
    (p for p in ROOT.rglob("*") if p.is_file() and p != OUT),
    key=lambda p: p.relative_to(ROOT).as_posix(),
)
with OUT.open("w", encoding="utf-8", newline="\n") as out:
    for p in files:
        h = hashlib.sha256()
        with p.open("rb") as fh:
            for block in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(block)
        out.write(f"{h.hexdigest()}  {p.relative_to(ROOT).as_posix()}\n")
print(f"Wrote {OUT} with {len(files):,} entries")
