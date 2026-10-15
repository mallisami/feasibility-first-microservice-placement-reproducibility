#!/usr/bin/env python3
"""Offline pipeline test with a synthetic cell function (no Docker, no ns-3).
It checks plan handling, rate construction, resumability and analysis plumbing only.
The synthetic delivery model is NOT evidence and its output must never be reported."""
import json, shutil, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import run_pd_validation as M

def fake_cell(root, phase, cid, rates, rng, duty, extra):
    acc = root / "cells" / phase / cid / "accepted.json"
    if acc.exists():
        return json.loads(acc.read_text())
    solo = 2160.0
    if phase == "calibration":
        pk = [{"sta_index": i, "offered_mbps": r, "achieved_mbps": solo, "delivered_fraction": solo / r, "active_seconds": 3.0, "rx_bytes": 1} for i, r in enumerate(rates) if r > 0]
    else:
        load = sum(r / solo for r in rates) / duty
        frac = min(1.0, 1.0 / load)
        pk = [{"sta_index": i, "offered_mbps": r, "achieved_mbps": r * frac, "delivered_fraction": frac, "active_seconds": 3.0, "rx_bytes": 1} for i, r in enumerate(rates) if r > 0]
    off = sum(p["offered_mbps"] for p in pk); ach = sum(p["achieved_mbps"] for p in pk)
    rec = {"phase": phase, "cell_id": cid, "rng_run": rng, "rates_mbps": rates, "aggregate_offered_mbps": off,
           "aggregate_achieved_mbps": ach, "aggregate_delivered_fraction": min(1.0, ach / off), "packets": pk, **extra}
    M.dump(acc, rec); return rec

tmp = Path(tempfile.mkdtemp())
M.RESULTS = tmp; M.CURRENT = tmp / "CURRENT_RUN.txt"
print(M.self_test.__name__, "skipped disk/docker parts in offline test")
s = M.execute(prepare_fn=lambda: None, cell_fn=fake_cell, workers=4)
assert s["science_cells"] == 2061 and s["unique_cells"] == 627 and s["n_graphs"] == 150
assert s["H2_group_cells_confusion"]["predicted_violation_but_sustained"] + s["H2_group_cells_confusion"]["predicted_violation_not_sustained"] == 24
assert s["H1_admission_contrast_all_graphs"]["n_zero"] >= 100
print(json.dumps({k: s[k] for k in ["mean_delivered_fraction_by_method", "graphs_with_sustained_delivery_by_method", "H2_group_cells_confusion"]}, indent=1))
print((Path(M.CURRENT.read_text().strip()) / "FINAL_REPORT.md").read_text()[:1500])
shutil.rmtree(tmp); print("PIPELINE TEST PASSED (synthetic data; not evidence)")
