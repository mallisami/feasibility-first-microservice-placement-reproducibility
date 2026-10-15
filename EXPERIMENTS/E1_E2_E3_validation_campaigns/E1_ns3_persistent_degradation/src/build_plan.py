#!/usr/bin/env python3
"""Build the placement plan for the persistent-degradation packet study (E1).

Uses the packaged planner code and the same 150 controlled graphs, state library, load
calibration, enumeration and tie-breaks as EXTENSION_STUDIES/2026-09-26/N2N3_admission_vs_ranking.
No packet outcome is involved.

    python src/build_plan.py            # writes config/placement_plan.json
    python src/build_plan.py --check    # rebuilds and compares with the existing file
"""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
# Planner code, generator and state library: the bundled copies in deps/ (byte-identical to the
# reproducibility package; hashes in DEPS_SHA256SUMS.txt), so this folder runs on its own.
PKG = HERE.parent / "deps"
sys.path.insert(0, str(PKG / "EXTENSION_STUDIES" / "2026-09-26" / "N2N3_admission_vs_ranking"))
import run_n2n3 as R                         # noqa: E402
from mape_cap_bplus.objective import evaluate_placement  # noqa: E402

TAU = 1.25
STATE = "persistent-degradation"
WINDOW = 60.0
PAIR_ORDER = ["rack-a>rack-b", "rack-b>rack-a", "rack-a>rack-c", "rack-c>rack-a", "rack-b>rack-c", "rack-c>rack-b"]
GROUP_OF = {0: "cg-ab", 1: "cg-ab", 2: "cg-ac", 3: "cg-ac", 4: "cg-bc", 5: "cg-bc"}
GROUP_STAS = {"cg-ab": (0, 1), "cg-ac": (2, 3), "cg-bc": (4, 5)}
EPS = 1e-12
METHODS = ["Affinity-Bytes", "Affinity-Bytes+Admission", "MAPE-CAP-WS"]
EXPECTED_AFFINITY_VIOLATIONS = 24            # published primary result; reproduction gate
SWEEP_SHAPES = 12
SWEEP_LEVELS = [0.8, 0.9, 1.0, 1.1, 1.2]


def pd_state():
    lib = R.LIB[STATE]
    good = {f"{l['source_rack']}>{l['destination_rack']}": l["goodput_bps"] for l in lib["links"]}
    grp = {f"{l['source_rack']}>{l['destination_rack']}": l["conflict_group"] for l in lib["links"]}
    budgets = lib["conflict_budgets_seconds"]
    assert all(grp[p] == GROUP_OF[i] for i, p in enumerate(PAIR_ORDER)), "pair/group order mismatch"
    assert set(budgets.values()) == {30.0}, budgets
    return [good[p] for p in PAIR_ORDER], budgets


def build():
    goodput, budgets = pd_state()
    duty = 30.0 / WINDOW
    placements, cells, viol = [], {}, 0
    for nrep, seeds in R.SEED_BLOCKS.items():
        for seed in seeds:
            p = R.base_problem(nrep, seed)
            rows = R.characterise(p)
            cur_key = tuple(sorted(p.current_placement.items()))
            cur = next(c for c in rows if c["key"] == cur_key)
            factor = TAU / cur["u_plan"]
            sel = R.select(rows, cur_key, factor)
            scaled = R.scale(p, factor)
            nodes = p.node_by_id
            for m in METHODS:
                c = sel[m]
                assert c is not None, (seed, m)
                pl = c["placement"]
                bits = [0.0] * 6
                for f in scaled.flows:
                    a, b = nodes[pl[f.source_replica]].rack_id, nodes[pl[f.destination_replica]].rack_id
                    if a != b:
                        bits[PAIR_ORDER.index(f"{a}>{b}")] += f.bits_per_window
                air = [bits[i] / goodput[i] / WINDOW for i in range(6)]      # fraction of the window
                ev = evaluate_placement(scaled, pl, R.RISK)
                planner_pd = ev.scenario_airtime_by_group.get(STATE, {})
                cell_ids, group_util = [], {}
                for g, (i, j) in GROUP_STAS.items():
                    u = (air[i] + air[j]) / duty
                    # the mapping must agree with the planner's own utilization for this group
                    assert abs(u - planner_pd.get(g, 0.0) / budgets[g]) < 1e-9, (seed, m, g)
                    group_util[g] = u
                    if air[i] + air[j] <= 0:
                        continue
                    key = (seed, g, round(air[i], 12), round(air[j], 12))
                    if key not in cells:
                        fr = [0.0] * 6
                        fr[i], fr[j] = air[i], air[j]
                        cells[key] = {"cell_id": f"s{seed}-{g}-{len(cells):04d}", "seed": seed, "group": g,
                                      "airtime_fraction": fr, "planner_group_utilization": u,
                                      "active_streams": int(air[i] > 0) + int(air[j] > 0)}
                    cell_ids.append(cells[key]["cell_id"])
                u_all = c["u_plan"] * factor
                if m == "Affinity-Bytes" and u_all > 1 + EPS:
                    viol += 1
                placements.append({"seed": seed, "replicas": nrep, "method": m, "cross_rack_bits": bits,
                                   "cells": cell_ids, "pd_group_utilization": group_util,
                                   "pd_worst_utilization": max(group_util.values()),
                                   "planner_worst_utilization_all_states": u_all,
                                   "planner_admissible": bool(u_all <= 1 + EPS)})
    assert viol == EXPECTED_AFFINITY_VIOLATIONS, f"reproduction gate failed: {viol} Affinity-Bytes violations"
    # Boundary sweep: 12 two-direction traffic shapes chosen by a rule that uses no outcome
    # (evenly spaced order statistics of the first direction's airtime share), each at five loads.
    two = sorted((c for c in cells.values() if c["active_streams"] == 2),
                 key=lambda c: (max(c["airtime_fraction"]) / sum(c["airtime_fraction"]), c["cell_id"]))
    picks = [two[round(k * (len(two) - 1) / (SWEEP_SHAPES - 1))] for k in range(SWEEP_SHAPES)]
    sweep = []
    for k, c in enumerate(picks, 1):
        tot = sum(c["airtime_fraction"])
        for u in SWEEP_LEVELS:
            fr = [a / tot * u * duty for a in c["airtime_fraction"]]
            sweep.append({"cell_id": f"sweep-{k:02d}-u{u:.1f}", "shape_id": f"shape-{k:02d}", "source_cell": c["cell_id"],
                          "seed": c["seed"], "group": c["group"], "airtime_fraction": fr, "planner_group_utilization": u,
                          "active_streams": 2, "dominant_direction_share": max(c["airtime_fraction"]) / tot})
    return {"tau": TAU, "state": STATE, "duty_fraction": duty, "pair_order": PAIR_ORDER,
            "group_stas": {k: list(v) for k, v in GROUP_STAS.items()}, "methods": METHODS,
            "n_graphs": len(placements) // len(METHODS), "placements": placements,
            "cells": sorted(cells.values(), key=lambda c: c["cell_id"]), "sweep_cells": sweep,
            "sweep_levels": SWEEP_LEVELS}


def close(x, y):
    if isinstance(x, float) or isinstance(y, float):
        return abs(x - y) <= 1e-9 * max(1.0, abs(x))
    if isinstance(x, dict):
        return x.keys() == y.keys() and all(close(x[k], y[k]) for k in x)
    if isinstance(x, list):
        return len(x) == len(y) and all(close(a, b) for a, b in zip(x, y))
    return x == y


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    plan = build()
    out = HERE / "config" / "placement_plan.json"
    if a.check:
        ok = close(json.loads(out.read_text()), plan)
        print("plan reproduces existing file:", ok)
        sys.exit(0 if ok else 1)
    text = json.dumps(plan, indent=1, sort_keys=True)
    out.write_text(text, encoding="utf-8")
    print("placements", len(plan["placements"]), "unique cells", len(plan["cells"]),
          "sha256", hashlib.sha256(text.encode()).hexdigest())


if __name__ == "__main__":
    main()
