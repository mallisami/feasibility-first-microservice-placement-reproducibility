#!/usr/bin/env python3
"""E2: does locality-induced inadmissibility persist on larger instances? (see PROTOCOL.md)

Pure computation with the packaged planner code. For every graph, all placements reachable from
the incumbent within the move budget are enumerated exactly, so each method's selection is exact
within that neighborhood (no time limits, no heuristics).

    python3 run_scale.py gate              # reproduce the published 150-graph result with this enumerator
    python3 run_scale.py smoke             # two non-science seeds per size, timing only
    python3 run_scale.py run --workers 4   # science run (resumable), then analysis
    python3 run_scale.py analyze
"""
from __future__ import annotations
import argparse, csv, hashlib, itertools, json, math, sys, time
from dataclasses import replace
from multiprocessing import Pool
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Planner code, generator and state library: the bundled copies in deps/ (byte-identical to the
# reproducibility package; hashes in DEPS_SHA256SUMS.txt), so this folder runs on its own.
PKG = HERE.parent / "deps"
sys.path.insert(0, str(PKG / "EXTENSION_STUDIES" / "2026-09-26" / "N2N3_admission_vs_ranking"))
import run_n2n3 as R  # noqa: E402
from mape_cap_bplus.generators import generate_problem  # noqa: E402
from mape_cap_bplus.models import RelocationCost  # noqa: E402
from mape_cap_bplus.objective import evaluate_placement  # noqa: E402

# (label, replicas, nodes per rack, move budget, science seeds)
SIZES = [
    ("n12", 12, 2, 3, range(61001, 61051)),
    ("n16", 16, 2, 4, range(62001, 62051)),
    ("n24", 24, 3, 3, range(63001, 63051)),
]
SMOKE_SEEDS = [99001, 99002]
TARGETS = [1.00, 1.10, 1.25, 1.50]
PRIMARY = 1.25
EPS = 1e-12
PAIR_GROUPS = {"cg-ab": {"rack-a", "rack-b"}, "cg-ac": {"rack-a", "rack-c"}, "cg-bc": {"rack-b", "rack-c"}}
OUT = HERE / "results"


def problem(nrep, npr, mmax, seed):
    p = generate_problem(replica_count=nrep, rack_count=3, nodes_per_rack=npr, scenario_count=3, seed=seed,
                         decision_window_seconds=60.0)
    rack_map = {"rack-0": "rack-a", "rack-1": "rack-b", "rack-2": "rack-c"}
    nodes = tuple(replace(n, rack_id=rack_map[n.rack_id]) for n in p.nodes)
    costs = {r.replica_id: RelocationCost(r.replica_id, cost_units=4062.0, expected_seconds=4.062,
                                          uncertainty_units=690.0, provenance="frozen-kind-pilot-mean") for r in p.replicas}
    return replace(p, nodes=nodes, scenarios=R.PLAN, relocation_costs=costs, max_relocations=mmax)


def group_utils(tiny, ev):
    out = {}
    for s in tiny.scenarios:
        am = ev.scenario_airtime_by_group.get(s.scenario_id, {})
        for g, b in s.conflict_budgets_seconds.items():
            if b > 0:
                out[(s.scenario_id, g)] = am.get(g, 0.0) / b / R.TINY
    return out


def candidates(p, mmax):
    reps = [r.replica_id for r in p.replicas]
    cur = dict(p.current_placement)
    alt = {r: [n for n in p.allowed_nodes_for(r) if n != cur[r]] for r in reps}
    for m in range(mmax + 1):
        for sub in itertools.combinations(reps, m):
            for a in itertools.product(*[alt[r] for r in sub]):
                pl = dict(cur)
                pl.update(zip(sub, a))
                yield pl, m


def solve_graph(args):
    label, nrep, npr, mmax, seed, p = args[0], args[1], args[2], args[3], args[4], None
    p = args[5] if len(args) > 5 and args[5] is not None else problem(nrep, npr, mmax, seed)
    t0 = time.time()
    tiny = R.scale(p, R.TINY)
    cur_key = tuple(sorted(p.current_placement.items()))
    ev = evaluate_placement(tiny, dict(p.current_placement), R.RISK)
    if not R.cluster_ok(p, dict(p.current_placement)) or not ev.feasible:
        return {"size": label, "seed": seed, "excluded": "invalid incumbent"}
    u_cur = R.unit_util(tiny, ev)
    if u_cur <= 0:
        return {"size": label, "seed": seed, "excluded": "zero incumbent utilization"}
    factors = {t: t / u_cur for t in TARGETS}
    # running minima: rule -> (value, moves, key) ; admission-constrained rules are kept per target
    best_aff = None
    best_adm = {t: None for t in TARGETS}
    best_mape = {t: None for t in TARGETS}
    n_cand = 0
    for pl, mv in candidates(p, mmax):
        if not R.cluster_ok(p, pl):
            continue
        ev = evaluate_placement(tiny, pl, R.RISK)
        if not ev.feasible:
            continue
        n_cand += 1
        u = R.unit_util(tiny, ev)
        b = R.cross(p, pl, "bytes") / 8.0
        key = tuple(sorted(pl.items()))
        rec = (b, mv, key, u, ev.total_objective)
        if best_aff is None or rec[:3] < best_aff[:3]:
            best_aff = rec
        for t, f in factors.items():
            if u * f <= 1.0 + EPS:
                if best_adm[t] is None or rec[:3] < best_adm[t][:3]:
                    best_adm[t] = rec
                mrec = (ev.total_objective, mv, key, u, b)
                if best_mape[t] is None or mrec[:3] < best_mape[t][:3]:
                    best_mape[t] = mrec
    nodes = p.node_by_id

    def detail(key, f):
        pl = dict(key)
        e = evaluate_placement(tiny, pl, R.RISK)
        gu = {k: v * f for k, v in group_utils(tiny, e).items()}
        worst = max(gu, key=lambda k: gu[k])
        pair = {}
        for fl in p.flows:
            a, b_ = nodes[pl[fl.source_replica]].rack_id, nodes[pl[fl.destination_replica]].rack_id
            if a != b_:
                k = "-".join(sorted((a, b_)))
                pair[k] = pair.get(k, 0.0) + fl.bits_per_window
        tot = sum(pair.values())
        return {"worst_state": worst[0], "worst_group": worst[1], "worst_u": gu[worst],
                "cd_u": gu.get(("conflict-dense", "cg-shared"), 0.0),
                "pair_share": {k: v / tot for k, v in pair.items()} if tot > 0 else {},
                "racks_used": len({nodes[n].rack_id for n in pl.values()})}

    rows = []
    for t, f in factors.items():
        aff_u = best_aff[3] * f
        row = {"size": label, "replicas": nrep, "nodes_per_rack": npr, "move_budget": mmax, "seed": seed, "target": t,
               "n_candidates": n_cand, "affinity_u": aff_u, "affinity_admissible": bool(aff_u <= 1 + EPS),
               "admissible_exists": best_adm[t] is not None, "affinity_bytes": best_aff[0] * f, "affinity_moves": best_aff[1]}
        da = detail(best_aff[2], f)
        row.update({"affinity_worst_state": da["worst_state"], "affinity_worst_group": da["worst_group"],
                    "affinity_cd_u": da["cd_u"], "affinity_racks_used": da["racks_used"]})
        if best_adm[t] is not None:
            adm, mp = best_adm[t], best_mape[t]
            dd, dm = detail(adm[2], f), detail(mp[2], f)
            row.update({"adm_u": adm[3] * f, "adm_bytes": adm[0] * f, "adm_identical_to_affinity": adm[2] == best_aff[2],
                        "mape_u": mp[3] * f, "mape_bytes": mp[4] * f, "mape_identical_to_adm": mp[2] == adm[2],
                        "adm_cd_u": dd["cd_u"], "mape_cd_u": dm["cd_u"]})
            if not row["affinity_admissible"] and da["worst_group"] in PAIR_GROUPS:
                k = "-".join(sorted(PAIR_GROUPS[da["worst_group"]]))
                row.update({"overloaded_pair": k, "affinity_share_on_overloaded_pair": da["pair_share"].get(k, 0.0),
                            "adm_share_on_overloaded_pair": dd["pair_share"].get(k, 0.0)})
        rows.append(row)
    for r in rows:
        r["elapsed_seconds"] = time.time() - t0
    return {"size": label, "seed": seed, "rows": rows}


def gate():
    """Reproduce the published primary result (24/150 avoidable violations at 1.25; 7 at 1.00; 12 at 1.10) with this enumerator."""
    counts = {t: 0 for t in TARGETS}
    for nrep, seeds in R.SEED_BLOCKS.items():
        for seed in seeds:
            p = R.base_problem(nrep, seed)
            res = solve_graph(("orig", nrep, 1, p.max_relocations, seed, p))
            for r in res["rows"]:
                counts[r["target"]] += (not r["affinity_admissible"]) and r["admissible_exists"]
    exp = {1.00: 7, 1.10: 12, 1.25: 24, 1.50: 35}
    print("avoidable Affinity-Bytes violations:", counts, "expected:", exp)
    assert counts == exp, "reproduction gate failed"
    return counts


def wilson(k, n, z=1.959964):
    if n == 0:
        return (float("nan"), float("nan"))
    ph = k / n
    d = 1 + z * z / n
    c = (ph + z * z / (2 * n)) / d
    h = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def analyze():
    rows = []
    excl = []
    for f in sorted((OUT / "graphs").glob("*.json")):
        d = json.loads(f.read_text())
        if "excluded" in d:
            excl.append(d)
        else:
            rows += d["rows"]
    if not rows:
        raise SystemExit("no results")
    fields = sorted({k for r in rows for k in r})
    with (OUT / "scale_cells.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    summ = {"excluded": excl, "by_size_and_target": []}
    for label, nrep, npr, mmax, seeds in SIZES:
        for t in TARGETS:
            x = [r for r in rows if r["size"] == label and r["target"] == t]
            if not x:
                continue
            viol = [r for r in x if not r["affinity_admissible"]]
            avoid = [r for r in viol if r["admissible_exists"]]
            lo, hi = wilson(len(avoid), len(x))
            s = {"size": label, "replicas": nrep, "nodes_per_rack": npr, "move_budget": mmax, "target": t, "graphs": len(x),
                 "affinity_violations": len(viol), "avoidable_violations": len(avoid), "avoidable_fraction": len(avoid) / len(x),
                 "avoidable_fraction_wilson95": [lo, hi], "no_admissible_placement": sum(not r["admissible_exists"] for r in x),
                 "violations_in_pair_group": sum(r["affinity_worst_group"] in PAIR_GROUPS for r in avoid),
                 "violations_in_multi_pair_group": sum(r["affinity_worst_group"] not in PAIR_GROUPS for r in avoid),
                 "violation_states": {st: sum(r["affinity_worst_state"] == st for r in avoid) for st in sorted({r["affinity_worst_state"] for r in avoid})}}
            sh = [(r["affinity_share_on_overloaded_pair"], r["adm_share_on_overloaded_pair"]) for r in avoid if "overloaded_pair" in r]
            if sh:
                s["mean_share_on_overloaded_pair"] = {"affinity": sum(a for a, _ in sh) / len(sh), "admission": sum(b for _, b in sh) / len(sh),
                                                      "graphs": len(sh), "lower_under_admission": sum(b < a for a, b in sh)}
            both = [r for r in x if r["admissible_exists"]]
            if both:
                s["mape_identical_to_admission"] = sum(r["mape_identical_to_adm"] for r in both)
                s["mean_headroom_mape_minus_admission"] = sum((1 - r["mape_u"]) - (1 - r["adm_u"]) for r in both) / len(both)
            s["median_candidates"] = sorted(r["n_candidates"] for r in x)[len(x) // 2]
            summ["by_size_and_target"].append(s)
    (OUT / "SUMMARY.json").write_text(json.dumps(summ, indent=2), encoding="utf-8")
    L = ["# E2 scale study: results", "", "| size | replicas | nodes/rack | moves | load | graphs | affinity violations | avoidable | avoidable fraction (Wilson 95%) | no admissible | in pair group | in multi-pair group |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in summ["by_size_and_target"]:
        L.append(f"| {s['size']} | {s['replicas']} | {s['nodes_per_rack']} | {s['move_budget']} | {s['target']} | {s['graphs']} | {s['affinity_violations']} | {s['avoidable_violations']} | {s['avoidable_fraction']:.3f} [{s['avoidable_fraction_wilson95'][0]:.3f}, {s['avoidable_fraction_wilson95'][1]:.3f}] | {s['no_admissible_placement']} | {s['violations_in_pair_group']} | {s['violations_in_multi_pair_group']} |")
    (OUT / "RESULTS.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))
    return summ


def run(workers, seeds_override=None):
    (OUT / "graphs").mkdir(parents=True, exist_ok=True)
    jobs = []
    for label, nrep, npr, mmax, seeds in SIZES:
        for seed in (seeds_override or seeds):
            if not (OUT / "graphs" / f"{label}-{seed}.json").exists():
                jobs.append((label, nrep, npr, mmax, seed, None))
    print(f"{len(jobs)} graphs to solve with {workers} workers", flush=True)
    t0 = time.time()
    with Pool(workers) as pool:
        for i, res in enumerate(pool.imap_unordered(solve_graph, jobs), 1):
            (OUT / "graphs" / f"{res['size']}-{res['seed']}.json").write_text(json.dumps(res), encoding="utf-8")
            if i % 5 == 0 or i == len(jobs):
                el = time.time() - t0
                print(f"[{i}/{len(jobs)}] {el / 60:.1f} min elapsed, est. {el / i * (len(jobs) - i) / 60:.1f} min remaining", flush=True)


def main():
    global OUT
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["gate", "smoke", "run", "analyze"])
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    if a.command == "gate":
        gate()
    elif a.command == "smoke":
        OUT = HERE / "smoke_results"
        run(a.workers, SMOKE_SEEDS)
        analyze()
    elif a.command == "run":
        gate()
        prov = {"script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "protocol_sha256": hashlib.sha256((HERE / "PROTOCOL.md").read_bytes()).hexdigest(), "python": sys.version}
        OUT.mkdir(exist_ok=True)
        (OUT / "provenance.json").write_text(json.dumps(prov, indent=2))
        run(a.workers)
        analyze()
    else:
        analyze()


if __name__ == "__main__":
    main()
