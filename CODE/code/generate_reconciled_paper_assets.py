#!/usr/bin/env python3
"""Generate layered-evidence LaTeX tables from canonical publication sources."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path


SYSTEM = Path(__file__).resolve().parents[1]
PACKAGED = SYSTEM.name == "implementation" and (SYSTEM.parent / "RESULTS").exists()
ROOT = SYSTEM.parent
if PACKAGED:
    SOURCE = ROOT / "RESULTS" / "supporting" / "canonical"
    OUT = ROOT / "PAPER" / "tables" / "supporting"
else:
    SOURCE = SYSTEM / "results" / "publication" / "reconciled-20260812"
    OUT = ROOT / "01_PAPER" / "BPLUS_MANUSCRIPT" / "generated" / "reconciled"


def rows(name: str) -> list[dict[str, str]]:
    with (SOURCE / name).open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def mean(values: list[float]) -> float:
    return sum(values) / len(values)


def tex_escape(value: str) -> str:
    return value.replace("_", r"\_").replace("%", r"\%")


ROW_END = r" \\"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((SOURCE / "publication-source-manifest.json").read_text(encoding="utf-8"))

    inventory = r"""% Layered evidence inventory
\begin{table}[htbp]
\centering
\caption{Layered evidence architecture. Counts are not pooled because their independent units differ.}
\label{tab:layered-evidence}
\small
\begin{tabularx}{\linewidth}{lXrX}
\toprule
Layer & Evidence family & Recorded count & Role \\
\midrule
Primary & v0.3 R1--R8 & 1,958 accepted cells & Live Kubernetes, packet-level simulation, uncertainty, official workload, and scalability \\
Supporting & APP\_A/APP\_B controlled campaign & 1,200 method runs (240 paired instances) & Modeled-objective comparison across fan-out and mesh fixtures \\
Supporting & APP\_C controlled campaign & 600 method runs (120 paired instances) & Pipeline-topology generalization \\
Supporting & Component ablations & 10 rows & Isolates CVaR, relocation, conflict, scenario, and wireless-state components \\
Supporting & Relocation/CVaR sensitivity & 144 configurations & Parameter trade-offs across four conditions \\
Supporting & Multi-interval dynamics & 200 windows & Ten controlled 20-window sequences \\
Audit & Classifier and exactness checks & separate units & Controller selection and solver correctness; not added to experimental totals \\
\bottomrule
\end{tabularx}
\end{table}
"""
    (OUT / "layered_evidence.tex").write_text(inventory, encoding="utf-8")

    controlled = rows("controlled_confirmatory_app_a_b_frozen_g11.csv") + rows("app_c_campaign.csv")
    grouped: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for row in controlled:
        if row["status"] == "complete":
            grouped[(row["application"], row["network_condition"], row["method"])].append(float(row["objective"]))
    methods = ["Current", "TrafficOnly-MAPE-CAP", "DeterministicNetworkAware", "BPlus-Exact"]
    labels = {"Current": "Current", "TrafficOnly-MAPE-CAP": "TrafficOnly", "DeterministicNetworkAware": "DetNet", "BPlus-Exact": "B+-Exact"}
    lines = [
        "% Canonical controlled topology results",
        r"\begin{table}[htbp]", r"\centering",
        r"\caption{Controlled modeled-objective means (30 paired replicates per complete method--condition cell). Dashes denote infeasible/failed cells without complete objective values.}",
        r"\label{tab:controlled-topologies}", r"\small",
        r"\begin{tabular}{llrrrr}", r"\toprule",
        "App & Condition & " + " & ".join(labels[m] for m in methods) + ROW_END, r"\midrule",
    ]
    for app in ["APP_A", "APP_B", "APP_C"]:
        for condition in ["stable", "persistent_degradation", "conflict_dense", "outage_with_fallback"]:
            values = []
            for method in methods:
                cell = grouped.get((app, condition, method), [])
                values.append(f"{mean(cell):.1f}" if cell else "---")
            lines.append(f"{app[-1]} & {tex_escape(condition.replace('_', ' ').title())} & " + " & ".join(values) + ROW_END)
    lines += [r"\bottomrule", r"\end{tabular}", r"\end{table}", ""]
    (OUT / "controlled_topologies.tex").write_text("\n".join(lines), encoding="utf-8")

    ablation_rows = rows("ablations.csv")
    pairs: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for row in ablation_rows:
        pairs[row["component"]][row["variant"]] = row
    ablation_lines = [
        "% Canonical component ablations", r"\begin{table}[htbp]", r"\centering",
        r"\caption{Corrected component ablations, re-evaluated under the full B+ objective.}",
        r"\label{tab:controlled-ablation}", r"\small",
        r"\begin{tabular}{llrrl}", r"\toprule",
        r"Component & Fixture & Full objective & Without component & Outcome \\", r"\midrule",
    ]
    for component in ["CVaR", "RelocationCost", "ConflictBudget", "ScenarioRobustness", "WirelessState"]:
        variants = pairs[component]
        full = variants.get("Full-BPlus", {})
        without = next((value for key, value in variants.items() if key != "Full-BPlus"), {})
        full_obj = float(full.get("objective", full.get("reference_objective", "nan")))
        if without.get("reference_feasible", "").lower() == "true":
            without_obj = float(without["reference_objective"] or without["objective"])
            degradation = (without_obj - full_obj) / full_obj * 100
            outcome = f"+{degradation:.1f}\\%"
            without_text = f"{without_obj:.1f}"
        else:
            without_text = r"$\infty$"
            outcome = "Infeasible"
        fixture = full.get("fixture") or without.get("fixture", "")
        ablation_lines.append(f"{component} & {tex_escape(fixture.replace('_', ' ').title())} & {full_obj:.1f} & {without_text} & {outcome}" + ROW_END)
    ablation_lines += [r"\bottomrule", r"\end{tabular}", r"\end{table}", ""]
    (OUT / "component_ablation.tex").write_text("\n".join(ablation_lines), encoding="utf-8")

    support = r"""% Supporting controlled studies
\begin{table}[htbp]
\centering
\caption{Supporting controlled studies. These outcomes concern the planning surrogate, not live end-to-end application performance.}
\label{tab:supporting-controlled}
\small
\begin{tabularx}{\linewidth}{lrrX}
\toprule
Study & Design & Complete/effective & Main descriptive result \\
\midrule
Relocation/CVaR sweep & $6\times6\times4$ & 144/144 & Relocations range from 0--2; the calibrated setting relocates under persistent degradation, outage, and conflict but not stable conditions. \\
Multi-interval dynamics & $10\times20$ windows & 200/200 & Mean modeled objective is 36.08\% below static, with eight relocations; outage windows are excluded from the percentage. \\
Full-local scenario checks & 27 rows & 26 complete, 1 infeasible & Exercises stable, degradation, outage/fallback, conflict, recovery, and negative-control behavior. \\
Controlled dynamic sequence & 11 windows & 11/11 & Transient changes are rejected while persistent changes can pass the benefit gate. \\
\bottomrule
\end{tabularx}
\end{table}
"""
    (OUT / "supporting_controlled.tex").write_text(support, encoding="utf-8")

    provenance = (
        "% Publication source provenance\n"
        r"\begin{table}[htbp]" "\n" r"\centering" "\n"
        r"\caption{Canonical publication-source controls. Full SHA-256 values and selection rules are machine-readable in the source manifest.}" "\n"
        r"\label{tab:source-provenance}" "\n" r"\small" "\n"
        r"\begin{tabularx}{\linewidth}{llrX}" "\n" r"\toprule" "\n"
        r"ID & Family & Rows & Selection rule \\" "\n" r"\midrule" "\n"
    )
    for entry in manifest["entries"]:
        if str(entry["id"]).startswith("C"):
            provenance += f"{entry['id']} & {tex_escape(str(entry['family']))} & {entry.get('rows', '---')} & {tex_escape(str(entry['selection_rule']))}" + ROW_END + "\n"
    provenance += r"\bottomrule" "\n" r"\end{tabularx}" "\n" r"\end{table}" "\n"
    (OUT / "source_provenance.tex").write_text(provenance, encoding="utf-8")
    print(f"Generated reconciled paper assets in {OUT}")


if __name__ == "__main__":
    main()
