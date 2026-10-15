#!/usr/bin/env python3
"""N3b (POST HOC, declared after N3 outcomes were seen): outage-rotation sensitivity.

N3 showed that the whole held-out admissibility difference arises in the single withheld
outage-with-fallback state (B-C pair down). This check asks whether the advantage is a property
of the ranking rule or of which pair the library happens to fail. The outage state is relabelled
by rack permutations so that each unordered rack pair (A-B, A-C, B-C) is the failed pair, with
the wired-fallback and surviving-link values carried along by the permutation. Placements are
those selected by N2 (planning states unchanged); only held-out evaluation changes.
"""
from __future__ import annotations

import itertools
import json
from pathlib import Path

import pandas as pd

import run_n2n3 as base

HERE = Path(__file__).resolve().parent
RACKS = ["a", "b", "c"]
TARGETS = [0.50, 1.00, 1.25, 1.50]
METHODS = ["Affinity-Bytes", "Affinity-Bytes+Admission", "MAPE-CAP-WS Risk-off", "MAPE-CAP-WS"]


def relabel(trace: dict, perm: dict, tag: str) -> dict:
    links = []
    for ln in trace["links"]:
        s = ln["source_rack"].split("-")[-1]
        d = ln["destination_rack"].split("-")[-1]
        cg = ln["conflict_group"]
        if cg and cg.startswith("cg-") and len(cg) == 5:
            pair = sorted(perm[x] for x in cg[3:])
            cg = "cg-" + "".join(pair)
        links.append({**ln, "source_rack": f"rack-{perm[s]}", "destination_rack": f"rack-{perm[d]}", "conflict_group": cg})
    budgets = {}
    for g, b in trace["conflict_budgets_seconds"].items():
        if g.startswith("cg-") and len(g) == 5:
            g = "cg-" + "".join(sorted(perm[x] for x in g[3:]))
        budgets[g] = b
    return {**trace, "scenario_id": tag, "links": links, "conflict_budgets_seconds": budgets}


def scenario_set_from(traces):
    tot = sum(x["weight"] for x in traces)
    return tuple(base.rc.trace_to_scenario({**x, "weight": x["weight"] / tot}) for x in traces)


def outage_variants():
    src = base.LIB["outage-with-fallback"]
    down = {tuple(sorted((ln["source_rack"][-1], ln["destination_rack"][-1])))
            for ln in src["links"] if not ln["available"]}
    assert down == {("b", "c")}, down
    out = {}
    for p in itertools.permutations(RACKS):
        perm = dict(zip(RACKS, p))
        pair = "".join(sorted((perm["b"], perm["c"])))
        tag = f"outage-{pair}-down"
        if tag not in out:
            out[tag] = scenario_set_from([relabel(src, perm, tag)])
    return out


def main():
    base.HELDOUT = outage_variants()
    ids = sorted(base.HELDOUT)
    print("held-out outage variants:", ids)
    recs = []
    for nrep, seeds in base.SEED_BLOCKS.items():
        for seed in seeds:
            p = base.base_problem(nrep, seed)
            rows = base.characterise(p)
            cur_key = tuple(sorted(p.current_placement.items()))
            u0 = next(c for c in rows if c["key"] == cur_key)["u_plan"]
            for t in TARGETS:
                f = t / u0
                for m, c in base.select(rows, cur_key, f).items():
                    if m not in METHODS or c is None:
                        continue
                    rec = {"seed": seed, "replica_count": nrep, "target": t, "method": m}
                    for sid in ids:
                        rec[sid] = bool(c[f"ho_avail_{sid}"] and c[f"ho_u_{sid}"] * f <= 1.0 + base.EPS)
                    recs.append(rec)
    df = pd.DataFrame(recs)
    df.to_csv(HERE / "n3b_outage_rotation_cells.csv", index=False)
    summ = df.groupby(["target", "method"])[ids].sum().astype(int).reset_index()
    summ["mean_over_pairs"] = summ[ids].mean(axis=1).round(1)
    summ.to_csv(HERE / "n3b_outage_rotation_summary.csv", index=False)
    print(summ.to_string(index=False))


if __name__ == "__main__":
    main()
