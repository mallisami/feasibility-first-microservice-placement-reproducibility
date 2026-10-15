# Protocol: packet-level execution of the persistent-degradation state on unselected graphs

**Protocol ID:** `mape-cap-ws-ns3-pd-admission-v1.0`
**Status:** written before any packet cell of this study was executed. Record the commit or file hash of this folder before running (`sha256sum protocol/* config/* src/* simulator/*`), and do not change scientific parameters after outcomes are seen.
**Hardware boundary:** pinned ns-3 IEEE 802.11ad/WiGig simulation; no physical 60-GHz hardware.

## 1. Question

In the controlled 150-graph study at load 1.25, byte-affinity placement exceeds a declared airtime budget on 24 graphs, always in the persistent-degradation state and always in a group holding the two directions of one rack pair. That violation has so far been executed only on an emulator that enforces the same budget. This study asks:

> When the planners' placements for all 150 unselected graphs are executed in a packet simulator that is given only offered rates and the 50% shared-resource fraction, do placements that exceed the declared budget lose traffic, and do placements within it sustain delivery?

## 2. Design

- **Graphs:** all 150 controlled graphs (seeds 11001-11050, 22001-22050, 33001-33050); no selection on any planning or packet outcome.
- **Load:** the primary load, tau = 1.25, with the published calibration.
- **Methods:** Affinity-Bytes, Affinity-Bytes+Admission, MAPE-CAP-WS, as selected by the packaged planner code (`src/build_plan.py`, which asserts the published 24/150 result and agreement of every group utilization with the planner's own evaluation).
- **State and resource:** persistent degradation. Each rack pair's two directions form one conflict group with a 30-s budget in the 60-s window, so each group is simulated as one shared contention period occupying 50% of the data-transmission interval. Groups are simulated separately, as the state declares them independent.
- **Offered rates:** for direction d with planner airtime fraction a_d = B_d / (G_d x 60 s), the offered packet rate is a_d x g_d, where g_d is the packet-calibrated solo goodput of the corresponding station at the full interval. The packet-level normalized load of a group, sum(rate/g)/0.5, then equals the planner's utilization of that group. The simulator receives rates and the resource fraction only; it is not given the planner's admissibility label or utilization.
- **Cells:** 627 unique (graph, group, rates) placement cells; identical cells shared by several methods are simulated once. A boundary sweep adds 60 cells (below). Three ns-3 RNG runs (501, 502, 503) per cell: 2,061 science cells. 18 calibration cells.
- **Boundary sweep:** the placement cells contain only 24 groups above the budget, so the location of the boundary at the 50% share is also measured directly. Twelve two-direction traffic shapes are taken from the 459 two-direction placement cells by a rule that uses no outcome (cells sorted by the dominant direction's airtime share; 12 evenly spaced order statistics). Each shape is run at group utilization 0.8, 0.9, 1.0, 1.1 and 1.2.
- **Execution:** cells run in parallel (4 workers on 4 vCPUs). ns-3 is a deterministic discrete-event simulator seeded by `RngRun`; wall-clock parallelism does not enter the simulation. If the built simulator binary, called directly, reproduces the waf-wrapped smoke run byte for byte, it is used to avoid wrapper overhead; otherwise the waf wrapper is used. The mode is recorded in `operator_logs/LAST_PREPARE.json`.
- **Simulator:** `evaluate_shared_airtime_boundary.cc`, byte-identical to the retained shared-airtime boundary study (hash in `config/experiment.json`), wigig-module v0.5 commit f340423, DMG_MCS9, DenseScenario, six stations.
- **Gates before science:** self-test, packet smoke run, and a full-interval versus 50% throughput gate (ratio must lie in [0.25, 0.75]). Acceptance of a cell is infrastructure-only; outcome magnitude is never an acceptance criterion; at most two attempts per cell.

## 3. Endpoints

- **Cell level:** delivered fraction D of each group cell, averaged over the three RNG runs; per-direction delivered fractions.
- **Placement level:** the fraction of the placement's cross-rack bits delivered in the persistent-degradation state, i.e. per-direction delivered fractions weighted by the planner's bits per direction.
- **Unit of analysis:** the graph. RNG runs are nested replicates.

## 4. Hypotheses and analysis (fixed in advance)

**H1 (primary, admission).** Over all 150 graphs, placement-level delivered fraction is higher for Affinity-Bytes+Admission than for Affinity-Bytes. Paired mean difference with a 100,000-resample graph bootstrap 95% interval (seed 20261003+1) and a one-sided Wilcoxon signed-rank test on non-zero differences. H1 is called supported only if the interval lies above zero **and** p < 0.05. The two methods select the same placement on most graphs, so most differences are exactly zero; this is part of the estimand, not a defect.

**H2 (boundary, descriptive).** Over the 627 unique group cells, cross-tabulate planner utilization (U <= 1 versus U > 1) against sustained delivery (D >= 0.95), and report D by utilization bin and Spearman correlation between U and D. No fitted threshold. The 0.95 rule is the same descriptive rule used in the retained boundary study.

**Boundary sweep (descriptive).** Mean and minimum D over the 12 shapes at each of the five loads, and the number of shapes below 0.95. This describes where delivery is lost relative to the declared budget at the 50% share; it is not fitted and not used to change the budget.

**Secondary.** MAPE-CAP-WS minus Affinity-Bytes+Admission (ranking after admission) and MAPE-CAP-WS minus Affinity-Bytes, same statistics, descriptive. Number of graphs with D >= 0.95 by method, with exact McNemar counts for the admission pair.

**Interpretation rule.** A null or opposite H1 result is reported as not supporting a packet-level consequence of the declared budget. If cells with U <= 1 fail to sustain delivery, or cells with U > 1 sustain it, that is reported as a mismatch between the declared budget and the packet model. No parameter is changed after outcomes are seen; any later analysis is labelled post hoc.

## 5. What this study cannot show

It does not validate the 30-s budget, the conflict-group structure or the effective goodputs against a physical fabric. It does not test interference between rack-pair groups. Offered load differs across methods because placement determines the traffic; the comparison is of placements as planned, not of equal-demand traffic. The graphs are generated instances with 6-8 replicas on three racks.

## 6. Deviations

Record any deviation (failed gate, changed worker count, interrupted run, replaced cell) in `operator_logs/DEVIATIONS.md` with time and reason. Changing `parallel_workers` is an execution setting and does not affect simulated outcomes.
