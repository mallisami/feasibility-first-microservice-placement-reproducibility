#!/usr/bin/env python3
"""E1 runner: packet-level execution of the persistent-degradation state for the planners'
placements on the 150 controlled graphs (see protocol/PD_ADMISSION_PROTOCOL.md).

Derived from the retained shared-airtime boundary runner. The simulator source is unchanged;
only the shared-resource fraction (0.50) and the offered-rate construction differ.

    python3 src/run_pd_validation.py self-test
    python3 src/run_pd_validation.py run          # prepare + calibration + science + analysis (resumable)
    python3 src/run_pd_validation.py analyze
"""
from __future__ import annotations
import argparse, csv, hashlib, json, math, os, platform, random, shutil, statistics, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "config/experiment.json").read_text())
PLAN_PATH = ROOT / "config/placement_plan.json"
RESULTS = ROOT / "results"
CURRENT = RESULTS / "CURRENT_RUN.txt"
EPS = 1e-12
EXEC = {"mode": "waf", "binary": None}   # set by prepare(); "direct" skips the waf wrapper after an equivalence check


def now(): return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def run(args, timeout=300, check=True):
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if check and p.returncode:
        raise RuntimeError(f"command failed ({p.returncode}): {' '.join(map(str, args))}\n{p.stdout[-3000:]}\n{p.stderr[-3000:]}")
    return p


def docker_ok(): return shutil.which("docker") is not None and run(["docker", "version"], timeout=60, check=False).returncode == 0


def image_id(name):
    p = run(["docker", "image", "inspect", name, "--format", "{{.Id}}"], timeout=60, check=False)
    return p.stdout.strip() if p.returncode == 0 else ""


def image_commit(name):
    p = run(["docker", "run", "--rm", name, "git", "rev-parse", "HEAD"], timeout=60, check=False)
    return p.stdout.strip() if p.returncode == 0 else ""


def load_plan():
    plan = json.loads(PLAN_PATH.read_text())
    return plan


def self_test():
    assert CFG["protocol_id"] == "mape-cap-ws-ns3-pd-admission-v1.0"
    assert CFG["shared_dti_fraction"] == 0.5
    assert sha(PLAN_PATH) == CFG["placement_plan_sha256"], "placement plan differs from the hash recorded in the config"
    assert sha(ROOT / "simulator/evaluate_shared_airtime_boundary.cc") == CFG["simulator_sha256"], "simulator source changed"
    plan = load_plan()
    assert plan["state"] == "persistent-degradation" and plan["tau"] == 1.25
    assert math.isclose(plan["duty_fraction"], CFG["shared_dti_fraction"], abs_tol=1e-12)
    assert plan["pair_order"] == CFG["pair_order"]
    assert len(plan["placements"]) == 450 and plan["n_graphs"] == 150
    ids = {c["cell_id"] for c in plan["cells"]}
    assert len(ids) == len(plan["cells"]) == CFG["planned_unique_cells"]
    for c in plan["cells"]:
        fr = c["airtime_fraction"]
        i, j = plan["group_stas"][c["group"]]
        assert len(fr) == 6 and all(fr[k] == 0 for k in range(6) if k not in (i, j)) and fr[i] + fr[j] > 0
        assert math.isclose((fr[i] + fr[j]) / plan["duty_fraction"], c["planner_group_utilization"], rel_tol=1e-9)
    assert len(plan["sweep_cells"]) == CFG["planned_sweep_cells"] == 12 * len(plan["sweep_levels"])
    for c in plan["sweep_cells"]:
        assert math.isclose(sum(c["airtime_fraction"]) / plan["duty_fraction"], c["planner_group_utilization"], rel_tol=1e-9)
    for p in plan["placements"]:
        assert set(p["cells"]) <= ids
    aff = [p for p in plan["placements"] if p["method"] == "Affinity-Bytes"]
    assert sum(not p["planner_admissible"] for p in aff) == 24
    cpp = (ROOT / "simulator/evaluate_shared_airtime_boundary.cc").read_text()
    for forbidden in ["planned_feasible", "worst_conflict_utilization", "planner_admissible"]:
        assert forbidden not in cpp
    free = shutil.disk_usage(RESULTS).free / 1024 ** 3
    if free < float(CFG["min_results_free_gib"]):
        raise RuntimeError("insufficient free disk space")
    return {"passed": True, "unique_cells": len(ids), "science_cells": (len(ids) + len(plan["sweep_cells"])) * len(CFG["science_rng_runs"]), "free_gib": free}


def container_spec(evidence, rates, rng, duty, name, mode=None):
    rates_csv = ",".join(f"{x:.6f}" for x in rates)
    spec = (f"evaluate_shared_airtime_boundary --simulationTime={CFG['simulation_seconds']} "
            f"--packetSize={CFG['packet_size_bytes']} --socketType={CFG['socket_type']} "
            f"--numSTAs={CFG['num_streams']} --ratesMbpsCsv={rates_csv} --csv=true "
            f"--reportDataSnr=true --directory=/evidence/ --qdChannelFolder={CFG['qd_channel_folder']} "
            f"--phyMode={CFG['phy_mode']} --dutyFraction={duty:.12g} --trafficStartSeconds={CFG['traffic_start_seconds']} "
            f"--minimumAssociationLeadMs={CFG['minimum_association_lead_ms']} --RngRun={rng}")
    mode = mode or EXEC["mode"]
    if mode == "direct":
        inner = f"set -o pipefail; mkdir -p Traces; LD_LIBRARY_PATH=build/lib:$LD_LIBRARY_PATH {EXEC['binary']} {spec.split(' ', 1)[1]}"
    else:
        inner = f"set -o pipefail; mkdir -p Traces; ./waf --run-no-build {json.dumps(spec)}"
    cmd = ["docker", "run", "--rm", "--name", name, "-v", f"{evidence.resolve()}:/evidence", CFG["experiment_image"],
           "/bin/bash", "-lc", inner]
    return cmd, spec


def parse_packet(path, expected_rates, require_positive=True):
    if not path.exists():
        raise RuntimeError("packet_summary.csv missing")
    rows = list(csv.DictReader(path.open(newline="", encoding="utf-8")))
    active = {i: r for i, r in enumerate(expected_rates) if r > 0}
    got = {int(r["sta_index"]): r for r in rows}
    if set(got) != set(active):
        raise RuntimeError(f"active STA mismatch: expected {sorted(active)}, got {sorted(got)}")
    out = []
    for i, offered in active.items():
        row = got[i]
        configured, achieved = float(row["configured_mbps"]), float(row["achieved_mbps"])
        if not math.isclose(configured, offered, rel_tol=1e-6, abs_tol=1e-3):
            raise RuntimeError("configured rate mismatch")
        if float(row["active_seconds"]) <= 0:
            raise RuntimeError("non-positive active interval")
        if require_positive and achieved <= 0:
            raise RuntimeError("non-positive achieved throughput")
        out.append({"sta_index": i, "offered_mbps": offered, "achieved_mbps": achieved,
                    "delivered_fraction": min(1.0, float(row["delivered_fraction"])),
                    "active_seconds": float(row["active_seconds"]), "rx_bytes": int(row["rx_bytes"])})
    return out


def parse_resource(path, duty):
    rows = list(csv.DictReader(path.open(newline="", encoding="utf-8")))
    if len(rows) != 1:
        raise RuntimeError("resource_summary.csv must contain one row")
    r = rows[0]
    if not math.isclose(float(r["duty_fraction"]), duty, abs_tol=1e-9):
        raise RuntimeError("duty fraction mismatch")
    if int(r["traffic_started"]) != 1:
        raise RuntimeError("pre-traffic association/resource gate failed")
    if duty < 0.999999 and int(r["scheduled_cbap_duration_us"]) <= 0:
        raise RuntimeError("shared CBAP was not scheduled")
    if float(r["association_lead_seconds"]) + 1e-9 < float(CFG["minimum_association_lead_ms"]) / 1000.0:
        raise RuntimeError("association lead guard not met")
    return r


def prepare():
    st = self_test()
    if not docker_ok():
        raise RuntimeError("Docker is required and must be usable by this user (try: sudo usermod -aG docker $USER, then re-login).")
    base, exp = CFG["base_image"], CFG["experiment_image"]
    if not image_id(base):
        print("building base ns-3/WiGig image (30-90 min on 4 vCPU) ...", flush=True)
        run(["docker", "build", "-f", str(ROOT / "simulator/Dockerfile.ns3-wigig"), "-t", base, str(ROOT / "simulator")], timeout=4 * 3600)
    if image_commit(base) != CFG["wigig_commit"]:
        raise RuntimeError("base WiGig commit mismatch")
    run(["docker", "build", "--pull=false", "-t", exp, str(ROOT / "simulator")], timeout=3600)
    duty = float(CFG["shared_dti_fraction"])
    EXEC.update({"mode": "waf", "binary": None})
    smoke = ROOT / "operator_logs" / f"smoke-{now()}"
    smoke.mkdir(parents=True, exist_ok=True)
    rates = [float(CFG["smoke_rate_mbps_per_stream"])] * 6
    cmd, _ = container_spec(smoke, rates, int(CFG["smoke_rng_run"]), duty, "mape-pd-smoke", "waf")
    p = run(cmd, timeout=CFG["cell_timeout_seconds"], check=False)
    (smoke / "stdout.log").write_text(p.stdout + p.stderr, encoding="utf-8")
    if p.returncode:
        raise RuntimeError("packet smoke failed; see " + str(smoke))
    parse_packet(smoke / "packet_summary.csv", rates, True)
    res = parse_resource(smoke / "resource_summary.csv", duty)
    # Execution-speed option: call the built simulator binary directly instead of through the waf
    # wrapper. It is used only if the same smoke run produces a byte-identical packet summary.
    exec_note = "waf wrapper (direct binary not verified)"
    try:
        ls = run(["docker", "run", "--rm", exp, "/bin/bash", "-lc", "ls build/scratch"], timeout=120, check=False).stdout.split()
        cands = [x for x in ls if "evaluate_shared_airtime_boundary" in x and "." not in x]
        if cands:
            EXEC.update({"mode": "direct", "binary": "build/scratch/" + cands[0]})
            d = smoke / "direct"
            d.mkdir(exist_ok=True)
            cmd, _ = container_spec(d, rates, int(CFG["smoke_rng_run"]), duty, "mape-pd-smoke-direct", "direct")
            q = run(cmd, timeout=CFG["cell_timeout_seconds"], check=False)
            (d / "stdout.log").write_text(q.stdout + q.stderr, encoding="utf-8")
            same = q.returncode == 0 and (d / "packet_summary.csv").exists() and \
                (d / "packet_summary.csv").read_bytes() == (smoke / "packet_summary.csv").read_bytes()
            if same:
                exec_note = "direct binary (byte-identical smoke output to the waf wrapper)"
            else:
                EXEC.update({"mode": "waf", "binary": None})
    except Exception:
        EXEC.update({"mode": "waf", "binary": None})
    print("execution mode:", exec_note, flush=True)
    # Engineering gate: a saturated single stream under the full DTI versus the 50% shared CBAP.
    gate = ROOT / "operator_logs" / f"duty-gate-{now()}"
    gr = [0.0] * 6
    gr[int(CFG["duty_gate_sta_index"])] = float(CFG["duty_gate_offer_mbps"])
    out = {}
    for label, d in [("full", 1.0), ("limited", duty)]:
        edir = gate / label
        edir.mkdir(parents=True, exist_ok=True)
        cmd, spec = container_spec(edir, gr, int(CFG["duty_gate_rng_run"]), d, f"mape-pd-duty-gate-{label}")
        (edir / "command.txt").write_text(spec + "\n", encoding="utf-8")
        p = run(cmd, timeout=CFG["cell_timeout_seconds"], check=False)
        (edir / "stdout.log").write_text(p.stdout + p.stderr, encoding="utf-8")
        if p.returncode:
            raise RuntimeError(f"duty gate {label} run failed")
        out[label] = sum(x["achieved_mbps"] for x in parse_packet(edir / "packet_summary.csv", gr, True))
        parse_resource(edir / "resource_summary.csv", d)
    ratio = out["limited"] / out["full"]
    if not (float(CFG["duty_gate_min_throughput_ratio"]) <= ratio <= float(CFG["duty_gate_max_throughput_ratio"])):
        raise RuntimeError(f"duty gate failed: limited/full throughput ratio {ratio:.4f}")
    rec = {"prepared": True, "self_test": st, "base_image_id": image_id(base), "experiment_image_id": image_id(exp),
           "wigig_commit": CFG["wigig_commit"], "smoke_dir": str(smoke.relative_to(ROOT)), "smoke_resource": res,
           "duty_gate_dir": str(gate.relative_to(ROOT)), "duty_gate": out, "duty_gate_ratio": ratio,
           "execution_mode": dict(EXEC), "execution_mode_note": exec_note}
    dump(ROOT / "operator_logs/LAST_PREPARE.json", rec)
    return rec


def run_cell(root, phase, cid, rates, rng, duty, extra):
    croot = root / "cells" / phase / cid
    accepted = croot / "accepted.json"
    if accepted.exists():
        return json.loads(accepted.read_text())
    for attempt in range(1, int(CFG["max_cell_attempts"]) + 1):
        adir = croot / f"attempt-{attempt}"
        adir.mkdir(parents=True, exist_ok=True)
        name = ("mape-pd-" + cid + "-a" + str(attempt)).lower().replace(".", "p").replace("_", "-")[:120]
        cmd, spec = container_spec(adir, rates, rng, duty, name)
        (adir / "command.txt").write_text(spec + "\n", encoding="utf-8")
        t0 = time.time()
        try:
            p = run(cmd, timeout=int(CFG["cell_timeout_seconds"]), check=False)
        except subprocess.TimeoutExpired:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, text=True)
            p = None
        elapsed = time.time() - t0
        if p is not None:
            (adir / "stdout_stderr.log").write_text(p.stdout + p.stderr, encoding="utf-8")
        if p is None or p.returncode != 0:
            dump(adir / "failure.json", {"timeout": p is None, "returncode": None if p is None else p.returncode, "elapsed_seconds": elapsed})
            continue
        try:
            packets = parse_packet(adir / "packet_summary.csv", rates, phase != "science")
            resource = parse_resource(adir / "resource_summary.csv", duty)
            off = sum(x["offered_mbps"] for x in packets)
            ach = sum(x["achieved_mbps"] for x in packets)
            rec = {"phase": phase, "cell_id": cid, "rng_run": rng, "duty_fraction": duty, "rates_mbps": rates,
                   "aggregate_offered_mbps": off, "aggregate_achieved_mbps": ach,
                   "aggregate_delivered_fraction": min(1.0, ach / off) if off > 0 else 1.0,
                   "packets": packets, "resource": resource, "attempt": attempt, "elapsed_seconds": elapsed, **extra}
            dump(accepted, rec)
            return rec
        except Exception as e:  # acceptance is infrastructure-only; outcome magnitude is never a criterion
            dump(adir / "failure.json", {"validation_error": str(e), "elapsed_seconds": elapsed})
            continue
    raise RuntimeError(f"cell failed after the attempt limit: {phase}/{cid}")


def calibration(root, cell_fn=run_cell):
    offered = float(CFG["calibration_offer_mbps"])
    cells = []
    for sta in range(6):
        for rng in CFG["calibration_rng_runs"]:
            rates = [0.0] * 6
            rates[sta] = offered
            cells.append(cell_fn(root, "calibration", f"sta{sta}-rng{rng}", rates, int(rng), 1.0, {"sta_index": sta}))
    good, rows = [], []
    for sta in range(6):
        vals = [c["aggregate_achieved_mbps"] for c in cells if c["sta_index"] == sta]
        dfs = [c["aggregate_delivered_fraction"] for c in cells if c["sta_index"] == sta]
        g = statistics.median(vals)
        if g <= 0:
            raise RuntimeError(f"zero calibration goodput for STA {sta}")
        if statistics.median(dfs) >= 0.98:
            raise RuntimeError(f"calibration offer did not saturate STA {sta}")
        good.append(g)
        rows.append({"sta_index": sta, "median_solo_goodput_mbps": g, "values_mbps": vals})
    dump(root / "calibration_summary.json", {"solo_goodputs_mbps": good, "rows": rows})
    return good


def planned_science(plan, goodputs):
    """Offered rate of each direction = planner airtime fraction x packet-calibrated solo goodput.
    The packet-level normalized load of a group, sum(rate/goodput)/duty, then equals the planner's
    group utilization. The simulator receives rates and the 0.50 resource fraction only."""
    duty = float(CFG["shared_dti_fraction"])
    cells = []
    for c in plan["cells"] + plan["sweep_cells"]:
        rates = [a * g for a, g in zip(c["airtime_fraction"], goodputs)]
        implied = sum(r / g for r, g in zip(rates, goodputs) if r > 0) / duty
        if not math.isclose(implied, c["planner_group_utilization"], rel_tol=1e-9):
            raise RuntimeError("utilization construction mismatch")
        if max(rates) > float(CFG["max_science_rate_mbps_per_stream"]):
            raise RuntimeError("science rate exceeds guard")
        for rng in CFG["science_rng_runs"]:
            cells.append({"cell_id": c["cell_id"], "seed": c["seed"], "group": c["group"], "rng_run": int(rng),
                          "rates_mbps": rates, "planner_group_utilization": c["planner_group_utilization"],
                          "active_streams": c["active_streams"]})
    random.Random(int(CFG["run_order_seed"])).shuffle(cells)
    return cells


# ----------------------------------------------------------------------------- analysis
def analyze(root):
    import numpy as np
    from scipy.stats import binomtest, spearmanr, wilcoxon
    plan = load_plan()
    thr = float(CFG["sustained_delivery_threshold"])
    B, seed0 = int(CFG["bootstrap_resamples"]), int(CFG["bootstrap_seed"])
    recs = [json.loads(p.read_text()) for p in sorted((root / "cells/science").glob("*/accepted.json"))]
    expected = (len(plan["cells"]) + len(plan["sweep_cells"])) * len(CFG["science_rng_runs"])
    if len(recs) != expected:
        raise RuntimeError(f"expected {expected} accepted science cells, found {len(recs)}")
    # per cell: mean over RNG runs of each active direction's delivered fraction and of the aggregate
    per = {}
    for r in recs:
        d = per.setdefault(r["cell_id"], {"agg": [], "sta": {}})
        d["agg"].append(r["aggregate_delivered_fraction"])
        for pk in r["packets"]:
            d["sta"].setdefault(pk["sta_index"], []).append(pk["delivered_fraction"])
    cell = {}
    for c in plan["cells"]:
        d = per[c["cell_id"]]
        if len(d["agg"]) != len(CFG["science_rng_runs"]):
            raise RuntimeError("missing RNG replicate for " + c["cell_id"])
        cell[c["cell_id"]] = {"cell_id": c["cell_id"], "seed": c["seed"], "group": c["group"],
                              "active_streams": c["active_streams"], "U": c["planner_group_utilization"],
                              "D": float(np.mean(d["agg"])), "sta": {k: float(np.mean(v)) for k, v in d["sta"].items()}}
    with (root / "cell_results.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["cell_id", "seed", "group", "active_streams", "U", "D"])
        w.writeheader()
        for c in cell.values():
            w.writerow({k: c[k] for k in w.fieldnames})
    # placement level: fraction of the placement's cross-rack bits delivered in the persistent-degradation state
    gs = plan["group_stas"]
    prow = []
    for p in plan["placements"]:
        tot = sum(p["cross_rack_bits"])
        dl = 0.0
        for cid in p["cells"]:
            c = cell[cid]
            for sta in gs[c["group"]]:
                if p["cross_rack_bits"][sta] > 0:
                    dl += p["cross_rack_bits"][sta] * c["sta"][sta]
        prow.append({"seed": p["seed"], "replicas": p["replicas"], "method": p["method"],
                     "planner_admissible": p["planner_admissible"], "pd_worst_utilization": p["pd_worst_utilization"],
                     "delivered_fraction": dl / tot if tot > 0 else 1.0, "cross_rack_bits": tot})
    with (root / "placement_results.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(prow[0]))
        w.writeheader()
        w.writerows(prow)
    seeds = sorted({r["seed"] for r in prow})
    D = {m: np.array([next(r["delivered_fraction"] for r in prow if r["seed"] == s and r["method"] == m) for s in seeds]) for m in plan["methods"]}
    AFF, ADM, MC = plan["methods"]

    def contrast(a, b, k):
        d = D[a] - D[b]
        rng = np.random.default_rng(seed0 + k)
        bm = d[rng.integers(0, len(d), (B, len(d)))].mean(1)
        nz = d[d != 0]
        return {"contrast": f"{a} - {b}", "n": int(len(d)), "mean_a": float(D[a].mean()), "mean_b": float(D[b].mean()),
                "mean_difference": float(d.mean()), "ci95": [float(np.percentile(bm, 2.5)), float(np.percentile(bm, 97.5))],
                "n_positive": int((d > 0).sum()), "n_negative": int((d < 0).sum()), "n_zero": int((d == 0).sum()),
                "wilcoxon_one_sided_greater_p": float(wilcoxon(nz, alternative="greater").pvalue) if len(nz) else 1.0,
                "wilcoxon_two_sided_p": float(wilcoxon(nz).pvalue) if len(nz) else 1.0}
    h1 = contrast(ADM, AFF, 1)
    h1["supported"] = bool(h1["ci95"][0] > 0 and h1["wilcoxon_one_sided_greater_p"] < 0.05)
    ranking = contrast(MC, ADM, 2)
    mape_aff = contrast(MC, AFF, 3)
    # paired sustained delivery (descriptive exact McNemar)
    sa, sb = D[ADM] >= thr, D[AFF] >= thr
    b01, b10 = int((sa & ~sb).sum()), int((~sa & sb).sum())
    mcn = {"admission_only_sustained": b01, "affinity_only_sustained": b10,
           "exact_two_sided_p": float(binomtest(b01, b01 + b10, 0.5).pvalue) if b01 + b10 else 1.0}
    sustained = {m: int((D[m] >= thr).sum()) for m in plan["methods"]}
    # H2: does the planner's group utilization boundary predict packet-level sustained delivery?
    # boundary sweep (12 two-direction shapes x 5 loads), reported separately from the placement cells
    sw = {}
    for c in plan["sweep_cells"]:
        sw.setdefault(c["planner_group_utilization"], []).append(float(np.mean(per[c["cell_id"]]["agg"])))
    sweep = [{"U": u, "shapes": len(v), "mean_D": float(np.mean(v)), "min_D": float(np.min(v)), "below_threshold": int((np.array(v) < thr).sum())}
             for u, v in sorted(sw.items())]
    with (root / "sweep_results.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["cell_id", "shape_id", "U", "dominant_direction_share", "D"])
        for c in plan["sweep_cells"]:
            w.writerow([c["cell_id"], c["shape_id"], c["planner_group_utilization"], c["dominant_direction_share"], float(np.mean(per[c["cell_id"]]["agg"]))])
    U = np.array([c["U"] for c in cell.values()])
    Dc = np.array([c["D"] for c in cell.values()])
    pred, obs = U <= 1 + EPS, Dc >= thr
    conf = {"predicted_ok_and_sustained": int((pred & obs).sum()), "predicted_ok_not_sustained": int((pred & ~obs).sum()),
            "predicted_violation_but_sustained": int((~pred & obs).sum()), "predicted_violation_not_sustained": int((~pred & ~obs).sum())}
    U2 = np.where(np.abs(U - 1.0) < 1e-9, 1.0, U)   # placements exactly at the budget count as within it
    bins = []
    for lo, hi in [(0, 0.5), (0.5, 0.8), (0.8, 0.9), (0.9, 1.0), (1.0, 1.1), (1.1, 1.25), (1.25, 9)]:
        msk = (U2 > lo) & (U2 <= hi)
        bins.append({"U_range": f"({lo}, {hi}]", "cells": int(msk.sum()), "mean_D": float(Dc[msk].mean()) if msk.any() else None,
                     "min_D": float(Dc[msk].min()) if msk.any() else None, "below_threshold": int((Dc[msk] < thr).sum())})
    over = U > 1 + EPS
    padm = np.array([r["planner_admissible"] for r in prow])
    pD = np.array([r["delivered_fraction"] for r in prow])
    summary = {
        "protocol_id": CFG["protocol_id"], "n_graphs": len(seeds), "unique_cells": len(cell), "science_cells": len(recs),
        "mean_delivered_fraction_by_method": {m: float(D[m].mean()) for m in plan["methods"]},
        "graphs_with_sustained_delivery_by_method": sustained,
        "H1_admission_contrast_all_graphs": h1, "H1_sustained_delivery_mcnemar": mcn,
        "secondary_ranking_contrast": ranking, "secondary_mape_vs_affinity": mape_aff,
        "H2_group_cells_confusion": conf, "H2_group_cells_by_utilization": bins,
        "H2_spearman_U_vs_D_all_cells": float(spearmanr(U, Dc).statistic),
        "H2_spearman_U_vs_D_over_budget_cells": float(spearmanr(U[over], Dc[over]).statistic) if over.sum() > 2 else None,
        "placements_planner_admissible": {"n": int(padm.sum()), "sustained": int((pD[padm] >= thr).sum()), "mean_D": float(pD[padm].mean())},
        "placements_planner_inadmissible": {"n": int((~padm).sum()), "sustained": int((pD[~padm] >= thr).sum()),
                                            "mean_D": float(pD[~padm].mean()) if (~padm).any() else None},
        "boundary_sweep_two_direction_shapes": sweep,
        "sustained_delivery_threshold": thr,
        "interpretation_rule": "H1 is supported only if the bootstrap interval lies above zero and the one-sided Wilcoxon p < 0.05. "
                               "A null or opposite result is reported as not supporting packet-level consequences of the declared budget.",
    }
    dump(root / "SUMMARY.json", summary)
    L = ["# Final report: packet-level execution of the persistent-degradation state", "", f"Protocol `{CFG['protocol_id']}`; {len(seeds)} unselected graphs; {len(cell)} unique group cells x {len(CFG['science_rng_runs'])} RNG runs.", "",
         "## H1 (primary): admission contrast over all graphs",
         f"Mean delivered fraction: Affinity-Bytes {D[AFF].mean():.4f}, Affinity-Bytes+Admission {D[ADM].mean():.4f}, MAPE-CAP-WS {D[MC].mean():.4f}.",
         f"Admission minus affinity: **{h1['mean_difference']:+.5f}** (95% graph-resampling interval [{h1['ci95'][0]:+.5f}, {h1['ci95'][1]:+.5f}]); higher on {h1['n_positive']}, lower on {h1['n_negative']}, tied on {h1['n_zero']} graphs; one-sided Wilcoxon p = {h1['wilcoxon_one_sided_greater_p']:.3g}.",
         f"H1 supported under the stated rule: **{h1['supported']}**.",
         f"Graphs with delivered fraction >= {thr}: " + ", ".join(f"{m} {sustained[m]}/{len(seeds)}" for m in plan["methods"]) + f"; discordant pairs {b01} vs {b10}.", "",
         "## H2: planner group utilization versus packet-level delivery (unique group cells)",
         f"Confusion: {conf}.", "", "| U range | cells | mean D | min D | D below threshold |", "|---|---|---|---|---|"]
    for b in bins:
        L.append(f"| {b['U_range']} | {b['cells']} | {b['mean_D'] if b['mean_D'] is None else round(b['mean_D'], 4)} | {b['min_D'] if b['min_D'] is None else round(b['min_D'], 4)} | {b['below_threshold']} |")
    L += ["", "## Boundary sweep: 12 two-direction shapes at the 50% share", "", "| U | shapes | mean D | min D | D below threshold |", "|---|---|---|---|---|"]
    for b in sweep:
        L.append(f"| {b['U']} | {b['shapes']} | {b['mean_D']:.4f} | {b['min_D']:.4f} | {b['below_threshold']} |")
    L += ["", "## Secondary: ranking after admission",
          f"MAPE-CAP-WS minus Affinity-Bytes+Admission: {ranking['mean_difference']:+.5f} (interval [{ranking['ci95'][0]:+.5f}, {ranking['ci95'][1]:+.5f}]).", "",
          "## Evidence boundary",
          "Packet-level construct evidence in a pinned IEEE 802.11ad/WiGig simulator. Each rack-pair group is simulated as its own shared resource, as the persistent-degradation state declares; interference between groups, physical RF behavior and the appropriateness of the 30-s budget for a real fabric are not tested.", ""]
    (root / "FINAL_REPORT.md").write_text("\n".join(L), encoding="utf-8")
    return summary


def manifest(root):
    lines = [f"{sha(p)}  {p.relative_to(root).as_posix()}" for p in sorted(root.rglob("*")) if p.is_file() and p.name != "SHA256SUMS.txt"]
    (root / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def provenance():
    return {"protocol_id": CFG["protocol_id"], "platform": platform.platform(), "python": sys.version,
            "config_sha256": sha(ROOT / "config/experiment.json"), "plan_sha256": sha(PLAN_PATH),
            "simulator_sha256": sha(ROOT / "simulator/evaluate_shared_airtime_boundary.cc"),
            "protocol_sha256": sha(ROOT / "protocol/PD_ADMISSION_PROTOCOL.md"), "runner_sha256": sha(Path(__file__)),
            "wigig_commit": CFG["wigig_commit"], "started_utc": now()}


def execute(prepare_fn=prepare, cell_fn=run_cell, workers=None):
    prepare_fn()
    if CURRENT.exists():
        runroot = Path(CURRENT.read_text().strip())
    else:
        runroot = RESULTS / f"run-{now()}"
        runroot.mkdir(parents=True)
        CURRENT.write_text(str(runroot.resolve()) + "\n", encoding="utf-8")
        dump(runroot / "provenance.json", provenance())
    plan = load_plan()
    good = calibration(runroot, cell_fn)
    cells = planned_science(plan, good)
    dump(runroot / "science_plan.json", {"solo_goodputs_mbps": good, "n_cells": len(cells)})
    duty = float(CFG["shared_dti_fraction"])
    done = [0]
    t0 = time.time()

    def one(c):
        cid = f"{c['cell_id']}-rng{c['rng_run']}"
        extra = {k: c[k] for k in ["seed", "group", "planner_group_utilization", "active_streams"]}
        extra["cell_id"] = c["cell_id"]
        rec = cell_fn(runroot, "science", cid, c["rates_mbps"], c["rng_run"], duty, extra)
        done[0] += 1
        if done[0] % 25 == 0 or done[0] == len(cells):
            el = time.time() - t0
            print(f"[{done[0]}/{len(cells)}] elapsed {el / 60:.1f} min, est. remaining {el / done[0] * (len(cells) - done[0]) / 60:.1f} min", flush=True)
        return rec

    n = int(workers or CFG["parallel_workers"])
    with ThreadPoolExecutor(max_workers=n) as ex:
        list(ex.map(one, cells))
    s = analyze(runroot)
    manifest(runroot)
    print(f"COMPLETE: {runroot}")
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["self-test", "prepare", "run", "analyze"])
    ap.add_argument("--run-root", type=Path)
    ap.add_argument("--workers", type=int)
    a = ap.parse_args()
    if a.command == "self-test":
        print(json.dumps(self_test(), indent=2))
    elif a.command == "prepare":
        print(json.dumps(prepare(), indent=2))
    elif a.command == "run":
        execute(workers=a.workers)
    else:
        rr = a.run_root or (Path(CURRENT.read_text().strip()) if CURRENT.exists() else None)
        if rr is None:
            raise SystemExit("no run root available")
        print(json.dumps(analyze(rr), indent=2))
        manifest(rr)


if __name__ == "__main__":
    main()
