#!/usr/bin/env python3
"""Generate manuscript and supplement artifacts from the validated B+ v0.3 run."""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path


SYSTEM = Path(__file__).resolve().parents[1]
ROOT = SYSTEM.parent
PACKAGED = SYSTEM.name == "implementation" and (ROOT / "RESULTS").exists()
if PACKAGED:
    RUN = ROOT / "RESULTS" / "primary" / "v03-20260811T151500Z"
    PAPER = ROOT / "PAPER"
else:
    RUN = SYSTEM / "results" / "v0.3" / "runs" / "v03-20260811T151500Z"
    PAPER = ROOT / "01_PAPER" / "BPLUS_MANUSCRIPT"
OUT = PAPER / "tables" / "v03"


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def number(value: str | float | int | None) -> float:
    if value in (None, ""):
        return math.nan
    return float(value)


def fmt(value: float, digits: int = 2) -> str:
    if not math.isfinite(value):
        return "---"
    return f"{value:.{digits}f}"


def mean(values: list[float]) -> float:
    values = [value for value in values if math.isfinite(value)]
    return sum(values) / len(values) if values else math.nan


def write(name: str, lines: list[str]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


def table_start(caption: str, label: str, columns: str, header: str, size: str = "\\small") -> list[str]:
    return [
        "% Auto-generated from the validated B+ v0.3 run; do not edit manually.",
        "\\begin{table}[htbp]",
        "\\centering",
        f"\\caption{{{caption}}}",
        f"\\label{{{label}}}",
        size,
        f"\\begin{{tabular}}{{{columns}}}",
        "\\toprule",
        header + " \\\\",
        "\\midrule",
    ]


def table_end() -> list[str]:
    return ["\\bottomrule", "\\end{tabular}", "\\end{table}"]


def main() -> int:
    if not RUN.exists():
        raise SystemExit(f"Validated run not found: {RUN}")

    regen = json.loads((RUN / "derived" / "phase-12-regeneration.json").read_text(encoding="utf-8"))
    stats_meta = json.loads((RUN / "derived" / "phase-13-statistics.json").read_text(encoding="utf-8"))
    validation = json.loads((RUN / "derived" / "phase-14-validation.json").read_text(encoding="utf-8"))
    r3_summary = json.loads((RUN / "derived" / "r3-summary.json").read_text(encoding="utf-8"))
    r4_summary = json.loads((RUN / "derived" / "r4-summary.json").read_text(encoding="utf-8"))

    derived = RUN / "derived" / "regenerated"
    r1 = rows(derived / "r1-aggregate.csv")
    r2 = rows(derived / "r2-aggregate.csv")
    r4 = rows(derived / "r4-aggregate.csv")
    r5 = rows(derived / "r5-effective-status.csv")
    r6 = rows(derived / "r6-aggregate.csv")
    r7 = rows(derived / "r7-aggregate.csv")
    r8 = rows(derived / "r8-aggregate.csv")
    paired = rows(RUN / "derived" / "statistics" / "paired-statistics.csv")
    r8_raw = rows(RUN / "raw" / "phase-4-r8-results.csv")

    significant = [row for row in paired if number(row["adjusted_p_value_holm"]) < 0.05]
    r1_significant = [row for row in significant if row["experiment"] == "R1"]
    r7_error = next(
        row for row in paired
        if row["experiment"] == "R7" and row["group"] == "conflict" and row["metric"] == "errors"
    )

    macros = [
        "% Auto-generated from B+ v0.3 run v03-20260811T151500Z.",
        f"\\newcommand{{\\VThreeTotalCells}}{{{sum(regen['counts'].values())}}}",
        f"\\newcommand{{\\RoneCells}}{{{regen['counts']['r1']}}}",
        f"\\newcommand{{\\RtwoCells}}{{{regen['counts']['r2']}}}",
        f"\\newcommand{{\\RthreeCells}}{{{regen['counts']['r3']}}}",
        f"\\newcommand{{\\RfourCells}}{{{regen['counts']['r4']}}}",
        f"\\newcommand{{\\RfiveCells}}{{{regen['counts']['r5']}}}",
        f"\\newcommand{{\\RsixCells}}{{{regen['counts']['r6']}}}",
        f"\\newcommand{{\\RsevenCells}}{{{regen['counts']['r7']}}}",
        f"\\newcommand{{\\ReightCells}}{{{regen['counts']['r8']}}}",
        f"\\newcommand{{\\VThreeComparisons}}{{{stats_meta['comparison_count']}}}",
        f"\\newcommand{{\\VThreeHolmSignificant}}{{{len(significant)}}}",
        f"\\newcommand{{\\RoneHolmSignificant}}{{{len(r1_significant)}}}",
        f"\\newcommand{{\\RthreeSequences}}{{{r3_summary['completed_sequences']}}}",
        f"\\newcommand{{\\RthreeAcceptedRelocations}}{{{r3_summary['accepted_relocations']}}}",
        f"\\newcommand{{\\RthreeRejectedWindows}}{{{r3_summary['rejected_gate_windows']}}}",
        f"\\newcommand{{\\RfourSuccessful}}{{{r4_summary['successful_relocations']}}}",
        f"\\newcommand{{\\RfourBoundaryFailures}}{{{r4_summary['expected_boundary_failures']}}}",
        f"\\newcommand{{\\RfourFailedProbes}}{{{r4_summary['total_failed_requests']}}}",
        f"\\newcommand{{\\RfourTransferMiB}}{{{r4_summary['total_state_transfer_bytes'] / 2**20:.1f}}}",
        f"\\newcommand{{\\RfiveScenarios}}{{{len(set(row['scenario'] for row in r5))}}}",
        f"\\newcommand{{\\RfiveRepairedCells}}{{{sum(row['recovered_by_retry'] == 'True' for row in r5)}}}",
        f"\\newcommand{{\\RsevenConflictErrorDelta}}{{{number(r7_error['paired_mean_difference']):.1f}}}",
        f"\\newcommand{{\\RsevenConflictErrorHolmP}}{{{number(r7_error['adjusted_p_value_holm']):.4f}}}",
        f"\\newcommand{{\\ExactProvenOptimal}}{{{sum(row['method'] == 'Exact' and row['proven_optimal'] == 'True' for row in r8_raw)}}}",
        f"\\newcommand{{\\ExactTimedIncumbents}}{{{sum(row['method'] == 'Exact' and row['status'] == 'incumbent-timeout' for row in r8_raw)}}}",
        f"\\newcommand{{\\ValidationTests}}{{53}}",
        f"\\newcommand{{\\ValidationPassed}}{{{'yes' if validation['passed'] else 'no'}}}",
    ]
    write("v03_macros.tex", macros)

    inventory = table_start(
        "Validated v0.3 evidence campaign. Counts are accepted experimental cells or observations, not HTTP requests.",
        "tab:v03-inventory", "clrr", "Experiment & Evidence & Accepted & Independent $n$"
    )
    descriptions = {
        "R1": ("Kubernetes paired-method campaign", "30 per method-condition"),
        "R2": ("Telemetry/controller modes", "3 per mode"),
        "R3": ("Dynamic hysteresis sequences", "5 seeds"),
        "R4": ("Relocation state/storage matrix", "1 per matrix cell"),
        "R5": ("Packet-level WiGig scenarios", "3 seeds"),
        "R6": ("Uncertainty/sensitivity", "3 seeds"),
        "R7": ("Official DeathStarBench workload", "5 paired replicates"),
        "R8": ("Exact/LNS scalability", "3 seeds"),
    }
    for key in [f"R{i}" for i in range(1, 9)]:
        desc, indep = descriptions[key]
        inventory.append(f"{key} & {desc} & {regen['counts'][key.lower()]} & {indep} " + r"\\")
    inventory.extend(table_end())
    write("campaign_inventory.tex", inventory)

    stat_lookup = {
        (row["experiment"], row["group"], row["metric"], row["left_method"], row["right_method"]): row
        for row in paired
    }
    r1_table = [
        "% Auto-generated from the validated B+ v0.3 run; do not edit manually.",
        "\\begin{table}[htbp]",
        "\\centering",
        "\\caption{R1 Online Boutique P95 comparison for BPlus-Exact versus Current (30 paired replicates per condition). $\\Delta$ is BPlus-Exact minus Current; CI is the paired 95\\% Student-$t$ interval; $d_z$ is paired Cohen's effect size; $p_H$ is the global Holm-adjusted $p$ value.}",
        "\\label{tab:r1-results}",
        "\\scriptsize",
        "\\resizebox{\\linewidth}{!}{%",
        "\\begin{tabular}{lrrrcrr}",
        "\\toprule",
        r"Condition & B+ P95 & Current P95 & $\Delta$ P95 & 95\% CI & $d_z$ & $p_H$ \\",
        "\\midrule",
    ]
    by_r1 = {(row["condition"], row["method"]): row for row in r1}
    order = ["stable", "persistent-degradation", "partial-blockage", "conflict-dense", "outage-with-fallback", "recovery", "bursty", "hotspot", "structural-workload-change"]
    for condition in order:
        bp = by_r1[(condition, "BPlus-Exact")]
        cur = by_r1[(condition, "Current")]
        stat = stat_lookup[("R1", condition, "p95_ms", "BPlus-Exact", "Current")]
        label = condition.replace("-", " ").title()
        ci = f"[{fmt(number(stat['ci95_low']),1)}, {fmt(number(stat['ci95_high']),1)}]"
        r1_table.append(
            f"{label} & {fmt(number(bp['mean_p95_ms']),1)} & {fmt(number(cur['mean_p95_ms']),1)} & "
            f"{fmt(number(stat['paired_mean_difference']),1)} & {ci} & "
            f"{fmt(number(stat['effect_size_cohens_dz']),2)} & {fmt(number(stat['adjusted_p_value_holm']),3)} " + r"\\")
    r1_table.extend(["\\bottomrule", "\\end{tabular}%", "}", "\\end{table}"])
    write("r1_results.tex", r1_table)

    overhead = table_start(
        "R2 telemetry/controller mode observations. Estimates use three independent replicates per mode; application metrics and resource use are descriptive because workload throughput differs across modes.",
        "tab:r2-overhead", "lrrrr", "Mode & P95 (ms) & Throughput (RPS) & CPU (cores) & Memory (MiB)"
    )
    for row in r2:
        label = row["mode"].replace("_", " ").title()
        overhead.append(f"{label} & {fmt(number(row['mean_p95_ms']),1)} & {fmt(number(row['mean_throughput_rps']),2)} & {fmt(number(row['mean_cpu_cores']),3)} & {fmt(number(row['mean_memory_mib']),1)} " + r"\\")
    overhead.extend(table_end())
    write("r2_overhead.tex", overhead)

    storage_groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    image_groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in r4:
        storage_groups[row["storage"]].append(row)
        image_groups[row["image_state"]].append(row)
    relocation = table_start(
        "R4 relocation outcomes aggregated over image state, state size, network state, and load. Downtime equals 0.2 s times the number of failed Redis availability probes; the historical raw field is named \\texttt{failed\\_requests}, but it contains probe failures rather than HTTP requests.",
        "tab:r4-relocation", "lrrrr", "Strategy/state & Cells & Relocation (s) & Downtime (s) & Failed probes"
    )
    for key in ["emptydir", "persistent-volume", "application-replication"]:
        group = storage_groups[key]
        relocation.append(
            f"{key.replace('-', ' ').title()} & {len(group)} & "
            f"{fmt(mean([number(x['mean_relocation_seconds']) for x in group]),2)} & "
            f"{fmt(mean([number(x['mean_downtime_seconds']) for x in group]),2)} & "
            f"{fmt(mean([number(x['mean_failed_requests']) for x in group]),2)} " + r"\\")
    relocation.append("\\midrule")
    for key in ["cached", "uncached"]:
        group = image_groups[key]
        relocation.append(
            f"{key.title()} image & {len(group)} & "
            f"{fmt(mean([number(x['mean_relocation_seconds']) for x in group]),2)} & "
            f"{fmt(mean([number(x['mean_downtime_seconds']) for x in group]),2)} & "
            f"{fmt(mean([number(x['mean_failed_requests']) for x in group]),2)} " + r"\\")
    relocation.extend(table_end())
    write("r4_relocation.tex", relocation)

    wireless_groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in r5:
        wireless_groups[row["scenario"]].append(row)
    wireless = table_start(
        "R5 packet-level WiGig coverage. Every scenario has three accepted seeds. Repaired cells are append-only reruns with retained original failures.",
        "tab:r5-wireless", "lrrl", "Scenario & Seeds & Repaired & Coverage", "\\scriptsize"
    )
    for scenario in sorted(wireless_groups):
        group = wireless_groups[scenario]
        coverage = next((x["coverage"] for x in group if x["coverage"]), "see supplement")
        coverage = coverage.replace(",", "; ").replace("_", " ")
        wireless.append(f"{scenario.replace('-', ' ').title()} & {len(group)} & {sum(x['recovered_by_retry'] == 'True' for x in group)} & {coverage} " + r"\\")
    wireless.extend(table_end())
    write("r5_wireless.tex", wireless)

    uncertainty = table_start(
        "R6 held-out tail cost under the empirical probability model. B+ uses $q=0.9$; entries are means over three seeds. The infeasible fraction is the number of infeasible held-out traces divided by three.",
        "tab:r6-uncertainty", "lrrrrr", "Method & Gen. scenarios & Mean held-out & Max. held-out & Infeasible & Runtime (s)", "\\scriptsize"
    )
    method_order = ["BPlus-CVaR", "Deterministic", "ExpectedValue", "Minimax"]
    for scenarios in [3, 5, 10, 20, 50]:
        for method in method_order:
            candidates = [x for x in r6 if x["method"] == method and x["scenario_count"] == str(scenarios) and x["probability_model"] == "empirical"]
            if method == "BPlus-CVaR":
                candidates = [x for x in candidates if x["quantile"] == "0.9"]
            row = candidates[0]
            uncertainty.append(
                f"{method.replace('ExpectedValue','Expected value').replace('BPlus-CVaR','B+ CVaR')} & {scenarios} & "
                f"{fmt(number(row['mean_heldout']),1)} & {fmt(number(row['mean_tail_p95']),1)} & "
                f"{fmt(number(row['mean_infeasible']) / 3.0,2)} & {fmt(number(row['mean_runtime_seconds']),3)} " + r"\\")
        if scenarios != 50:
            uncertainty.append("\\addlinespace")
    uncertainty.extend(table_end())
    write("r6_uncertainty.tex", uncertainty)

    workload = table_start(
        "R7 official DeathStarBench workload results (five paired replicates). Lower P99, errors, and downtime are preferable; higher throughput is preferable.",
        "tab:r7-deathstar", "llrrrr", "Condition & Method & RPS & P99 (ms) & Errors & Downtime (s)", "\\scriptsize"
    )
    for condition in ["stable", "degradation", "conflict", "recovery"]:
        for method in ["Baseline", "BPlus"]:
            row = next(x for x in r7 if x["condition"] == condition and x["method"] == method)
            workload.append(
                f"{condition.title()} & {'FixedTarget' if method == 'BPlus' else method} & "
                f"{fmt(number(row['mean_throughput_rps']),2)} & {fmt(number(row['mean_p99_ms']),1)} & "
                f"{fmt(number(row['mean_errors']),1)} & {fmt(number(row['mean_downtime_seconds']),2)} " + r"\\")
        if condition != "recovery":
            workload.append("\\addlinespace")
    workload.extend(table_end())
    write("r7_deathstar.tex", workload)

    raw_groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in r8_raw:
        raw_groups[(row["replica_count"], row["method"])].append(row)
    scalability = table_start(
        "R8 exact/LNS scalability (three seeds per row). Exact status reports the number of proven optima; other exact rows are feasible time-limited incumbents. LNS gap is relative to the exact optimum or available bound/incumbent as recorded by the campaign.",
        "tab:r8-scalability", "rrrrrr", "Replicas & Exact (s) & Proven & LNS (s) & LNS gap (\\%) & Feasible", "\\scriptsize"
    )
    by_r8 = {(row["replica_count"], row["method"]): row for row in r8}
    for size in [6, 8, 10, 12, 16, 20, 24, 40, 50]:
        exact = by_r8[(str(size), "Exact")]
        lns = by_r8[(str(size), "LNS")]
        exact_raw = raw_groups[(str(size), "Exact")]
        proven = sum(row["proven_optimal"] == "True" for row in exact_raw)
        scalability.append(
            f"{size} & {fmt(number(exact['mean_runtime_seconds']),2)} & {proven}/3 & "
            f"{fmt(number(lns['mean_runtime_seconds']),2)} & {fmt(number(lns['mean_gap_percent']),2)} & "
            f"{fmt(number(lns['feasible_rate']),2)} " + r"\\")
    scalability.extend(table_end())
    write("r8_scalability.tex", scalability)

    sig_table = table_start(
        "All Holm-significant paired comparisons in v0.3. The family contains 142 reported tests.",
        "tab:holm-significant", "llllrr", "Experiment & Group & Metric & Contrast & Mean difference & Holm $p$", "\\scriptsize"
    )
    for row in significant:
        contrast = f"{row['left_method']}--{row['right_method']}"
        sig_table.append(
            f"{row['experiment']} & {row['group']} & {row['metric'].replace('_',' ')} & {contrast} & "
            f"{fmt(number(row['paired_mean_difference']),3)} & {fmt(number(row['adjusted_p_value_holm']),4)} " + r"\\")
    sig_table.extend(table_end())
    write("holm_significant.tex", sig_table)

    from generate_complete_paper_artifacts import generate_complete
    generate_complete(RUN, PAPER)
    print(f"Generated v0.3 manuscript artifacts in {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
