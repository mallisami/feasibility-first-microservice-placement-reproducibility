#!/usr/bin/env python3
"""N5 runner: live application visibility when the executed wireless state binds.

Implements PROTOCOL_FROZEN.md. The frozen AFF-K8S harness (live_confirmatory.py) is imported
unchanged; only in-memory module globals for cluster name, context and image tag are redirected
to the dedicated `rev-n5` cluster. Usage (inside the VM venv):

    python n5_runner.py setup      # create cluster, build/load image, deploy emulator
    python n5_runner.py screen     # planning-only enrollment -> screening.csv, enrolled.json
    python n5_runner.py smoke      # one 10-s cell per method on the first S1 graph (not analysed)
    python n5_runner.py run        # all enrolled cells (resumable)
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = Path.home() / "revision_2026-09-26" / "pkg"          # frozen package subset uploaded to the VM
EXP = PKG / "EXPERIMENTS" / "k8s_affinity_wireless_confirmatory"
sys.path.insert(0, str(EXP / "src"))

import live_confirmatory as lc  # noqa: E402  (frozen harness)

# ---- redirect harness to the dedicated revision cluster (in memory only) ----
CLUSTER = "rev-n5"
lc.CLUSTER = CLUSTER
lc.CONTEXT = f"kind-{CLUSTER}"
lc.IMAGE = "mape-cap-confirm-bench:rev-n5"
lc.CFG = {**lc.CFG, "cluster_name": CLUSTER, "benchmark_image": lc.IMAGE}

OUT = HERE / "results"
RISK = lc.RISK
TIMEOUT_MS = 1000.0 * float(lc.CFG["benchmark_http_timeout_seconds"])
MEASURE_S = 40
STRATA = {"S1": {"tau": 1.25, "n": 20, "methods": ["Affinity-Bytes", "Affinity-Bytes+Admission", "MAPE-CAP-WS"]},
          "S2": {"tau": 1.00, "n": 10, "methods": ["Current", "Affinity-Bytes", "Affinity-Bytes+Admission", "MAPE-CAP-WS"]}}
SEED0, SEED_MAX = 55001, 57000
ORDER_SEED = 20260926


def dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, default=lc._json_default), encoding="utf-8")
    tmp.replace(path)


# ------------------------------------------------------------------ planning
def build(seed: int, info, tau: float):
    """AFF-C-convention calibration: Current's worst planning-state utilization = tau."""
    g = lc.generate_problem(replica_count=6, rack_count=3, nodes_per_rack=1, scenario_count=3,
                            seed=seed, decision_window_seconds=60.0)
    alias = {"rack-0": "rack-a", "rack-1": "rack-b", "rack-2": "rack-c"}
    gnodes = sorted(g.nodes, key=lambda n: n.rack_id)
    node_map = {n.node_id: info["rack_to_worker"][alias[n.rack_id]] for n in gnodes}
    nodes = tuple(lc.NodeSpec(node_map[n.node_id], alias[n.rack_id],
                              info["allocatable"][node_map[n.node_id]]["cpu"] * 0.95,
                              info["allocatable"][node_map[n.node_id]]["memory_mb"] * 0.95) for n in gnodes)
    allowed = tuple(n.node_id for n in nodes)
    reps = tuple(replace(r, allowed_nodes=allowed) for r in g.replicas)
    cur = {rid: node_map[nid] for rid, nid in g.current_placement.items()}
    reloc = {r.replica_id: lc.RelocationCost(r.replica_id, 4062.0, 4.062, 690.0, provenance="frozen Kind relocation pilot")
             for r in reps}
    base = replace(g, nodes=nodes, replicas=reps, current_placement=cur, scenarios=lc.load_frozen_scenarios(),
                   relocation_costs=reloc, metadata={**g.metadata, "n5_seed": seed, "live_confirmation_seed": seed})
    u0 = lc.max_conflict_util(base, base.current_placement)
    if not math.isfinite(u0) or u0 <= 0:
        return None, {"reason": "zero/invalid Current utilization"}
    s = u0 / tau
    scen = tuple(replace(sc, links={k: replace(l, goodput_bps=l.goodput_bps * s) for k, l in sc.links.items()})
                 for sc in base.scenarios)
    p = replace(base, scenarios=scen, metadata={**base.metadata, "tau": tau, "goodput_scale": s})
    return p, {"u0": u0, "goodput_scale": s, "current_worst_util": lc.max_conflict_util(p, p.current_placement)}


def affinity_admission(p):
    rank = {n.node_id: i for i, n in enumerate(sorted(p.nodes, key=lambda x: x.node_id))}
    order = tuple(sorted(r.replica_id for r in p.replicas))
    best = None
    for pl in _enum(p):
        if not lc.evaluate_placement(p, pl, RISK).feasible:
            continue
        key = (lc.cross_rack_bits(p, pl), lc.move_count(p, pl), tuple(rank[pl[r]] for r in order))
        if best is None or key < best[0]:
            best = (key, dict(pl))
    return None if best is None else best[1]


def _enum(p):
    from affinity_exact import enumerate_cluster_feasible
    return enumerate_cluster_feasible(p)


def plans_for(p):
    out = {"Current": dict(p.current_placement)}
    out["Affinity-Bytes"], _ = lc.solve_affinity_bytes(p)
    out["Affinity-Bytes+Admission"] = affinity_admission(p)
    try:
        out["MAPE-CAP-WS"], _ = lc.solve_exact(p, RISK, time_limit_seconds=60.0, require_optimal=True)
    except lc.ExactSolveError:
        out["MAPE-CAP-WS"] = None
    return out


def feasible(p, pl) -> bool:
    return pl is not None and bool(lc.evaluate_placement(p, pl, RISK).feasible)


def executed_state(p, aff_pl) -> str:
    utils = [(lc.scenario_conflict_util(p, aff_pl, s.scenario_id), -i, s.scenario_id) for i, s in enumerate(p.scenarios)]
    return max(utils)[2]


def rates_ok(p, sid) -> bool:
    sc = lc.scenario_by_id(p, sid)
    mb = [l.goodput_bps / 1e6 for l in sc.links.values() if l.available]
    return min(mb) >= float(lc.CFG["emulator_min_mbit"]) and max(mb) <= float(lc.CFG["emulator_max_mbit"])


def cluster():
    return lc.cluster_info()


def cmd_screen():
    info = cluster()
    rows, enrolled = [], {k: [] for k in STRATA}
    for seed in range(SEED0, SEED_MAX + 1):
        if all(len(enrolled[k]) >= STRATA[k]["n"] for k in STRATA):
            break
        for k, st in STRATA.items():
            if len(enrolled[k]) >= st["n"]:
                continue
            p, cal = build(seed, info, st["tau"])
            rec = {"seed": seed, "stratum": k, "tau": st["tau"], **cal}
            if p is None:
                rows.append({**rec, "enrolled": False}); continue
            pl = plans_for(p)
            f = {m: feasible(p, x) for m, x in pl.items()}
            rec.update({f"feasible_{m}": v for m, v in f.items()})
            ok = (not f["Affinity-Bytes"]) and f["MAPE-CAP-WS"]
            if k == "S2":
                ok = ok and f["Current"]
            ex = executed_state(p, pl["Affinity-Bytes"]) if ok else None
            if ok and not rates_ok(p, ex):
                ok = False; rec["excluded"] = "emulator rate guard"
            rec.update({"executed_state": ex, "enrolled": ok})
            if ok:
                rec.update({f"exec_util_{m}": lc.scenario_conflict_util(p, x, ex) for m, x in pl.items() if x is not None})
                enrolled[k].append({"seed": seed, "tau": st["tau"], "executed_state": ex, "plans": pl})
            rows.append(rec)
    OUT.mkdir(parents=True, exist_ok=True)
    keys = sorted({k for r in rows for k in r})
    with open(OUT / "screening.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys); w.writeheader(); w.writerows(rows)
    dump(OUT / "enrolled.json", {"cluster": info, "enrolled": enrolled})
    print({k: len(v) for k, v in enrolled.items()}, "screened seeds up to", rows[-1]["seed"] if rows else None)


# ------------------------------------------------------------------ execution
def nearest_rank(v, q):
    return lc.nearest_rank(v, q)


def endpoints(p, run):
    lat, attempted, success, errors = [], 0, 0, 0
    dur = float(run["stop_epoch"]) - float(run["start_epoch"])
    scheduled = sum(int(math.ceil(max(0.0, dur * float(c["rate_rps"]) - 1e-12)))
                    for cfgs in run["flow_configs"].values() for c in cfgs)
    for m in run["pod_metrics"].values():
        for row in m.get("flows", {}).values():
            attempted += int(row.get("attempted", 0)); success += int(row.get("success", 0)); errors += int(row.get("errors", 0))
            lat.extend(float(x) for x in row.get("latencies_ms", []))
    missing = max(0, scheduled - attempted)
    sched_lat = lat + [TIMEOUT_MS] * missing
    med = run.get("wireless_medium_metrics", {}).get("metrics", {})
    qw = med.get("queue_wait_ms", []) or []
    return {"scheduled": scheduled, "attempted": attempted, "success": success, "errors": errors,
            "scheduled_completion": success / scheduled if scheduled else float("nan"),
            "sched_p50_ms": nearest_rank(sched_lat, 0.50), "sched_p95_ms": nearest_rank(sched_lat, 0.95),
            "sched_p99_ms": nearest_rank(sched_lat, 0.99), "attempted_p95_ms": nearest_rank(lat, 0.95),
            "medium_requests": int(med.get("requests", 0)),
            "medium_mean_queue_wait_ms": (sum(qw) / len(qw)) if qw else 0.0}


def run_cell(stratum, g, method, p, info, *, smoke=False):
    root = OUT / ("smoke" if smoke else "cells") / stratum / f"seed-{g['seed']}" / method
    for prev in sorted(root.glob("attempt-*/result.json")):
        return json.loads(prev.read_text(encoding="utf-8"))
    n = len(list(root.glob("attempt-*"))) + 1
    ar = root / f"attempt-{n:02d}"
    ar.mkdir(parents=True, exist_ok=False)
    pl = g["plans"][method]
    sc = lc.scenario_by_id(p, g["executed_state"])
    rid = f"n5:{stratum}:seed{g['seed']}:{method}:attempt{n}"
    load_before = Path("/proc/loadavg").read_text().split()[0]
    try:
        reloc = lc.apply_placement(p, pl, rid)
        time.sleep(float(lc.CFG["settle_seconds"]))
        run = lc.configure_and_run_for_scenario(p, pl, rid, 10 if smoke else MEASURE_S, sc)
        ep = endpoints(p, run)
        health = lc.deployment_health(p)
        cross = any(pl[f.source_replica] != pl[f.destination_replica] for f in p.flows)
        if ep["attempted"] <= 0:
            raise RuntimeError("zero attempts")
        if cross and ep["medium_requests"] <= 0:
            raise RuntimeError("medium saw no traffic despite cross-rack flows")
        if not health["healthy"]:
            raise RuntimeError(f"unhealthy after traffic: {health}")
        res = {"run_id": rid, "stratum": stratum, "seed": g["seed"], "tau": g["tau"], "method": method,
               "executed_state": g["executed_state"], "placement": pl, "completed_utc": lc.utc_now(),
               "planned_exec_util": lc.scenario_conflict_util(p, pl, g["executed_state"]),
               "planned_feasible": feasible(p, pl), "moves": lc.move_count(p, pl),
               "cross_rack_bits": lc.cross_rack_bits(p, pl), "endpoints": ep, "relocation": reloc,
               "traffic": run, "accepted_infrastructure": True, "smoke": smoke,
               "loadavg_1m_before": float(load_before),
               "loadavg_1m_after": float(Path("/proc/loadavg").read_text().split()[0])}
        dump(ar / "result.json", res)
        return res
    except Exception as exc:
        dump(ar / "failure.json", {"run_id": rid, "error": f"{type(exc).__name__}: {exc}", "utc": lc.utc_now()})
        raise
    finally:
        try:
            _, _, pods = lc.pod_service_ips(p)
            for r in sorted(pods):
                lc.control_pod(pods[r], "stop", {})
        except Exception:
            pass


def with_retries(*a, **k):
    last = None
    for i in range(2):
        try:
            return run_cell(*a, **k)
        except Exception as exc:
            last = exc
            print(f"    attempt {i + 1} failed: {exc}", flush=True)
            time.sleep(5)
    raise RuntimeError(f"cell failed after retries: {last}")


def load_enrolled():
    return json.loads((OUT / "enrolled.json").read_text(encoding="utf-8"))


def cmd_run(smoke=False):
    en = load_enrolled()
    info = en["cluster"]
    todo = [("S1", en["enrolled"]["S1"][0])] if smoke else [(k, g) for k in STRATA for g in en["enrolled"][k]]
    for k, g in todo:
        p, _ = build(g["seed"], info, g["tau"])
        methods = list(STRATA[k]["methods"])
        random.Random(ORDER_SEED + g["seed"]).shuffle(methods)
        for m in methods:
            t0 = time.time()
            try:
                r = with_retries(k, g, m, p, info, smoke=smoke)
            except Exception as exc:  # keep going; the wrapper re-invokes `run` for missing cells
                print(f"{k} seed {g['seed']} {m}: CELL FAILED ({exc}); continuing", flush=True)
                continue
            e = r["endpoints"]
            print(f"{k} seed {g['seed']} {m:26s} p95={e['sched_p95_ms']:.0f}ms "
                  f"compl={e['scheduled_completion']:.3f} execU={r['planned_exec_util']:.2f} ({time.time() - t0:.0f}s)", flush=True)
    if smoke:
        dump(OUT / "smoke" / "SMOKE_PASSED.json", {"utc": lc.utc_now()})


def cmd_setup():
    pf = lc.preflight()
    info = lc.ensure_cluster()
    img = lc.ensure_benchmark_image()
    lc.ensure_namespace()
    med = lc.ensure_wireless_medium(info)
    files = [HERE / "PROTOCOL_FROZEN.md", Path(__file__)] + sorted((EXP / "src").glob("*.py")) + \
        sorted((EXP / "benchmark").glob("*")) + sorted((PKG / "implementation" / "code" / "mape_cap_bplus").glob("*.py")) + \
        [lc.CANONICAL_TRACE_FILE]
    dump(OUT / "frozen" / "preexecution_manifest.json", {
        "utc": lc.utc_now(), "preflight": pf, "cluster": info, "image": img, "medium": med,
        "files_sha256": {str(f.relative_to(f.anchor)): hashlib.sha256(f.read_bytes()).hexdigest() for f in files if f.is_file()}})
    print("setup complete", info["rack_to_worker"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["setup", "screen", "smoke", "run"])
    a = ap.parse_args()
    {"setup": cmd_setup, "screen": cmd_screen, "smoke": lambda: cmd_run(smoke=True), "run": cmd_run}[a.command]()


if __name__ == "__main__":
    main()
