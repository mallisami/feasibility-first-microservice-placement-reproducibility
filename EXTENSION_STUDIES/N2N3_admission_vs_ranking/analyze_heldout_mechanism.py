#!/usr/bin/env python3
"""Secondary (protocol-listed) N3 breakdown: which withheld state drives held-out inadmissibility,
and does it follow from availability or from airtime? Reads N2/N3 outputs only."""
from pathlib import Path
import json
import pandas as pd

HERE = Path(__file__).resolve().parent
df = pd.read_csv(HERE / "cell_results.csv")
states = ["nominal-los", "asymmetric-los", "outage-with-fallback", "recovery", "mixed-regime"]
methods = ["Affinity-Bytes", "Affinity-Bytes+Admission", "MAPE-CAP-WS Risk-off", "MAPE-CAP-WS"]

rows = []
for t in (0.5, 1.0, 1.25, 1.5):
    for m in methods:
        s = df[(df.target == t) & (df.method == m) & (~df.no_admissible_placement.astype(bool))]
        rec = {"target": t, "method": m, "n": len(s), "all_heldout": int(s.heldout_admissible.sum())}
        for st in states:
            rec[st] = int(s[f"ho_ok_{st}"].astype(bool).sum())
        rows.append(rec)
out = pd.DataFrame(rows)
out.to_csv(HERE / "heldout_mechanism.csv", index=False)
print(out.to_string(index=False))

# Does the placement route any flow over the B-C pair (down in outage-with-fallback)?
# Racks: node ids map one node per rack; use placements to count graphs whose placement
# puts communicating replicas on rack-b and rack-c simultaneously is not recoverable without
# flows, so report outage-state admissibility jointly with airtime-only held-out utilisation.
t = df[(df.target == 1.25) & df.method.isin(["Affinity-Bytes+Admission", "MAPE-CAP-WS"])]
piv = t.pivot_table(index="seed", columns="method", values="ho_ok_outage-with-fallback", aggfunc="first")
both = {
    "outage_ok_mape_only": int((piv["MAPE-CAP-WS"].astype(bool) & ~piv["Affinity-Bytes+Admission"].astype(bool)).sum()),
    "outage_ok_affadm_only": int((~piv["MAPE-CAP-WS"].astype(bool) & piv["Affinity-Bytes+Admission"].astype(bool)).sum()),
}
ex = df[(df.target == 1.25) & (df.method != "Current")]
ex = ex[~ex.no_admissible_placement.astype(bool)]
nonoutage = [s for s in states if s != "outage-with-fallback"]
ex = ex.assign(non_outage_ok=ex[[f"ho_ok_{s}" for s in nonoutage]].astype(bool).all(axis=1))
both["heldout_admissible_excluding_outage_state"] = ex.groupby("method").non_outage_ok.sum().astype(int).to_dict()
print(json.dumps(both, indent=2))
(HERE / "heldout_mechanism.json").write_text(json.dumps(both, indent=2), encoding="utf-8")
