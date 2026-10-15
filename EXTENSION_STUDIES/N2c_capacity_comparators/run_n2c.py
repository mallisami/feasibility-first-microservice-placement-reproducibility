#!/usr/bin/env python3
"""N2c: capacity-aware affinity comparators on the AFF-C graph set (see PROTOCOL_FROZEN.md).

Reuses the frozen N2/N3 instance construction, candidate screen and load calibration
(run_n2n3.py is imported, not modified). Per candidate placement, cross-rack bits are
aggregated per directed rack pair at unit payload; the two comparators and the full
MAPE-CAP-WS admission constraint are then evaluated from those loads. A consistency check
requires the reconstructed full-model utilization to match the evaluator's for every candidate.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import platform
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "N2N3_admission_vs_ranking"))
import run_n2n3 as R  # noqa: E402

TW = 60.0
N2N3_CELLS = HERE.parent / "N2N3_admission_vs_ranking" / "cell_results.csv"


def link_tables():
    """Per planning state: directed goodput/availability, pair budget (per-pair model), group budget/membership."""
    out = {}
    for sid in R.PLAN_IDS:
        st = R.LIB[sid]
        g, avail, grp = {}, {}, {}
        for l in st["links"]:
            k = (l["source_rack"], l["destination_rack"])
            g[k], avail[k], grp[k] = l["goodput_bps"], l["available"], l["conflict_group"]
        budgets = st["conflict_budgets_seconds"]
        out[sid] = {"g": g, "avail": avail, "group": grp, "budgets": budgets}
    return out


LT = link_tables()


def pair_bits(p, pl):
    nodes = p.node_by_id
    bits = {}
    for f in p.flows:
        r, s = nodes[pl[f.source_replica]].rack_id, nodes[pl[f.destination_replica]].rack_id
        if r != s:
            bits[(r, s)] = bits.get((r, s), 0.0) + f.bits_per_window
    return bits


def utilizations(bits):
    """Unit-payload worst utilizations: (a) directed link capacity, (b) half-duplex pair budget, full model."""
    ua = ub = uf = 0.0
    for sid, t in LT.items():
        grp_air = {}
        pairs = {}
        for (r, s), b in bits.items():
            if not t["avail"].get((r, s), False) or t["g"].get((r, s), 0.0) <= 0:
                return float("inf"), float("inf"), float("inf")
            air = b / t["g"][(r, s)]
            ua = max(ua, air / TW)
            key = tuple(sorted((r, s)))
            pairs[key] = pairs.get(key, 0.0) + air
            gname = t["group"].get((r, s))
            if gname:
                grp_air[gname] = grp_air.get(gname, 0.0) + air
        for key, air in pairs.items():
            gname = t["group"].get(key) or t["group"].get((key[1], key[0]))
            budget = t["budgets"].get(gname, 0.0) if gname else 0.0
            if budget > 0:
                ub = max(ub, air / budget)
        for gname, air in grp_air.items():
            budget = t["budgets"].get(gname, 0.0)
            if budget > 0:
                uf = max(uf, air / budget)
    return ua, ub, uf


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
        if not ev.feasible:  # AFF-C screen, as in N2/N3
            continue
        ua, ub, uf = utilizations(pair_bits(p, pl))
        rows.append({"key": tuple(sorted(pl.items())), "bytes": R.cross(p, pl, "bytes") / 8.0,
                     "moves": R.moves(p, pl), "u_plan": R.unit_util(tiny, ev),
                     "u_a": ua, "u_b": ub, "u_full_recon": uf})
    return rows


def pick(rows, ok):
    c = [r for r in rows if ok(r)]
    return min(c, key=lambda r: (r["bytes"], r["moves"], r["key"])) if c else None


def main():
    cells, worst_recon = [], 0.0
    grid = sorted(set(R.TARGETS) | set(R.FINE))
    done = 0
    for nrep, seeds in R.SEED_BLOCKS.items():
        for seed in seeds:
            p = R.base_problem(nrep, seed)
            rows = candidates(p)
            for r in rows:
                if np.isfinite(r["u_plan"]):
                    worst_recon = max(worst_recon, abs(r["u_plan"] - r["u_full_recon"]) / max(r["u_plan"], 1e-12))
            cur_key = tuple(sorted(p.current_placement.items()))
            u0 = next(r for r in rows if r["key"] == cur_key)["u_plan"]
            for t in grid:
                f = t / u0
                sel = {
                    "Affinity-Bytes": pick(rows, lambda r: True),
                    "Affinity-Bytes+LinkCap": pick(rows, lambda r: r["u_a"] * f <= 1 + R.EPS),
                    "Affinity-Bytes+PairAirtime": pick(rows, lambda r: r["u_b"] * f <= 1 + R.EPS),
                    "Affinity-Bytes+Admission": pick(rows, lambda r: r["u_plan"] * f <= 1 + R.EPS),
                }
                for m, c in sel.items():
                    rec = {"replica_count": nrep, "seed": seed, "target": t, "method": m, "found": c is not None}
                    if c is not None:
                        rec.update({"full_admissible": bool(c["u_plan"] * f <= 1 + R.EPS), "u_full": c["u_plan"] * f,
                                    "u_linkcap": c["u_a"] * f, "u_pair": c["u_b"] * f,
                                    "only_multipair_violated": bool(c["u_plan"] * f > 1 + R.EPS and c["u_b"] * f <= 1 + R.EPS),
                                    "cross_rack_bytes": c["bytes"] * f, "moves": c["moves"],
                                    "placement": json.dumps(dict(c["key"]), sort_keys=True)})
                    else:
                        rec.update({"full_admissible": False})
                    cells.append(rec)
            done += 1
            if done % 15 == 0:
                print(f"processed {done}/150; worst relative utilization reconstruction error so far {worst_recon:.2e}", flush=True)

    if worst_recon > 1e-9:
        raise SystemExit(f"reconstruction check failed: {worst_recon}")
    df = pd.DataFrame(cells)
    # Reproduction gate against N2/N3 for the two reference comparators on the six primary targets.
    ref = pd.read_csv(N2N3_CELLS)
    bad = 0
    for m in ("Affinity-Bytes", "Affinity-Bytes+Admission"):
        a = df[(df.method == m) & df.target.isin(R.TARGETS)].set_index(["seed", "target"])["full_admissible"]
        b = ref[ref.method == m].set_index(["seed", "target"])["admissible"].astype(bool)
        bad += int((a.sort_index() != b.reindex(a.sort_index().index)).sum())
    print(f"reproduction gate vs N2/N3 (admissibility of reference comparators): {bad} mismatches")
    if bad:
        raise SystemExit("reproduction gate failed")

    df.to_csv(HERE / "n2c_cells.csv", index=False)
    summ = df.groupby(["target", "method"]).agg(
        found=("found", "sum"), full_admissible=("full_admissible", "sum"),
        only_multipair_violated=("only_multipair_violated", "sum"),
        mean_bytes=("cross_rack_bytes", "mean")).reset_index()
    summ.to_csv(HERE / "n2c_summary.csv", index=False)
    prov = {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__,
            "T_w": TW, "grid": grid, "reconstruction_max_rel_error": worst_recon, "reproduction_gate_mismatches": bad}
    (HERE / "provenance.json").write_text(json.dumps(prov, indent=2), encoding="utf-8")
    with open(HERE / "SHA256SUMS.txt", "w", encoding="utf-8") as fh:
        for f in sorted(HERE.glob("*")):
            if f.is_file() and f.name != "SHA256SUMS.txt":
                fh.write(f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}\n")
    pd.set_option("display.width", 200)
    print(summ[summ.target.isin(R.TARGETS)].to_string(index=False))


if __name__ == "__main__":
    main()
