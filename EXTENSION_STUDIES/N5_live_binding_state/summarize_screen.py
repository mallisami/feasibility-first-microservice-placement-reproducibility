#!/usr/bin/env python3
"""Planning-only summary of N5 enrollment (no application data)."""
from pathlib import Path
import pandas as pd

d = pd.read_csv(Path(__file__).resolve().parent / "results" / "screening.csv")
print("screened rows:", len(d), " seeds:", d.seed.min(), "-", d.seed.max())
for s, g in d.groupby("stratum"):
    e = g[g.enrolled == True]  # noqa: E712
    print(f"\n{s}: screened {len(g)}, enrolled {len(e)} ({len(e) / len(g):.1%})")
    print("  executed states:", e.executed_state.value_counts().to_dict())
    cols = [c for c in e.columns if c.startswith("exec_util_")]
    print(e[cols].describe().loc[["mean", "min", "max"]].round(3).to_string())
    if "excluded" in g:
        print("  exclusions:", g.excluded.dropna().value_counts().to_dict())
