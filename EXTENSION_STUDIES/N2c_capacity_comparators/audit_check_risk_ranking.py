#!/usr/bin/env python3
"""N2c audit check (post hoc; not part of the frozen N2c protocol).

The frozen N2c comparators all rank by cross-rack bytes. A second audit asked whether its
statement "the multi-pair conflict-dense group binds only from tau = 1.35 upward" also holds for
MAPE-CAP-WS's own risk-aware ranking. This script answers three questions on the same 150 graphs,
candidate sets, planning states and load calibration (run_n2n3.py and run_n2c.py are imported
unchanged):

  B1  MAPE-CAP-WS ranking under per-pair budgets only (N2c comparator (b) without the multi-pair
      group): on how many graphs does its selection exceed the shared conflict-dense budget?
  B3  For byte-affinity ranking under (b): does a multi-pair violation occur on graphs that still
      have a fully admissible placement?
  B4  Affinity-Bytes under a per-direction budget that is NOT shared by the two directions of a
      pair: how many of the plain Affinity-Bytes violations remain?

Gates: MAPE-CAP-WS under full admission must reproduce the published N2/N3 placements, and the
byte-affinity selections must reproduce n2c_cells.csv; otherwise nothing is written.
"""
from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "N2N3_admission_vs_ranking"))
import run_n2n3 as R  # noqa: E402
import run_n2c as C  # noqa: E402

GRID = sorted(set(R.TARGETS) | set(R.FINE))
CD = "conflict-dense"


def loads(bits):
    """Unit-payload worst utilizations: per-direction unshared budget, and the conflict-dense group alone."""
    ud = ucd = 0.0
    for sid, t in C.LT.items():
        grp_air = {}
        for (r, s), b in bits.items():
            if not t["avail"].get((r, s), False) or t["g"].get((r, s), 0.0) <= 0:
                return float("inf"), float("inf")
            air = b / t["g"][(r, s)]
            gname = t["group"].get((r, s))
            budget = t["budgets"].get(gname, 0.0) if gname else 0.0
            if budget > 0:
                ud = max(ud, air / budget)
            if gname:
                grp_air[gname] = grp_air.get(gname, 0.0) + air
        if sid == CD:
            for gname, air in grp_air.items():
                if t["budgets"].get(gname, 0.0) > 0:
                    ucd = max(ucd, air / t["budgets"][gname])
    return ud, ucd


def candidates(p):
    reps = [r.replica_id for r in p.replicas]
    allowed = [p.allowed_nodes_for(r) for r in reps]
    tiny = R.scale(p, R.TINY)
    rows = []
    for assign in itertools.product(*allowed):
        pl = dict(zip(reps, assign))
        if not R.cluster_ok(p, pl):
            continue
        ev = R.evaluate_placement(tiny, pl, R.RISK)
        if not ev.feasible:  # AFF-C screen, as in N2/N3 and N2c
            continue
        bits = C.pair_bits(p, pl)
        ua, ub, uf = C.utilizations(bits)
        ud, ucd = loads(bits)
        rows.append({"key": tuple(sorted(pl.items())), "bytes": R.cross(p, pl, "bytes") / 8.0,
                     "moves": R.moves(p, pl), "obj": ev.total_objective, "u_plan": R.unit_util(tiny, ev),
                     "u_b": ub, "u_d": ud, "u_cd": ucd})
    return rows


def pick(rows, ok, rank):
    c = [r for r in rows if ok(r)]
    return min(c, key=lambda r: (r[rank], r["moves"], r["key"])) if c else None


def plc(c):
    return json.dumps(dict(c["key"]), sort_keys=True) if c is not None else None


def main():
    out = []
    for nrep, seeds in R.SEED_BLOCKS.items():
        for seed in seeds:
            p = R.base_problem(nrep, seed)
            rows = candidates(p)
            cur_key = tuple(sorted(p.current_placement.items()))
            u0 = next(r for r in rows if r["key"] == cur_key)["u_plan"]
            for t in GRID:
                f = t / u0
                full = lambda r: r["u_plan"] * f <= 1 + R.EPS  # noqa: E731
                sel = {
                    "M_full": pick(rows, full, "obj"),
                    "M_pair": pick(rows, lambda r: r["u_b"] * f <= 1 + R.EPS, "obj"),
                    "A_plain": pick(rows, lambda r: True, "bytes"),
                    "A_full": pick(rows, full, "bytes"),
                    "A_pair": pick(rows, lambda r: r["u_b"] * f <= 1 + R.EPS, "bytes"),
                    "A_dir": pick(rows, lambda r: r["u_d"] * f <= 1 + R.EPS, "bytes"),
                }
                rec = {"replica_count": nrep, "seed": seed, "target": t,
                       "any_admissible": sel["A_full"] is not None}
                for k, c in sel.items():
                    rec[f"{k}_placement"] = plc(c)
                    rec[f"{k}_u_full"] = c["u_plan"] * f if c is not None else np.nan
                    rec[f"{k}_admissible"] = bool(c is not None and full(c))
                rec["M_full_u_conflict_dense"] = sel["M_full"]["u_cd"] * f if sel["M_full"] else np.nan
                rec["A_plain_u_conflict_dense"] = sel["A_plain"]["u_cd"] * f
                rec["M_pair_u_conflict_dense"] = sel["M_pair"]["u_cd"] * f if sel["M_pair"] else np.nan
                out.append(rec)
            if seed % 10 == 0:
                print(f"done graph {nrep}-{seed}", flush=True)
    df = pd.DataFrame(out)
    df["target"] = df.target.round(2)
    norm = lambda x: x if isinstance(x, str) else None  # noqa: E731  (no placement -> None)

    # Gate 1: MAPE-CAP-WS under full admission reproduces the published N2/N3 placements (six targets).
    ref = pd.read_csv(R.HERE / "cell_results.csv")
    ref["target"] = ref.target.round(2)
    ref = ref[ref.method == "MAPE-CAP-WS"].set_index(["seed", "target"])["placement"]
    mine = df[df.target.isin([round(t, 2) for t in R.TARGETS])].set_index(["seed", "target"])["M_full_placement"]
    g1 = sum(int(norm(ref.loc[i]) != norm(mine.loc[i])) for i in mine.index)
    # Gate 2: byte-affinity selections reproduce n2c_cells.csv on the full grid.
    n2c = pd.read_csv(HERE / "n2c_cells.csv")
    n2c["target"] = n2c.target.round(2)
    g2 = n2 = 0
    for m, k in (("Affinity-Bytes", "A_plain"), ("Affinity-Bytes+Admission", "A_full"),
                 ("Affinity-Bytes+PairAirtime", "A_pair")):
        a = n2c[n2c.method == m].set_index(["seed", "target"])["placement"]
        b = df.set_index(["seed", "target"])[f"{k}_placement"]
        g2 += sum(int(norm(a.loc[i]) != norm(b.loc[i])) for i in b.index)
        n2 += len(b)
    print(f"gate 1 (MAPE-CAP-WS vs N2/N3, {len(mine)} cells): {g1} mismatches")
    print(f"gate 2 (affinity selections vs n2c_cells.csv, {n2} cells): {g2} mismatches")
    if g1 or g2:
        raise SystemExit("gate failed; nothing written")
    df.to_csv(HERE / "audit_check_cells.csv", index=False)

    lines = ["# N2c audit check: risk-aware ranking and direction sharing (post hoc)", "",
             "Script `audit_check_risk_ranking.py` (imports run_n2n3.py and run_n2c.py unchanged); cells in",
             "`audit_check_cells.csv`. Counts are graphs out of 150.",
             f"- Gate 1: MAPE-CAP-WS under full admission reproduces the published N2/N3 placements in {len(mine) - g1}/{len(mine)} cells.",
             f"- Gate 2: the byte-affinity selections reproduce n2c_cells.csv in {n2 - g2}/{n2} cells.", "",
             "Columns:",
             "- B1 = MAPE-CAP-WS ranking with per-pair budgets only (comparator (b)): selections that exceed the full model",
             "  (all in the multi-pair conflict-dense group), and how many of those graphs have an admissible placement;",
             "- CD max = largest conflict-dense (multi-pair) utilization of the full-admission MAPE-CAP-WS / Affinity-Bytes placements;",
             "- B3 = byte-affinity ranking under (b): multi-pair violators, and how many of them are on graphs with no admissible placement;",
             "- B4 = plain Affinity-Bytes violations, and how many remain under a per-direction budget not shared by the two directions",
             "  (n/f = that comparator found no placement).", "",
             "| tau | admissible exists | B1 violators (avoidable) | B1 seeds (full-model util) | CD max MAPE / Aff | B3 violators / no admissible | B4 violations / remain (n/f) |",
             "|---|---|---|---|---|---|---|"]
    cd_ok = True
    for t in GRID:
        d = df[np.isclose(df.target, t)]
        b1 = d[d.M_pair_placement.notna() & ~d.M_pair_admissible]
        cd_ok &= bool((b1.M_pair_u_conflict_dense > 1 + R.EPS).all())
        seeds = ", ".join(f"{s} ({u:.2f})" for s, u in zip(b1.seed, b1.M_pair_u_full)) if len(b1) <= 5 else "(see cells)"
        b3 = d[d.A_pair_placement.notna() & ~d.A_pair_admissible]
        b4 = d[~d.A_plain_admissible]
        left = int((b4.A_dir_placement.notna() & ~b4.A_dir_admissible).sum())
        nf = int(b4.A_dir_placement.isna().sum())
        lines.append(f"| {t:.2f} | {int(d.any_admissible.sum())} | {len(b1)} ({int(b1.any_admissible.sum())}) | {seeds} | "
                     f"{d.M_full_u_conflict_dense.max():.3f} / {d.A_plain_u_conflict_dense.max():.3f} | "
                     f"{len(b3)} / {int((~b3.any_admissible).sum())} | {len(b4)} / {left} ({nf}) |")
    lines += ["", f"Every B1 violator exceeds the conflict-dense (multi-pair) budget: {cd_ok}."]
    (HERE / "AUDIT_CHECK.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
