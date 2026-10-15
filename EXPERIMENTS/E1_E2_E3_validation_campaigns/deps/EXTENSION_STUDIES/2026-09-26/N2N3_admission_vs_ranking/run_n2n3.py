#!/usr/bin/env python3
"""N2/N3: admission versus ranking on the AFF-C graph set (see PROTOCOL_FROZEN.md).

Reuses the AFF-C instances, state library, relocation economics, load calibration and
exhaustive placement enumeration. Payload scaling is linear in airtime and leaves delay,
relocation and slack unchanged, so each placement is characterised once at unit scale and
selection at any load target reduces to filtering on scaled utilisation.

A reproduction gate re-derives the four original AFF-C methods at the six original targets and
aborts unless feasibility, cross-rack bytes and objective match the frozen cell_results.csv.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import platform
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import binomtest, wilcoxon

HERE = Path(__file__).resolve().parent
PKG = HERE.parents[2]  # .../M
sys.path.insert(0, str(PKG / "implementation" / "code"))

from mape_cap_bplus.generators import generate_problem  # noqa: E402
from mape_cap_bplus.models import RelocationCost, RiskConfig  # noqa: E402
from mape_cap_bplus.objective import evaluate_placement  # noqa: E402
import run_confirmatory_campaign as rc  # noqa: E402

AFFC_DIR = PKG / "RESULTS" / "post-manuscript" / "affinity-wireless-computational-confirmation-20260915"
TRACE_CSV = PKG / "RESULTS" / "calibration" / "external" / "ns3_simulation_backed_traces.csv"

RISK = RiskConfig(cvar_quantile=0.8, cvar_weight=1.5, relocation_weight=1.0, slo_slack_weight=1000.0)
RISK_OFF = RiskConfig(cvar_quantile=0.8, cvar_weight=0.0, relocation_weight=1.0, slo_slack_weight=1000.0)
PLAN_IDS = ["conflict-dense", "partial-blockage", "persistent-degradation"]
HELDOUT_IDS = ["nominal-los", "asymmetric-los", "outage-with-fallback", "recovery", "mixed-regime"]
TARGETS = [0.50, 0.90, 1.00, 1.10, 1.25, 1.50]
FINE = [round(0.50 + 0.05 * i, 2) for i in range(31)]  # 0.50 .. 2.00
PRIMARY = 1.25
SEED_BLOCKS = {6: range(11001, 11051), 7: range(22001, 22051), 8: range(33001, 33051)}
BOOT_N, BOOT_SEED = 100_000, 20260926
TINY = 1e-6  # evaluation payload scale at which no airtime budget can bind
EPS = 1e-12


def load_library() -> dict:
    df = pd.read_csv(TRACE_CSV)
    db = {}
    for sid, g in df.groupby("scenario_id", sort=False):
        first = g.iloc[0]
        links, budgets = [], {}
        for _, r in g.iterrows():
            cg = None if pd.isna(r.conflict_group) or str(r.conflict_group).strip() == "" else str(r.conflict_group)
            links.append({"source_rack": str(r.source_rack), "destination_rack": str(r.destination_rack),
                          "latency_ms": float(r.latency_ms), "goodput_bps": float(r.goodput_bps),
                          "available": bool(r.available), "path_id": str(r.path_id), "conflict_group": cg,
                          "provenance": str(r.provenance)})
            if cg and not pd.isna(r.budget_seconds):
                budgets[cg] = float(r.budget_seconds)
        db[str(sid)] = {"scenario_id": str(sid), "weight": float(first.weight), "links": links,
                        "conflict_budgets_seconds": budgets, "intra_rack_latency_ms": 0.2,
                        "intra_rack_goodput_bps": 1e11,
                        "regime_duration_seconds": float(first.regime_duration_seconds)}
    return db


LIB = load_library()


def scenario_set(ids):
    raw = [LIB[i] for i in ids]
    tot = sum(x["weight"] for x in raw)
    return tuple(rc.trace_to_scenario({**x, "weight": x["weight"] / tot}) for x in raw)


PLAN = scenario_set(PLAN_IDS)
HELDOUT = {sid: scenario_set([sid]) for sid in HELDOUT_IDS}


def base_problem(nrep: int, seed: int):
    p = generate_problem(replica_count=nrep, rack_count=3, nodes_per_rack=1, scenario_count=3,
                         seed=seed, decision_window_seconds=60.0)
    rack_map = {"rack-0": "rack-a", "rack-1": "rack-b", "rack-2": "rack-c"}
    nodes = tuple(replace(n, rack_id=rack_map[n.rack_id]) for n in p.nodes)
    costs = {r.replica_id: RelocationCost(r.replica_id, cost_units=4062.0, expected_seconds=4.062,
                                          uncertainty_units=690.0, provenance="frozen-kind-pilot-mean")
             for r in p.replicas}
    return replace(p, nodes=nodes, scenarios=PLAN, relocation_costs=costs)


def scale(p, factor: float):
    return replace(p, flows=tuple(replace(f, bits_per_window=f.bits_per_window * factor) for f in p.flows))


def cluster_ok(p, pl) -> bool:
    nodes, reps = p.node_by_id, p.replica_by_id
    cpu = {n: 0.0 for n in nodes}
    mem = {n: 0.0 for n in nodes}
    groups = {n: set() for n in nodes}
    mv = 0
    for rid, nid in pl.items():
        r = reps[rid]
        if nid not in p.allowed_nodes_for(rid):
            return False
        cpu[nid] += r.cpu_request
        mem[nid] += r.memory_request_mb
        if r.anti_affinity_group:
            if r.anti_affinity_group in groups[nid]:
                return False
            groups[nid].add(r.anti_affinity_group)
        mv += int(p.current_placement.get(rid) != nid)
    if p.max_relocations is not None and mv > p.max_relocations:
        return False
    return all(cpu[n] <= nodes[n].cpu_capacity + EPS and mem[n] <= nodes[n].memory_capacity_mb + EPS for n in nodes)


def cross(p, pl, mode):
    nodes = p.node_by_id
    return sum((f.bits_per_window if mode == "bytes" else f.requests_per_window)
               for f in p.flows
               if nodes[pl[f.source_replica]].rack_id != nodes[pl[f.destination_replica]].rack_id)


def moves(p, pl):
    return sum(int(p.current_placement.get(r) != n) for r, n in pl.items())


def unit_util(p_tiny, ev) -> float:
    """Worst airtime/budget over the problem's scenarios, rescaled to unit payload."""
    mx = 0.0
    for s in p_tiny.scenarios:
        amap = ev.scenario_airtime_by_group.get(s.scenario_id, {})
        for g, b in s.conflict_budgets_seconds.items():
            if b > 0:
                mx = max(mx, amap.get(g, 0.0) / b)
    return mx / TINY


def characterise(p):
    """Enumerate AFF-C cluster-feasible placements and characterise each at unit payload."""
    reps = [r.replica_id for r in p.replicas]
    allowed = [p.allowed_nodes_for(r) for r in reps]
    tiny = scale(p, TINY)
    rows = []
    for assign in itertools.product(*allowed):
        pl = dict(zip(reps, assign))
        if not cluster_ok(p, pl):
            continue
        ev = evaluate_placement(tiny, pl, RISK)
        # AFF-C screen: drop placements with any non-airtime planning-set violation.
        if not ev.feasible:
            continue
        ev_off = evaluate_placement(tiny, pl, RISK_OFF)
        rec = {"placement": pl, "key": tuple(sorted(pl.items())),
               "u_plan": unit_util(tiny, ev), "bytes": cross(p, pl, "bytes") / 8.0,
               "requests": cross(p, pl, "frequency"), "moves": moves(p, pl),
               "obj_full": ev.total_objective, "obj_off": ev_off.total_objective,
               "exp_delay": ev.expected_delay_cost, "cvar": ev.cvar_delay_cost}
        worst_ho, avail_all = 0.0, True
        for sid, scen in HELDOUT.items():
            ph = replace(tiny, scenarios=scen)
            evh = evaluate_placement(ph, pl, RISK)
            unavailable = any("unavailable path" in x for x in evh.reasons)
            u = unit_util(ph, evh)
            rec[f"ho_avail_{sid}"] = not unavailable
            rec[f"ho_u_{sid}"] = u
            avail_all &= not unavailable
            worst_ho = max(worst_ho, u)
        rec["ho_avail_all"], rec["ho_u_max"] = avail_all, worst_ho
        rows.append(rec)
    return rows


def pick(cands, key):
    return min(cands, key=lambda c: (key(c), c["moves"], c["key"])) if cands else None


def select(rows, current_key, factor):
    adm = [c for c in rows if c["u_plan"] * factor <= 1.0 + EPS]
    cur = next((c for c in rows if c["key"] == current_key), None)
    return {
        "Current": cur,
        "Affinity-Bytes": pick(rows, lambda c: c["bytes"]),
        "Affinity-Bytes+Admission": pick(adm, lambda c: c["bytes"]),
        "MAPE-CAP-WS Risk-off": pick(adm, lambda c: c["obj_off"]),
        "MAPE-CAP-WS": pick(adm, lambda c: c["obj_full"]),
    }


def row_for(c, factor):
    if c is None:
        return {"admissible": False, "no_admissible_placement": True}
    u = c["u_plan"] * factor
    out = {"admissible": u <= 1.0 + EPS, "no_admissible_placement": False, "u_max": u, "headroom": 1.0 - u,
           "cross_rack_bytes": c["bytes"] * factor, "moves": c["moves"], "expected_delay": c["exp_delay"],
           "cvar_delay": c["cvar"], "objective_full": c["obj_full"],
           "ho_u_max": c["ho_u_max"] * factor}
    ho_ok = c["ho_avail_all"] and c["ho_u_max"] * factor <= 1.0 + EPS
    out["heldout_admissible"] = bool(ho_ok)
    for sid in HELDOUT_IDS:
        out[f"ho_ok_{sid}"] = bool(c[f"ho_avail_{sid}"] and c[f"ho_u_{sid}"] * factor <= 1.0 + EPS)
    out["placement"] = json.dumps(c["placement"], sort_keys=True)
    return out


def boot_ci(d, seed):
    d = np.asarray(d, float)
    rng = np.random.default_rng(seed)
    means = []
    left = BOOT_N
    while left:
        m = min(5000, left)
        means.append(d[rng.integers(0, len(d), size=(m, len(d)))].mean(axis=1))
        left -= m
    v = np.concatenate(means)
    return float(d.mean()), float(np.quantile(v, 0.025)), float(np.quantile(v, 0.975))


def reproduction_gate(df):
    frozen = pd.read_csv(AFFC_DIR / "cell_results.csv")
    name = {"BPlus-Exact": "MAPE-CAP-WS", "Affinity-Bytes": "Affinity-Bytes", "Current": "Current"}
    bad = 0
    for _, fr in frozen[frozen.method.isin(name)].iterrows():
        m = df[(df.seed == fr.seed) & np.isclose(df.target, fr.target_current_util) & (df.method == name[fr.method])]
        if len(m) != 1:
            bad += 1
            continue
        r = m.iloc[0]
        mine_b, frozen_b = float(r.cross_rack_bytes), float(fr.cross_rack_bytes)
        if bool(r.admissible) != bool(fr.feasible):
            bad += 1
        elif math.isnan(mine_b) and math.isnan(frozen_b):
            continue  # both report "no admissible placement"
        elif not math.isclose(mine_b, frozen_b, rel_tol=1e-9):
            bad += 1
        elif bool(fr.feasible) and not math.isclose(float(r.objective_full), float(fr.objective), rel_tol=1e-9):
            bad += 1
    return bad, int(frozen.method.isin(name).sum())


def main():
    cells, fine = [], []
    done = 0
    for nrep, seeds in SEED_BLOCKS.items():
        for seed in seeds:
            p = base_problem(nrep, seed)
            rows = characterise(p)
            cur_key = tuple(sorted(p.current_placement.items()))
            cur = next(c for c in rows if c["key"] == cur_key)
            u0 = cur["u_plan"]  # unit-payload worst planning utilisation of Current
            for grid, sink in ((TARGETS, cells), (FINE, fine)):
                for t in grid:
                    factor = t / u0
                    for method, c in select(rows, cur_key, factor).items():
                        sink.append({"replica_count": nrep, "seed": seed, "target": t, "method": method,
                                     "n_candidates": len(rows), **row_for(c, factor)})
            done += 1
            if done % 15 == 0:
                print(f"processed {done}/150", flush=True)

    df = pd.DataFrame(cells)
    bad, n = reproduction_gate(df)
    print(f"reproduction gate: {n - bad}/{n} AFF-C cells reproduced")
    if bad:
        df.to_csv(HERE / "cell_results.GATE_FAILED.csv", index=False)
        raise SystemExit("reproduction gate failed; outputs not published")

    df.to_csv(HERE / "cell_results.csv", index=False)
    pd.DataFrame(fine).to_csv(HERE / "fine_grid.csv", index=False)
    ho = df[["replica_count", "seed", "target", "method"] + [f"ho_ok_{s}" for s in HELDOUT_IDS]]
    ho.to_csv(HERE / "heldout_by_state.csv", index=False)

    # Primary analyses at target 1.25 (two-sided), Holm across three tests.
    t = df[np.isclose(df.target, PRIMARY)].set_index(["replica_count", "seed"])
    M = t[t.method == "MAPE-CAP-WS"]
    A = t[t.method == "Affinity-Bytes+Admission"]
    both = M.index.intersection(A.index)
    both = both[(~M.loc[both, "no_admissible_placement"].astype(bool)) & (~A.loc[both, "no_admissible_placement"].astype(bool))]
    res = {"n_graphs_both_admissible": int(len(both))}
    same = (M.loc[both, "placement"] == A.loc[both, "placement"])
    res["identical_placements"] = int(same.sum())
    tests = {}
    for key, col, s in (("N2P_a_headroom", "headroom", 1), ("N2P_b_bytes", "cross_rack_bytes", 2)):
        d = (M.loc[both, col].astype(float) - A.loc[both, col].astype(float)).to_numpy()
        mean, lo, hi = boot_ci(d, BOOT_SEED + s)
        nz = d[np.abs(d) > 1e-12]
        p = float(wilcoxon(nz, alternative="two-sided").pvalue) if len(nz) else 1.0
        tests[key] = {"mean_diff_mape_minus_affadm": mean, "ci95": [lo, hi], "wilcoxon_p": p,
                      "n_nonzero": int(len(nz)), "median_diff": float(np.median(d))}
    mh = M.loc[both, "heldout_admissible"].astype(bool)
    ah = A.loc[both, "heldout_admissible"].astype(bool)
    b, c = int((mh & ~ah).sum()), int((~mh & ah).sum())
    p = float(binomtest(b, b + c, 0.5, alternative="two-sided").pvalue) if b + c else 1.0
    rd, lo, hi = boot_ci(mh.astype(float).to_numpy() - ah.astype(float).to_numpy(), BOOT_SEED + 3)
    tests["N3P_heldout"] = {"mape_heldout_rate": float(mh.mean()), "affadm_heldout_rate": float(ah.mean()),
                            "mape_only": b, "affadm_only": c, "mcnemar_exact_p": p,
                            "risk_difference": rd, "ci95": [lo, hi]}
    order = sorted(tests, key=lambda k: tests[k].get("wilcoxon_p", tests[k].get("mcnemar_exact_p")))
    running = 0.0
    for i, k in enumerate(order):
        raw = tests[k].get("wilcoxon_p", tests[k].get("mcnemar_exact_p"))
        running = max(running, min(1.0, raw * (len(order) - i)))
        tests[k]["holm_p"] = running
    res["tests"] = tests
    (HERE / "primary_tests.json").write_text(json.dumps(res, indent=2), encoding="utf-8")

    summ = df.groupby(["target", "method"]).agg(
        n=("admissible", "size"), admissible=("admissible", "sum"),
        heldout_admissible=("heldout_admissible", "sum"), mean_headroom=("headroom", "mean"),
        mean_bytes=("cross_rack_bytes", "mean"), mean_exp_delay=("expected_delay", "mean"),
        mean_cvar=("cvar_delay", "mean"), mean_moves=("moves", "mean")).reset_index()
    summ.to_csv(HERE / "summary.csv", index=False)

    prov = {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__,
            "risk": RISK.__dict__, "risk_off": RISK_OFF.__dict__, "plan": PLAN_IDS, "heldout": HELDOUT_IDS,
            "targets": TARGETS, "fine_grid": [FINE[0], FINE[-1], 0.05], "reproduction_gate": f"{n - bad}/{n}"}
    (HERE / "provenance.json").write_text(json.dumps(prov, indent=2), encoding="utf-8")
    with open(HERE / "SHA256SUMS.txt", "w", encoding="utf-8") as fh:
        for f in sorted(HERE.glob("*")):
            if f.is_file() and f.name != "SHA256SUMS.txt":
                fh.write(f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}\n")
    print(summ.to_string(index=False))
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
