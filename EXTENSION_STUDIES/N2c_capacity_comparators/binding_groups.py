"""Which conflict group does each Affinity-Bytes violation overload? (independent check of the audit's claim 3.1)"""
import sys, itertools, collections
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "N2N3_admission_vs_ranking"))  # package layout; was an absolute path when executed
import run_n2n3 as R  # module-level code only loads the state library

def group_util(p, pl, factor):
    tiny = R.scale(p, R.TINY)
    ev = R.evaluate_placement(tiny, pl, R.RISK)
    out = {}
    for s in tiny.scenarios:
        amap = ev.scenario_airtime_by_group.get(s.scenario_id, {})
        for g, b in s.conflict_budgets_seconds.items():
            if b > 0:
                out[(s.scenario_id, g)] = amap.get(g, 0.0) / R.TINY * factor / b
    return out, ev

def affinity_pick(p):
    reps = [r.replica_id for r in p.replicas]
    allowed = [p.allowed_nodes_for(r) for r in reps]
    cands = []
    for assign in itertools.product(*allowed):
        pl = dict(zip(reps, assign))
        if R.cluster_ok(p, pl):
            cands.append((R.cross(p, pl, "bytes"), R.moves(p, pl), tuple(sorted(pl.items())), pl))
    cands.sort(key=lambda c: (c[0], c[1], c[2]))
    tiny = R.scale(p, R.TINY)
    for c in cands:  # AFF-C screen: first placement without non-airtime planning violations
        if R.evaluate_placement(tiny, c[3], R.RISK).feasible:
            return c[3]

viol = {t: collections.Counter() for t in (1.0, 1.25, 1.5)}
graphs_viol = {t: 0 for t in viol}
cd_max = {t: 0.0 for t in viol}
for nrep, seeds in R.SEED_BLOCKS.items():
    for seed in seeds:
        p = R.base_problem(nrep, seed)
        cur = dict(p.current_placement)
        cu, _ = group_util(p, cur, 1.0)
        u0 = max(cu.values())
        aff = affinity_pick(p)
        for t in viol:
            gu, _ = group_util(p, aff, t / u0)
            bad = [k for k, v in gu.items() if v > 1.0 + R.EPS]
            if bad:
                graphs_viol[t] += 1
                for k in bad:
                    viol[t][k] += 1
            cd_max[t] = max(cd_max[t], max(v for k, v in gu.items() if k[0] == "conflict-dense"))
for t in viol:
    print(f"tau={t}: graphs with affinity violation={graphs_viol[t]}; violated (state, group) counts={dict(viol[t])}; max conflict-dense util={cd_max[t]:.3f}")
print("groups per planning state:", {s.scenario_id: sorted(s.conflict_budgets_seconds) for s in R.PLAN})
