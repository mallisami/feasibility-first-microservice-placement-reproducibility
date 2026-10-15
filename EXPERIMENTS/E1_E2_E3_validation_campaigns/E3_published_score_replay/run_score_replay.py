#!/usr/bin/env python3
"""E3: replay of a published network-aware node-scoring rule on the 150 controlled graphs.

Rule replayed (Marchese and Tomarchio, ICSOC 2022, Algorithm 1 "Node scoring algorithm"):
for a Pod p and a candidate node n,
    cmCost(p, n) = sum over cluster nodes cn of [ traffic between p and the Pods on cn ] x netCost(n, cn)
    score(p, n)  = -cmCost(p, n)
and the Pod is placed on the node with the highest score (lowest communication cost).
This is an independent implementation of that rule in the placement setting of this paper. It is not
the authors' scheduler plugin, operators or testbed. See PROTOCOL.md for the adaptations.

    python3 run_score_replay.py smoke    # non-science seeds, plumbing only
    python3 run_score_replay.py run      # 150 science graphs; full-text rule check is frozen in FULLTEXT_RULE_VERIFICATION.md
"""
from __future__ import annotations
import argparse, csv, hashlib, json, sys
from dataclasses import replace
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Planner code, generator and state library: the bundled copies in deps/ (byte-identical to the
# reproducibility package; hashes in DEPS_SHA256SUMS.txt), so this folder runs on its own.
PKG = HERE.parent / "deps"
sys.path.insert(0, str(PKG / "EXTENSION_STUDIES" / "2026-09-26" / "N2N3_admission_vs_ranking"))
import run_n2n3 as R  # noqa: E402
from mape_cap_bplus.objective import evaluate_placement  # noqa: E402

TARGETS = [1.00, 1.10, 1.25, 1.50]
EPS = 1e-12
SMOKE = {6: range(99101, 99104), 7: range(99201, 99204), 8: range(99301, 99304)}


def net_cost():
    """netCost(rack r, rack s): the declared directed latency averaged over the three planning
    states with their normalized design weights; zero within a rack (one node per rack here)."""
    cost = {}
    tot = sum(R.LIB[s]["weight"] for s in R.PLAN_IDS)
    for s in R.PLAN_IDS:
        w = R.LIB[s]["weight"] / tot
        for l in R.LIB[s]["links"]:
            k = (l["source_rack"], l["destination_rack"])
            cost[k] = cost.get(k, 0.0) + w * l["latency_ms"]
    return cost


def cm_cost(p, placement, pod, node, cost, traffic="bits"):
    """Communication cost of `pod` if placed on `node`, all other Pods where they are
    (Algorithm 1: for each node cn, the affinity weights between the Pod and the Pods on cn are
    multiplied by the network cost between n and cn and accumulated; score = -cmCost)."""
    amount = (lambda f: f.bits_per_window) if traffic == "bits" else (lambda f: f.requests_per_window)
    nodes = p.node_by_id
    r = nodes[node].rack_id
    c = 0.0
    for f in p.flows:
        if f.source_replica == pod and f.destination_replica != pod:
            s = nodes[placement[f.destination_replica]].rack_id
            if s != r:
                c += amount(f) * cost[(r, s)]
        elif f.destination_replica == pod and f.source_replica != pod:
            s = nodes[placement[f.source_replica]].rack_id
            if s != r:
                c += amount(f) * cost[(s, r)]
    return c


def replay(p, cost, move_cap, traffic="bits", order="best"):
    """Apply the scoring rule from the incumbent until no Pod improves or the move budget is used.
    order="best": move the Pod whose best-scoring feasible node lowers its cmCost the most.
    order="fixed": take Pods in lexicographic order and move the first one that can improve to its
    best-scoring feasible node; this variant does not depend on how weights are scaled across Pods.
    Ties: stay, then lexicographic Pod and node id."""
    prob = replace(p, max_relocations=move_cap)
    pl = dict(p.current_placement)
    steps = 0
    while True:
        best = None
        for pod in sorted(pl):
            if order == "fixed" and best is not None:
                break
            here = cm_cost(p, pl, pod, pl[pod], cost, traffic)
            for node in sorted(p.allowed_nodes_for(pod)):
                if node == pl[pod]:
                    continue
                gain = here - cm_cost(p, pl, pod, node, cost, traffic)
                if gain <= EPS:
                    continue
                trial = dict(pl)
                trial[pod] = node
                if not R.cluster_ok(prob, trial):
                    continue
                cand = (-gain, pod, node)
                if best is None or cand < best:
                    best = cand
        if best is None:
            return pl, steps
        pl[best[1]] = best[2]
        steps += 1
        if steps > 10 * len(pl):
            raise RuntimeError("replay did not converge")


VARIANTS = ["capped", "capped_fixed_order", "capped_requests", "uncapped"]


def variants(p):
    """capped is the primary variant; the others are declared sensitivity variants."""
    m = p.max_relocations
    return {"capped": (m, "bits", "best"), "capped_fixed_order": (m, "bits", "fixed"),
            "capped_requests": (m, "requests", "best"), "uncapped": (None, "bits", "best")}


def solve(nrep, seed, cost):
    p = R.base_problem(nrep, seed)
    tiny = R.scale(p, R.TINY)
    rows = R.characterise(p)
    cur_key = tuple(sorted(p.current_placement.items()))
    cur = next(c for c in rows if c["key"] == cur_key)
    out = []
    placed = {}
    for name, (cap, traffic, order) in variants(p).items():
        pl, steps = replay(p, cost, cap, traffic, order)
        ev = evaluate_placement(replace(tiny, max_relocations=cap), pl, R.RISK)
        placed[name] = {"placement": pl, "u_unit": R.unit_util(tiny, ev), "bytes_unit": R.cross(p, pl, "bytes") / 8.0,
                        "moves": R.moves(p, pl), "racks": len({p.node_by_id[n].rack_id for n in pl.values()}),
                        "non_airtime_feasible": bool(ev.feasible), "steps": steps}
    for t in TARGETS:
        f = t / cur["u_plan"]
        sel = R.select(rows, cur_key, f)
        aff, adm = sel["Affinity-Bytes"], sel["Affinity-Bytes+Admission"]
        row = {"replicas": nrep, "seed": seed, "target": t, "admissible_exists": adm is not None,
               "affinity_u": aff["u_plan"] * f, "affinity_admissible": bool(aff["u_plan"] * f <= 1 + EPS)}
        for name, d in placed.items():
            u = d["u_unit"] * f
            row.update({f"score_{name}_u": u, f"score_{name}_admissible": bool(u <= 1 + EPS and d["non_airtime_feasible"]),
                        f"score_{name}_bytes": d["bytes_unit"] * f, f"score_{name}_moves": d["moves"],
                        f"score_{name}_racks_used": d["racks"],
                        f"score_{name}_same_as_affinity": tuple(sorted(d["placement"].items())) == aff["key"]})
        out.append(row)
    return out


def verification_level():
    full = HERE / "FULLTEXT_RULE_VERIFICATION.md"
    if not full.exists() or not full.read_text(encoding="utf-8").strip():
        raise RuntimeError("FULLTEXT_RULE_VERIFICATION.md is missing; refusing to characterize the replay as full-text verified")
    return "published node-scoring rule checked against full text before execution; study-specific replay adaptations declared in FULLTEXT_RULE_VERIFICATION.md"


def analyze(rows, out):
    out.mkdir(parents=True, exist_ok=True)
    with (out / "score_replay_cells.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    summ = []
    for t in TARGETS:
        x = [r for r in rows if r["target"] == t]
        s = {"target": t, "graphs": len(x), "admissible_placement_exists": sum(r["admissible_exists"] for r in x),
             "affinity_bytes_violations": sum(not r["affinity_admissible"] for r in x)}
        for v in VARIANTS:
            viol = [r for r in x if not r[f"score_{v}_admissible"]]
            s[v] = {"violations": len(viol), "avoidable_violations": sum(r["admissible_exists"] for r in viol),
                    "violations_shared_with_affinity_bytes": sum(not r["affinity_admissible"] for r in viol),
                    "same_placement_as_affinity_bytes": sum(r[f"score_{v}_same_as_affinity"] for r in x),
                    "mean_utilization": sum(r[f"score_{v}_u"] for r in x) / len(x),
                    "mean_moves": sum(r[f"score_{v}_moves"] for r in x) / len(x)}
        summ.append(s)
    (out / "SUMMARY.json").write_text(json.dumps(summ, indent=2), encoding="utf-8")
    L = ["# E3 published-score replay: results", "", "Verification level of the rule implementation: " + verification_level(), "",
         "Entries per variant: violations / avoidable / shared with Affinity-Bytes.", "",
         "| load | graphs | Affinity-Bytes violations | " + " | ".join(VARIANTS) + " |", "|---|---|---|" + "---|" * len(VARIANTS)]
    for s in summ:
        cells = " | ".join(f"{s[v]['violations']} / {s[v]['avoidable_violations']} / {s[v]['violations_shared_with_affinity_bytes']}" for v in VARIANTS)
        L.append(f"| {s['target']} | {s['graphs']} | {s['affinity_bytes_violations']} | {cells} |")
    (out / "RESULTS.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["smoke", "run"])
    a = ap.parse_args()
    cost = net_cost()
    if a.command == "run":
        for req in ("RULE_CHECK.md", "FULLTEXT_RULE_VERIFICATION.md"):
            if not (HERE / req).exists():
                raise SystemExit(f"Refusing to run: {req} is missing.")
        blocks, out = R.SEED_BLOCKS, HERE / "results"
    else:
        blocks, out = SMOKE, HERE / "smoke_results"
    rows = []
    for nrep, seeds in blocks.items():
        for seed in seeds:
            rows += solve(nrep, seed, cost)
    analyze(rows, out)
    (out / "provenance.json").write_text(json.dumps({
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "protocol_sha256": hashlib.sha256((HERE / "PROTOCOL.md").read_bytes()).hexdigest(),
        "verification_level": verification_level(), "net_cost_ms": {f"{a_}>{b_}": v for (a_, b_), v in cost.items()}, "python": sys.version}, indent=2))


if __name__ == "__main__":
    main()
