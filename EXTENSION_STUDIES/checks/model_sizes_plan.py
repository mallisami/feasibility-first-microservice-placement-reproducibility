import sys, collections
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "N2N3_admission_vs_ranking"))  # package layout; was an absolute path when executed
import run_n2n3 as R
from mape_cap_bplus.exact import solve_exact
rows = []
for nrep, seeds in R.SEED_BLOCKS.items():
    for seed in seeds:
        p = R.base_problem(nrep, seed)  # AFF-C instance with the three planning states
        pl, meta = solve_exact(p, R.RISK, 60.0, require_optimal=False)
        rows.append((nrep, len(p.nodes), len(p.flows), meta["variable_count"], meta["constraint_count"], meta["proven_optimal"]))
by = collections.defaultdict(list)
for r in rows: by[r[0]].append(r)
for n in sorted(by):
    rr = by[n]
    print(n, "nodes", {r[1] for r in rr}, "flows", min(r[2] for r in rr), max(r[2] for r in rr),
          "vars", min(r[3] for r in rr), max(r[3] for r in rr), "cons", min(r[4] for r in rr), max(r[4] for r in rr),
          "proven", sum(bool(r[5]) for r in rr), "/", len(rr))
print("overall vars", min(r[3] for r in rows), max(r[3] for r in rows), "cons", min(r[4] for r in rows), max(r[4] for r in rows), "proven", sum(bool(r[5]) for r in rows))
