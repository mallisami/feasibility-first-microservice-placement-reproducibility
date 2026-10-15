# Frozen Packet-Level ns-3/WiGig Confirmation Protocol

**Protocol ID:** `wireless-beyond-affinity-ns3-v1.1`  
**Freeze date:** 16 September 2026  
**Status:** frozen before packet-level scientific outcomes  
**Hardware boundary:** no physical 60-GHz/WiGig hardware is available or required for this protocol.

## 1. Purpose

This experiment tests whether the placement distinction observed in the controlled and Kubernetes shared-airtime studies survives a packet-level IEEE 802.11ad/WiGig contention model. It is a separate confirmation and does not replace or alter the already frozen Kubernetes campaign.

The question is deliberately narrower than a physical-RF claim:

> Under the fixed Q-D DenseScenario contention mapping, does `BPlus-Exact` preserve a larger delivered fraction of offered traffic than exact byte-affinity placement under a predeclared high offered-load condition?

Version 1.1 is a **pre-execution amendment** to the packet protocol. No packet-level scientific outcome existed when this amendment was frozen. The amendment replaces the earlier analytically scaled offered rates with an independent packet-level load anchor already present in the retained WiGig experiment family, strengthens the execution smoke gate and resume provenance, and defines the aggregate delivered fraction directly from received bytes and each stream's actual post-association active interval.

### Amendment 1.1.1 (16 September 2026): DATA PHY MCS correction — pre-execution, no scientific outcomes existed

The mandatory six-stream packet smoke gate (RNG run `991001`) failed on first live execution: 3 of the 6 fixed rack-pair links (STA indices 0, 3, 5) received zero payload bytes, while association and SLS beamforming succeeded on all 6. Root-cause investigation (preserved in `operator_logs/packet-smoke-20260916T121932Z/`, `operator_logs/packet-smoke-diagnostic-verbose-text/`, and `operator_logs/mcs-diagnostic-sweep-v2/`) found:

- `DmgWifiHelper`'s own constructor hardcodes `DataMode=DMG_MCS12` for every node via an explicit `ObjectFactory::Set()` call, which is applied identically regardless of per-link channel quality and cannot be changed via a command-line `Config` default.
- A controlled MCS sweep against the unmodified simulator (only the DATA MCS varied, all else — topology, channel data, seed, offered rate — held fixed) showed MCS4 through MCS9 all restore ~99.98% delivery on all 6 real link positions, while MCS12 reproduces the original failure exactly.
- MCS4 (1155 Mbps PHY capacity) is below this protocol's own self-test maximum single-stream demand (`max_stream_mbps` = 1194.22 Mbps) and was excluded on capacity grounds alone, independent of the reliability finding.
- The historical, independently produced calibration reference (`RESULTS/calibration/external/ns3_simulation_backed_traces.csv`) already labels these same six directed rack pairs at MCS7–MCS9 under nominal-los provenance, including the three pairs that failed at MCS12 here.

**Correction:** `evaluate_bplus_affinity_dense.cc` now explicitly sets `wifi.SetRemoteStationManager("ns3::ConstantRateWifiManager", "ControlMode", "DMG_MCS4", "DataMode", "DMG_MCS9")` immediately after `DmgWifiHelper` construction, overriding the constructor default. `ControlMode` is unchanged. This is one uniform PHY policy applied to every node and every method (`Current`, `Affinity-Bytes`, `BPlus-Exact`) identically — no per-method or per-link tuning. The unrelated log-component name (`EvaluateQdDenseScenarioSingleAP` → `EvaluateBplusAffinityDense`) was also corrected in the same file; it only affected an unused `--verbose` debug branch and has no effect on any executed configuration.

**Old setting:** `DataMode=DMG_MCS12` (4620 Mbps PHY capacity, unreachable on 3 of 6 real links). **New setting:** `DataMode=DMG_MCS9` (2502.5 Mbps PHY capacity, ~110% headroom above the protocol's own maximum demand, empirically verified reliable on all 6 links).

**Scientific implication:** this changes the effective per-link PHY data rate ceiling used throughout the packet-level campaign, from an unreachable 4620 Mbps to an empirically-achievable 2502.5 Mbps. It does not change graph identities, placement methods, workloads, seeds, targets, risk/relocation weights, wireless traces, the packet-level load anchor, retry limits, the primary endpoint, or the statistical test. This MCS change must be disclosed in the eventual manuscript alongside its effect on the simulation's physical assumptions.

Source hash: `evaluate_bplus_affinity_dense.cc` changed from `c5fc18832a8357d51168515194d3ca7933f3cfb75db2f75f97b39085158554e6` to `63ff5709ea7286d01cbdeaf33549963ba1fb294f383cb11c28b96adf28853454` (see `SHA256SUMS.txt`). No scientific packet cell had executed prior to this amendment.

## 2. Primary hypothesis and endpoint

**H1:** At target `1.25`, graph-level mean `aggregate_delivered_fraction` is higher for `BPlus-Exact` than for `Affinity-Bytes`.

For an accepted ns-3 cell, let stream `i` have configured rate `R_i` bits/s, valid active interval `T_i` seconds after association, and received payload `N_i^rx` bytes. The primary cell endpoint is

`aggregate_delivered_fraction = min(1, (sum_i 8 N_i^rx) / (sum_i R_i T_i))`.

Thus the denominator is byte-weighted over the actual active intervals rather than assuming that all STAs begin transmission at exactly the same instant. Zero-goodput scientific outcomes remain valid when execution and output structure are valid.

The three ns-3 RNG replications are averaged within each graph-method-target cell before inference. The **communication graph is the independent unit**; simulator RNG runs are nested replications and are not treated as independent samples.

Primary comparison: paired `BPlus-Exact - Affinity-Bytes` across all 30 held-out graphs at target `1.25`.

Primary inference: one-sided paired Wilcoxon signed-rank test plus fixed-seed 100,000-resample paired bootstrap 95% CI for the mean difference. The hypothesis is called supported only if `p < .05` and the bootstrap interval is entirely above zero.

## 3. Specificity control

The same comparison is run at target `0.50`. This is a low-load specificity condition, not a second primary hypothesis. A large low-load advantage would weaken the interpretation that any primary separation is specifically contention-related.

## 4. Frozen graphs, methods, and nested simulator seeds

Held-out graph seeds: `44001` through `44030`, identical to the separately frozen Kubernetes campaign.

Methods:

- `Current`
- `Affinity-Bytes`
- `BPlus-Exact`

Nested ns-3 RNG runs per graph-method-target: `201`, `202`, `203`.

Total planned packet-level cells:

`30 graphs x 3 methods x 2 load targets x 3 ns-3 RNG runs = 540 cells`.

No graph, method, target, or RNG run may be removed because of an unfavorable scientific outcome. B+ robust-planner abstention retains `Current`, is recorded, and is not excluded.

## 5. Placement construction and independent packet-load anchor

Graph generation, wireless-state loading, exact byte-affinity placement, and B+ exact planning are imported from the canonical Kubernetes-confirmatory implementation and canonical B+ source. No second planner implementation is permitted.

The packet-level offered-load scale is **not fitted to packet outcomes**. The retained upstream Q-D dense experiment uses six STAs at the upstream default `300 Mbps` offered rate per STA. This gives the frozen six-STA DenseScenario offered-load reference

`L_ref = 6 x 300 Mbps = 1800 Mbps`.

For each graph and target, a single graph-specific load multiplier is computed from the `Current` placement so that:

- target `0.50`: `Current` aggregate configured offered rate = `900 Mbps`;
- target `1.25`: `Current` aggregate configured offered rate = `2250 Mbps`.

The **same graph-specific multiplier** is then applied to the raw directed rack-pair traffic of `Current`, `Affinity-Bytes`, and `BPlus-Exact`. Therefore a method cannot receive a favorable load rescaling because of its placement. A method can have a different aggregate configured rate only because its placement changes which service traffic remains local versus crosses racks.

The placement planners themselves retain the target-specific frozen analytical wireless problem used by the Kubernetes-confirmatory construction. The packet experiment then tests those frozen placements on the independent Q-D packet-level mapping.

The maximum allowed configured stream rate is frozen at `1500 Mbps`. The pre-execution complete 540-cell planning audit must pass this guard before Docker execution begins.

## 6. Packet-level mapping

The upstream WiGig Q-D `DenseScenario` is used. The experiment creates six STAs and one DMG AP. Each directed rack-pair aggregate is permanently mapped to one STA:

| Directed rack pair | STA |
|---|---:|
| rack-a -> rack-b | 0 |
| rack-b -> rack-a | 1 |
| rack-a -> rack-c | 2 |
| rack-c -> rack-a | 3 |
| rack-b -> rack-c | 4 |
| rack-c -> rack-b | 5 |

All service flows that cross the same directed rack pair are aggregated into that stream's offered rate. Same-rack traffic is not sent through the WiGig medium. An inactive rack pair has zero offered rate and no source application.

This mapping is frozen to prevent post-outcome reassignment of favorable Q-D station positions.

## 7. ns-3/WiGig execution

- upstream source: `wigig-tools/wigig-module` release `v0.5`;
- required upstream Git commit: `f3404236d05eb1da1cab80eec06c56ea8ab43f7d`;
- standard/model: IEEE 802.11ad/WiGig implementation in the pinned upstream fork;
- Q-D scenario: `DenseScenario`;
- application: UDP OnOff;
- packet size: 1448 bytes;
- simulation duration: 3.0 s;
- six possible directed rack-pair streams;
- maximum frozen offered-rate guard: 1500 Mbps per stream;
- per-cell wall-clock timeout: 300 s.

The custom scratch program differs from the retained upstream dense-scenario program only to accept one frozen offered rate per STA, allow zero-rate inactive streams, track actual post-association active intervals, and emit a machine-readable packet summary.

## 8. Mandatory pre-science execution gates

No one of the 540 scientific cells may begin until all gates pass:

1. repository and packet-release structural verification;
2. automated tests and frozen scientific self-test;
3. complete 540-cell offline plan/rate audit;
4. at least 8 GiB free on the results filesystem;
5. build/inspect the pinned WiGig base image and verify `git rev-parse HEAD` equals the required commit;
6. build the experiment image and verify the custom scratch program exposes the expected command-line options;
7. run a real packet smoke simulation with all six streams configured at `5 Mbps`, RNG run `991001`;
8. require all six smoke streams to appear in `packet_summary.csv`, have positive active intervals, and receive at least one payload byte.

A compile or smoke failure stops the campaign before any scientific packet result is generated.

## 9. Required outputs and frozen resume identity

Every accepted scientific cell must retain:

- exact Docker command;
- stdout/stderr, return status, timeout status, and runtime;
- `packet_summary.csv`;
- Q-D/SNR artifacts emitted by the simulator;
- configured per-stream offered rates;
- placement and planner status;
- analytical conflict-utilization/cross-rack metadata;
- attempt number.

At run creation, provenance freezes the identities of at least:

- packet protocol;
- packet configuration;
- custom simulator source;
- canonical Kubernetes planner-construction source/configuration;
- canonical simulation-backed wireless trace;
- canonical B+ planner tree;
- WiGig upstream commit;
- base Docker image ID;
- experiment Docker image ID.

A resume must reproduce these identities exactly. Existing saved plans are recomputed from the current frozen source and compared before reuse. Existing accepted cells are revalidated against their retained `packet_summary.csv` and frozen plan before reuse.

Campaign outputs must include graph-level aggregates, target/method summaries, `PRIMARY_RESULT.json`, `FINAL_REPORT.md`, and `SHA256SUMS.txt`.

## 10. Failure, interruption, timeout, and retry rule

An attempt is invalid only for execution/infrastructure reasons: nonzero simulator exit, wall-clock timeout, missing/malformed packet summary, impossible active time, configured-rate mismatch, or other execution/output-structure failure. Scientific outcomes, including zero goodput, are **not** infrastructure failures when execution and outputs are valid.

Each cell has at most two attempts. Attempt directories are never deleted or silently reused. An attempt directory left by an interruption counts as an attempt and is marked as interrupted on resume. Stale Docker containers from timed-out/interrupted attempts are forcibly removed before continuing. Failed/interrupted attempt evidence is retained.

Any change to graphs, methods, primary target, endpoint, load anchor, Q-D mapping, simulator RNG runs, or inferential rule after packet outcomes exist requires a new protocol ID and cannot be pooled into this confirmation.

## 11. Manifest and re-analysis rule

Re-analysis is permitted only from the retained accepted cell evidence under the same frozen protocol. Because report files contain analysis timestamps, every explicit re-analysis refreshes `SHA256SUMS.txt` before checksum verification. The run manifest therefore always describes the latest complete state of that run directory.

## 12. Claim boundary

A favorable result supports only:

> Packet-level dense-WiGig evidence that wireless-state/conflict-aware placement can add value beyond byte affinity under the frozen shared-contention mapping.

It does **not** establish:

- physical RF interference reduction;
- measured SINR/collision reduction on hardware;
- faithful reproduction of a complete three-rack antenna geometry;
- universal superiority of B+;
- improved end-to-end application latency or throughput outside the tested packet-level mapping.

Because no physical hardware is available, the paper must retain simulation/emulation wording and must not make a physical-radio validation claim.
